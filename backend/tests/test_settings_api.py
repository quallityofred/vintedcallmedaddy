import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AppSettings, User, UserSession
from app.web import settings_api_router
from app.web.csrf import csrf_token_for_session
from app.web.dependencies import get_db
from app.web.app_web_dependencies import BotLifecycleResult


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

    async def fake_stop_bot(token: str) -> BotLifecycleResult:
        stopped_tokens.append(token)
        return BotLifecycleResult(ok=True, state="stopped", message="Telegram bot stopped", running=False)

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
        cf_payload = cf_response.json()["cloudflare_worker"]
        assert cf_payload == {
            "url": "https://worker.example.com/proxy",
            "configured": True,
            "block_threshold": 4,
            "recovery_minutes": 15,
            "mode": "auto",
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
async def test_cloudflare_worker_mode_persists_through_patch_and_get(db_session):
    user = await _create_user(db_session, username="cf_mode_user")
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, "cf-mode-session")
    async with client:
        settings_response = await client.get("/api/v1/settings")
        assert settings_response.status_code == 200
        assert settings_response.json()["cloudflare_worker"]["mode"] == "auto"

        direct_response = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            headers={"X-CSRF-Token": csrf_token},
            json={"cf_worker_mode": "direct"},
        )
        assert direct_response.status_code == 200
        assert direct_response.json()["cloudflare_worker"]["mode"] == "direct"

        get_direct = await client.get("/api/v1/settings")
        assert get_direct.status_code == 200
        assert get_direct.json()["cloudflare_worker"]["mode"] == "direct"

        auto_response = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            headers={"X-CSRF-Token": csrf_token},
            json={"cf_worker_mode": "auto"},
        )
        assert auto_response.status_code == 200
        assert auto_response.json()["cloudflare_worker"]["mode"] == "auto"

        get_auto = await client.get("/api/v1/settings")
        assert get_auto.status_code == 200
        assert get_auto.json()["cloudflare_worker"]["mode"] == "auto"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cloudflare_worker_mode_validation_and_url_requirement(db_session):
    user = await _create_user(db_session, username="cf_mode_validation_user")
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, "cf-mode-validation-session")
    async with client:
        missing_csrf = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            json={"cf_worker_mode": "direct"},
        )
        assert missing_csrf.status_code == 403

        invalid_mode = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            headers={"X-CSRF-Token": csrf_token},
            json={"cf_worker_mode": "invalid"},
        )
        assert invalid_mode.status_code == 422

        worker_without_url = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            headers={"X-CSRF-Token": csrf_token},
            json={"cf_worker_mode": "worker"},
        )
        assert worker_without_url.status_code == 422
        assert worker_without_url.json()["detail"] == "Worker mode requires a configured Worker URL"

        worker_with_url = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "cf_worker_url": "https://worker.example.com/proxy/",
                "cf_worker_mode": "worker",
            },
        )
        assert worker_with_url.status_code == 200
        assert worker_with_url.json()["cloudflare_worker"]["mode"] == "worker"

        get_worker = await client.get("/api/v1/settings")
        assert get_worker.status_code == 200
        assert get_worker.json()["cloudflare_worker"]["mode"] == "worker"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cloudflare_worker_mode_only_patch_accepts_omitted_numeric_fields(db_session):
    user = await _create_user(db_session, username="cf_mode_numeric_user")
    user.cf_worker_block_threshold = 5
    user.cf_worker_recovery_minutes = 20
    await db_session.commit()
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, "cf-mode-numeric-session")
    async with client:
        response = await client.patch(
            "/api/v1/settings/cloudflare-worker",
            headers={"X-CSRF-Token": csrf_token},
            json={"cf_worker_mode": "direct"},
        )

    assert response.status_code == 200
    payload = response.json()["cloudflare_worker"]
    assert payload["mode"] == "direct"
    assert payload["block_threshold"] == 5
    assert payload["recovery_minutes"] == 20
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_telegram_api_controls_are_user_scoped_and_do_not_expose_token(db_session, monkeypatch):
    running: set[str] = set()
    sent_tests: list[tuple[str, str]] = []

    async def fake_start_bot(token: str, owner_user_id: int | None = None) -> str:
        running.add(token)
        return "started"

    async def fake_stop_bot(token: str) -> BotLifecycleResult:
        running.discard(token)
        return BotLifecycleResult(ok=True, state="stopped", message="Telegram bot stopped", running=False)

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


@pytest.mark.asyncio
async def test_telegram_stop_timeout_returns_safe_failure(db_session, monkeypatch):
    async def fake_stop_bot(token: str) -> BotLifecycleResult:
        return BotLifecycleResult(
            ok=False,
            state="stop_timeout",
            message="Telegram bot did not stop within the timeout. It may still be shutting down.",
            running=True,
        )

    def fake_is_bot_running(token: str) -> bool:
        return True

    monkeypatch.setattr(settings_api_router, "stop_bot", fake_stop_bot)
    monkeypatch.setattr(settings_api_router, "is_bot_running", fake_is_bot_running)

    user = await _create_user(
        db_session,
        username="telegram_stop_timeout_user",
        telegram_bot_token="telegram-secret-abcdef",
        telegram_chat_id="555123456",
    )
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, "telegram-stop-timeout-session")
    async with client:
        response = await client.post(
            "/api/v1/telegram/stop",
            headers={"X-CSRF-Token": csrf_token},
        )

    payload = response.json()
    assert response.status_code == 503
    assert payload["ok"] is False
    assert payload["code"] == "stop_timeout"
    assert payload["telegram"]["bot_running"] is True
    assert "telegram-secret-abcdef" not in response.text
    assert "555123456" not in response.text
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_telegram_test_returns_safe_error_when_credentials_missing(db_session):
    user = await _create_user(db_session, username="telegram_missing_credentials")
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, "telegram-missing-session")
    async with client:
        response = await client.post(
            "/api/v1/telegram/test",
            headers={"X-CSRF-Token": csrf_token},
        )

    payload = response.json()
    assert response.status_code == 400
    assert payload["code"] == "telegram_credentials_missing"
    assert payload["detail"] == "Telegram credentials are not configured. Add your bot token and chat ID first."
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "status_code", "code", "detail"),
    [
        (
            ValueError("invalid literal for int() with base 10"),
            400,
            "telegram_invalid_chat_id",
            "Telegram chat ID looks invalid. Check the chat ID and save it again.",
        ),
        (
            RuntimeError("Unauthorized"),
            400,
            "telegram_invalid_token",
            "Telegram bot token looks invalid. Check the token from BotFather and save it again.",
        ),
        (
            RuntimeError("Bad Request: chat not found"),
            400,
            "telegram_chat_not_found",
            "Telegram chat was not found. Open Telegram, start the bot, then try again.",
        ),
        (
            RuntimeError("Forbidden: bot was blocked by the user"),
            403,
            "telegram_bot_blocked",
            "The bot cannot message this chat. Make sure the bot is not blocked and has access to the chat.",
        ),
        (
            RuntimeError("Conflict: terminated by other getUpdates request"),
            409,
            "telegram_bot_busy",
            "Telegram bot is busy or already running elsewhere. Stop other bot sessions/webhooks and try again. Another process may already be using this bot token.",
        ),
        (
            TimeoutError("timed out"),
            503,
            "telegram_unavailable",
            "Telegram is unavailable or timed out. Try again in a moment.",
        ),
        (
            RuntimeError("Too Many Requests: retry after 30"),
            429,
            "telegram_rate_limited",
            "Telegram rate limit reached. Wait a bit before trying again.",
        ),
        (
            RuntimeError("unexpected telegram failure"),
            502,
            "telegram_test_failed",
            "Telegram test message failed. Check your bot token, chat ID, and bot access, then try again.",
        ),
    ],
)
async def test_telegram_test_classifies_safe_failures(
    db_session,
    monkeypatch,
    exc: Exception,
    status_code: int,
    code: str,
    detail: str,
):
    async def fake_send_telegram_test_message(token: str, chat_id: str) -> None:
        raise exc

    monkeypatch.setattr(
        settings_api_router,
        "_send_telegram_test_message",
        fake_send_telegram_test_message,
    )

    user = await _create_user(
        db_session,
        username=f"telegram_failure_{code}",
        telegram_bot_token="telegram-secret-abcdef",
        telegram_chat_id="555123456",
    )
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, f"telegram-failure-session-{code}")
    async with client:
        response = await client.post(
            "/api/v1/telegram/test",
            headers={"X-CSRF-Token": csrf_token},
        )

    payload = response.json()
    assert response.status_code == status_code
    assert payload == {"ok": False, "code": code, "detail": detail}
    assert "telegram-secret-abcdef" not in response.text
    assert "555123456" not in response.text
    app.dependency_overrides.clear()
