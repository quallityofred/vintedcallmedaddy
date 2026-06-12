import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.models import Monitor, FoundItem, SeenItem, User, MonitorFilterBaseline
from app.scheduler.cold_start_reset import run_monitor_cold_start_reset
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
async def test_reset_clears_filter_baselines(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="test",
        original_url="http://vinted.fr",
        params_json="{}",
        domains_json='["vinted.fr"]'
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Add a baseline
    baseline = MonitorFilterBaseline(
        monitor_id=monitor.id,
        domain="vinted.fr",
        filter_fingerprint="old_fingerprint",
        filter_contract_version="v1",
        source_strategy="api"
    )
    db_session.add(baseline)
    await db_session.commit()

    # Reset
    await run_monitor_cold_start_reset(db_session, monitor.id, dry_run=False)

    # Verify baseline is gone
    from sqlalchemy import select
    res = await db_session.execute(select(MonitorFilterBaseline).where(MonitorFilterBaseline.monitor_id == monitor.id))
    assert res.scalar_one_or_none() is None

@pytest.mark.asyncio
@patch("app.scheduler.tasks._fetch_domain_results")
async def test_partial_baseline_failure_protection(mock_fetch, db_session, engine):
    from app.scheduler.tasks import AsyncSessionLocal as TasksAsyncSessionLocal
    import app.scheduler.tasks as tasks
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    
    # Setup session factory for tasks
    test_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    with patch("app.scheduler.tasks.AsyncSessionLocal", test_session_factory):
        user = await _create_test_user(db_session)
        # Ensure user has semaphore
        from app.scheduler.tasks import _user_check_semaphores
        import asyncio
        _user_check_semaphores[user.id] = asyncio.Semaphore(10)

        monitor = Monitor(
            user_id=user.id,
            name="test",
            original_url="https://vinted.fr/catalog?brand_ids[]=1",
            params_json='{"brand_ids[]": [1]}',
            domains_json='["vinted.fr", "vinted.de"]',
            is_active=True
        )
        db_session.add(monitor)
        await db_session.commit()
        await db_session.refresh(monitor)

        # 1. First check: vinted.fr succeeds, vinted.de fails
        mock_fetch.return_value = [
            DomainSearchResult(domain="vinted.fr", items=[
                VintedItem(id=1, title="Item 1", price=10.0, currency="EUR", domain="vinted.fr", 
                           brand="B", size="M", condition="N", photo_url="P", item_url="U", seller_id=0)
            ], request_count=1, duration_ms=100),
            DomainSearchResult(domain="vinted.de", items=[], request_count=1, duration_ms=100, error="Timeout")
        ]

        await check_monitor(monitor.id)
        await db_session.refresh(monitor)
        assert monitor.last_check_status == "baseline_created"
        
        # Verify vinted.fr has baseline, vinted.de does NOT
        from sqlalchemy import select
        res_fr = await db_session.execute(select(MonitorFilterBaseline).where(
            MonitorFilterBaseline.monitor_id == monitor.id, 
            MonitorFilterBaseline.domain == "vinted.fr"
        ))
        assert res_fr.scalar_one_or_none() is not None

        res_de = await db_session.execute(select(MonitorFilterBaseline).where(
            MonitorFilterBaseline.monitor_id == monitor.id, 
            MonitorFilterBaseline.domain == "vinted.de"
        ))
        assert res_de.scalar_one_or_none() is None

        # 2. Second check: vinted.de now succeeds with an OLD item (no timestamp)
        mock_fetch.return_value = [
            DomainSearchResult(domain="vinted.fr", items=[], request_count=1, duration_ms=100),
            DomainSearchResult(domain="vinted.de", items=[
                VintedItem(id=2, title="Old Item", price=20.0, currency="EUR", domain="vinted.de",
                           brand="B", size="M", condition="N", photo_url="P", item_url="U", seller_id=0)
            ], request_count=1, duration_ms=100)
        ]

        await check_monitor(monitor.id)
        await db_session.refresh(monitor)
        
        # ASSERT: Should NOT notify (because vinted.de was never baselined)
        assert monitor.last_check_status == "success_no_new_items"

        # Verify vinted.de now HAS a baseline
        res_de_2 = await db_session.execute(select(MonitorFilterBaseline).where(
            MonitorFilterBaseline.monitor_id == monitor.id, 
            MonitorFilterBaseline.domain == "vinted.de"
        ))
        assert res_de_2.scalar_one_or_none() is not None

        # Verify no FoundItem created for id 2
        res_found = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 2))
        assert res_found.scalar_one_or_none() is None
