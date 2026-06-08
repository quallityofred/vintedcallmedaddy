import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.web.diagnostics_api_router import router
from app.models import User
from app.web.api_dependencies import require_api_user

def create_test_app():
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.mark.asyncio
async def test_process_notifications_diagnostic_dry_run():
    app = create_test_app()
    mock_user = User(id=1, username="admin", is_admin=True)
    app.dependency_overrides[require_api_user] = lambda: mock_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.scheduler.tasks.process_pending_notifications") as mock_process:
            response = await client.post("/api/v1/diagnostics/notifications/process-pending?dry_run=true&limit=10")
            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Dry run: notification processing would be triggered with limit"
            assert data["limit"] == 10
            assert not mock_process.called

@pytest.mark.asyncio
async def test_process_notifications_diagnostic_executes():
    app = create_test_app()
    mock_user = User(id=1, username="admin", is_admin=True)
    app.dependency_overrides[require_api_user] = lambda: mock_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.scheduler.tasks.process_pending_notifications", new_callable=AsyncMock) as mock_process:
            response = await client.post("/api/v1/diagnostics/notifications/process-pending?dry_run=false&limit=20")
            assert response.status_code == 200
            mock_process.assert_awaited_with(limit=20)
