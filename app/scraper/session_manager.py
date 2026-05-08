# app/scraper/session_manager.py
import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from curl_cffi.requests import AsyncSession

from app.scraper.domains import VINTED_DOMAINS

logger = logging.getLogger(__name__)

SESSION_REFRESH_MARGIN_SECONDS = 300


@dataclass
class VintedSession:
    domain: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    proxy: str | None = None
    requests_count: int = 0
    max_requests: int = field(default_factory=lambda: random.randint(40, 80))
    last_used_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def is_near_expiry(self) -> bool:
        margin = timedelta(seconds=SESSION_REFRESH_MARGIN_SECONDS)
        return datetime.now(timezone.utc) >= (self.expires_at - margin)

    @property
    def needs_rotation(self) -> bool:
        return self.requests_count >= self.max_requests


class SessionManager:
    def __init__(self, proxies: list[str], sessions_per_domain: int) -> None:
        self.proxies = proxies
        self.sessions_per_domain = sessions_per_domain
        self._pools: dict[str, list[VintedSession]] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, domain: str) -> VintedSession:
        async with self._lock:
            pool = self._pools.setdefault(domain, [])
            pool[:] = [
                s for s in pool
                if not s.is_expired and not s.needs_rotation
            ]
            if pool:
                session = pool.pop(0)
                session.requests_count += 1
                session.last_used_at = datetime.now(timezone.utc)
                return session

        session = await self._create_session(domain)
        session.requests_count += 1
        return session

    async def return_session(self, session: VintedSession) -> None:
        if session.is_expired or session.needs_rotation or not session.access_token:
            return
        async with self._lock:
            pool = self._pools.setdefault(session.domain, [])
            if session not in pool and len(pool) < self.sessions_per_domain:
                pool.append(session)

    async def invalidate_session(self, session: VintedSession) -> None:
        async with self._lock:
            pool = self._pools.get(session.domain, [])
            if session in pool:
                pool.remove(session)
            logger.warning("Session invalidated for domain=%s", session.domain)

    def get_cached_count(self) -> dict[str, int]:
        return {domain: len(pool) for domain, pool in self._pools.items() if pool}

    async def _create_session(self, domain: str) -> VintedSession:
        domain_info = VINTED_DOMAINS.get(domain, {})
        domain_code = domain_info.get("code", "com")
        proxy = random.choice(self.proxies) if self.proxies else None

        user_agent = (
            f"vinted-ios Vinted/24.8.1 (lt.manodrabuziai.{domain_code}; "
            f"build:22501; iOS 17.4.1) iPhone15,2"
        )

        headers = {
            "User-Agent": user_agent,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        url = f"https://www.{domain}/oauth/token"
        payload = {
            "grant_type": "password",
            "client_id": "ios",
            "scope": "public",
        }

        try:
            async with AsyncSession(impersonate="safari17_0") as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    proxy=proxy,
                    timeout=30.0,
                )
                data = response.json()

            access_token = data["access_token"]
            refresh_token = data.get("refresh_token", "")
            expires_in = data.get("expires_in", 3600)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            logger.info("Created new session for domain=%s", domain)
            session = VintedSession(
                domain=domain,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                proxy=proxy,
            )
            async with self._lock:
                pool = self._pools.setdefault(domain, [])
                if len(pool) < self.sessions_per_domain:
                    pool.append(session)
            return session
        except Exception:
            logger.exception("Failed to create session for domain=%s", domain)
            dummy_expires = datetime.now(timezone.utc) + timedelta(seconds=60)
            return VintedSession(
                domain=domain,
                access_token="",
                refresh_token="",
                expires_at=dummy_expires,
                proxy=proxy,
            )
