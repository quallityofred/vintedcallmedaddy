from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import User
from app.scheduler import tasks
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.web.diagnostics_api_router import router
from tests.test_notification_hotfix import seed_pending_items, create_test_app

@pytest.fixture
def hotfix_session_factory(engine, monkeypatch):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", factory)
    yield factory
    tasks.AsyncSessionLocal = None

@pytest.mark.asyncio
async def test_worker_stats_initial_state():
    stats = tasks.get_pending_notifications_worker_stats()
    assert stats["last_run_status"] == "never_run"
    assert stats["enabled"] is False

@pytest.mark.asyncio
async def test_worker_tick_success(db_session, hotfix_session_factory, monkeypatch):
    user, monitor, _, items = await seed_pending_items(db_session, count=1)
    
    # Mock Telegram success
    send_mock = AsyncMock(return_value="photo")
    monkeypatch.setattr(tasks, "send_item_notification", send_mock)
    
    # Mock settings
    monkeypatch.setattr(tasks.settings, "pending_notifications_worker_enabled", True)
    monkeypatch.setattr(tasks.settings, "pending_notifications_worker_batch_limit", 5)
    
    await tasks.run_pending_notifications_worker()
    
    stats = tasks.get_pending_notifications_worker_stats()
    assert stats["last_run_status"] == "success"
    assert stats["last_run_result"]["marked_notified_count"] == 1
    assert stats["last_run_result"]["pending_after"] == 0
    
    await db_session.refresh(items[0])
    assert items[0].notified is True

@pytest.mark.asyncio
async def test_worker_non_overlap(db_session, hotfix_session_factory, monkeypatch):
    # Mock process_pending_notifications to hang
    hang_event = asyncio.Event()
    original_process = tasks.process_pending_notifications
    
    async def slow_process(*args, **kwargs):
        await hang_event.wait()
        return await original_process(*args, **kwargs)
        
    monkeypatch.setattr(tasks, "process_pending_notifications", slow_process)
    
    # Start first tick in background
    tick1 = asyncio.create_task(tasks.run_pending_notifications_worker())
    
    # Wait for it to start and lock
    while not tasks._worker_lock.locked():
        await asyncio.sleep(0.01)
        
    # Second tick should skip
    await tasks.run_pending_notifications_worker()
    
    stats = tasks.get_pending_notifications_worker_stats()
    assert stats["skipped_due_to_overlap_count"] == 1
    
    # Finish first tick
    hang_event.set()
    await tick1
    
    final_stats = tasks.get_pending_notifications_worker_stats()
    assert final_stats["last_run_status"] == "success"

@pytest.mark.asyncio
async def test_worker_error_recording(db_session, hotfix_session_factory, monkeypatch):
    monkeypatch.setattr(tasks, "process_pending_notifications", AsyncMock(side_effect=RuntimeError("test error")))
    
    await tasks.run_pending_notifications_worker()
    
    stats = tasks.get_pending_notifications_worker_stats()
    assert stats["last_run_status"] == "failed"
    assert "test error" in stats["last_error"]
    assert stats["consecutive_failures"] == 1

@pytest.mark.asyncio
async def test_diagnostics_endpoint(db_session, hotfix_session_factory):
    app = create_test_app(db_session=db_session)
    transport = ASGITransport(app=app)
    
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/diagnostics/notifications/worker")
        assert res.status_code == 200
        data = res.json()
        assert "last_run_status" in data
        assert "running" in data
        assert data["side_effects"]["sends_telegram"] is False

@pytest.mark.asyncio
async def test_health_endpoint(db_session, hotfix_session_factory, monkeypatch):
    from app.app_main import create_app
    app = create_app()
    transport = ASGITransport(app=app)
    
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert "pending_notifications_worker" in data
        assert data["pending_notifications_worker"]["enabled"] is False
