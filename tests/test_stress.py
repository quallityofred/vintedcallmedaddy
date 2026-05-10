# tests/test_stress.py
import asyncio
import json
import random
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select

from app.models import FoundItem, Monitor, SeenItem
from app.scheduler.tasks import check_monitor
from app.scraper.parser import VintedItem


@pytest.mark.asyncio
async def test_concurrent_monitor_execution(db_session):
    """Stress test: Run many monitors concurrently and verify deduplication works."""
    # Create 10 monitors
    monitor_ids = []
    for i in range(10):
        monitor = Monitor(
            name=f"Monitor {i}",
            original_url="http://test.com",
            params_json=json.dumps({"q": f"test {i}"}),
            domains_json=json.dumps(["vinted.fr"]),
            is_active=True
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

    # Run all monitors concurrently
    # We need a NEW session for each task because sessions are not async-safe for concurrent use
    async def mock_session_local_factory():
        session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
        async with session_factory() as session:
            yield session

    # Instead of patching with a single session, we patch with a factory that creates a new one
    # But AsyncSessionLocal is used as a context manager: async with AsyncSessionLocal() as db:
    # So we need a callable that returns an async context manager.
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory), \
         patch("app.scheduler.tasks.send_item_notification", AsyncMock()):
        
        tasks = [check_monitor(mid, mock_client) for mid in monitor_ids]
        await asyncio.gather(*tasks)

    # Verify only ONE SeenItem exists for this ID
    result = await db_session.execute(
        select(func.count(SeenItem.id)).where(SeenItem.vinted_item_id == 999)
    )
    assert result.scalar() == 1

    # Verify only ONE FoundItem exists for this item_id/domain (across all monitors)
    # Wait, our logic allows different monitors to have the same item in FoundItem?
    # No, check_monitor uses:
    # found_stmt = pg_insert(FoundItem).on_conflict_do_nothing(index_elements=['vinted_item_id', 'domain'])
    # This means only the FIRST monitor that finds it will record it.
    
    result = await db_session.execute(
        select(func.count(FoundItem.id)).where(FoundItem.vinted_item_id == 999)
    )
    assert result.scalar() == 1
