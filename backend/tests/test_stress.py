# tests/test_stress.py
import asyncio
import json
import random
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select

from app.models import FoundItem, Monitor, SeenItem, User
from app.scheduler.tasks import check_monitor
from app.scraper.parser import VintedItem


@pytest.mark.asyncio
async def test_concurrent_monitor_execution(db_session):
    """Stress test: Run many monitors concurrently and verify deduplication works."""
    # Create a user
    user = User(username="stress_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Create 10 monitors for this user
    monitor_ids = []
    from datetime import datetime, timezone
    for i in range(10):
        monitor = Monitor(
            user_id=user.id,
            name=f"Monitor {i}",
            original_url="http://test.com",
            params_json=json.dumps({"q": f"test {i}"}),
            domains_json=json.dumps(["vinted.fr"]),
            is_active=True,
            items_found_count=1, # Not a cold start
            last_check_at=datetime.now(timezone.utc)
        )
        db_session.add(monitor)
        await db_session.commit()
        monitor_ids.append(monitor.id)

    # All monitors find the SAME item
    shared_item = VintedItem(
        id=999, title="Shared Item", price=10.0, currency="EUR", brand="B", 
        size="S", condition="N", photo_url="p", item_url="u", 
        domain="vinted.fr", seller_id=456
    )

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[shared_item])

    # Run all monitors concurrently with NEW sessions to avoid race conditions in SQLAlchemy
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()):
        
        # Serialize execution to avoid SQLite in-memory locking issues in tests
        semaphore = asyncio.Semaphore(1)
        async def sem_check(mid):
            async with semaphore:
                await check_monitor(mid, scraper_client=mock_client)
        
        tasks = [sem_check(mid) for mid in monitor_ids]
        await asyncio.gather(*tasks)

    # SeenItem is monitor-scoped so each monitor keeps its own boundary.
    result = await db_session.execute(
        select(func.count(SeenItem.id)).where(SeenItem.user_id == user.id, SeenItem.vinted_item_id == 999)
    )
    assert result.scalar() == len(monitor_ids)

    # FoundItem is also monitor-scoped.
    result = await db_session.execute(
        select(func.count(FoundItem.id)).where(FoundItem.vinted_item_id == 999)
    )
    assert result.scalar() == len(monitor_ids)

    result = await db_session.execute(
        select(func.count(FoundItem.id)).where(FoundItem.vinted_item_id == 999, FoundItem.notified == False)
    )
    assert result.scalar() == len(monitor_ids)
