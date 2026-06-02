# tests/test_bot_startup_fix.py
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.models import User
from app.web.csrf import csrf_token_for_session
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_start_bot_endpoint_success(db_session):
    # Create a test user
    user = User(username="test_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("password123")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Login to get session
    from app.web.auth import generate_session_token
    from app.models import UserSession
    token = generate_session_token()
    db_session.add(UserSession(user_id=user.id, token=token))
    await db_session.commit()

    # Override get_db to return our test db_session
    from app.web.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set("session_token", token)

        with patch("app.web.router.start_bot", AsyncMock(return_value="Р‘РѕС‚ СѓСЃРїРµС€РЅРѕ Р·Р°РїСѓС‰РµРЅ")):
            response = await ac.post(
                "/settings/start-bot",
                data={"telegram_token": "123456:ABC-DEF", "telegram_chat_id": "123456789"},
                headers={"X-CSRF-Token": csrf_token_for_session(token)},
            )
            assert response.status_code == 200
            # FastAPI returns strings as JSON-encoded strings by default (with quotes)
            assert "Р‘РѕС‚ СѓСЃРїРµС€РЅРѕ Р·Р°РїСѓС‰РµРЅ" in response.json()["message"]

            # Verify user settings updated in DB
            await db_session.refresh(user)
            assert user.telegram_bot_token == "123456:ABC-DEF"
            assert user.telegram_chat_id == "123456789"
    
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_start_bot_endpoint_missing_token(db_session):
    # Create a test user
    user = User(username="test_user_missing", telegram_bot_token="", telegram_chat_id="")
    user.set_password("password123")
    db_session.add(user)
    await db_session.commit()

    from app.web.auth import generate_session_token
    from app.models import UserSession
    token = generate_session_token()
    db_session.add(UserSession(user_id=user.id, token=token))
    await db_session.commit()

    from app.web.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set("session_token", token)

        response = await ac.post(
            "/settings/start-bot",
            data={"telegram_token": "", "telegram_chat_id": "123456789"},
            headers={"X-CSRF-Token": csrf_token_for_session(token)},
        )
        assert response.status_code == 400
        assert "РўРѕРєРµРЅ РЅРµ СѓРєР°Р·Р°РЅ" in response.json()["message"]
    
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_start_bot_duplicate_start_prevention(db_session):
    user = User(username="test_user_dup", telegram_bot_token="token123", telegram_chat_id="chat123")
    user.set_password("password")
    db_session.add(user)
    await db_session.commit()

    from app.web.auth import generate_session_token
    from app.models import UserSession
    token = generate_session_token()
    db_session.add(UserSession(user_id=user.id, token=token))
    await db_session.commit()

    from app.web.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set("session_token", token)

        # Mock is_bot_running to return True
        with patch("app.web.router.web_deps.is_bot_running", return_value=True):
            response = await ac.post(
                "/settings/start-bot",
                data={"telegram_token": "", "telegram_chat_id": ""},
                headers={"X-CSRF-Token": csrf_token_for_session(token)},
            )
            assert response.status_code == 200
            assert "СѓР¶Рµ Р·Р°РїСѓС‰РµРЅ" in response.json()["message"]
    
    app.dependency_overrides.clear()
