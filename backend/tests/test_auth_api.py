import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import User, UserSession
from app.web.dependencies import get_db


async def _create_user(db_session, username: str = "api_user", password: str = "password") -> User:
    user = User(username=username, telegram_bot_token="", telegram_chat_id="")
    user.set_password(password)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _override_db(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session


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
