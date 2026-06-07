import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.web.diagnostics_api_router import router
from app.models import User, Monitor
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
import json

def create_test_app():
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.mark.asyncio
async def test_full_cycle_rejects_oversized_max_domains_before_vinted_calls():
    app = create_test_app()
    mock_user = User(id=1, username="qwerty")
    app.dependency_overrides[require_api_user] = lambda: mock_user
    
    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.domains_json = json.dumps(["vinted.pl", "vinted.fr", "vinted.de", "vinted.es", "vinted.it", "vinted.nl", "vinted.pt", "vinted.co.uk"])
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db
    
    with patch("app.web.diagnostics_api_router.perform_monitor_full_cycle_dry_run", new_callable=AsyncMock) as mock_helper:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-full-cycle?max_domains=8")
            
            assert response.status_code == 200
            data = response.json()
            assert data["safe_error"] == "full_cycle_dry_run_request_too_large"
            assert data["side_effects"]["calls_vinted"] is False
            mock_helper.assert_not_called()
