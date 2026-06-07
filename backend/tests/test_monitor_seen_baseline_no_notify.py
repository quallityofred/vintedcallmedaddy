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
async def test_baseline_seen_requires_auth():
    app = create_test_app()
    # No auth override
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/diagnostics/monitors/22/baseline-seen-no-notify")
        assert response.status_code == 401
