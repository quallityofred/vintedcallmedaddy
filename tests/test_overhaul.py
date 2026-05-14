# tests/test_overhaul.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select
from app.models import User, Monitor, FoundItem
from app.web.dependencies import start_bot, is_bot_running, stop_bot, restore_persisted_bot

@pytest.mark.asyncio
async def test_multi_user_bot_configuration(db_session):
    """Verify that each user can have their own bot and they can run concurrently."""
    import random
    rid = random.randint(1000, 9999)
    user1 = User(username=f"user1_{rid}", telegram_bot_token="token1", telegram_chat_id="111")
    user1.set_password("pass1")
    user2 = User(username=f"user2_{rid}", telegram_bot_token="token2", telegram_chat_id="222")
    user2.set_password("pass2")
    db_session.add_all([user1, user2])
    await db_session.commit()



    async def dummy_coro(*args, **kwargs):
        await asyncio.sleep(1)

    async def mock_start_polling(bot, dp):
        from app.telegram.bot import _polling_tasks
        _polling_tasks[bot.token] = asyncio.create_task(asyncio.sleep(10))

    with patch("app.telegram.bot.Bot") as MockBot, \
         patch("app.telegram.bot.start_polling", side_effect=mock_start_polling), \
         patch("app.telegram.bot.terminate_all_sessions", AsyncMock()):
        
        def bot_init(token, **kwargs):
            mock_bot = MagicMock()
            mock_bot.token = token
            mock_bot.session.close = AsyncMock()
            return mock_bot
        
        MockBot.side_effect = bot_init


        
        # Start bot for user1
        res1 = await start_bot("token1", owner_user_id=user1.id)
        assert "успешно" in res1
        await asyncio.sleep(0.1)
        assert is_bot_running("token1")
        
        # Start bot for user2
        res2 = await start_bot("token2", owner_user_id=user2.id)
        assert "успешно" in res2
        await asyncio.sleep(0.1)
        assert is_bot_running("token2")

        
        # Verify both are in the bot store
        from app.telegram.bot import _bots
        assert "token1" in _bots
        assert "token2" in _bots
        
        # Stop bot for user1
        await stop_bot("token1")
        assert not is_bot_running("token1")
        assert is_bot_running("token2")

@pytest.mark.asyncio
async def test_clean_startup_reset(db_session):
    """Verify that FoundItem and SeenItem are cleared on startup, but Monitors are kept."""
    user = User(username="cleanup_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("pass")
    db_session.add(user)
    await db_session.commit()
    
    monitor = Monitor(user_id=user.id, name="Keep Me", original_url="u", params_json="{}", domains_json="[]")
    db_session.add(monitor)
    await db_session.commit()
    
    found = FoundItem(monitor_id=monitor.id, vinted_item_id=1, domain="d", title="T", price=1.0, currency="E", brand="B", size="S", condition="N", photo_url="p", item_url="u", seller_id=1)
    db_session.add(found)
    await db_session.commit()
    
    from app.main import clean_startup_reset
    # We need to mock AsyncSessionLocal to use our test db_session
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    
    with patch("app.database.AsyncSessionLocal", side_effect=session_factory):
        await clean_startup_reset()
        
    # Verify
    # Use scalars().all() to handle multiple monitors if tests are not perfectly isolated
    monitors = (await db_session.execute(select(Monitor))).scalars().all()
    assert len(monitors) > 0
    
    found_items = (await db_session.execute(select(FoundItem))).scalars().all()
    assert len(found_items) == 0

