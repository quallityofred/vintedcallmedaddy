import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.web.diagnostics_api_router import router
from app.models import User
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db

@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.mark.asyncio
async def test_post_monitor_dry_run_source_requires_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-source")
        assert response.status_code == 401

@pytest.mark.asyncio
async def test_post_monitor_dry_run_source_calls_hydration_and_returns_samples(app):
    mock_user = User(id=1, username="qwerty")
    app.dependency_overrides[require_api_user] = lambda: mock_user
    
    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.params_json = '{"catalog[]": ["1231"]}'
    mock_monitor.domains_json = '["vinted.pl"]'
    mock_monitor.original_url = "https://www.vinted.pl/catalog?catalog[]=1231"
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    # Patch VintedClient globally in the scraper client module to be absolutely sure
    with patch("app.scraper.client.VintedClient") as mock_client_cls, \
         patch("app.web.diagnostics_api_router.get_settings") as mock_settings_func, \
         patch("app.scraper.source_selector.get_settings") as mock_sel_settings_func:
        
        mock_settings = MagicMock()
        mock_settings.monitor_hydration_source_enabled = True
        mock_settings.rate_limit_per_minute = "60"
        mock_settings.monitor_detail_guard_enabled = False
        mock_settings.monitor_detail_category_guard_enabled = False
        mock_settings.monitor_detail_freshness_guard_enabled = False
        
        mock_settings_func.return_value = mock_settings
        mock_sel_settings_func.return_value = mock_settings
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.close = AsyncMock()
        mock_client_cls.return_value = mock_client
        
        mock_items = [
            {
                "id": "123",
                "title": "Nike Shox",
                "brand_title": "Nike",
                "price": 100.0,
                "currency": "PLN",
                "url": "https://www.vinted.pl/p/123",
                "photo_url": "p"
            }
        ]
        mock_client.fetch_catalog_hydration_items = AsyncMock(return_value=mock_items)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-source")
            assert response.status_code == 200
            data = response.json()
            assert data["selected_source"] == "hydration"
            assert data["counts_by_domain"]["vinted.pl"] == 1
            assert data["samples_by_domain"]["vinted.pl"][0]["id"] == "123"

@pytest.mark.asyncio
async def test_post_monitor_dry_run_rejects_unselected_domain(app):
    mock_user = User(id=1, username="qwerty")
    app.dependency_overrides[require_api_user] = lambda: mock_user
    
    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.params_json = '{"catalog[]": ["1231"]}'
    mock_monitor.domains_json = '["vinted.pl"]'
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.web.diagnostics_api_router.get_settings") as mock_settings_func:
        mock_settings = MagicMock()
        mock_settings.rate_limit_per_minute = "60"
        mock_settings_func.return_value = mock_settings

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-source", params={"domain": "vinted.fr"})
            assert response.status_code == 400
            assert "not selected" in response.json()["detail"]
