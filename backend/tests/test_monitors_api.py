import pytest
from httpx import ASGITransport, AsyncClient
from datetime import datetime, timezone
import json

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
    user1 = await _create_user(db_session, "mon_mut_user1")
    user2 = await _create_user(db_session, "mon_mut_user2")
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
        await _login_user(client, "mon_mut_user1")
        response = await client.get("/api/v1/monitors")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "M1"
        assert "password_hash" not in response.text

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_monitor_success(db_session):
    await _create_user(db_session, "mon_mut_user3")
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_mut_user3")
        
        payload = {
            "name": "New Monitor",
            "url": "https://www.vinted.fr/catalog?search_text=nike",
            "interval_sec": 300,
            "domains": ["vinted.fr"]
        }
        response = await client.post(
            "/api/v1/monitors",
            headers={"X-CSRF-Token": csrf_token},
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Monitor"
        assert data["interval_sec"] == 300
        assert data["is_active"] is True

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_monitor_owner_only(db_session):
    user1 = await _create_user(db_session, "mon_mut_user4")
    user2 = await _create_user(db_session, "mon_mut_user5")
    _override_db(db_session)

    m1 = Monitor(
        user_id=user1.id,
        name="Old Name",
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
        # User 2 tries to update User 1's monitor
        csrf_token2 = await _login_user(client, "mon_mut_user5")
        response = await client.patch(
            f"/api/v1/monitors/{m1.id}",
            headers={"X-CSRF-Token": csrf_token2},
            json={"name": "Stolen Name"}
        )
        assert response.status_code == 404

        # User 1 updates own monitor
        async with AsyncClient(transport=transport, base_url="http://test") as client1:
            csrf_token1 = await _login_user(client1, "mon_mut_user4")
            response = await client1.patch(
                f"/api/v1/monitors/{m1.id}",
                headers={"X-CSRF-Token": csrf_token1},
                json={"name": "New Name", "is_active": False}
            )
            assert response.status_code == 200
            assert response.json()["name"] == "New Name"
            assert response.json()["is_active"] is False

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_monitor_owner_only(db_session):
    user1 = await _create_user(db_session, "mon_mut_user6")
    user2 = await _create_user(db_session, "mon_mut_user7")
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
        # User 2 tries to delete User 1's monitor
        csrf_token2 = await _login_user(client, "mon_mut_user7")
        response = await client.delete(
            f"/api/v1/monitors/{m1.id}",
            headers={"X-CSRF-Token": csrf_token2}
        )
        assert response.status_code == 404

        # User 1 deletes own monitor
        async with AsyncClient(transport=transport, base_url="http://test") as client1:
            csrf_token1 = await _login_user(client1, "mon_mut_user6")
            response = await client1.delete(
                f"/api/v1/monitors/{m1.id}",
                headers={"X-CSRF-Token": csrf_token1}
            )
            assert response.status_code == 204

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_bulk_delete_monitors(db_session):
    user1 = await _create_user(db_session, "mon_mut_user8")
    user2 = await _create_user(db_session, "mon_mut_user9")
    _override_db(db_session)

    m1 = Monitor(user_id=user1.id, name="M1", original_url="u1", params_json="{}", domains_json="[]")
    m2 = Monitor(user_id=user1.id, name="M2", original_url="u2", params_json="{}", domains_json="[]")
    m3 = Monitor(user_id=user2.id, name="M3", original_url="u3", params_json="{}", domains_json="[]")
    db_session.add_all([m1, m2, m3])
    await db_session.commit()
    await db_session.refresh(m1)
    await db_session.refresh(m2)
    await db_session.refresh(m3)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_mut_user8")
        
        # Try to delete m1, m2 (own) and m3 (someone else's)
        payload = {"monitor_ids": [m1.id, m2.id, m3.id, 9999]}
        response = await client.post(
            "/api/v1/monitors/bulk-delete",
            headers={"X-CSRF-Token": csrf_token},
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 2
        assert set(data["not_found_or_forbidden_ids"]) == {m3.id, 9999}

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pause_resume_monitor(db_session):
    user = await _create_user(db_session, "mon_mut_user10")
    _override_db(db_session)

    m1 = Monitor(user_id=user.id, name="M1", original_url="u1", params_json="{}", domains_json="[]", is_active=True)
    db_session.add(m1)
    await db_session.commit()
    await db_session.refresh(m1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "mon_mut_user10")
        
        # Pause
        response = await client.post(f"/api/v1/monitors/{m1.id}/pause", headers={"X-CSRF-Token": csrf_token})
        assert response.status_code == 200
        assert response.json()["is_active"] is False
        
        # Resume
        response = await client.post(f"/api/v1/monitors/{m1.id}/resume", headers={"X-CSRF-Token": csrf_token})
        assert response.status_code == 200
        assert response.json()["is_active"] is True

    app.dependency_overrides.clear()
