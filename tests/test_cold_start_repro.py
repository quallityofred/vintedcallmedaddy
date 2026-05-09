# tests/test_cold_start_repro.py
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Monitor, FoundItem, User
from app.scheduler.tasks import check_monitor
from app.scraper.parser import VintedItem

@pytest.mark.asyncio
async def test_cold_start_behavior():
    # Setup in-memory database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create a user and a monitor
    async with session_factory() as db:
        user = User(
            username="testuser", 
            password_hash="hash", 
            password_salt="salt",
            telegram_bot_token="123:abc",
            telegram_chat_id="999"
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
        monitor = Monitor(
            user_id=user.id,
            name="Test Monitor",
            original_url="https://vinted.fr/items?search_text=test",
            params_json=json.dumps({"search_text": "test"}),
            domains_json=json.dumps(["vinted.fr"]),
            interval_sec=120,
            is_active=True,
            last_check_at=None  # Explicitly None for cold start
        )
        db.add(monitor)
        await db.commit()
        await db.refresh(monitor)
        monitor_id = monitor.id

    # Mock VintedClient
    mock_client = MagicMock()
    mock_item = VintedItem(
        id=123,
        domain="vinted.fr",
        title="Test Item",
        price=10.0,
        currency="EUR",
        brand="Brand",
        size="M",
        condition="New",
        photo_url="https://photo.com/1.jpg",
        item_url="https://vinted.fr/items/123",
        seller_id=456,
    )
    mock_client.search_all_domains = AsyncMock(return_value=[mock_item])

    # Mock send_item_notification
    with patch("app.scheduler.tasks.send_item_notification", new_callable=AsyncMock) as mock_send_notif:
        with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory):
            # First run (Cold Start)
            await check_monitor(monitor_id, mock_client)
            
            # Verify no notification sent
            mock_send_notif.assert_not_called()
            
            # Verify item saved to DB
            async with session_factory() as db:
                result = await db.execute(select(FoundItem).where(FoundItem.monitor_id == monitor_id))
                items = result.scalars().all()
                assert len(items) == 1
                assert items[0].vinted_item_id == 123
                assert items[0].notified is False
                
                # Verify monitor updated
                result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
                mon = result.scalar_one()
                assert mon.last_check_at is not None
                assert mon.items_found_count == 1

            # Second run (with a NEW item)
            mock_item2 = VintedItem(
                id=124,
                domain="vinted.fr",
                title="Test Item 2",
                price=20.0,
                currency="EUR",
                brand="Brand",
                size="L",
                condition="New",
                photo_url="https://photo.com/2.jpg",
                item_url="https://vinted.fr/items/124",
                seller_id=457,
            )
            mock_client.search_all_domains = AsyncMock(return_value=[mock_item, mock_item2])
            
            await check_monitor(monitor_id, mock_client)
            
            # Verify notification sent ONLY for the second item
            assert mock_send_notif.call_count == 1
            args, kwargs = mock_send_notif.call_args
            assert args[2].id == 124
            
            async with session_factory() as db:
                result = await db.execute(select(FoundItem).where(FoundItem.monitor_id == monitor_id))
                items = result.scalars().all()
                assert len(items) == 2
                
                # Check notified status in DB
                fi123 = next(i for i in items if i.vinted_item_id == 123)
                fi124 = next(i for i in items if i.vinted_item_id == 124)
                assert fi123.notified is False
                assert fi124.notified is True

    await engine.dispose()

@pytest.mark.asyncio
async def test_cold_start_empty_first_run():
    # Setup in-memory database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create a user and a monitor
    async with session_factory() as db:
        user = User(
            username="testuser", 
            password_hash="hash", 
            password_salt="salt",
            telegram_bot_token="123:abc",
            telegram_chat_id="999"
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
        monitor = Monitor(
            user_id=user.id,
            name="Test Monitor",
            original_url="https://vinted.fr/items?search_text=test",
            params_json=json.dumps({"search_text": "test"}),
            domains_json=json.dumps(["vinted.fr"]),
            interval_sec=120,
            is_active=True,
            last_check_at=None
        )
        db.add(monitor)
        await db.commit()
        await db.refresh(monitor)
        monitor_id = monitor.id

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[])

    with patch("app.scheduler.tasks.send_item_notification", new_callable=AsyncMock) as mock_send_notif:
        with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory):
            # First run: NO items found
            await check_monitor(monitor_id, mock_client)
            mock_send_notif.assert_not_called()
            
            async with session_factory() as db:
                mon = (await db.execute(select(Monitor).where(Monitor.id == monitor_id))).scalar_one()
                assert mon.last_check_at is not None # It's no longer a "cold start" by definition of last_check_at is None
            
            # Second run: items found
            mock_item = VintedItem(
                id=123,
                domain="vinted.fr",
                title="Test Item",
                price=10.0,
                currency="EUR",
                brand="Brand",
                size="M",
                condition="New",
                photo_url="https://photo.com/1.jpg",
                item_url="https://vinted.fr/items/123",
                seller_id=456,
            )
            mock_client.search_all_domains = AsyncMock(return_value=[mock_item])
            
            await check_monitor(monitor_id, mock_client)
            
            # EXPECTED with the FIX: It should NOT be called because it's the FIRST time items are found
            assert mock_send_notif.call_count == 0

    await engine.dispose()

@pytest.mark.asyncio
async def test_cold_start_on_edit():
    # Setup in-memory database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create a user and a monitor
    async with session_factory() as db:
        user = User(
            username="testuser", 
            password_hash="hash", 
            password_salt="salt",
            telegram_bot_token="123:abc",
            telegram_chat_id="999"
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
        monitor = Monitor(
            user_id=user.id,
            name="Test Monitor",
            original_url="https://vinted.fr/items?search_text=old",
            params_json=json.dumps({"search_text": "old"}),
            domains_json=json.dumps(["vinted.fr"]),
            interval_sec=120,
            is_active=True,
            last_check_at=datetime.now(timezone.utc),
            items_found_count=10
        )
        db.add(monitor)
        await db.commit()
        await db.refresh(monitor)
        monitor_id = monitor.id

    mock_client = MagicMock()
    mock_item = VintedItem(
        id=789,
        domain="vinted.fr",
        title="New Search Item",
        price=10.0,
        currency="EUR",
        brand="Brand",
        size="M",
        condition="New",
        photo_url="https://photo.com/1.jpg",
        item_url="https://vinted.fr/items/789",
        seller_id=456,
    )
    mock_client.search_all_domains = AsyncMock(return_value=[mock_item])

    with patch("app.scheduler.tasks.send_item_notification", new_callable=AsyncMock) as mock_send_notif:
        with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory):
            # Simulation of edit: changing URL and params
            async with session_factory() as db:
                mon = await db.get(Monitor, monitor_id)
                new_url = "https://vinted.fr/items?search_text=new"
                new_params = {"search_text": "new"}
                new_params_json = json.dumps(new_params)
                
                # Replicate router logic: reset if params changed
                if mon.params_json != new_params_json:
                    mon.last_check_at = None
                    mon.items_found_count = 0
                
                mon.original_url = new_url
                mon.params_json = new_params_json
                await db.commit()

            # Next check
            await check_monitor(monitor_id, mock_client)
            
            # EXPECTED: Should NOT send notification for the new item 789
            assert mock_send_notif.call_count == 0

    await engine.dispose()
