# app/scraper/client.py
import asyncio
import logging
import random

from curl_cffi.requests import AsyncSession

from app.scraper.parser import VintedItem, parse_response
from app.scraper.rate_limiter import TokenBucketLimiter

logger = logging.getLogger(__name__)

MAX_CONCURRENT_DOMAINS = 2
DOMAIN_DELAY_MIN = 3.0
DOMAIN_DELAY_MAX = 7.0

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

_global_search_lock = asyncio.Lock()


class VintedClient:
    def __init__(self, rate_limiter: TokenBucketLimiter) -> None:
        self.rate_limiter = rate_limiter
        self._sessions: dict[str, AsyncSession] = {}
        self._session_ready: dict[str, bool] = {}
        self._lock = asyncio.Lock()
        self._domain_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOMAINS)

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

    async def search(self, domain: str, params: dict) -> list[VintedItem]:
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
                data = response.json()
                return parse_response(data, domain)

            if response.status_code in (429, 403):
                logger.warning("Blocked on domain=%s status=%d", domain, response.status_code)
                self.rate_limiter.report_error(domain)
                async with self._lock:
                    self._session_ready[domain] = False
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
            return []

    async def _search_with_semaphore(
        self, domain: str, params: dict
    ) -> list[VintedItem]:
        async with self._domain_semaphore:
            result = await self.search(domain, params)
            await asyncio.sleep(random.uniform(DOMAIN_DELAY_MIN, DOMAIN_DELAY_MAX))
            return result

    async def search_all_domains(
        self, params: dict, domains: list[str]
    ) -> list[VintedItem]:
        async with _global_search_lock:
            shuffled = list(domains)
            random.shuffle(shuffled)

            tasks = [self._search_with_semaphore(domain, params) for domain in shuffled]
            results_per_domain = await asyncio.gather(*tasks, return_exceptions=True)

        seen_ids: set[int] = set()
        unique_items: list[VintedItem] = []

        for result in results_per_domain:
            if isinstance(result, Exception):
                logger.warning("Domain search failed: %s", result)
                continue
            if not isinstance(result, list):
                continue
            for item in result:
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
