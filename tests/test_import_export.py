# tests/test_import_export.py
import pytest
import json
from unittest.mock import MagicMock, patch
from sqlalchemy import select
from app.models import Monitor

@pytest.mark.asyncio
async def test_import_monitors_flow(db_session):
    """Test monitor import functionality."""
    from app.web.router import import_monitors
    from app.models import User
    
    # Create user manually
    user = User(username="testuser", is_admin=False)
    user.set_password("pass")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    # Mock Request and Form data
    request = MagicMock()
    request.form = MagicMock(return_value={})
    
    raw_text = "https://www.vinted.pl/catalog?search_text=nike"
    
    # Patch scheduler and settings
    with patch("app.web.router.get_scheduler") as mock_get_scheduler, \
         patch("app.web.router.settings") as mock_settings:
        
        mock_scheduler = MagicMock()
        mock_get_scheduler.return_value = mock_scheduler
        mock_settings.check_interval_seconds = 120
        
        # Call import endpoint
        await import_monitors(request, raw_text=raw_text, db=db_session, user=user)
        
    # Verify monitor created
    result = await db_session.execute(select(Monitor).where(Monitor.user_id == user.id))
    monitors = result.scalars().all()
    assert len(monitors) == 1
    assert "nike" in monitors[0].params_json
    assert mock_scheduler.add_monitor.called
