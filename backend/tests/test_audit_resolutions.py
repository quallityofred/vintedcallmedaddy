import asyncio
from collections import Counter
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.logger import log_manager
from app.models import AppSettings, FoundItem, HiddenSeller, InviteCode, Monitor, User, UserSession
from app.scheduler.tasks import process_pending_notifications
from app.telegram.handlers import hide_seller_handler
from app.web.auth import generate_session_token, set_session_cookie
from app.web.csrf import csrf_token_for_session
from app.web.invite_codes import consume_invite_code


async def _create_user_session(db_session, username: str, *, is_admin: bool = False) -> tuple[User, str]:
    user = User(username=username, telegram_bot_token="", telegram_chat_id="", is_admin=is_admin)
    user.set_password("password")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = generate_session_token()
    db_session.add(UserSession(user_id=user.id, token=token))
    await db_session.commit()
    return user, token


def _override_db(db_session) -> None:
    from app.web.dependencies import get_db

    app.dependency_overrides[get_db] = lambda: db_session


@pytest.mark.asyncio
async def test_route_table_has_no_duplicate_registrations():
    pairs = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        methods = tuple(sorted(m for m in methods if m not in {"HEAD", "OPTIONS"}))
        if methods:
            pairs.append((route.path, methods))

    duplicates = {
        (path, methods): count
        for (path, methods), count in Counter(pairs).items()
        if count > 1
    }
    assert duplicates == {}
    assert ("/api/v1/admin/invites", ("GET",)) in pairs
    assert ("/api/v1/admin/invites", ("POST",)) in pairs
    assert ("/api/v1/admin/invites/{invite_id}", ("DELETE",)) in pairs
    assert ("/dashboard", ("GET",)) not in pairs
    assert ("/login", ("GET",)) not in pairs
    assert ("/settings", ("GET",)) not in pairs


@pytest.mark.asyncio
async def test_backend_root_returns_api_info_in_production_without_frontend(monkeypatch):
    import app.app_main as app_main

    monkeypatch.setattr(app_main.settings, "environment", "production")
    monkeypatch.setattr(app_main.settings, "frontend_url", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload == {
        "service": "vintedbot-backend",
        "status": "ok",
        "frontend": None,
        "health": "/health",
        "api_health": "/api/health",
        "api": "/api/v1",
    }


@pytest.mark.asyncio
async def test_backend_root_redirects_to_frontend_in_production(monkeypatch):
    import app.app_main as app_main

    monkeypatch.setattr(app_main.settings, "environment", "production")
    monkeypatch.setattr(app_main.settings, "frontend_url", "https://frontend.example")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "https://frontend.example"


@pytest.mark.asyncio
async def test_backend_root_returns_api_info_in_development(monkeypatch):
    import app.app_main as app_main

    monkeypatch.setattr(app_main.settings, "environment", "development")
    monkeypatch.setattr(app_main.settings, "frontend_url", "")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert response.json()["service"] == "vintedbot-backend"


@pytest.mark.asyncio
async def test_legacy_ui_routes_are_absent():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/dashboard", "/login", "/register", "/settings", "/monitors", "/logs", "/admin/invites"):
            response = await client.get(path, follow_redirects=False)
            assert response.status_code == 404
            assert response.json() == {"detail": "Not found"}


@pytest.mark.asyncio
async def test_health_endpoints_remain_public():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        api_health = await client.get("/api/health")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "vinted-monitor"}
    assert api_health.status_code == 200
    assert api_health.json()["status"] == "ok"
    assert "scheduler_jobs" in api_health.json()
    assert "bots_running" in api_health.json()


@pytest.mark.asyncio
async def test_settings_api_persists_admin_scraper_settings(db_session):
    user, token = await _create_user_session(db_session, "settings_user", is_admin=True)
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("session_token", token)
        response = await client.patch(
            "/api/v1/settings/scraper",
            headers={"X-CSRF-Token": csrf_token_for_session(token)},
            json={
                "proxies": "http://proxy.example:8080",
                "sessions_per_domain": 4,
                "rate_limit_per_minute": 9,
                "check_interval_seconds": 180,
                "offpeak_interval_multiplier": 2.2,
                "night_interval_multiplier": 4.5,
                "peak_start_hour": 7,
                "peak_end_hour": 22,
            },
        )
        assert response.status_code == 200
        assert "http://proxy.example:8080" not in response.text
        response = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            headers={"X-CSRF-Token": csrf_token_for_session(token)},
            json={
                "cf_worker_url": "https://worker.example.workers.dev",
                "cf_worker_block_threshold": 3,
                "cf_worker_recovery_minutes": 15,
            },
        )
        assert response.status_code == 200

    result = await db_session.execute(select(AppSettings).where(AppSettings.key == "rate_limit_per_minute"))
    assert result.scalar_one().value == "9"
    result = await db_session.execute(select(AppSettings).where(AppSettings.key == "cf_worker_url"))
    assert result.scalar_one().value == "https://worker.example.workers.dev"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_settings_api_masks_saved_telegram_credentials(db_session):
    user, token = await _create_user_session(db_session, "masked_settings_user")
    user.telegram_bot_token = "123456:SECRET-TOKEN"
    user.telegram_chat_id = "987654321"
    await db_session.commit()
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("session_token", token)
        response = await client.get("/api/v1/settings")
        assert response.status_code == 200
        assert "123456:SECRET-TOKEN" not in response.text
        assert "987654321" not in response.text
        assert "******OKEN" in response.text
        assert "******4321" in response.text
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_invite_routes_are_registered_and_admin_only(db_session):
    admin, admin_token = await _create_user_session(db_session, "admin_user_2", is_admin=True)
    _, user_token = await _create_user_session(db_session, "regular_user_2", is_admin=False)
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Non-admin access
        client.cookies.set("session_token", user_token)
        assert (await client.get("/api/v1/admin/invites")).status_code == 403

        # Admin access
        client.cookies.set("session_token", admin_token)
        assert (await client.get("/api/v1/admin/invites")).status_code == 200
        
        # Test creation
        response = await client.post(
            "/api/v1/admin/invites",
            headers={"X-CSRF-Token": csrf_token_for_session(admin_token)},
            json={"code": "audit-code-2", "max_uses": 2},
        )
        assert response.status_code == 200

    result = await db_session.execute(select(InviteCode).where(InviteCode.code == "audit-code-2"))
    invite = result.scalar_one()
    assert invite.created_by_id == admin.id
    assert invite.max_uses == 2
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_logs_reject_non_admin(db_session):
    user, user_token = await _create_user_session(db_session, "logs_user")
    _, admin_token = await _create_user_session(db_session, "logs_admin", is_admin=True)
    with log_manager.lock:
        log_manager.system_buffer.clear()
        log_manager.user_buffers.clear()
    log_manager.add_log(None, "system secret-ish operational event")
    log_manager.add_log(user.id, "user event")

    _override_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("session_token", user_token)
        response = await client.get("/api/v1/admin/logs")
        assert response.status_code == 403

        client.cookies.set("session_token", admin_token)
        response = await client.get("/api/v1/admin/logs")
        assert response.status_code == 200
        assert response.json()["message"] == "Logs access is restricted for security."
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_hide_seller_callback_persists_user_scoped_row(db_session):
    user = User(username="telegram_user", telegram_bot_token="bot-token", telegram_chat_id="42")
    user.set_password("password")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    callback = MagicMock()
    callback.data = "hide:987"
    callback.bot.token = "bot-token"
    callback.answer = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()

    with patch("app.telegram.handlers.AsyncSessionLocal", side_effect=session_factory):
        await hide_seller_handler(callback)

    result = await db_session.execute(
        select(HiddenSeller).where(HiddenSeller.user_id == user.id, HiddenSeller.seller_id == 987)
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_notification_worker_contains_invalid_token_failure(db_session):
    user = User(username="notify_user", telegram_bot_token="bad-token", telegram_chat_id="123")
    user.set_password("password")
    monitor = Monitor(
        user_id=None,
        name="m",
        original_url="u",
        params_json="{}",
        domains_json='["vinted.pl"]',
        last_check_at=datetime.now(timezone.utc),
    )
    db_session.add_all([user, monitor])
    await db_session.commit()
    monitor.user_id = user.id
    item = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=123456,
        domain="vinted.pl",
        title="item",
        price=1.0,
        currency="PLN",
        brand="",
        size="",
        condition="",
        photo_url="",
        item_url="",
        seller_id=1,
        notified=False,
    )
    db_session.add(item)
    await db_session.commit()
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory), patch(
        "app.telegram.bot.get_or_create_bot", side_effect=ValueError("invalid token")
    ):
        await process_pending_notifications()

    await db_session.refresh(item)
    assert item.notified is False


@pytest.mark.asyncio
async def test_invite_code_consumption_is_guarded(db_session):
    invite = InviteCode(code="single-use-audit", max_uses=1, used_count=0, is_active=True)
    db_session.add(invite)
    await db_session.commit()

    first = await consume_invite_code(db_session, "single-use-audit")
    second = await consume_invite_code(db_session, "single-use-audit")

    assert first is not None
    assert second is None
    await db_session.commit()
    await db_session.refresh(invite)
    assert invite.used_count == 1


@pytest.mark.asyncio
async def test_csrf_required_for_authenticated_state_change(db_session):
    _, token = await _create_user_session(db_session, "csrf_user")
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("session_token", token)
        response = await client.post("/api/v1/telegram/start")
        assert response.status_code == 403
    app.dependency_overrides.clear()


def test_session_cookie_secure_in_production(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    response = MagicMock()
    set_session_cookie(response, "token")
    kwargs = response.set_cookie.call_args.kwargs
    assert kwargs["secure"] is True
    assert kwargs["httponly"] is True


def test_env_example_documents_secret_key():
    content = open(".env.example", encoding="utf-8").read()
    assert "SECRET_KEY=" in content
    assert "SESSION_COOKIE_SECURE=" in content
