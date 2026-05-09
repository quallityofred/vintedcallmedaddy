# tests/test_new_features.py
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import AppSettings, Base, User
from app.scraper.client import CloudflareFallback, VintedClient
from app.scraper.rate_limiter import TokenBucketLimiter
from app.scraper.session_manager import SessionManager, VintedSession
from app.telegram.settings_store import (
    ACTIVE_TELEGRAM_USER_ID_KEY,
    get_active_telegram_user_id,
    set_active_telegram_user_id,
    update_user_chat_id_by_bot_token,
)


# ---------------------------------------------------------------------------
# CloudflareFallback tests
# ---------------------------------------------------------------------------

class TestCloudflareFallback:

    def test_not_configured_without_url(self):
        cf = CloudflareFallback(worker_url="", block_threshold=2, recovery_minutes=10)
        assert not cf.is_configured
        assert not cf.should_use_cf("vinted.fr")

    def test_configured_with_url(self):
        cf = CloudflareFallback(worker_url="https://worker.example.com", block_threshold=2, recovery_minutes=10)
        assert cf.is_configured

    def test_switches_to_cf_after_threshold(self):
        cf = CloudflareFallback(worker_url="https://worker.example.com", block_threshold=2, recovery_minutes=10)
        assert not cf.should_use_cf("vinted.fr")

        cf.report_block("vinted.fr")
        assert not cf.should_use_cf("vinted.fr")

        cf.report_block("vinted.fr")
        assert cf.should_use_cf("vinted.fr")

    def test_independent_domain_tracking(self):
        cf = CloudflareFallback(worker_url="https://worker.example.com", block_threshold=2, recovery_minutes=10)
        cf.report_block("vinted.fr")
        cf.report_block("vinted.fr")
        assert cf.should_use_cf("vinted.fr")
        assert not cf.should_use_cf("vinted.de")

    def test_direct_success_resets_block_count(self):
        cf = CloudflareFallback(worker_url="https://worker.example.com", block_threshold=3, recovery_minutes=10)
        cf.report_block("vinted.fr")
        cf.report_block("vinted.fr")
        cf.report_direct_success("vinted.fr")
        cf.report_block("vinted.fr")
        assert not cf.should_use_cf("vinted.fr")

    def test_recovery_after_timeout(self):
        cf = CloudflareFallback(worker_url="https://worker.example.com", block_threshold=1, recovery_minutes=1)
        cf.report_block("vinted.fr")
        assert cf.should_use_cf("vinted.fr")

        # Simulate that recovery period has passed by backdating activation
        cf._cf_activated_at["vinted.fr"] = time.monotonic() - 120
        assert not cf.should_use_cf("vinted.fr")

    def test_still_using_cf_before_recovery(self):
        cf = CloudflareFallback(worker_url="https://worker.example.com", block_threshold=1, recovery_minutes=60)
        cf.report_block("vinted.fr")
        assert cf.should_use_cf("vinted.fr")

    def test_get_status(self):
        cf = CloudflareFallback(worker_url="https://worker.example.com", block_threshold=1, recovery_minutes=10)
        assert cf.get_status() == {}
        cf.report_block("vinted.fr")
        assert cf.get_status() == {"vinted.fr": True}

    def test_trailing_slash_stripped(self):
        cf = CloudflareFallback(worker_url="https://worker.example.com/", block_threshold=2, recovery_minutes=10)
        assert cf.worker_url == "https://worker.example.com"


# ---------------------------------------------------------------------------
# Adaptive scheduling tests
# ---------------------------------------------------------------------------

class TestAdaptiveScheduling:

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setenv("PEAK_START_HOUR", "8")
        monkeypatch.setenv("PEAK_END_HOUR", "23")
        monkeypatch.setenv("OFFPEAK_INTERVAL_MULTIPLIER", "2.5")
        monkeypatch.setenv("NIGHT_INTERVAL_MULTIPLIER", "5.0")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_peak_time_returns_base_interval(self):
        from app.scheduler.tasks import _get_effective_interval, _is_peak_time
        with patch("app.scheduler.tasks.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert _is_peak_time()
            assert _get_effective_interval(120) == 120

    def test_night_time_multiplier(self):
        from app.scheduler.tasks import _get_effective_interval
        with patch("app.scheduler.tasks.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 8, 3, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert _get_effective_interval(120) == 600

    def test_offpeak_multiplier(self):
        from app.scheduler.tasks import _get_effective_interval
        with patch("app.scheduler.tasks.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 8, 23, 30, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert _get_effective_interval(120) == 300

    def test_normalize_adaptive_interval_never_below_original(self):
        from app.models import Monitor
        from app.scheduler.tasks import _normalize_adaptive_interval

        monitor = Monitor(
            name="test",
            original_url="https://example.com",
            params_json='{"_original_interval": 120}',
            domains_json="[]",
            interval_sec=60,
            is_active=True,
        )

        assert _normalize_adaptive_interval(monitor) == 120

    def test_night_scaled_interval_resets_to_original_base(self):
        from app.models import Monitor
        from app.scheduler.tasks import _reset_interval_if_scaled_from_time_window

        monitor = Monitor(
            name="test",
            original_url="https://example.com",
            params_json='{"_original_interval": 120}',
            domains_json="[]",
            interval_sec=600,
            is_active=True,
        )

        assert _reset_interval_if_scaled_from_time_window(monitor) == 120

    def test_offpeak_scaled_interval_resets_to_original_base(self):
        from app.models import Monitor
        from app.scheduler.tasks import _reset_interval_if_scaled_from_time_window

        monitor = Monitor(
            name="test",
            original_url="https://example.com",
            params_json='{"_original_interval": 120}',
            domains_json="[]",
            interval_sec=300,
            is_active=True,
        )

        assert _reset_interval_if_scaled_from_time_window(monitor) == 120

    def test_adaptive_interval_above_original_is_preserved(self):
        from app.models import Monitor
        from app.scheduler.tasks import _reset_interval_if_scaled_from_time_window

        monitor = Monitor(
            name="test",
            original_url="https://example.com",
            params_json='{"_original_interval": 120}',
            domains_json="[]",
            interval_sec=180,
            is_active=True,
        )

        assert _reset_interval_if_scaled_from_time_window(monitor) == 180


# ---------------------------------------------------------------------------
# Session caching tests
# ---------------------------------------------------------------------------

class TestSessionCaching:

    @pytest.mark.asyncio
    async def test_return_session_adds_to_pool(self):
        sm = SessionManager(proxies=[], sessions_per_domain=3)
        session = VintedSession(
            domain="vinted.fr",
            access_token="test_token",
            refresh_token="test_refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await sm.return_session(session)
        assert sm.get_cached_count() == {"vinted.fr": 1}

    @pytest.mark.asyncio
    async def test_return_expired_session_not_added(self):
        sm = SessionManager(proxies=[], sessions_per_domain=3)
        session = VintedSession(
            domain="vinted.fr",
            access_token="test_token",
            refresh_token="test_refresh",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        await sm.return_session(session)
        assert sm.get_cached_count() == {}

    @pytest.mark.asyncio
    async def test_return_empty_token_session_not_added(self):
        sm = SessionManager(proxies=[], sessions_per_domain=3)
        session = VintedSession(
            domain="vinted.fr",
            access_token="",
            refresh_token="",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await sm.return_session(session)
        assert sm.get_cached_count() == {}

    @pytest.mark.asyncio
    async def test_pool_limit_respected(self):
        sm = SessionManager(proxies=[], sessions_per_domain=2)
        for i in range(5):
            session = VintedSession(
                domain="vinted.fr",
                access_token=f"token_{i}",
                refresh_token=f"refresh_{i}",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            await sm.return_session(session)
        assert sm.get_cached_count() == {"vinted.fr": 2}

    def test_is_near_expiry(self):
        soon = VintedSession(
            domain="vinted.fr",
            access_token="t",
            refresh_token="r",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=100),
        )
        assert soon.is_near_expiry

        far = VintedSession(
            domain="vinted.fr",
            access_token="t",
            refresh_token="r",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert not far.is_near_expiry

    def test_needs_rotation(self):
        session = VintedSession(
            domain="vinted.fr",
            access_token="t",
            refresh_token="r",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            max_requests=5,
        )
        assert not session.needs_rotation
        session.requests_count = 5
        assert session.needs_rotation

    @pytest.mark.asyncio
    async def test_invalidate_session(self):
        sm = SessionManager(proxies=[], sessions_per_domain=3)
        session = VintedSession(
            domain="vinted.fr",
            access_token="test_token",
            refresh_token="test_refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await sm.return_session(session)
        assert sm.get_cached_count() == {"vinted.fr": 1}
        await sm.invalidate_session(session)
        assert sm.get_cached_count() == {}


# ---------------------------------------------------------------------------
# VintedClient with CF fallback integration tests
# ---------------------------------------------------------------------------

class TestVintedClientCFFallback:

    @pytest.mark.asyncio
    async def test_client_without_cf_fallback(self):
        rate_limiter = TokenBucketLimiter(rate=100.0, per=1.0)
        client = VintedClient(rate_limiter=rate_limiter)
        assert client.cf_fallback is None

    @pytest.mark.asyncio
    async def test_client_with_cf_fallback(self):
        rate_limiter = TokenBucketLimiter(rate=100.0, per=1.0)
        cf = CloudflareFallback(worker_url="https://worker.example.com", block_threshold=2, recovery_minutes=10)
        client = VintedClient(rate_limiter=rate_limiter, cf_fallback=cf)
        assert client.cf_fallback is not None
        assert client.cf_fallback.is_configured


# ---------------------------------------------------------------------------
# Telegram settings persistence tests
# ---------------------------------------------------------------------------

class TestTelegramSettingsPersistence:

    @pytest.mark.asyncio
    async def test_active_telegram_user_id_roundtrip(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            await set_active_telegram_user_id(db, 42)
            await db.commit()

        async with session_factory() as db:
            assert await get_active_telegram_user_id(db) == 42

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_clear_active_telegram_user_id_removes_setting(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            await set_active_telegram_user_id(db, 42)
            await db.commit()

        async with session_factory() as db:
            await set_active_telegram_user_id(db, None)
            await db.commit()

        async with session_factory() as db:
            assert await get_active_telegram_user_id(db) is None
            assert await db.get(AppSettings, ACTIVE_TELEGRAM_USER_ID_KEY) is None

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_update_user_chat_id_by_bot_token_updates_matching_user(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            user = User(
                username="alice",
                password_hash="",
                password_salt="",
                telegram_bot_token="bot-token",
                telegram_chat_id="",
            )
            user.set_password("secret123")
            db.add(user)
            await db.commit()

        async with session_factory() as db:
            updated = await update_user_chat_id_by_bot_token(db, "bot-token", "123456")
            await db.commit()
            assert updated is True

        async with session_factory() as db:
            saved_user = await db.get(User, 1)
            assert saved_user is not None
            assert saved_user.telegram_chat_id == "123456"

        await engine.dispose()
