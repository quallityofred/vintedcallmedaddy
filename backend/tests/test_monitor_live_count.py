import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.models import Monitor, User, FoundItem
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
    await client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf_token},
        json={"username": username, "password": password},
    )
    # Refresh CSRF after login
    csrf_resp = await client.get("/api/v1/auth/csrf")
    return csrf_resp.json()["csrf_token"]

def _override_db(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session

@pytest.mark.asyncio
async def test_monitors_list_uses_live_found_item_count(db_session):
    user = await _create_user(db_session, "live_count_user")
    _override_db(db_session)

    # Monitor with stale cached count
    m = Monitor(
        user_id=user.id,
        name="Stale Monitor",
        original_url="url1",
        params_json="{}",
        domains_json="[]",
        items_found_count=999, # STALE
        is_active=True,
    )
    db_session.add(m)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "live_count_user")
        response = await client.get("/api/v1/monitors")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        # Should return 0 because FoundItem table is empty
        assert data[0]["items_found_count"] == 0

    # Add live found items
    fi1 = FoundItem(
        monitor_id=m.id,
        vinted_item_id=1,
        domain="vinted.pl",
        title="Item 1",
        price=10.0,
        currency="PLN",
        brand="Brand",
        size="S",
        condition="New",
        photo_url="url",
        item_url="url",
        seller_id=1,
    )
    fi2 = FoundItem(
        monitor_id=m.id,
        vinted_item_id=2,
        domain="vinted.pl",
        title="Item 2",
        price=20.0,
        currency="PLN",
        brand="Brand",
        size="S",
        condition="New",
        photo_url="url",
        item_url="url",
        seller_id=1,
    )
    db_session.add_all([fi1, fi2])
    await db_session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "live_count_user")
        response = await client.get("/api/v1/monitors")
        assert response.status_code == 200
        data = response.json()
        assert data[0]["items_found_count"] == 2

    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_monitor_detail_uses_live_found_item_count(db_session):
    user = await _create_user(db_session, "live_detail_user")
    _override_db(db_session)

    m = Monitor(
        user_id=user.id,
        name="Detail Monitor",
        original_url="url1",
        params_json="{}",
        domains_json="[]",
        items_found_count=50, # STALE
        is_active=True,
    )
    db_session.add(m)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "live_detail_user")
        
        # Detail endpoint
        response = await client.get(f"/api/v1/monitors/{m.id}")
        assert response.status_code == 200
        assert response.json()["items_found_count"] == 0

        # Debug endpoint
        response = await client.get(f"/api/v1/monitors/{m.id}/debug")
        assert response.status_code == 200
        assert response.json()["items_found_count"] == 0

    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_monitors_list_counts_are_user_scoped(db_session):
    user1 = await _create_user(db_session, "scoped_user1")
    user2 = await _create_user(db_session, "scoped_user2")
    _override_db(db_session)

    m1 = Monitor(user_id=user1.id, name="M1", original_url="u1", params_json="{}", domains_json="[]")
    m2 = Monitor(user_id=user2.id, name="M2", original_url="u2", params_json="{}", domains_json="[]")
    db_session.add_all([m1, m2])
    await db_session.commit()

    # FoundItem for user 2's monitor
    fi = FoundItem(
        monitor_id=m2.id,
        vinted_item_id=1,
        domain="vinted.pl",
        title="T", price=1.0, currency="P", brand="B", size="S", condition="C", photo_url="P", item_url="I", seller_id=1
    )
    db_session.add(fi)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "scoped_user1")
        response = await client.get("/api/v1/monitors")
        assert response.json()[0]["items_found_count"] == 0

    app.dependency_overrides.clear()
