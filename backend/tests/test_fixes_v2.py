# tests/test_fixes_v2.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy import select, func
from datetime import datetime, timezone

from app.models import User, Monitor, FoundItem, SeenItem
from app.scheduler.tasks import check_monitor, process_pending_notifications
from app.main import clean_startup_reset
from app.scraper.parser import VintedItem

@pytest.mark.asyncio
async def test_duplicate_notification_prevention_same_user(db_session):
    """Ensure that if two monitors find the same item for the same user, only one notification is queued."""
    user = User(username="dupe_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    m1 = Monitor(user_id=user.id, name="M1", original_url="u1", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=10)
    m2 = Monitor(user_id=user.id, name="M2", original_url="u2", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=10)
    db_session.add_all([m1, m2])
    await db_session.commit()
    await db_session.refresh(m1)
    await db_session.refresh(m2)

    item = VintedItem(id=123, title="Dupe Item", price=10.0, currency="PLN", brand="Nike", size="M", condition="New", photo_url="p", item_url="u", domain="vinted.pl", seller_id=999)

    # Mock VintedClient to return the same item for both monitors
    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[item])
    mock_client.close = AsyncMock()

    # Run check_monitor for M1
    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()):
        await check_monitor(m1.id, scraper_client=mock_client)
        # Run check_monitor for M2
        await check_monitor(m2.id, scraper_client=mock_client)

    # Verify:
    # 1. SeenItem has only 1 entry for this user/item
    seen_result = await db_session.execute(select(SeenItem).where(SeenItem.user_id == user.id, SeenItem.vinted_item_id == 123))
    assert len(seen_result.scalars().all()) == 1

    # 2. FoundItem has 2 entries (one for each monitor)
    found_result = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 123, FoundItem.monitor_id.in_([m1.id, m2.id])))
    found_items = found_result.scalars().all()
    assert len(found_items) == 2
    
    # 3. Only ONE FoundItem has notified=False
    notified_false = [f for f in found_items if f.notified == False]
    assert len(notified_false) == 1

@pytest.mark.asyncio
async def test_cross_user_notifications(db_session):
    """Ensure that Item 1 found by User A is still notified to User B."""
    u1 = User(username="user_a", telegram_bot_token="t1", telegram_chat_id="c1")
    u1.set_password("p")
    u2 = User(username="user_b", telegram_bot_token="t2", telegram_chat_id="c2")
    u2.set_password("p")
    db_session.add_all([u1, u2])
    await db_session.commit()
    await db_session.refresh(u1)
    await db_session.refresh(u2)

    m1 = Monitor(user_id=u1.id, name="MA", original_url="ua", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=1)
    m2 = Monitor(user_id=u2.id, name="MB", original_url="ub", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=1)
    db_session.add_all([m1, m2])
    await db_session.commit()

    item = VintedItem(id=456, title="Cross Item", price=10.0, currency="PLN", brand="Nike", size="M", condition="New", photo_url="p", item_url="u", domain="vinted.pl", seller_id=999)

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[item])
    mock_client.close = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()):
        await check_monitor(m1.id, scraper_client=mock_client)
        await check_monitor(m2.id, scraper_client=mock_client)

    # Verify:
    # Both users should have a FoundItem with notified=False
    found_result = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 456, FoundItem.notified == False))
    assert len(found_result.scalars().all()) == 2

@pytest.mark.asyncio
async def test_cold_start_on_restart(db_session):
    """Verify that after clean_startup_reset, the first check doesn't notify."""
    user = User(username="cold_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()

    monitor = Monitor(user_id=user.id, name="Cold M", original_url="u", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=10)
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Run cleanup
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    with patch("app.database.AsyncSessionLocal", side_effect=session_factory):
        await clean_startup_reset()

    # Re-fetch monitor
    await db_session.refresh(monitor)
    assert monitor.last_check_at is None
    assert monitor.items_found_count == 0

    # Run check_monitor
    item = VintedItem(id=789, title="Initial Item", price=10.0, currency="PLN", brand="Nike", size="M", condition="New", photo_url="p", item_url="u", domain="vinted.pl", seller_id=999)
    
    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[item])
    mock_client.close = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()):
        await check_monitor(monitor.id, scraper_client=mock_client)

    # Verify: notified should be True (SILENCED)
    found = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 789))
    fi = found.scalar_one()
    assert fi.notified == True
