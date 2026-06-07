import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.web.diagnostics_api_router import router
from app.models import User, Monitor, SeenItem
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
import json
from app.scheduler.dry_run import perform_monitor_baseline_seen

def create_test_app():
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.mark.asyncio
async def test_baseline_seen_route_dry_run_false_creates_seen_items():
    app = create_test_app()
    mock_user = User(id=1, username="qwerty")
    app.dependency_overrides[require_api_user] = lambda: mock_user
    
    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.name = "test_monitor"
    mock_monitor.original_url = "https://www.vinted.pl"
    mock_monitor.domains_json = json.dumps(["vinted.pl"])
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    
    # Mock DB execute result for insert
    mock_res_db = MagicMock()
    mock_res_db.rowcount = 1
    
    # Define a side effect that returns monitor, then an empty result for item check, then the insert result
    async def db_execute_side_effect(stmt):
        # We need to distinguish between select (monitor) and insert
        if hasattr(stmt, 'compile'):
            stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            if "INSERT" in stmt_str:
                return mock_res_db
        return mock_result
    
    mock_db.execute = AsyncMock(side_effect=db_execute_side_effect)
    
    app.dependency_overrides[get_db] = lambda: mock_db
    
    # Patch the *correct* helper function
    with patch("app.web.diagnostics_api_router.perform_monitor_baseline_seen") as mock_helper:
        # Mock result dict
        mock_res = {
            "summary": {"raw_fetched_total": 1, "after_filters_total": 1, "already_seen_total": 0, "would_create_seen_items_total": 1, "created_seen_items_total": 1},
            "counts_by_domain": {"vinted.pl": {"raw_fetched": 1, "after_filters": 1, "already_seen": 0, "would_create_seen_items": 1, "created_seen_items": 1}},
            "samples_by_domain": {"vinted.pl": [{"id": "1", "title": "test", "brand": "Nike", "price": 10.0, "currency": "PLN", "path": "/items/1", "url": "https://www.vinted.pl/items/1", "domain": "vinted.pl", "source": "hydration"}]}
        }
        mock_helper.return_value = mock_res
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/diagnostics/monitors/22/baseline-seen-no-notify?domain=vinted.pl&dry_run=false")
            
            assert response.status_code == 200
            data = response.json()
            # Verify the response fields match the baseline output
            assert data["summary"]["created_seen_items_total"] == 1
            assert data["side_effects"]["writes_seen_items"] is True
            # Verify DB was called for insert
            assert mock_db.execute.call_count >= 2
