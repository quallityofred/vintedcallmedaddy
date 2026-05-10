# tests/test_admin_invite.py
import asyncio
import pytest
from sqlalchemy import select
from app.models import User, InviteCode, UserSession
from app.web.auth import generate_session_token

@pytest.mark.asyncio
async def test_invite_code_validation(db_session):
    """Test that invite codes correctly validate their state."""
    invite = InviteCode(code="test-code", max_uses=1, used_count=0, is_active=True)
    db_session.add(invite)
    await db_session.commit()
    
    assert invite.is_valid is True
    
    invite.used_count = 1
    assert invite.is_valid is False
    
    invite.used_count = 0
    invite.is_active = False
    assert invite.is_valid is False

@pytest.mark.asyncio
async def test_registration_requires_valid_invite(db_session):
    """Integration test for registration flow with invite codes."""
    from app.web.auth_router import register_submit
    from unittest.mock import MagicMock
    
    request = MagicMock()
    request.app.state.templates.TemplateResponse = MagicMock()
    
    # 1. Test invalid code
    response = await register_submit(
        request, db_session, "user1", "pass123", "pass123", "invalid-code"
    )
    assert "Неверный или использованный инвайт-код" in request.app.state.templates.TemplateResponse.call_args[0][2]["error"]

    # 2. Test valid code
    invite = InviteCode(code="valid-code", max_uses=1, used_count=0, is_active=True)
    db_session.add(invite)
    await db_session.commit()
    
    with patch("app.web.auth_router.generate_session_token", return_value="test-token"), \
         patch("app.web.auth_router.set_session_cookie", MagicMock()):
        response = await register_submit(
            request, db_session, "user2", "pass123", "pass123", "valid-code"
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"

    # 3. Verify user created and code used
    result = await db_session.execute(select(User).where(User.username == "user2"))
    user = result.scalar_one()
    assert user.invite_code_id == invite.id
    
    await db_session.refresh(invite)
    assert invite.used_count == 1
    assert invite.is_valid is False

@pytest.mark.asyncio
async def test_admin_permissions(db_session):
    """Verify that only admins can access invite management."""
    from app.web.auth import require_admin
    from fastapi import HTTPException
    from unittest.mock import MagicMock
    
    request = MagicMock()
    
    # 1. Non-admin user
    user = User(username="normie", is_admin=False)
    
    with patch("app.web.auth.get_current_user", return_value=user):
        with pytest.raises(HTTPException) as exc:
            await require_admin(request, db_session)
        assert exc.value.status_code == 403

    # 2. Admin user
    admin = User(username="admin", is_admin=True)
    with patch("app.web.auth.get_current_user", return_value=admin):
        result = await require_admin(request, db_session)
        assert result == admin

from unittest.mock import patch
