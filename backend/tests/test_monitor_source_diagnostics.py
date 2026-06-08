import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
async def test_get_monitor_source_selection_requires_auth():
    app = create_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/diagnostics/monitors/22/source-selection")
        assert response.status_code == 401

@pytest.mark.asyncio
async def test_get_monitor_source_selection_returns_hydration_when_enabled():
    app = create_test_app()
    mock_user = User(id=1, username="qwerty")
    app.dependency_overrides[require_api_user] = lambda: mock_user
    
    # Simple mock session
    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.params_json = '{"catalog[]": ["1231"]}'
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute.return_value = mock_result
    
    app.dependency_overrides[require_api_user] = lambda: mock_user
    from app.web.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.web.diagnostics_api_router.get_settings") as mock_diag_settings, \
         patch("app.scraper.source_selector.get_settings") as mock_sel_settings, \
         patch("app.web.diagnostics_api_router.registry") as mock_registry:
        
        mock_settings = MagicMock()
        mock_settings.monitor_hydration_source_enabled = True
        mock_settings.monitor_ssr_photo_merge_enabled = False
        mock_settings.monitor_detail_guard_enabled = False
        mock_settings.monitor_detail_category_guard_enabled = False
        mock_settings.monitor_detail_freshness_guard_enabled = False
        
        mock_diag_settings.return_value = mock_settings
        mock_sel_settings.return_value = mock_settings
        mock_registry.get_check = AsyncMock(return_value=None)
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/diagnostics/monitors/22/source-selection")
            assert response.status_code == 200
            data = response.json()
            assert data["selected_source"] == "hydration"
            assert data["reason"] == "catalog_filter_detected"
            assert data["hydration_ssr_photo_merge_enabled"] is False
            assert data["hydration_ssr_photo_merge_eligible"] is False

@pytest.mark.asyncio
async def test_get_monitor_source_selection_returns_api_when_flag_disabled():
    app = create_test_app()
    mock_user = User(id=1, username="qwerty")
    app.dependency_overrides[require_api_user] = lambda: mock_user
    
    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.params_json = '{"catalog[]": ["1231"]}'
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute.return_value = mock_result
    
    from app.web.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.web.diagnostics_api_router.get_settings") as mock_diag_settings, \
         patch("app.scraper.source_selector.get_settings") as mock_sel_settings, \
         patch("app.web.diagnostics_api_router.registry") as mock_registry:
        
        mock_settings = MagicMock()
        mock_settings.monitor_hydration_source_enabled = False
        mock_settings.monitor_ssr_photo_merge_enabled = False
        mock_settings.monitor_detail_guard_enabled = False
        mock_settings.monitor_detail_category_guard_enabled = False
        mock_settings.monitor_detail_freshness_guard_enabled = False
        
        mock_diag_settings.return_value = mock_settings
        mock_sel_settings.return_value = mock_settings
        mock_registry.get_check = AsyncMock(return_value=None)
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/diagnostics/monitors/22/source-selection")
            assert response.status_code == 200
            data = response.json()
            assert data["selected_source"] == "api"
            assert data["reason"] == "flag_disabled"


@pytest.mark.asyncio
async def test_get_monitor_source_selection_reports_ssr_photo_merge_when_enabled():
    app = create_test_app()
    mock_user = User(id=1, username="qwerty")
    app.dependency_overrides[require_api_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.params_json = '{"catalog[]": ["1231"]}'
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute.return_value = mock_result

    from app.web.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.web.diagnostics_api_router.get_settings") as mock_diag_settings, \
         patch("app.scraper.source_selector.get_settings") as mock_sel_settings, \
         patch("app.web.diagnostics_api_router.registry") as mock_registry:
        settings = MagicMock()
        settings.monitor_hydration_source_enabled = True
        settings.monitor_ssr_photo_merge_enabled = True
        settings.monitor_detail_guard_enabled = False
        settings.monitor_detail_category_guard_enabled = False
        settings.monitor_detail_freshness_guard_enabled = False
        mock_diag_settings.return_value = settings
        mock_sel_settings.return_value = settings
        mock_registry.get_check = AsyncMock(return_value=None)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/diagnostics/monitors/22/source-selection")

    assert response.status_code == 200
    data = response.json()
    assert data["selected_source"] == "hydration_ssr_photo_merge"
    assert data["hydration_ssr_photo_merge_enabled"] is True
    assert data["hydration_ssr_photo_merge_eligible"] is True
