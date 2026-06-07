import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.web.diagnostics_api_router import router
from app.models import User
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
from app.scheduler.diagnostics import registry

def create_test_app():
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_starts_async():
    app = create_test_app()
    mock_user = User(id=1, username="admin")
    mock_user.token = "secret"
    app.dependency_overrides[require_api_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.scheduler.tasks.run_hydration_ssr_merge_job") as mock_task:
            response = await client.post(
                f"/api/v1/diagnostics/monitors/{mock_monitor.id}/jobs/hydration-ssr-photo-merge",
                headers={"Authorization": "Bearer secret"}
            )
            assert response.status_code == 200, response.json()
            data = response.json()
            assert "job_id" in data
            assert data["status"] == "running"
            assert mock_task.called
