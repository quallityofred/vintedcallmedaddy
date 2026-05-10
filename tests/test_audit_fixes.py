# tests/test_audit_fixes.py
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import FoundItem, Monitor, SeenItem, User
from app.scheduler.tasks import check_monitor
from app.scraper.parser import VintedItem


@pytest.mark.asyncio
async def test_bot_token_change_lifecycle():
    """Verify that changing bot token correctly starts the old bot and starts a new one."""
    async def dummy_coro(*args, **kwargs):
        await asyncio.sleep(100) # Keep it running

    with patch("app.telegram.bot.Bot") as MockBot, \
         patch("app.telegram.bot.Dispatcher") as MockDp, \
         patch("app.telegram.bot.terminate_all_sessions", AsyncMock()):
        
        # We need the real get_or_create_bot but with mocked Bot/Dispatcher classes
        # MockBot and MockDp are already patching the classes.
        
        # Ensure the mocked Bot instance has a token attribute
        # We use a side_effect to return different tokens
        tokens = ["token1", "token2"]
        def bot_init(token, **kwargs):
            mock_bot = MagicMock()
            mock_bot.token = token
            mock_bot.session.close = AsyncMock()
            return mock_bot
        
        MockBot.side_effect = bot_init
        MockDp.return_value.start_polling.side_effect = dummy_coro
        
        from app.web.dependencies import start_bot, is_bot_running
        
        # Start bot with token1
        await start_bot("token1", persist=False)
        await asyncio.sleep(0.1)
        assert is_bot_running()
        
        # Start bot with token2
        await start_bot("token2", persist=False)
        await asyncio.sleep(0.1)
        assert is_bot_running()
        
        from app.telegram.bot import _bots
        assert "token1" not in _bots
        assert "token2" in _bots


@pytest.mark.asyncio
async def test_check_monitor_efficiency(db_session):
    """Verify check_monitor uses atomic upserts and correctly updates monitor state."""
    # Setup monitor
    monitor = Monitor(
        name="Test",
        original_url="http://test.com",
        params_json=json.dumps({"q": "test"}),
        domains_json=json.dumps(["vinted.fr"]),
        is_active=True
    )
    db_session.add(monitor)
    await db_session.commit()
    monitor_id = monitor.id

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[
        VintedItem(
            id=123, title="Item 1", price=10.0, currency="EUR", brand="B", 
            size="S", condition="N", photo_url="p", item_url="u", 
            domain="vinted.fr", seller_id=456
        )
    ])

    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def mock_session_local():
        yield db_session

    with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=mock_session_local), \
         patch("app.scheduler.tasks.send_item_notification", AsyncMock()):
        
        await check_monitor(monitor_id, mock_client)

    # Verify SeenItem created
    result = await db_session.execute(select(SeenItem).where(SeenItem.vinted_item_id == 123))
    assert result.scalar_one_or_none() is not None

    # Verify FoundItem created
    result = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 123))
    assert result.scalar_one_or_none() is not None

    # Verify Monitor updated
    result = await db_session.execute(select(Monitor).where(Monitor.id == monitor_id))
    updated_monitor = result.scalar_one()
    assert updated_monitor.items_found_count == 1
    assert updated_monitor.last_check_at is not None
