import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BackoffTelemetry:
    domain: str
    status_code: int
    timestamp: float
    retry_after: Optional[int]
    backoff_seconds: float

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "status_code": self.status_code,
            "timestamp": self.timestamp,
            "retry_after": self.retry_after,
            "backoff_seconds": self.backoff_seconds,
        }


class VintedRateLimiter:
    """
    Shared async rate limiter for Vinted requests.
    Supports global RPM, per-domain RPM, and backoff logic.
    """

    def __init__(self, global_rpm: int, domain_rpm: int):
        self.global_rpm = global_rpm
        self.domain_rpm = domain_rpm

        self._global_bucket: float = float(global_rpm)
        self._global_last_refill: float = time.monotonic()

        self._domain_buckets: Dict[str, float] = {}
        self._domain_last_refill: Dict[str, float] = {}

        self._domain_backoff_until: Dict[str, float] = {}
        self._domain_backoff_level: Dict[str, int] = {}

        self._telemetry: List[BackoffTelemetry] = []
        self._lock = asyncio.Lock()

    def _get_domain_bucket(self, domain: str) -> float:
        if domain not in self._domain_buckets:
            self._domain_buckets[domain] = float(self.domain_rpm)
            self._domain_last_refill[domain] = time.monotonic()
        return self._domain_buckets[domain]

    async def acquire(self, domain: str):
        """
        Acquire a token for the given domain.
        Waits asynchronously if budget is exhausted or in backoff.
        """
        while True:
            async with self._lock:
                now = time.monotonic()

                # 1. Check backoff
                backoff_until = self._domain_backoff_until.get(domain, 0.0)
                if backoff_until > now:
                    wait = backoff_until - now
                    logger.debug(
                        "Limiter: domain %s in backoff, waiting %.2fs", domain, wait
                    )
                else:
                    wait = 0.0

                if wait > 0:
                    # Release lock and sleep
                    pass
                else:
                    # 2. Refill global
                    elapsed_global = now - self._global_last_refill
                    refill_global = elapsed_global * (self.global_rpm / 60.0)
                    self._global_bucket = min(
                        float(self.global_rpm), self._global_bucket + refill_global
                    )
                    self._global_last_refill = now

                    # 3. Refill domain
                    elapsed_domain = now - self._domain_last_refill.get(domain, now)
                    refill_domain = elapsed_domain * (self.domain_rpm / 60.0)
                    bucket_domain = min(
                        float(self.domain_rpm),
                        self._get_domain_bucket(domain) + refill_domain,
                    )
                    self._domain_buckets[domain] = bucket_domain
                    self._domain_last_refill[domain] = now

                    # 4. Check if tokens available
                    if self._global_bucket >= 1.0 and bucket_domain >= 1.0:
                        self._global_bucket -= 1.0
                        self._domain_buckets[domain] -= 1.0
                        logger.debug(
                            "Limiter: token acquired for domain %s (G:%.1f, D:%.1f)",
                            domain,
                            self._global_bucket,
                            self._domain_buckets[domain],
                        )
                        return

                    # 5. Calculate wait for next token
                    wait_global = (
                        (1.0 - self._global_bucket) * (60.0 / self.global_rpm)
                        if self._global_bucket < 1.0
                        else 0
                    )
                    wait_domain = (
                        (1.0 - bucket_domain) * (60.0 / self.domain_rpm)
                        if bucket_domain < 1.0
                        else 0
                    )
                    wait = max(wait_global, wait_domain)
                    logger.debug(
                        "Limiter: waiting %.2fs for tokens for %s", wait, domain
                    )

            # Sleep outside the lock
            await asyncio.sleep(wait)

    def report_status(
        self, domain: str, status_code: int, retry_after: Optional[int] = None
    ):
        """
        Record result of a request to update backoff state.
        """
        if status_code == 200:
            self._domain_backoff_level[domain] = 0
            return

        if status_code not in (429, 403) and status_code < 500:
            return

        now = time.monotonic()
        level = self._domain_backoff_level.get(domain, 0) + 1
        self._domain_backoff_level[domain] = level

        if retry_after:
            backoff = float(retry_after)
        else:
            # exponential: 120, 240, 480, ... max 1800
            backoff = min(1800.0, 120.0 * (2.0 ** (level - 1)))

        self._domain_backoff_until[domain] = now + backoff

        self._telemetry.append(
            BackoffTelemetry(
                domain=domain,
                status_code=status_code,
                timestamp=now,
                retry_after=retry_after,
                backoff_seconds=backoff,
            )
        )
        # Keep last 50 telemetry records
        if len(self._telemetry) > 50:
            self._telemetry.pop(0)

        logger.warning(
            "Limiter: domain %s backoff applied for %.2fs (level %d, status %d)",
            domain,
            backoff,
            level,
            status_code,
        )

    def get_diagnostics(self) -> dict:
        now = time.monotonic()
        active_backoffs = {
            d: until - now
            for d, until in self._domain_backoff_until.items()
            if until > now
        }
        return {
            "global_rpm": self.global_rpm,
            "domain_rpm": self.domain_rpm,
            "global_bucket": self._global_bucket,
            "domain_buckets": self._domain_buckets,
            "active_backoffs": active_backoffs,
            "telemetry": [t.to_dict() for t in self._telemetry],
        }


_limiter_instance: Optional[VintedRateLimiter] = None
_limiter_lock = asyncio.Lock()


async def get_vinted_rate_limiter() -> VintedRateLimiter:
    global _limiter_instance
    if _limiter_instance is None:
        async with _limiter_lock:
            if _limiter_instance is None:
                from app.config import get_settings

                s = get_settings()
                _limiter_instance = VintedRateLimiter(
                    global_rpm=s.vinted_global_safe_requests_per_minute,
                    domain_rpm=s.vinted_domain_safe_requests_per_minute,
                )
    return _limiter_instance
