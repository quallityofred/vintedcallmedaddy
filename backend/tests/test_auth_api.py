import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

import app.app_database as app_database
from app.main import app
from app.models import InviteCode, User, UserSession
from app.web import auth_api_router
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
    def __init__(self, *results, commit_results=()):
        self.results = list(results)
        self.commit_results = list(commit_results)
        self.execute_calls = 0
        self.rollback_calls = 0
        self.commit_calls = 0
        self.added = []

    async def execute(self, statement):
        self.execute_calls += 1
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return _ScalarResult(result)

    async def rollback(self):
        self.rollback_calls += 1

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commit_calls += 1
        if self.commit_results:
            result = self.commit_results.pop(0)
            if isinstance(result, BaseException):
                raise result


class _SlowCommitAuthDb(_FlakyAuthDb):
    async def commit(self):
        self.commit_calls += 1
        await asyncio.sleep(10)


class _FakeSessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        close = getattr(self.db, "close", None)
        if close is not None:
            await close()


class _FakeSessionFactory:
    def __init__(self, *sessions):
        self.sessions = list(sessions)

    def __call__(self):
        return _FakeSessionContext(self.sessions.pop(0))


def _disconnect_error() -> DBAPIError:
    return DBAPIError(
        "SELECT user_sessions.id FROM user_sessions WHERE user_sessions.token = :token",
        {},
        RuntimeError("connection was closed in the middle of operation"),
        connection_invalidated=True,
    )


def _production_like_disconnect_error(*, connection_invalidated: bool = False) -> DBAPIError:
    class ConnectionDoesNotExistError(RuntimeError):
        pass

    orig = ConnectionDoesNotExistError("connection was closed in the middle of operation")
    return DBAPIError(
        "SELECT users.id FROM users WHERE users.username = $1",
        {},
        orig,
        connection_invalidated=connection_invalidated,
    )


def _supabase_pool_capacity_error() -> DBAPIError:
    class InternalServerError(RuntimeError):
        pass

    orig = InternalServerError(
        "(EMAXCONNSESSION) max clients reached in session mode - max clients are limited to pool_size: 15"
    )
    return DBAPIError(
        "SELECT users.id FROM users WHERE users.username = $1",
        {},
        orig,
        connection_invalidated=False,
    )


def test_disconnect_detection_matches_production_wrapped_asyncpg_shape():
    exc = _production_like_disconnect_error(connection_invalidated=False)

    assert app_database.is_db_disconnect_error(exc) is True


def test_capacity_detection_matches_supabase_session_pooler_error():
    exc = _supabase_pool_capacity_error()

    assert app_database.is_db_capacity_error(exc) is True


@pytest.mark.asyncio
async def test_retry_helper_does_not_catch_unrelated_programming_errors():
    db = _FlakyAuthDb()

    async def broken_operation(active_db):
        raise ValueError("programming mistake")

    with pytest.raises(ValueError, match="programming mistake"):
        await app_database.run_db_with_retry(db, broken_operation, operation_name="broken operation")


@pytest.mark.asyncio
async def test_retry_helper_retries_once_after_database_operation_timeout(monkeypatch):
    db = _FlakyAuthDb()
    retry_db = _FlakyAuthDb()
    monkeypatch.setattr(
        app_database,
        "get_settings",
        lambda: SimpleNamespace(db_operation_timeout_seconds=0.01),
    )
    monkeypatch.setattr(app_database, "get_session_factory", lambda: _FakeSessionFactory(retry_db))
    calls = 0

    async def operation(active_db):
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(10)
        return "ok"

    result = await app_database.run_db_with_retry(db, operation, operation_name="timeout operation")

    assert result == "ok"
    assert calls == 2
    assert db.rollback_calls == 1


@pytest.mark.asyncio
async def test_retry_helper_returns_temporary_unavailable_after_repeated_timeout(monkeypatch):
    db = _FlakyAuthDb()
    retry_db = _FlakyAuthDb()
    monkeypatch.setattr(
        app_database,
        "get_settings",
        lambda: SimpleNamespace(db_operation_timeout_seconds=0.01),
    )
    monkeypatch.setattr(app_database, "get_session_factory", lambda: _FakeSessionFactory(retry_db))

    async def operation(active_db):
        await asyncio.sleep(10)

    with pytest.raises(app_database.DatabaseTemporarilyUnavailable):
        await app_database.run_db_with_retry(db, operation, operation_name="timeout operation")

    assert db.rollback_calls == 1
    assert retry_db.rollback_calls == 1


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
async def test_get_current_user_retries_once_after_db_disconnect(monkeypatch):
    user = User(id=7, username="retry_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("password")
    session = UserSession(id=1, user_id=user.id, token="session-token")
    db = _FlakyAuthDb(_production_like_disconnect_error())
    retry_db = _FlakyAuthDb(session, user)
    monkeypatch.setattr(app_database, "get_session_factory", lambda: _FakeSessionFactory(retry_db))
    request = type("Request", (), {"cookies": {"session_token": "session-token"}})()

    result = await app_web_dependencies.get_current_user(request, db)

    assert result is user
    assert db.execute_calls == 1
    assert db.rollback_calls == 1
    assert retry_db.execute_calls == 2


@pytest.mark.asyncio
async def test_primary_get_current_user_retries_once_after_db_disconnect(monkeypatch):
    user = User(id=8, username="primary_retry_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("password")
    session = UserSession(id=2, user_id=user.id, token="session-token")
    db = _FlakyAuthDb(_production_like_disconnect_error())
    retry_db = _FlakyAuthDb(session, user)
    monkeypatch.setattr(app_database, "get_session_factory", lambda: _FakeSessionFactory(retry_db))
    request = type("Request", (), {"cookies": {"session_token": "session-token"}})()

    result = await web_auth.get_current_user(request, db)

    assert result is user
    assert db.execute_calls == 1
    assert db.rollback_calls == 1
    assert retry_db.execute_calls == 2


@pytest.mark.asyncio
async def test_get_current_user_returns_503_after_repeated_db_disconnect(monkeypatch):
    db = _FlakyAuthDb(_production_like_disconnect_error())
    retry_db = _FlakyAuthDb(_production_like_disconnect_error())
    monkeypatch.setattr(app_database, "get_session_factory", lambda: _FakeSessionFactory(retry_db))
    request = type("Request", (), {"cookies": {"session_token": "session-token"}})()

    with pytest.raises(HTTPException) as exc_info:
        await app_web_dependencies.get_current_user(request, db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database temporarily unavailable"
    assert db.execute_calls == 1
    assert db.rollback_calls == 1
    assert retry_db.execute_calls == 1
    assert retry_db.rollback_calls == 1


@pytest.mark.asyncio
async def test_primary_get_current_user_returns_503_after_repeated_db_disconnect(monkeypatch):
    db = _FlakyAuthDb(_production_like_disconnect_error())
    retry_db = _FlakyAuthDb(_production_like_disconnect_error())
    monkeypatch.setattr(app_database, "get_session_factory", lambda: _FakeSessionFactory(retry_db))
    request = type("Request", (), {"cookies": {"session_token": "session-token"}})()

    with pytest.raises(HTTPException) as exc_info:
        await web_auth.get_current_user(request, db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database temporarily unavailable"
    assert db.execute_calls == 1
    assert db.rollback_calls == 1
    assert retry_db.execute_calls == 1
    assert retry_db.rollback_calls == 1


@pytest.mark.asyncio
async def test_primary_get_current_user_returns_503_after_supabase_pool_capacity_error():
    db = _FlakyAuthDb(_supabase_pool_capacity_error())
    request = type("Request", (), {"cookies": {"session_token": "session-token"}})()

    with pytest.raises(HTTPException) as exc_info:
        await web_auth.get_current_user(request, db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database temporarily unavailable"
    assert db.execute_calls == 1
    assert db.rollback_calls == 1


@pytest.mark.asyncio
async def test_login_retries_once_after_db_disconnect_and_succeeds(monkeypatch):
    user = User(id=9, username="login_retry_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("password")
    db = _FlakyAuthDb(_production_like_disconnect_error())
    retry_db = _FlakyAuthDb(user)
    monkeypatch.setattr(app_database, "get_session_factory", lambda: _FakeSessionFactory(retry_db))

    response = await auth_api_router.login(
        auth_api_router.LoginRequest(username="login_retry_user", password="password"),
        db,
    )

    assert response.status_code == 200
    assert db.execute_calls == 1
    assert db.rollback_calls == 1
    assert db.commit_calls == 1
    assert retry_db.execute_calls == 1
    assert retry_db.commit_calls == 0
    assert len(db.added) == 1
    assert isinstance(db.added[0], UserSession)


@pytest.mark.asyncio
async def test_login_returns_503_after_repeated_db_disconnect(monkeypatch):
    db = _FlakyAuthDb(_production_like_disconnect_error())
    retry_db = _FlakyAuthDb(_production_like_disconnect_error())
    monkeypatch.setattr(app_database, "get_session_factory", lambda: _FakeSessionFactory(retry_db))

    with pytest.raises(HTTPException) as exc_info:
        await auth_api_router.login(
            auth_api_router.LoginRequest(username="login_retry_user", password="password"),
            db,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database temporarily unavailable"
    assert db.execute_calls == 1
    assert db.rollback_calls == 1
    assert retry_db.execute_calls == 1
    assert retry_db.rollback_calls == 1
    assert db.commit_calls == 0


@pytest.mark.asyncio
async def test_login_returns_503_after_supabase_pool_capacity_error():
    db = _FlakyAuthDb(_supabase_pool_capacity_error())

    with pytest.raises(HTTPException) as exc_info:
        await auth_api_router.login(
            auth_api_router.LoginRequest(username="login_retry_user", password="password"),
            db,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database temporarily unavailable"
    assert db.execute_calls == 1
    assert db.rollback_calls == 1


@pytest.mark.asyncio
async def test_login_returns_503_when_auth_operation_exceeds_deadline(monkeypatch):
    db = _FlakyAuthDb()
    monkeypatch.setattr(
        auth_api_router,
        "get_settings",
        lambda: SimpleNamespace(auth_db_operation_timeout_seconds=0.01),
    )

    async def stuck_lookup(active_db, *, username: str):
        await asyncio.sleep(10)

    monkeypatch.setattr(auth_api_router, "_lookup_login_user", stuck_lookup)

    with pytest.raises(HTTPException) as exc_info:
        await auth_api_router.login(
            auth_api_router.LoginRequest(username="slow_user", password="password"),
            db,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database temporarily unavailable"


@pytest.mark.asyncio
async def test_login_commit_timeout_returns_503(monkeypatch):
    user = User(id=11, username="login_commit_timeout_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("password")
    db = _SlowCommitAuthDb(user)
    monkeypatch.setattr(
        auth_api_router,
        "get_settings",
        lambda: SimpleNamespace(auth_db_operation_timeout_seconds=0.01),
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth_api_router.login(
            auth_api_router.LoginRequest(username="login_commit_timeout_user", password="password"),
            db,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database temporarily unavailable"


@pytest.mark.asyncio
async def test_auth_login_timing_logs_do_not_include_credentials(caplog):
    db = _FlakyAuthDb(None)
    secret_username = "secret_user_name_for_logs"
    secret_password = "secret-password-for-logs"

    with caplog.at_level("INFO", logger="app.web.auth_api_router"):
        with pytest.raises(HTTPException) as exc_info:
            await auth_api_router.login(
                auth_api_router.LoginRequest(username=secret_username, password=secret_password),
                db,
            )

    assert exc_info.value.status_code == 401
    assert secret_username not in caplog.text
    assert secret_password not in caplog.text
    assert "auth_login_user_lookup_start" in caplog.text


@pytest.mark.asyncio
async def test_login_commit_disconnect_retries_whole_operation_with_fresh_session(monkeypatch):
    user = User(id=10, username="login_commit_retry_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("password")
    db = _FlakyAuthDb(user, commit_results=[_production_like_disconnect_error()])
    retry_db = _FlakyAuthDb(user)
    monkeypatch.setattr(app_database, "get_session_factory", lambda: _FakeSessionFactory(retry_db))

    response = await auth_api_router.login(
        auth_api_router.LoginRequest(username="login_commit_retry_user", password="password"),
        db,
    )

    assert response.status_code == 200
    assert db.execute_calls == 1
    assert db.commit_calls == 1
    assert db.rollback_calls == 1
    assert retry_db.execute_calls == 0
    assert retry_db.commit_calls == 1
    assert len(retry_db.added) == 1


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
