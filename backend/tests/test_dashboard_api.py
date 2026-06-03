import pytest
from httpx import ASGITransport, AsyncClient
from datetime import datetime, timezone

from app.main import app
from app.models import Monitor, FoundItem, User
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
async def test_dashboard_stats_api_unauthenticated(db_session):
    _override_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/dashboard/stats")
        assert response.status_code == 401
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dashboard_stats_api_authenticated_user_scoping(db_session):
    user1 = await _create_user(db_session, "user1")
    user2 = await _create_user(db_session, "user2")
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
    m2 = Monitor(
        user_id=user1.id,
        name="M2",
        original_url="url2",
        params_json="{}",
        domains_json="[]",
        is_active=False,
    )
    db_session.add_all([m1, m2])
    await db_session.commit()
    await db_session.refresh(m1)

    # Found items for User 1
    f1 = FoundItem(
        monitor_id=m1.id,
        vinted_item_id=123,
        domain="fr",
        title="T1",
        price=10.0,
        currency="EUR",
        brand="B",
        size="S",
        condition="C",
        photo_url="P",
        item_url="I",
        seller_id=456,
        found_at=datetime.now(timezone.utc),
    )
    db_session.add(f1)

    # User 2 monitor
    m3 = Monitor(
        user_id=user2.id,
        name="M3",
        original_url="url3",
        params_json="{}",
        domains_json="[]",
        is_active=True,
    )
    db_session.add(m3)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "user1")
        response = await client.get("/api/v1/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["active_monitors_count"] == 1
        assert data["paused_monitors_count"] == 1
        assert data["items_today_count"] == 1
        assert data["total_items_count"] == 1
        assert data["last_found_at"] is not None
        assert "password_hash" not in response.text

        # Test User 2 (separate client to clear cookies)
        async with AsyncClient(transport=transport, base_url="http://test") as client2:
            await _login_user(client2, "user2")
            response2 = await client2.get("/api/v1/dashboard/stats")
            assert response2.status_code == 200
            data2 = response2.json()
            assert data2["active_monitors_count"] == 1
            assert data2["paused_monitors_count"] == 0
            assert data2["items_today_count"] == 0
            assert data2["total_items_count"] == 0
            assert data2["last_found_at"] is None

    app.dependency_overrides.clear()
