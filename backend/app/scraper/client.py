# app/scraper/client.py
import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlencode

from curl_cffi.requests import AsyncSession
import httpx

from app.scraper.parser import VintedItem, VintedItemDetail, parse_item_detail, parse_response
from app.scraper.rate_limiter import TokenBucketLimiter
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

DOMAIN_DELAY_MIN = 1.0
DOMAIN_DELAY_MAX = 3.0
WARMUP_DELAY_MIN = 0.5
WARMUP_DELAY_MAX = 1.5
MAX_CONCURRENT_DOMAINS = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

_domain_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOMAINS)

class HttpBudgetLimiter:
    def __init__(self) -> None:
        self._global_semaphore = asyncio.Semaphore(settings.scraper_global_http_concurrency)
        self._domain_semaphores: dict[str, asyncio.Semaphore] = {}
        self._domain_cooldown_until: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._active_requests = 0
        self._active_requests_by_domain: dict[str, int] = {}
        self._cooldown_counts = 0

    async def _get_domain_semaphore(self, domain: str) -> asyncio.Semaphore:
        async with self._lock:
            if domain not in self._domain_semaphores:
                self._domain_semaphores[domain] = asyncio.Semaphore(settings.scraper_domain_http_concurrency)
            return self._domain_semaphores[domain]

    def is_in_cooldown(self, domain: str) -> bool:
        until = self._domain_cooldown_until.get(domain, 0.0)
        if until > time.monotonic():
            return True
        return False

    def report_block(self, domain: str) -> None:
        cooldown = settings.scraper_domain_cooldown_seconds
        if cooldown > 0:
            logger.warning("Domain %s entered cooldown for %d seconds", domain, cooldown)
            self._domain_cooldown_until[domain] = time.monotonic() + cooldown
            self._cooldown_counts += 1

    @asynccontextmanager
    async def acquire(self, domain: str):
        if self.is_in_cooldown(domain):
            raise RuntimeError(f"Domain {domain} is in cooldown")

        domain_sem = await self._get_domain_semaphore(domain)
        async with self._global_semaphore:
            async with domain_sem:
                async with self._lock:
                    self._active_requests += 1
                    self._active_requests_by_domain[domain] = self._active_requests_by_domain.get(domain, 0) + 1
                try:
                    yield
                finally:
                    async with self._lock:
                        self._active_requests -= 1
                        self._active_requests_by_domain[domain] -= 1
                        if self._active_requests_by_domain[domain] <= 0:
                            self._active_requests_by_domain.pop(domain, None)

    def get_stats(self) -> dict[str, object]:
        active_cooldowns = [d for d, until in self._domain_cooldown_until.items() if until > time.monotonic()]
        return {
            "scraper_global_http_concurrency": settings.scraper_global_http_concurrency,
            "scraper_domain_http_concurrency": settings.scraper_domain_http_concurrency,
            "scraper_active_http_requests": self._active_requests,
            "scraper_active_http_requests_by_domain": dict(self._active_requests_by_domain),
            "scraper_domain_cooldowns_count": len(active_cooldowns),
        }

_http_budget = HttpBudgetLimiter()


@dataclass
class DomainSearchResult:
    domain: str
    items: list[VintedItem]
    request_count: int = 1
    duration_ms: int = 0
    error: str | None = None


class CloudflareFallback:
    def __init__(
        self,
        worker_url: str,
        mode: str = "auto",
        block_threshold: int = 2,
        recovery_minutes: int = 10,
    ) -> None:
        self.worker_url = worker_url.rstrip("/") if worker_url else ""
        self.mode = mode
        self.block_threshold = block_threshold
        self.recovery_minutes = recovery_minutes
        self._block_counts: dict[str, int] = {}
        self._using_cf: dict[str, bool] = {}
        self._cf_activated_at: dict[str, float] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.worker_url)

    def should_use_cf(self, domain: str) -> bool:
        if self.mode == "direct":
            return False
        if self.mode == "worker":
            return self.is_configured
        
        # Default/Auto mode
        if not self.is_configured:
            return False
        if self._using_cf.get(domain, False):
            activated_at = self._cf_activated_at.get(domain, 0.0)
            elapsed = (time.monotonic() - activated_at) / 60.0
            if elapsed >= self.recovery_minutes:
                logger.info(
                    "Recovery period elapsed for domain=%s, trying direct",
                    domain,
                )
                self._using_cf[domain] = False
                self._block_counts[domain] = 0
                return False
            return True
        return False

    def report_block(self, domain: str) -> None:
        self._block_counts[domain] = self._block_counts.get(domain, 0) + 1
        count = self._block_counts[domain]
        if self.is_configured and count >= self.block_threshold:
            if not self._using_cf.get(domain, False):
                logger.warning(
                    "Switching to CF Worker for domain=%s after %d blocks",
                    domain,
                    count,
                )
                self._using_cf[domain] = True
                self._cf_activated_at[domain] = time.monotonic()

    def report_direct_success(self, domain: str) -> None:
        self._block_counts[domain] = 0

    def get_status(self) -> dict[str, bool]:
        return {d: v for d, v in self._using_cf.items() if v}


class VintedClient:
    def __init__(
        self,
        rate_limiter: TokenBucketLimiter,
        cf_fallback: CloudflareFallback | None = None,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.cf_fallback = cf_fallback
        self._sessions: dict[str, AsyncSession] = {}
        self._session_ready: dict[str, bool] = {}
        self._lock = asyncio.Lock()

    async def _ensure_session(self, domain: str, force_new: bool = False) -> AsyncSession:
        async with self._lock:
            if domain not in self._sessions or force_new:
                if domain in self._sessions:
                    try:
                        await self._sessions[domain].close()
                    except Exception:
                        pass
                
                proxies = settings.get_proxy_list()
                proxy = random.choice(proxies) if proxies else None
                
                self._sessions[domain] = AsyncSession(
                    impersonate="chrome124",
                    proxy=proxy,
                    verify=False if proxy else True
                )
                self._session_ready[domain] = False
                if proxy:
                    logger.info("Created new session for domain=%s with proxy", domain)
                else:
                    logger.info("Created new session for domain=%s without proxy", domain)
            return self._sessions[domain]

    async def _warmup_session(self, domain: str) -> None:
        session = await self._ensure_session(domain)
        async with self._lock:
            if self._session_ready.get(domain, False):
                return
            # Mark as ready optimistically to prevent concurrent warmups
            self._session_ready[domain] = True

        try:
            await asyncio.sleep(random.uniform(WARMUP_DELAY_MIN, WARMUP_DELAY_MAX))
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            response = await session.get(
                f"https://www.{domain}/",
                headers=headers,
                timeout=30.0,
            )
            if response.status_code == 200:
                logger.info("Session warmed up for domain=%s", domain)
            else:
                async with self._lock:
                    self._session_ready[domain] = False
                logger.warning("Warmup returned status=%d for domain=%s", response.status_code, domain)
        except Exception:
            async with self._lock:
                self._session_ready[domain] = False
            logger.exception("Warmup error for domain=%s", domain)

    async def _search_via_cf(self, domain: str, params: dict) -> list[VintedItem]:
        if not self.cf_fallback or not self.cf_fallback.worker_url:
            return []

        query_string = urlencode(params, doseq=True)
        target_url = f"https://www.{domain}/api/v2/catalog/items?{query_string}"
        worker_url = f"{self.cf_fallback.worker_url}?url={target_url}"

        try:
            async with _http_budget.acquire(domain):
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    response = await http_client.get(worker_url)

            if response.status_code == 200:
                data = response.json()
                logger.info("CF Worker success for domain=%s", domain)
                return parse_response(data, domain)

            logger.warning(
                "CF Worker returned status=%d for domain=%s",
                response.status_code,
                domain,
            )
            if response.status_code in (403, 429):
                _http_budget.report_block(domain)
            return []
        except Exception:
            logger.exception("CF Worker request failed for domain=%s", domain)
            return []

    async def fetch_catalog_html(self, url: str, *, domain: str | None = None) -> str:
        """
        Fetch the public catalog HTML page.
        """
        if domain is None:
            # Simple domain extraction from URL
            domain = "vinted.pl"
            if ".fr/" in url: domain = "vinted.fr"
            elif ".de/" in url: domain = "vinted.de"
            # ... can be improved later
            
        await self.rate_limiter.acquire(domain)
        await self._warmup_session(domain)

        session = await self._ensure_session(domain)
        
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://www.{domain}/",
        }

        try:
            async with _http_budget.acquire(domain):
                response = await session.get(
                    url,
                    headers=headers,
                    timeout=30.0,
                )
            
            if response.status_code != 200:
                logger.warning("Failed to fetch catalog HTML, status=%d", response.status_code)
                return ""
                
            return response.text
        except Exception:
            logger.exception("Failed to fetch catalog HTML for url=%s", url)
            return ""

    async def fetch_catalog_hydration_items(self, url: str, *, domain: str = "vinted.pl") -> list[dict]:
        """
        Fetch and parse catalog items via hydration payload.
        """
        html = await self.fetch_catalog_html(url, domain=domain)
        if not html:
            return []
            
        from app.scraper.hydration_parser import extract_hydration_items
        return extract_hydration_items(html, domain=domain)

    async def search(self, domain: str, params: dict, mode: str = "auto") -> list[VintedItem]:
        if self.cf_fallback:
            self.cf_fallback.mode = mode
            if self.cf_fallback.should_use_cf(domain):
                logger.info("Using CF Worker for domain=%s (mode=%s)", domain, mode)
                return await self._search_via_cf(domain, params)

        await self.rate_limiter.acquire(domain)
        await self._warmup_session(domain)

        session = await self._ensure_session(domain)
        url = f"https://www.{domain}/api/v2/catalog/items"

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://www.{domain}/",
            "X-Requested-With": "XMLHttpRequest",
        }

        try:
            async with _http_budget.acquire(domain):
                response = await session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=30.0,
                )

            if response.status_code == 200:
                self.rate_limiter.report_success(domain)
                if self.cf_fallback:
                    self.cf_fallback.report_direct_success(domain)
                data = response.json()
                return parse_response(data, domain)

            if response.status_code in (429, 403):
                logger.warning("Blocked on domain=%s status=%d", domain, response.status_code)
                self.rate_limiter.report_error(domain)
                _http_budget.report_block(domain)
                if self.cf_fallback:
                    self.cf_fallback.report_block(domain)
                
                # Reset session to try with a new proxy next time
                await self._ensure_session(domain, force_new=True)
                
                if self.cf_fallback and self.cf_fallback.should_use_cf(domain):
                    logger.info("Retrying via CF Worker for domain=%s", domain)
                    return await self._search_via_cf(domain, params)
                return []

            if response.status_code == 401:
                logger.warning("Auth expired for domain=%s, re-warming", domain)
                async with self._lock:
                    self._session_ready[domain] = False
                return []

            logger.warning("Unexpected status=%d from domain=%s", response.status_code, domain)
            return []

        except Exception:
            logger.exception("Request failed for domain=%s", domain)
            self.rate_limiter.report_error(domain)
            _http_budget.report_block(domain)
            if self.cf_fallback:
                self.cf_fallback.report_block(domain)
            return []

    async def fetch_item_detail(self, domain: str, item_id: int) -> VintedItemDetail | None:
        await self.rate_limiter.acquire(domain)
        await self._warmup_session(domain)

        session = await self._ensure_session(domain)
        url = f"https://www.{domain}/api/v2/items/{item_id}/details"
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://www.{domain}/items/{item_id}",
            "X-Requested-With": "XMLHttpRequest",
        }

        try:
            async with _http_budget.acquire(domain):
                response = await session.get(url, headers=headers, timeout=20.0)

            if response.status_code == 200:
                self.rate_limiter.report_success(domain)
                data = response.json()
                return parse_item_detail(data, item_id)

            if response.status_code in (403, 429):
                logger.warning("Blocked on item detail domain=%s status=%d", domain, response.status_code)
                self.rate_limiter.report_error(domain)
                _http_budget.report_block(domain)
                if self.cf_fallback:
                    self.cf_fallback.report_block(domain)
                return None

            if response.status_code == 404:
                logger.info("Item detail not found domain=%s item_id=%s", domain, item_id)
                return None

            logger.warning("Unexpected item detail status=%d domain=%s", response.status_code, domain)
            return None
        except Exception:
            logger.exception("Item detail request failed for domain=%s item_id=%s", domain, item_id)
            self.rate_limiter.report_error(domain)
            return None

    async def _search_domain_with_semaphore(
        self, domain: str, params: dict, mode: str = "auto"
    ) -> DomainSearchResult:
        started = time.monotonic()
        async with _domain_semaphore:
            try:
                items = await self.search(domain, params, mode=mode)
                await asyncio.sleep(random.uniform(DOMAIN_DELAY_MIN, DOMAIN_DELAY_MAX))
                return DomainSearchResult(
                    domain=domain,
                    items=items,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception as exc:
                if "cooldown" in str(exc).lower():
                    logger.info("Domain %s search skipped due to cooldown", domain)
                else:
                    logger.warning("Domain search failed for %s: %s", domain, exc)
                return DomainSearchResult(
                    domain=domain,
                    items=[],
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error=str(exc) if "cooldown" in str(exc).lower() else type(exc).__name__,
                )

    async def search_domains(
        self, params: dict, domains: list[str], mode: str = "auto"
    ) -> list[DomainSearchResult]:
        shuffled = list(domains)
        random.shuffle(shuffled)

        tasks = [
            self._search_domain_with_semaphore(domain, params, mode=mode)
            for domain in shuffled
        ]
        return await asyncio.gather(*tasks)

    async def search_all_domains(
        self, params: dict, domains: list[str], mode: str = "auto"
    ) -> list[VintedItem]:
        results = await self.search_domains(params, domains, mode=mode)

        seen_ids: set[int] = set()
        unique_items: list[VintedItem] = []
        for result in results:
            for item in result.items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    unique_items.append(item)

        return unique_items

    async def close(self) -> None:
        for session in self._sessions.values():
            try:
                await session.close()
            except Exception:
                pass
        self._sessions.clear()
        self._session_ready.clear()
