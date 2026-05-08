# app/scraper/client.py
import asyncio
import logging
import random
import time
from urllib.parse import urlencode

from curl_cffi.requests import AsyncSession
import httpx

from app.scraper.parser import VintedItem, parse_response
from app.scraper.rate_limiter import TokenBucketLimiter

logger = logging.getLogger(__name__)

DOMAIN_DELAY_MIN = 1.0
DOMAIN_DELAY_MAX = 3.0
WARMUP_DELAY_MIN = 0.5
WARMUP_DELAY_MAX = 1.5
MAX_CONCURRENT_DOMAINS = 3

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

_domain_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOMAINS)


class CloudflareFallback:
    def __init__(
        self,
        worker_url: str,
        block_threshold: int = 2,
        recovery_minutes: int = 10,
    ) -> None:
        self.worker_url = worker_url.rstrip("/") if worker_url else ""
        self.block_threshold = block_threshold
        self.recovery_minutes = recovery_minutes
        self._block_counts: dict[str, int] = {}
        self._using_cf: dict[str, bool] = {}
        self._cf_activated_at: dict[str, float] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.worker_url)

    def should_use_cf(self, domain: str) -> bool:
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

    async def _ensure_session(self, domain: str) -> AsyncSession:
        async with self._lock:
            if domain not in self._sessions:
                self._sessions[domain] = AsyncSession(impersonate="chrome124")
                self._session_ready[domain] = False
            return self._sessions[domain]

    async def _warmup_session(self, domain: str) -> None:
        session = await self._ensure_session(domain)
        async with self._lock:
            if self._session_ready.get(domain, False):
                return
        try:
            await asyncio.sleep(random.uniform(WARMUP_DELAY_MIN, WARMUP_DELAY_MAX))
            response = await session.get(
                f"https://www.{domain}/",
                headers=WEB_HEADERS,
                timeout=30.0,
            )
            if response.status_code == 200:
                async with self._lock:
                    self._session_ready[domain] = True
                logger.info("Session warmed up for domain=%s", domain)
        except Exception:
            logger.exception("Warmup error for domain=%s", domain)

    async def _search_via_cf(self, domain: str, params: dict) -> list[VintedItem]:
        if not self.cf_fallback or not self.cf_fallback.worker_url:
            return []

        query_string = urlencode(params, doseq=True)
        target_url = f"https://www.{domain}/api/v2/catalog/items?{query_string}"
        worker_url = f"{self.cf_fallback.worker_url}?url={target_url}"

        try:
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
            return []
        except Exception:
            logger.exception("CF Worker request failed for domain=%s", domain)
            return []

    async def search(self, domain: str, params: dict) -> list[VintedItem]:
        if self.cf_fallback and self.cf_fallback.should_use_cf(domain):
            logger.info("Using CF Worker for domain=%s", domain)
            return await self._search_via_cf(domain, params)

        await self.rate_limiter.acquire(domain)
        await self._warmup_session(domain)

        session = await self._ensure_session(domain)
        url = f"https://www.{domain}/api/v2/catalog/items"

        try:
            response = await session.get(
                url,
                params=params,
                headers={
                    **WEB_HEADERS,
                    "Referer": f"https://www.{domain}/",
                    "X-Requested-With": "XMLHttpRequest",
                },
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
                if self.cf_fallback:
                    self.cf_fallback.report_block(domain)
                async with self._lock:
                    self._session_ready[domain] = False
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
            if self.cf_fallback:
                self.cf_fallback.report_block(domain)
            return []

    async def _search_domain_with_semaphore(
        self, domain: str, params: dict
    ) -> list[VintedItem]:
        async with _domain_semaphore:
            try:
                items = await self.search(domain, params)
                await asyncio.sleep(random.uniform(DOMAIN_DELAY_MIN, DOMAIN_DELAY_MAX))
                return items
            except Exception:
                logger.warning("Domain search failed for %s", domain)
                return []

    async def search_all_domains(
        self, params: dict, domains: list[str]
    ) -> list[VintedItem]:
        shuffled = list(domains)
        random.shuffle(shuffled)

        tasks = [
            self._search_domain_with_semaphore(domain, params)
            for domain in shuffled
        ]
        results = await asyncio.gather(*tasks)

        seen_ids: set[int] = set()
        unique_items: list[VintedItem] = []
        for items in results:
            for item in items:
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
