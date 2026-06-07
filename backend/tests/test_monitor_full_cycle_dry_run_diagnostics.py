import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.web.diagnostics_api_router import router
from app.models import User
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db

def create_test_app():
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.mark.asyncio
async def test_full_cycle_dry_run_top_level_exception_returns_json():
    app = create_test_app()
    mock_user = User(id=1, username="qwerty")
    app.dependency_overrides[require_api_user] = lambda: mock_user
    
    # Mock DB and monitor
    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db
    
    # Patch helper to raise exception
    with patch("app.web.diagnostics_api_router.perform_monitor_full_cycle_dry_run", side_effect=Exception("Unexpected")):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-full-cycle")
            
            # Should be 200 with error JSON, not 500
            assert response.status_code == 200
            data = response.json()
            assert data["errors_by_domain"]["__global__"] == "InternalServerError"
            assert data["side_effects"]["calls_vinted"] is False
