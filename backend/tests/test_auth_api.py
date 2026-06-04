import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.main import app
from app.models import InviteCode, User, UserSession
from app.web import auth as web_auth
from app.web import app_web_dependencies
from app.web.dependencies import get_db


async def _create_user(db_session, username: str = "api_user", password: str = "password") -> User:
    user = User(username=username, telegram_bot_token="", telegram_chat_id="")
    user.set_password(password)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _create_invite(db_session, code: str = "api-register-code") -> InviteCode:
    invite = InviteCode(code=code, max_uses=1, used_count=0, is_active=True)
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    return invite


def _override_db(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FlakyAuthDb:
    def __init__(self, *results):
        self.results = list(results)
        self.execute_calls = 0
        self.rollback_calls = 0

    async def execute(self, statement):
        self.execute_calls += 1
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return _ScalarResult(result)

    async def rollback(self):
        self.rollback_calls += 1


def _disconnect_error() -> DBAPIError:
    return DBAPIError(
        "SELECT user_sessions.id FROM user_sessions WHERE user_sessions.token = :token",
        {},
        RuntimeError("connection was closed in the middle of operation"),
        connection_invalidated=True,
    )


@pytest.mark.asyncio
async def test_auth_api_csrf_login_me_logout_flow(db_session):
    user = await _create_user(db_session)
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_response = await client.get("/api/v1/auth/csrf")
        assert csrf_response.status_code == 200
        csrf_token = csrf_response.json()["csrf_token"]
        assert csrf_token
        assert "api_csrf_seed" in client.cookies

        missing_csrf = await client.post(
            "/api/v1/auth/login",
            json={"username": "api_user", "password": "password"},
        )
        assert missing_csrf.status_code == 403

        failed_login = await client.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": csrf_token},
            json={"username": "api_user", "password": "wrong"},
        )
        assert failed_login.status_code == 401
        assert "session_token" not in client.cookies

        login_response = await client.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": csrf_token},
            json={"username": "api_user", "password": "password"},
        )
        assert login_response.status_code == 200
        login_payload = login_response.json()
        assert login_payload["user"] == {"id": user.id, "username": "api_user", "is_admin": False}
        assert "csrf_token" in login_payload
        assert "password_hash" not in login_response.text
        assert "password_salt" not in login_response.text
        assert "session_token" in client.cookies

        me_response = await client.get("/api/v1/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["user"]["username"] == "api_user"

        logout_response = await client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": login_payload["csrf_token"]},
        )
        assert logout_response.status_code == 200
        assert logout_response.json() == {"status": "ok"}

        logged_out_me = await client.get("/api/v1/auth/me")
        assert logged_out_me.status_code == 401

    sessions = await db_session.execute(select(UserSession).where(UserSession.user_id == user.id))
    assert sessions.scalars().all() == []
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_auth_api_me_requires_session(db_session):
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_current_user_retries_once_after_db_disconnect():
    user = User(id=7, username="retry_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("password")
    session = UserSession(id=1, user_id=user.id, token="session-token")
    db = _FlakyAuthDb(_disconnect_error(), session, user)
    request = type("Request", (), {"cookies": {"session_token": "session-token"}})()

    result = await app_web_dependencies.get_current_user(request, db)

    assert result is user
    assert db.execute_calls == 3
    assert db.rollback_calls == 1


@pytest.mark.asyncio
async def test_primary_get_current_user_retries_once_after_db_disconnect():
    user = User(id=8, username="primary_retry_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("password")
    session = UserSession(id=2, user_id=user.id, token="session-token")
    db = _FlakyAuthDb(_disconnect_error(), session, user)
    request = type("Request", (), {"cookies": {"session_token": "session-token"}})()

    result = await web_auth.get_current_user(request, db)

    assert result is user
    assert db.execute_calls == 3
    assert db.rollback_calls == 1


@pytest.mark.asyncio
async def test_get_current_user_returns_503_after_repeated_db_disconnect():
    db = _FlakyAuthDb(_disconnect_error(), _disconnect_error())
    request = type("Request", (), {"cookies": {"session_token": "session-token"}})()

    with pytest.raises(HTTPException) as exc_info:
        await app_web_dependencies.get_current_user(request, db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database temporarily unavailable"
    assert db.execute_calls == 2
    assert db.rollback_calls == 2


@pytest.mark.asyncio
async def test_primary_get_current_user_returns_503_after_repeated_db_disconnect():
    db = _FlakyAuthDb(_disconnect_error(), _disconnect_error())
    request = type("Request", (), {"cookies": {"session_token": "session-token"}})()

    with pytest.raises(HTTPException) as exc_info:
        await web_auth.get_current_user(request, db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database temporarily unavailable"
    assert db.execute_calls == 2
    assert db.rollback_calls == 2


@pytest.mark.asyncio
async def test_auth_api_register_creates_user_consumes_invite_and_starts_session(db_session):
    invite = await _create_invite(db_session, "api-register-success")
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_response = await client.get("/api/v1/auth/csrf")
        csrf_token = csrf_response.json()["csrf_token"]

        missing_csrf = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "registered_user",
                "password": "password",
                "password_confirm": "password",
                "invite_code": "api-register-success",
            },
        )
        assert missing_csrf.status_code == 403

        response = await client.post(
            "/api/v1/auth/register",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "username": "registered_user",
                "password": "password",
                "password_confirm": "password",
                "invite_code": "api-register-success",
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["user"]["username"] == "registered_user"
        assert payload["user"]["is_admin"] is False
        assert "csrf_token" in payload
        assert "password_hash" not in response.text
        assert "password_salt" not in response.text
        assert "session_token" in client.cookies

        me_response = await client.get("/api/v1/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["user"]["username"] == "registered_user"

    await db_session.refresh(invite)
    assert invite.used_count == 1

    result = await db_session.execute(select(User).where(User.username == "registered_user"))
    user = result.scalar_one()
    assert user.invite_code_id == invite.id
    assert user.password_hash
    assert user.password_salt
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_auth_api_register_rejects_invalid_payloads_without_consuming_invite(db_session):
    await _create_user(db_session, username="existing_api_user")
    invite = await _create_invite(db_session, "api-register-invalid")
    _override_db(db_session)

    async def csrf_for(client: AsyncClient) -> str:
        response = await client.get("/api/v1/auth/csrf")
        return response.json()["csrf_token"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        mismatch = await client.post(
            "/api/v1/auth/register",
            headers={"X-CSRF-Token": await csrf_for(client)},
            json={
                "username": "new_api_user",
                "password": "password",
                "password_confirm": "different",
                "invite_code": "api-register-invalid",
            },
        )
        assert mismatch.status_code == 400

        duplicate = await client.post(
            "/api/v1/auth/register",
            headers={"X-CSRF-Token": await csrf_for(client)},
            json={
                "username": "existing_api_user",
                "password": "password",
                "password_confirm": "password",
                "invite_code": "api-register-invalid",
            },
        )
        assert duplicate.status_code == 409

        invalid_invite = await client.post(
            "/api/v1/auth/register",
            headers={"X-CSRF-Token": await csrf_for(client)},
            json={
                "username": "another_api_user",
                "password": "password",
                "password_confirm": "password",
                "invite_code": "does-not-exist",
            },
        )
        assert invalid_invite.status_code == 400

    await db_session.refresh(invite)
    assert invite.used_count == 0
    app.dependency_overrides.clear()
