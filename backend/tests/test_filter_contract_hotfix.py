from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, ANY

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models import Monitor, User
from app.scheduler import tasks
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.web.diagnostics_api_router import router

def create_test_app(*, admin: bool = True, db_session = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_user] = lambda: User(
        id=999,
        username="admin",
        is_admin=admin,
    )
    app.dependency_overrides[require_api_csrf] = lambda: None
    if db_session is not None:
        app.dependency_overrides[get_db] = lambda: db_session
    return app

@pytest.mark.asyncio
async def test_runtime_repair_of_stale_monitor_params(db_session, monkeypatch):
    # Vivienne Westwood case: brand in path, but missing from params_json
    user = User(
        id=1, 
        username="testuser",
        password_hash="hash",
        password_salt="salt"
    )
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="vivienne-westwood",
        original_url="https://www.vinted.pl/brand/14217-vivienne-westwood?order=newest_first",
        params_json=json.dumps({"order": "newest_first"}),
        domains_json=json.dumps(["vinted.pl"]),
        interval_sec=120,
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()
    
    # Mock _new_session to use db_session
    class MockContext:
        def __init__(self, s): self.session = s
        async def __aenter__(self): return self.session
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(tasks, "_new_session", lambda: MockContext(db_session))
    
    context = await tasks._load_monitor_check_context(monitor.id)
    
    assert context is not None
    # Brand ID should be recovered from URL
    assert context.params.get("brand_ids[]") == [14217]
    assert context.monitor_filters.brand_ids == frozenset({"14217"})

from app.scheduler.dry_run import perform_monitor_dry_run, MonitorDryRunResult, perform_monitor_full_cycle_dry_run, MonitorFullCycleDryRunResult

@pytest.mark.asyncio
async def test_diagnostic_dry_run_respects_domain_override(db_session, monkeypatch):
    # Ensure hydration is disabled so it uses search_all_domains (brand-only)
    from app.config import Settings
    monkeypatch.setattr("app.scraper.source_selector.get_settings", lambda: Settings(monitor_hydration_source_enabled=False))

    admin_user = User(
        id=999,
        username="admin",
        password_hash="hash",
        password_salt="salt",
        is_admin=True,
    )
    db_session.add(admin_user)
    await db_session.flush()

    monitor = Monitor(
        user_id=admin_user.id,
        name="test-monitor",
        original_url="https://www.vinted.fr/catalog?brand_ids[]=1",
        params_json=json.dumps({"brand_ids[]": [1]}),
        domains_json=json.dumps(["vinted.fr", "vinted.pl", "vinted.be"]),
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()
    
    app = create_test_app(db_session=db_session)
    # Correct override to return the admin_user instance from DB
    app.dependency_overrides[require_api_user] = lambda: admin_user
    
    transport = ASGITransport(app=app)
    
    # Mock perform_monitor_dry_run
    res_dry = MonitorDryRunResult(
        monitor_id=monitor.id,
        selected_source="api",
        reason="brand_only_api_path",
        selected_domains=["vinted.fr", "vinted.pl", "vinted.be"],
        dry_run_domains=["vinted.fr"],
        counts_by_domain={},
        samples_by_domain={},
        errors_by_domain={},
        pipeline_counts_by_domain={},
        fetch_diagnostics_by_domain={},
        filter_diagnostics={},
        side_effects={}
    )
    mock_perform = AsyncMock(return_value=res_dry)
    monkeypatch.setattr("app.scheduler.dry_run.perform_monitor_dry_run", mock_perform)
    
    # Mock perform_monitor_full_cycle_dry_run
    async def mock_full_cycle(*args, **kwargs):
        domain = kwargs.get("target_domain")
        return MonitorFullCycleDryRunResult(
            monitor_id=monitor.id,
            selected_source="api",
            reason="brand_only_api_path",
            selected_domains=["vinted.fr", "vinted.pl", "vinted.be"],
            dry_run_domains=[domain] if domain else ["vinted.fr"],
            summary={},
            counts_by_domain={},
            pipeline_counts_by_domain={},
            seen_found_simulation_by_domain={},
            samples_by_domain={},
            errors_by_domain={},
            filter_diagnostics={},
            side_effects={}
        )

    
    mock_perform_full = AsyncMock(side_effect=mock_full_cycle)
    monkeypatch.setattr("app.scheduler.dry_run.perform_monitor_full_cycle_dry_run", mock_perform_full)
    
    # Mock VintedClient class to avoid actual API calls
    monkeypatch.setattr("app.web.diagnostics_api_router.VintedClient", MagicMock())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test dry-run-source with domain override
        res = await client.post(
            f"/api/v1/diagnostics/monitors/{monitor.id}/dry-run-source",
            json={"domain": "vinted.fr"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["dry_run_domains"] == ["vinted.fr"]
        
        # Verify it actually called perform_monitor_dry_run with target_domain="vinted.fr"
        mock_perform.assert_awaited()
        call_args = mock_perform.await_args
        assert call_args.kwargs["target_domain"] == "vinted.fr"

        # 2. Test dry-run-full-cycle with domain override bypassing guard
        # (Guard is > 2 effective domains)
        res_full = await client.post(
            f"/api/v1/diagnostics/monitors/{monitor.id}/dry-run-full-cycle",
            json={"domain": "vinted.be"}
        )
        assert res_full.status_code == 200
        data_full = res_full.json()
        assert data_full["dry_run_domains"] == ["vinted.be"]

@pytest.mark.asyncio
async def test_diagnostic_dry_run_guard_still_protects_broad_requests(db_session):
    admin_user = User(
        id=998, # Unique ID for this test case
        username="admin2",
        password_hash="hash",
        password_salt="salt",
        is_admin=True,
    )
    db_session.add(admin_user)
    await db_session.flush()

    monitor = Monitor(
        user_id=admin_user.id,
        name="test-monitor-broad",
        original_url="https://www.vinted.fr/catalog?brand_ids[]=1",
        params_json=json.dumps({"brand_ids[]": [1]}),
        domains_json=json.dumps(["vinted.fr", "vinted.pl", "vinted.be", "vinted.it"]),
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()
    
    app = create_test_app(db_session=db_session)
    app.dependency_overrides[require_api_user] = lambda: admin_user
    transport = ASGITransport(app=app)
    
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Requesting max_domains=3 without override should trigger guard (limit is 2)
        res = await client.post(
            f"/api/v1/diagnostics/monitors/{monitor.id}/dry-run-full-cycle",
            json={"max_domains": 3}
        )
        assert res.status_code == 200
        assert res.json()["reason"] == "full_cycle_dry_run_request_too_large"
