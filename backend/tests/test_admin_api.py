import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.models import InviteCode, User
from app.web.dependencies import get_db

async def _create_user(db_session, username: str, is_admin: bool = False) -> User:
    user = User(username=username, telegram_bot_token="", telegram_chat_id="", is_admin=is_admin)
    user.set_password("password")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

async def _login_user(client: AsyncClient, username: str) -> str:
    csrf_resp = await client.get("/api/v1/auth/csrf")
    csrf_token = csrf_resp.json()["csrf_token"]
    login_resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf_token},
        json={"username": username, "password": "password"},
    )
    return login_resp.json()["csrf_token"]

def _override_db(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session

@pytest.mark.asyncio
async def test_system_status(db_session):
    await _create_user(db_session, "user")
    _override_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _login_user(client, "user")
        response = await client.get("/api/v1/system/status")
        assert response.status_code == 200
        data = response.json()
        assert "scheduler_running" in data
        assert "database_status" in data
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_admin_invites(db_session):
    admin = await _create_user(db_session, "admin_user_1", is_admin=True)
    user = await _create_user(db_session, "normal_user_1", is_admin=False)
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Admin access
        admin_csrf = await _login_user(client, "admin_user_1")
        
        # Create invite
        payload = {"code": "test_invite", "max_uses": 5}
        response = await client.post("/api/v1/admin/invites", headers={"X-CSRF-Token": admin_csrf}, json=payload)
        assert response.status_code == 200
        
        # List invites
        response = await client.get("/api/v1/admin/invites", headers={"X-CSRF-Token": admin_csrf})
        assert response.status_code == 200
        assert len(response.json()) == 1
        invite_id = response.json()[0]["id"]
        
        # Delete invite
        response = await client.delete(f"/api/v1/admin/invites/{invite_id}", headers={"X-CSRF-Token": admin_csrf})
        assert response.status_code == 204

        # Non-admin access
        await _login_user(client, "normal_user_1")
        response = await client.get("/api/v1/admin/invites")
        assert response.status_code == 403

    app.dependency_overrides.clear()
