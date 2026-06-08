from __future__ import annotations

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models import Monitor, User
from app.scheduler.monitor_status import reconcile_monitor_check_status
from app.scheduler import tasks
from app.web import monitors_api_router
from app.web.dependencies import get_db
from app.web.api_dependencies import require_api_user as global_require_api_user
from app.web.monitors_api_router import require_api_user as monitors_require_api_user
from app.web.csrf import require_api_csrf, require_csrf
from app.web.monitors_api_router import router as monitors_router
from app.web.diagnostics_api_router import router as diagnostics_router

def create_test_app(db_session, user_override=None) -> FastAPI:
    app = FastAPI()
    app.include_router(monitors_router)
    app.include_router(diagnostics_router)
    
    admin_user = User(
        id=999,
        username="admin",
        is_admin=True,
    )
    
    def get_test_user():
        return user_override or admin_user

    app.dependency_overrides[global_require_api_user] = get_test_user
    app.dependency_overrides[monitors_require_api_user] = get_test_user
    app.dependency_overrides[require_api_csrf] = lambda: None
    app.dependency_overrides[require_csrf] = lambda: None
    app.dependency_overrides[get_db] = lambda: db_session
    return app

def test_reconciliation_logic():
    # 1. DB running + registry active = not stale
    m1 = Monitor(last_check_status="running", last_check_started_at=datetime.now(timezone.utc))
    res1 = reconcile_monitor_check_status(m1, is_running_in_registry=True)
    assert res1["effective_status"] == "running"
    assert res1["is_stale_running"] is False
    assert "currently running" in res1["explanation"]

    # 2. DB running + registry inactive = stale
    m2 = Monitor(last_check_status="running", last_check_started_at=datetime.now(timezone.utc))
    res2 = reconcile_monitor_check_status(m2, is_running_in_registry=False)
    assert res2["effective_status"] == "failed"
    assert res2["is_stale_running"] is True
    assert "stale" in res2["explanation"]

    # 3. DB failed + impossible timestamps + registry inactive = inconsistent
    now = datetime.now(timezone.utc)
    m3 = Monitor(
        last_check_status="failed", 
        last_check_started_at=now, 
        last_check_completed_at=now - timedelta(seconds=10)
    )
    res3 = reconcile_monitor_check_status(m3, is_running_in_registry=False)
    assert res3["effective_status"] == "failed"
    assert res3["is_stale_running"] is False
    assert res3["is_inconsistent_check_state"] is True
    assert "inconsistent" in res3["explanation"]

    # 4. DB success + normal timestamps + registry inactive = success
    m4 = Monitor(
        last_check_status="success_new_items", 
        last_check_started_at=now - timedelta(seconds=20),
        last_check_completed_at=now
    )
    res4 = reconcile_monitor_check_status(m4, is_running_in_registry=False)
    assert res4["effective_status"] == "success_new_items"
    assert res4["is_stale_running"] is False
    assert res4["is_inconsistent_check_state"] is False
    assert "successfully" in res4["explanation"]

@pytest.mark.asyncio
async def test_check_now_guard_bypass_stale(db_session, monkeypatch):
    user = User(username="u1", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Stale monitor: DB says running, but we'll mock registry as inactive
    monitor = Monitor(
        user_id=user.id, 
        name="stale-m", 
        original_url="http://v.pl/m", 
        params_json='{}',
        domains_json='["vinted.pl"]',
        last_check_status="running",
        last_check_started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        is_active=True
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    app = create_test_app(db_session, user_override=user)
    
    # Mock registry: NOT running
    monkeypatch.setattr(tasks, "is_monitor_check_running", lambda mid: False)
    monkeypatch.setattr(tasks, "is_monitor_check_capacity_saturated", lambda uid: False)
    
    mock_scheduler = MagicMock()
    mock_scheduler.trigger_now.return_value = True
    monkeypatch.setattr(monitors_api_router, "get_scheduler", lambda req: mock_scheduler)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Should NOT return 409 because it's stale
        response = await client.post(f"/api/v1/monitors/{monitor.id}/check-now")
        assert response.status_code == 200
        assert response.json()["ok"] is True

@pytest.mark.asyncio
async def test_repair_stale_status_endpoint(db_session, monkeypatch):
    user = User(username="u2", password_hash="h", password_salt="s", is_admin=True)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    now = datetime.now(timezone.utc)
    monitor = Monitor(
        user_id=user.id, 
        name="repair-m", 
        original_url="http://v.pl/m", 
        params_json='{}',
        domains_json='["vinted.pl"]',
        last_check_status="running",
        last_check_started_at=now,
        last_check_completed_at=now - timedelta(minutes=1),
        is_active=True
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    app = create_test_app(db_session, user_override=user)
    monkeypatch.setattr(tasks, "is_monitor_check_running", lambda mid: False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Dry run
        response = await client.post(f"/api/v1/diagnostics/monitors/{monitor.id}/repair-stale-status?dry_run=true")
        assert response.status_code == 200
        data = response.json()
        assert data["is_stale_running"] is True
        assert data["is_inconsistent_check_state"] is True
        assert data["would_repair"] is True
        
        await db_session.refresh(monitor)
        assert monitor.last_check_status == "running"

        # 2. Actual repair
        response = await client.post(f"/api/v1/diagnostics/monitors/{monitor.id}/repair-stale-status?dry_run=false")
        assert response.status_code == 200
        data = response.json()
        assert data["after_repair"]["last_check_status"] == "failed"
        
        await db_session.refresh(monitor)
        assert monitor.last_check_status == "failed"
        assert monitor.last_check_completed_at == monitor.last_check_started_at

        # 3. Idempotent
        response = await client.post(f"/api/v1/diagnostics/monitors/{monitor.id}/repair-stale-status?dry_run=false")
        assert response.status_code == 200
        assert response.json()["would_repair"] is False

@pytest.mark.asyncio
async def test_repair_endpoint_rejects_active_check(db_session, monkeypatch):
    user = User(username="u3", password_hash="h", password_salt="s", is_admin=True)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(user_id=user.id, name="active-m", original_url="http://v.pl/m", params_json='{}', domains_json='[]', last_check_status="running")
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    app = create_test_app(db_session, user_override=user)
    monkeypatch.setattr(tasks, "is_monitor_check_running", lambda mid: True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/diagnostics/monitors/{monitor.id}/repair-stale-status?dry_run=false")
        assert response.status_code == 409
        assert "actively running" in response.json()["detail"]
