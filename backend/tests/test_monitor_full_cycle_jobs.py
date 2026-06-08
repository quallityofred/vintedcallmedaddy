import pytest
import json
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.models import FoundItem, Monitor, SeenItem, User
from app.scheduler.monitor_full_cycle import (
    cleanup_pending_no_notify_for_monitor,
    baseline_seen_no_notify_for_monitor,
    send_all_pending_for_monitor,
    run_monitor_full_cycle_job
)
import app.scheduler.monitor_full_cycle as monitor_full_cycle
from app.web.full_cycle_api_router import router
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db

import pytest_asyncio

@pytest_asyncio.fixture
async def test_user(db_session):
    user = User(
        username=f"testuser-{uuid.uuid4().hex[:8]}",
        password_hash="hash",
        password_salt="salt",
        is_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

@pytest_asyncio.fixture
async def test_monitor(db_session, test_user):
    monitor = Monitor(
        user_id=test_user.id,
        name="Test Monitor",
        original_url="https://vinted.pl/catalog",
        params_json='{"brand_ids": [53]}',
        domains_json='["vinted.pl"]',
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    return monitor

@pytest.fixture
def mock_session_factory(engine, monkeypatch):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(monitor_full_cycle, "get_session_factory", lambda: factory)
    return factory

@pytest.mark.asyncio
async def test_cleanup_pending_no_notify(db_session, test_monitor, mock_session_factory):
    # Setup: Create some pending items
    for i in range(5):
        item = FoundItem(
            monitor_id=test_monitor.id,
            vinted_item_id=100 + i,
            domain="vinted.pl",
            title=f"Item {i}",
            price=10.0,
            currency="PLN",
            brand="Nike",
            size="M",
            condition="new",
            photo_url="http://photo.com",
            item_url=f"http://vinted.pl/items/{i}",
            seller_id=1000,
            notified=False,
            found_at=datetime.now(timezone.utc)
        )
        db_session.add(item)
    await db_session.commit()

    # Test dry run
    res_dry = await cleanup_pending_no_notify_for_monitor(test_monitor.id, dry_run=True)
    assert res_dry["pending_before"] == 5
    assert res_dry["selected_for_ack"] == 5
    assert res_dry["marked_notified_count"] == 0
    assert res_dry["pending_after"] == 5

    # Test live run
    res_live = await cleanup_pending_no_notify_for_monitor(test_monitor.id, dry_run=False)
    assert res_live["pending_before"] == 5
    assert res_live["marked_notified_count"] == 5
    assert res_live["pending_after"] == 0

    # Verify in DB
    final_pending = await db_session.scalar(
        select(func.count(FoundItem.id)).where(FoundItem.monitor_id == test_monitor.id, FoundItem.notified == False)
    )
    assert final_pending == 0

@pytest.mark.asyncio
async def test_baseline_seen_no_notify(db_session, test_monitor, mock_session_factory):
    with patch("app.scheduler.monitor_full_cycle.VintedClient") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.close = AsyncMock()
        with patch("app.scheduler.monitor_full_cycle.perform_monitor_baseline_seen") as mock_baseline:
            mock_baseline.return_value = {"status": "success", "created_seen_items_total": 10}

            res = await baseline_seen_no_notify_for_monitor(test_monitor.id, dry_run=False)
            assert res["status"] == "success"
            assert res["created_seen_items_total"] == 10
            mock_baseline.assert_called_once()
            mock_client.close.assert_called_once()

@pytest.mark.asyncio
async def test_run_monitor_full_cycle_job_simulated_check_dry_run(db_session, test_monitor, mock_session_factory):
    # Test the simulated_check branch which uses VintedClient directly
    with patch("app.scheduler.monitor_full_cycle.VintedClient") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.close = AsyncMock()
        with patch("app.scheduler.monitor_full_cycle.perform_monitor_full_cycle_dry_run") as mock_dry_run:
            from app.scheduler.dry_run import MonitorFullCycleDryRunResult
            mock_dry_run.return_value = MonitorFullCycleDryRunResult(
                monitor_id=test_monitor.id,
                selected_source="hydration",
                reason="test",
                selected_domains=["vinted.pl"],
                dry_run_domains=["vinted.pl"],
                summary={},
                counts_by_domain={},
                pipeline_counts_by_domain={},
                seen_found_simulation_by_domain={},
                samples_by_domain={},
                errors_by_domain={}
            )

            # dry_run=True, run_check=True
            res = await run_monitor_full_cycle_job(
                test_monitor.id,
                dry_run=True,
                run_check=True,
                pause_before=False,
                pause_after=False
            )

            assert "simulated_check" in res["side_effects"]
            assert "check_dry_run" in res["results"]
            mock_client.close.assert_called_once()

@pytest.mark.asyncio
async def test_run_monitor_full_cycle_job_error_reporting(db_session, test_monitor, mock_session_factory):
    with patch("app.scheduler.monitor_full_cycle.baseline_seen_no_notify_for_monitor") as mock_baseline:
        mock_baseline.side_effect = ValueError("test_error")

        with pytest.raises(RuntimeError) as exc_info:
            await run_monitor_full_cycle_job(
                test_monitor.id,
                dry_run=True,
                cold_baseline=True
            )

        assert "baseline_failed: ValueError" in str(exc_info.value)

@pytest.mark.asyncio
async def test_send_all_pending_for_monitor(db_session, test_monitor, mock_session_factory):
    # Setup: Create pending items
    for i in range(10):
        item = FoundItem(
            monitor_id=test_monitor.id,
            vinted_item_id=200 + i,
            domain="vinted.pl",
            title=f"New Item {i}",
            price=20.0,
            currency="PLN",
            brand="Adidas",
            size="L",
            condition="good",
            photo_url="http://photo.com",
            item_url=f"http://vinted.pl/items/2{i}",
            seller_id=2000,
            notified=False,
            found_at=datetime.now(timezone.utc)
        )
        db_session.add(item)
    await db_session.commit()

    with patch("app.scheduler.monitor_full_cycle.process_pending_notifications") as mock_process:
        mock_process.side_effect = [
            {"sent_photo_count": 4, "selected_for_processing": 4, "marked_notified_count": 4},
            {"sent_photo_count": 4, "selected_for_processing": 4, "marked_notified_count": 4},
            {"sent_photo_count": 2, "selected_for_processing": 2, "marked_notified_count": 2},
        ]

        res = await send_all_pending_for_monitor(
            test_monitor.id, batch_limit=4, max_batches=5, dry_run=False
        )

        assert res["pending_before"] == 10
        assert res["batches_run"] == 3
        assert res["total_marked_notified"] == 10
        assert mock_process.call_count == 3

@pytest.mark.asyncio
async def test_run_monitor_full_cycle_job_live_check_success(db_session, test_monitor, mock_session_factory):
    # Mock check_monitor to simulate finding items and updating monitor status
    async def mock_check(m_id):
        async with mock_session_factory() as db:
            m = await db.get(Monitor, m_id)
            m.last_check_status = "success_new_items"
            m.items_found_count += 5
            m.last_check_at = datetime.now(timezone.utc)
            await db.commit()

    with patch("app.scheduler.monitor_full_cycle.check_monitor", side_effect=mock_check), \
         patch("app.scheduler.monitor_full_cycle.cleanup_pending_no_notify_for_monitor") as mock_cleanup, \
         patch("app.scheduler.monitor_full_cycle.baseline_seen_no_notify_for_monitor") as mock_baseline, \
         patch("app.scheduler.monitor_full_cycle.send_all_pending_for_monitor") as mock_send:
        
        mock_cleanup.return_value = {"selected_for_ack": 0}
        mock_baseline.return_value = {"created_seen_items_total": 10}
        mock_send.return_value = {"total_marked_notified": 5}

        # Monitor initially inactive
        test_monitor.is_active = False
        await db_session.commit()

        res = await run_monitor_full_cycle_job(
            test_monitor.id,
            dry_run=False,
            run_check=True,
            pause_before=False,
            pause_after=True
        )

        assert "check" in res["results"]
        assert res["results"]["check"]["last_check_status"] == "success_new_items"
        assert res["results"]["check"]["items_found_count"] == 5
        assert "ran_check" in res["side_effects"]
        
        # Verify monitor was paused after
        await db_session.refresh(test_monitor)
        assert test_monitor.is_active is False

@pytest.mark.asyncio
async def test_full_cycle_api_routes_status_shape(db_session, test_user, test_monitor):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_user] = lambda: test_user
    app.dependency_overrides[require_api_csrf] = lambda: None
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create a dummy completed job in registry
        from app.scheduler.diagnostics import registry
        job_id = "test_job_123"
        await registry.start_job(job_id, test_monitor.id, "test")
        dummy_result = {"foo": "bar", "status": "completed"}
        await registry.complete_job(job_id, dummy_result)

        # 2. Get status and verify shape
        response = await client.get(f"/api/v1/monitors/{test_monitor.id}/full-cycle-jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == "completed"
        assert data["foo"] == "bar"
