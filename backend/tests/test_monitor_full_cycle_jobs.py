import pytest
import json
import uuid
from unittest.mock import AsyncMock, patch
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
        mock_client = mock_client_class.return_value.__aenter__.return_value
        with patch("app.scheduler.monitor_full_cycle.perform_monitor_baseline_seen") as mock_baseline:
            mock_baseline.return_value = {"status": "success", "created_seen_items_total": 10}
            
            res = await baseline_seen_no_notify_for_monitor(test_monitor.id, dry_run=False)
            assert res["status"] == "success"
            assert res["created_seen_items_total"] == 10
            mock_baseline.assert_called_once()

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
async def test_run_monitor_full_cycle_job(db_session, test_monitor, mock_session_factory):
    with patch("app.scheduler.monitor_full_cycle.cleanup_pending_no_notify_for_monitor") as mock_cleanup, \
         patch("app.scheduler.monitor_full_cycle.baseline_seen_no_notify_for_monitor") as mock_baseline, \
         patch("app.scheduler.monitor_full_cycle.check_monitor") as mock_check, \
         patch("app.scheduler.monitor_full_cycle.send_all_pending_for_monitor") as mock_send:
        
        mock_cleanup.return_value = {"selected_for_ack": 1}
        mock_baseline.return_value = {"created_seen_items_total": 5}
        mock_send.return_value = {"total_marked_notified": 3}
        
        res = await run_monitor_full_cycle_job(
            test_monitor.id,
            dry_run=False,
            cleanup_existing_pending=True,
            cold_baseline=True,
            run_check=True,
            send_pending=True,
            pause_before=True,
            pause_after=True
        )
        
        assert "cleanup" in res["results"]
        assert "baseline" in res["results"]
        assert "notifications" in res["results"]
        assert "ran_check" in res["side_effects"]
        
        # Verify monitor is paused (pause_after=True)
        await db_session.refresh(test_monitor)
        assert test_monitor.is_active == False

@pytest.mark.asyncio
async def test_full_cycle_api_routes(db_session, test_user, test_monitor):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_user] = lambda: test_user
    app.dependency_overrides[require_api_csrf] = lambda: None
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.scheduler.tasks.run_monitor_full_cycle_job_task") as mock_task:
            response = await client.post(
                f"/api/v1/monitors/{test_monitor.id}/full-cycle-jobs",
                params={"dry_run": "true"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "job_id" in data
            
            job_id = data["job_id"]
            response = await client.get(f"/api/v1/monitors/{test_monitor.id}/full-cycle-jobs/{job_id}")
            assert response.status_code == 200
            assert response.json()["status"] == "running"

        with patch("app.scheduler.tasks.run_monitor_send_all_pending_job_task") as mock_task:
            response = await client.post(
                f"/api/v1/monitors/{test_monitor.id}/notifications/send-pending-jobs",
                params={"dry_run": "true"}
            )
            assert response.status_code == 200
            assert "job_id" in response.json()
