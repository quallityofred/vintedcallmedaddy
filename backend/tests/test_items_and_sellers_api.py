import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.models import Monitor, FoundItem, HiddenSeller, User
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
async def test_items_api_scoping(db_session):
    user1 = await _create_user(db_session, "user1")
    user2 = await _create_user(db_session, "user2")
    _override_db(db_session)

    m1 = Monitor(user_id=user1.id, name="M1", original_url="u1", params_json="{}", domains_json="[]")
    m2 = Monitor(user_id=user2.id, name="M2", original_url="u2", params_json="{}", domains_json="[]")
    db_session.add_all([m1, m2])
    await db_session.commit()

    f1 = FoundItem(monitor_id=m1.id, vinted_item_id=1, domain="v.fr", title="T1", price=1.0, currency="EUR", brand="B", size="S", condition="C", photo_url="p", item_url="u", seller_id=10)
    f2 = FoundItem(monitor_id=m2.id, vinted_item_id=2, domain="v.fr", title="T2", price=2.0, currency="EUR", brand="B", size="S", condition="C", photo_url="p", item_url="u", seller_id=20)
    db_session.add_all([f1, f2])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "user1")
        response = await client.get("/api/v1/items")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "T1"

    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_hidden_sellers_api(db_session):
    user = await _create_user(db_session, "user_hidden")
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "user_hidden")
        
        # Add hidden seller
        payload = {"seller_id": 123}
        response = await client.post("/api/v1/hidden-sellers", headers={"X-CSRF-Token": csrf_token}, json=payload)
        assert response.status_code == 200
        
        # List hidden sellers
        response = await client.get("/api/v1/hidden-sellers")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["seller_id"] == 123
        
        # Delete hidden seller
        response = await client.delete("/api/v1/hidden-sellers/123", headers={"X-CSRF-Token": csrf_token})
        assert response.status_code == 204
        
        # Verify empty
        response = await client.get("/api/v1/hidden-sellers")
        assert len(response.json()) == 0

    app.dependency_overrides.clear()
