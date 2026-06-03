import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AppSettings, User, UserSession
from app.web import settings_api_router
from app.web.csrf import csrf_token_for_session
from app.web.dependencies import get_db


async def _create_user(
    db_session,
    username: str,
    password: str = "password",
    is_admin: bool = False,
    telegram_bot_token: str = "",
    telegram_chat_id: str = "",
) -> User:
    user = User(
        username=username,
        is_admin=is_admin,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )
    user.set_password(password)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _create_session(db_session, user: User, token: str) -> str:
    db_session.add(UserSession(user_id=user.id, token=token))
    await db_session.commit()
    return token


def _override_db(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session


async def _authenticated_client(user: User, db_session, token: str):
    session_token = await _create_session(db_session, user, token)
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    client.cookies.set("session_token", session_token)
    return client, csrf_token_for_session(session_token)


@pytest.mark.asyncio
async def test_settings_api_requires_session(db_session):
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/settings")

    assert response.status_code == 401
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_settings_api_masks_and_updates_user_telegram_credentials(db_session, monkeypatch):
    stopped_tokens: list[str] = []

    async def fake_stop_bot(token: str) -> None:
        stopped_tokens.append(token)

    monkeypatch.setattr(settings_api_router, "stop_bot", fake_stop_bot)

    user = await _create_user(
        db_session,
        username="settings_api_user",
        telegram_bot_token="secret-token-abcdef",
        telegram_chat_id="9876543210",
    )
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, "settings-api-session")
    async with client:
        response = await client.get("/api/v1/settings")
        assert response.status_code == 200
        payload = response.json()
        assert payload["telegram"]["token_configured"] is True
        assert payload["telegram"]["token_masked"].endswith("cdef")
        assert payload["telegram"]["chat_id_configured"] is True
        assert "secret-token-abcdef" not in response.text
        assert "9876543210" not in response.text
        assert "global_settings" not in payload

        missing_csrf = await client.patch(
            "/api/v1/settings/telegram",
            json={"telegram_bot_token": "new-token-123456"},
        )
        assert missing_csrf.status_code == 403

        update_response = await client.patch(
            "/api/v1/settings/telegram",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "telegram_bot_token": "new-token-123456",
                "telegram_chat_id": "123456789",
            },
        )
        assert update_response.status_code == 200
        assert "new-token-123456" not in update_response.text
        assert "123456789" not in update_response.text
        assert update_response.json()["telegram"]["token_masked"].endswith("3456")

    await db_session.refresh(user)
    assert user.telegram_bot_token == "new-token-123456"
    assert user.telegram_chat_id == "123456789"
    assert stopped_tokens == ["secret-token-abcdef"]
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_settings_api_admin_updates_global_cf_worker_and_scraper_settings(db_session, monkeypatch):
    applied_settings: list[dict[str, str]] = []

    async def fake_apply_global_settings_to_runtime(saved: dict[str, str], scraper_client=None) -> None:
        applied_settings.append(dict(saved))

    monkeypatch.setattr(
        settings_api_router,
        "apply_global_settings_to_runtime",
        fake_apply_global_settings_to_runtime,
    )

    admin = await _create_user(db_session, username="settings_api_admin", is_admin=True)
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(admin, db_session, "settings-api-admin-session")
    async with client:
        settings_response = await client.get("/api/v1/settings")
        assert settings_response.status_code == 200
        assert settings_response.json()["can_edit_global_settings"] is True
        assert "global_settings" in settings_response.json()

        invalid_url = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            headers={"X-CSRF-Token": csrf_token},
            json={"cf_worker_url": "not-a-url"},
        )
        assert invalid_url.status_code == 422

        cf_response = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "cf_worker_url": "https://worker.example.com/proxy/",
                "cf_worker_block_threshold": 4,
                "cf_worker_recovery_minutes": 15,
            },
        )
        assert cf_response.status_code == 200
        cf_payload = cf_response.json()["global_settings"]["cloudflare_worker"]
        assert cf_payload == {
            "url": "https://worker.example.com/proxy",
            "configured": True,
            "block_threshold": 4,
            "recovery_minutes": 15,
        }

        proxy_url = "http://user:pass@proxy.local:8080"
        scraper_response = await client.patch(
            "/api/v1/settings/scraper",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "proxies": proxy_url,
                "sessions_per_domain": 5,
                "rate_limit_per_minute": 12,
                "check_interval_seconds": 180,
                "offpeak_interval_multiplier": 3.0,
                "night_interval_multiplier": 6.0,
                "peak_start_hour": 9,
                "peak_end_hour": 22,
            },
        )
        assert scraper_response.status_code == 200
        scraper_payload = scraper_response.json()["global_settings"]["scraper"]
        assert scraper_payload["proxies_configured"] is True
        assert proxy_url not in scraper_response.text
        assert scraper_payload["sessions_per_domain"] == 5
        assert scraper_payload["rate_limit_per_minute"] == 12
        assert scraper_payload["check_interval_seconds"] == 180

    result = await db_session.execute(select(AppSettings).where(AppSettings.key == "proxies"))
    assert result.scalar_one().value == "http://user:pass@proxy.local:8080"
    assert applied_settings[-1]["proxies"] == "http://user:pass@proxy.local:8080"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_settings_api_rejects_non_admin_global_updates(db_session):
    user = await _create_user(db_session, username="settings_api_non_admin")
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, "settings-api-non-admin-session")
    async with client:
        response = await client.patch(
            "/api/v1/settings/scraper",
            headers={"X-CSRF-Token": csrf_token},
            json={"rate_limit_per_minute": 10},
        )

    assert response.status_code == 403
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_telegram_api_controls_are_user_scoped_and_do_not_expose_token(db_session, monkeypatch):
    running: set[str] = set()
    sent_tests: list[tuple[str, str]] = []

    async def fake_start_bot(token: str, owner_user_id: int | None = None) -> str:
        running.add(token)
        return "started"

    async def fake_stop_bot(token: str) -> None:
        running.discard(token)

    def fake_is_bot_running(token: str) -> bool:
        return token in running

    async def fake_send_telegram_test_message(token: str, chat_id: str) -> None:
        sent_tests.append((token, chat_id))

    monkeypatch.setattr(settings_api_router, "start_bot", fake_start_bot)
    monkeypatch.setattr(settings_api_router, "stop_bot", fake_stop_bot)
    monkeypatch.setattr(settings_api_router, "is_bot_running", fake_is_bot_running)
    monkeypatch.setattr(
        settings_api_router,
        "_send_telegram_test_message",
        fake_send_telegram_test_message,
    )

    user = await _create_user(
        db_session,
        username="telegram_api_user",
        telegram_bot_token="telegram-secret-abcdef",
        telegram_chat_id="555123456",
    )
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, "telegram-api-session")
    async with client:
        status_response = await client.get("/api/v1/telegram/status")
        assert status_response.status_code == 200
        assert status_response.json()["telegram"]["bot_running"] is False
        assert "telegram-secret-abcdef" not in status_response.text

        start_response = await client.post(
            "/api/v1/telegram/start",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert start_response.status_code == 200
        assert start_response.json()["telegram"]["bot_running"] is True
        assert "telegram-secret-abcdef" not in start_response.text

        test_response = await client.post(
            "/api/v1/telegram/test",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert test_response.status_code == 200
        assert sent_tests == [("telegram-secret-abcdef", "555123456")]
        assert "telegram-secret-abcdef" not in test_response.text

        stop_response = await client.post(
            "/api/v1/telegram/stop",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert stop_response.status_code == 200
        assert stop_response.json()["telegram"]["bot_running"] is False
        assert "telegram-secret-abcdef" not in stop_response.text

    app.dependency_overrides.clear()
