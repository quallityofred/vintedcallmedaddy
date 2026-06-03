import pytest
from httpx import ASGITransport, AsyncClient
from datetime import datetime, timezone

from app.main import app
from app.models import Monitor, User
from app.web.dependencies import get_db


async def _create_user(db_session, username: str, password: str = "password") -> User:
    user = User(username=username, telegram_bot_token="", telegram_chat_id="")
    user.set_password(password)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _login_user(client: AsyncClient, username: str, password: str = "password") -> str:
    csrf_resp = await client.get("/api/v1/auth/csrf")
    csrf_token = csrf_resp.json()["csrf_token"]
    login_resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf_token},
        json={"username": username, "password": password},
    )
    return login_resp.json()["csrf_token"]


def _override_db(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session


@pytest.mark.asyncio
async def test_list_monitors_unauthenticated(db_session):
    _override_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/monitors")
        assert response.status_code == 401
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_monitors_user_scoping(db_session):
    user1 = await _create_user(db_session, "mon_user1")
    user2 = await _create_user(db_session, "mon_user2")
    _override_db(db_session)

    # User 1 monitors
    m1 = Monitor(
        user_id=user1.id,
        name="M1",
        original_url="url1",
        params_json="{}",
        domains_json="[]",
        is_active=True,
    )
    # User 2 monitor
    m2 = Monitor(
        user_id=user2.id,
        name="M2",
        original_url="url2",
        params_json="{}",
        domains_json="[]",
        is_active=True,
    )
    db_session.add_all([m1, m2])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "mon_user1")
        response = await client.get("/api/v1/monitors")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "M1"
        assert "password_hash" not in response.text

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_monitor_owner_access(db_session):
    user1 = await _create_user(db_session, "mon_user3")
    user2 = await _create_user(db_session, "mon_user4")
    _override_db(db_session)

    m1 = Monitor(
        user_id=user1.id,
        name="M1",
        original_url="url1",
        params_json="{}",
        domains_json="[]",
        is_active=True,
    )
    db_session.add(m1)
    await db_session.commit()
    await db_session.refresh(m1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Owner access
        await _login_user(client, "mon_user3")
        response = await client.get(f"/api/v1/monitors/{m1.id}")
        assert response.status_code == 200
        assert response.json()["name"] == "M1"

        # Non-owner access (User 2)
        async with AsyncClient(transport=transport, base_url="http://test") as client2:
            await _login_user(client2, "mon_user4")
            response2 = await client2.get(f"/api/v1/monitors/{m1.id}")
            assert response2.status_code == 404

    app.dependency_overrides.clear()
