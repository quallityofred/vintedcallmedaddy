import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.main import app
from app.models import Monitor, User
from app.web.dependencies import get_db

async def _create_user(db_session, username: str) -> User:
    user = User(username=username, telegram_bot_token="", telegram_chat_id="")
    user.set_password("password")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

async def _login_user(client: AsyncClient, username: str) -> str:
    csrf_resp = await client.get("/api/v1/auth/csrf")
    csrf_token = csrf_resp.json()["csrf_token"]
    await client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf_token},
        json={"username": username, "password": "password"},
    )
    csrf_resp2 = await client.get("/api/v1/auth/csrf")
    return csrf_resp2.json()["csrf_token"]

def _override_db(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session

@pytest.mark.asyncio
async def test_bulk_pause_dry_run(db_session):
    _override_db(db_session)
    user = await _create_user(db_session, "test_bulk_pause")
    
    # Create sample monitors
    m1 = Monitor(user_id=user.id, name="M1", original_url="https://www.vinted.fr/1", is_active=True, interval_sec=120, params_json="{}", domains_json='["vinted.fr"]')
    m2 = Monitor(user_id=user.id, name="M2", original_url="https://www.vinted.fr/2", is_active=True, interval_sec=120, params_json="{}", domains_json='["vinted.fr"]')
    db_session.add_all([m1, m2])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, user.username)
        response = await client.post(
            "/api/v1/monitors/bulk-state",
            json={"action": "pause", "dry_run": True},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is True
        assert data["changed_count"] == 2
        assert data["side_effects"]["writes_database"] is False
    
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_bulk_pause_live(db_session):
    _override_db(db_session)
    user = await _create_user(db_session, "test_bulk_pause_live")
    
    m1 = Monitor(user_id=user.id, name="M1", original_url="https://www.vinted.fr/1", is_active=True, interval_sec=120, params_json="{}", domains_json='["vinted.fr"]')
    m2 = Monitor(user_id=user.id, name="M2", original_url="https://www.vinted.fr/2", is_active=False, interval_sec=120, params_json="{}", domains_json='["vinted.fr"]')
    db_session.add_all([m1, m2])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, user.username)
        response = await client.post(
            "/api/v1/monitors/bulk-state",
            json={"action": "pause", "dry_run": False},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["changed_count"] == 1 # Only m1 was active
        
    # Verify DB
    await db_session.refresh(m1)
    await db_session.refresh(m2)
    assert m1.is_active is False
    assert m2.is_active is False
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_bulk_resume_live(db_session):
    _override_db(db_session)
    user = await _create_user(db_session, "test_bulk_resume")
    
    m1 = Monitor(user_id=user.id, name="M1", original_url="https://www.vinted.fr/1", is_active=False, interval_sec=120, params_json="{}", domains_json='["vinted.fr"]')
    m2 = Monitor(user_id=user.id, name="M2", original_url="https://www.vinted.fr/2", is_active=False, interval_sec=120, params_json="{}", domains_json='["vinted.fr"]')
    db_session.add_all([m1, m2])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, user.username)
        response = await client.post(
            "/api/v1/monitors/bulk-state",
            json={"action": "resume", "dry_run": False},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["changed_count"] == 2
        
    # Verify DB
    await db_session.refresh(m1)
    await db_session.refresh(m2)
    assert m1.is_active is True
    assert m2.is_active is True
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_bulk_state_ownership(db_session):
    _override_db(db_session)
    user1 = await _create_user(db_session, "user1")
    user2 = await _create_user(db_session, "user2")
    
    m1 = Monitor(user_id=user1.id, name="U1", original_url="https://www.vinted.fr/1", is_active=True, interval_sec=120, params_json="{}", domains_json='["vinted.fr"]')
    m2 = Monitor(user_id=user2.id, name="U2", original_url="https://www.vinted.fr/2", is_active=True, interval_sec=120, params_json="{}", domains_json='["vinted.fr"]')
    db_session.add_all([m1, m2])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_token = await _login_user(client, "user1")
        response = await client.post(
            "/api/v1/monitors/bulk-state",
            json={"action": "pause", "dry_run": False},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == 200
        assert response.json()["changed_count"] == 1
        
    # Verify DB
    await db_session.refresh(m1)
    await db_session.refresh(m2)
    assert m1.is_active is False
    assert m2.is_active is True # User 2's monitor untouched
    app.dependency_overrides.clear()
