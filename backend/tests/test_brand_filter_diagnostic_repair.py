from __future__ import annotations
import json
import pytest
from httpx import ASGITransport, AsyncClient
from app.models import Monitor, User
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.web.diagnostics_api_router import router
from fastapi import FastAPI

def create_test_app(*, admin: bool = True, db_session = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    # Attach a dummy scheduler to app.state
    app.state.scheduler = MagicMock()
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
async def test_diagnostic_source_selection_repairs_path_based_brand_filter(db_session, monkeypatch):
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
        user_id=999,
        name="vivienne-westwood",
        original_url="https://www.vinted.pl/brand/14217-vivienne-westwood?order=newest_first",
        params_json=json.dumps({"order": "newest_first"}),
        domains_json=json.dumps(["vinted.pl"]),
        interval_sec=120,
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()
    
    app = create_test_app(db_session=db_session)
    transport = ASGITransport(app=app)
    
    # Mock VintedClient class to avoid actual API calls
    monkeypatch.setattr("app.web.diagnostics_api_router.VintedClient", MagicMock())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/v1/diagnostics/monitors/{monitor.id}/source-selection")
        assert res.status_code == 200
        data = res.json()
        
        # This is expected to FAIL currently, based on the task description
        assert data["has_brand_filter"] is True
        assert "14217" in data["filter_diagnostics"]["brand_ids"]
        assert "brand_ids[]" in data["filter_diagnostics"]["effective_request_param_keys"]
        assert data["filter_diagnostics"]["request_params_match_original_url"] is True

from unittest.mock import MagicMock
