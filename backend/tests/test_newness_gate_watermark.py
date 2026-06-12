import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from app.models import Monitor, FoundItem, SeenItem, User, MonitorFilterBaseline
from app.scheduler.tasks import check_monitor
from app.scraper.client import DomainSearchResult
from app.scraper.parser import VintedItem
import uuid

async def _create_test_user(db_session):
    username = f"user_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        password_hash="hash",
        password_salt="salt",
        is_telegram_enabled=False
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

@pytest.mark.asyncio
@patch("app.scheduler.tasks._fetch_domain_results")
async def test_newness_gate_watermark_enforcement(mock_fetch, db_session, engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    test_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    with patch("app.scheduler.tasks.AsyncSessionLocal", test_session_factory):
        user = await _create_test_user(db_session)
        # Ensure user has semaphore
        from app.scheduler.tasks import _user_check_semaphores
        import asyncio
        _user_check_semaphores[user.id] = asyncio.Semaphore(10)

        monitor = Monitor(
            user_id=user.id,
            name="testbrand",
            original_url="https://vinted.fr/catalog?brand_ids[]=1",
            params_json='{"brand_ids[]": [1]}',
            domains_json='["vinted.fr"]',
            is_active=True
        )
        db_session.add(monitor)
        await db_session.commit()
        await db_session.refresh(monitor)

        # 1. Baseline: returns items 100, 90, 80.
        # Max ID = 100.
        mock_fetch.return_value = [
            DomainSearchResult(domain="vinted.fr", items=[
                VintedItem(id=100, title="Item 100", price=10.0, currency="EUR", domain="vinted.fr", 
                           brand="testbrand", size="M", condition="N", photo_url="P", item_url="U", seller_id=0, brand_id=1),
                VintedItem(id=90, title="Item 90", price=10.0, currency="EUR", domain="vinted.fr", 
                           brand="testbrand", size="M", condition="N", photo_url="P", item_url="U", seller_id=0, brand_id=1),
                VintedItem(id=80, title="Item 80", price=10.0, currency="EUR", domain="vinted.fr", 
                           brand="testbrand", size="M", condition="N", photo_url="P", item_url="U", seller_id=0, brand_id=1),
            ], request_count=1, duration_ms=100)
        ]

        await check_monitor(monitor.id)
        
        # Verify watermark
        from sqlalchemy import select
        res = await db_session.execute(select(MonitorFilterBaseline).where(
            MonitorFilterBaseline.monitor_id == monitor.id
        ))
        baseline = res.scalar_one()
        assert baseline.max_vinted_item_id == 100

        # 2. Check 2: Returns 95 (Old item < watermark, not in seen, no timestamp).
        # Should be suppressed.
        mock_fetch.return_value = [
            DomainSearchResult(domain="vinted.fr", items=[
                VintedItem(id=95, title="Old Item 95", price=20.0, currency="EUR", domain="vinted.fr",
                           brand="testbrand", size="M", condition="N", photo_url="P", item_url="U", seller_id=0, brand_id=1)
            ], request_count=1, duration_ms=100)
        ]
        await check_monitor(monitor.id)

        # Verify 95 is NOT found (no FoundItem)
        res_found = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 95))
        assert res_found.scalar_one_or_none() is None

        # 3. Check 3: Returns 105 (New item > watermark). Should send.
        mock_fetch.return_value = [
            DomainSearchResult(domain="vinted.fr", items=[
                VintedItem(id=105, title="New Item 105", price=20.0, currency="EUR", domain="vinted.fr",
                           brand="testbrand", size="M", condition="N", photo_url="P", item_url="U", seller_id=0, brand_id=1)
            ], request_count=1, duration_ms=100)
        ]
        await check_monitor(monitor.id)
        
        # Verify 105 is found
        res_found = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 105))
        assert res_found.scalar_one_or_none() is not None
