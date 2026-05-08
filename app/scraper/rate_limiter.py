# app/scraper/rate_limiter.py
import asyncio
import random
import time


class TokenBucketLimiter:
    def __init__(self, rate: float = 3.0, per: float = 60.0) -> None:
        self.rate = rate
        self.per = per
        self.buckets: dict[str, float] = {}
        self.last_time: dict[str, float] = {}
        self.error_counts: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    async def acquire(self, domain: str) -> None:
        async with self._get_lock(domain):
            error_count = self.error_counts.get(domain, 0)
            if error_count >= 3:
                wait = 600.0 + random.uniform(0.0, 60.0)
                await asyncio.sleep(wait)
            elif error_count > 0:
                base = 30.0 * (2 ** (error_count - 1))
                await asyncio.sleep(base + random.uniform(0.0, base * 0.5))

            now = time.monotonic()
            tokens = self.buckets.get(domain, self.rate)
            last_refill = self.last_time.get(domain, now)
            elapsed = now - last_refill
            refill_amount = elapsed * (self.rate / self.per)
            tokens = min(self.rate, tokens + refill_amount)

            if tokens < 1.0:
                wait_seconds = (1.0 - tokens) * (self.per / self.rate)
                await asyncio.sleep(wait_seconds)
                now = time.monotonic()
                tokens = 1.0

            self.buckets[domain] = tokens - 1.0
            self.last_time[domain] = now
            await asyncio.sleep(random.uniform(4.0, 10.0))

    def report_error(self, domain: str) -> None:
        self.error_counts[domain] = self.error_counts.get(domain, 0) + 1

    def report_success(self, domain: str) -> None:
        self.error_counts[domain] = 0
