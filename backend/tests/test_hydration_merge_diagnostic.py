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
async def test_hydration_with_ssr_photos_merges_data():
    app = create_test_app()
    mock_user = User(id=1, username="admin")
    mock_user.token = "secret"
    app.dependency_overrides[require_api_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.original_url = "https://www.vinted.pl/catalog?catalog[]=1231"
    mock_monitor.domains_json = '["vinted.pl"]'
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.scraper.client.VintedClient") as mock_client_cls, \
         patch("app.scraper.hydration_parser.extract_hydration_items") as mock_hydration, \
         patch("app.scraper.catalog_ssr_parser.parse_catalog_ssr_photo_map") as mock_ssr:

        mock_client = AsyncMock()
        mock_client.fetch_catalog_html = AsyncMock(return_value="<html></html>")
        mock_client_cls.return_value = mock_client

        mock_hydration.return_value = [
            {'id': 1, 'title': 'Nike Shoes', 'price': 100.0, 'path': '/items/1-nike-shoes'}
        ]
        mock_ssr.return_value = {
            '1': 'https://images1.vinted.net/t/01.webp'
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/diagnostics/monitors/{mock_monitor.id}/dry-run-source?source=hydration_with_ssr_photos",
                headers={"Authorization": "Bearer secret"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["overlap_total"] == 1
            assert data["samples_by_domain"]["vinted.pl"][0]["has_ssr_photo"] == True
            assert data["samples_by_domain"]["vinted.pl"][0]["photo_host"] == "images1.vinted.net"
            assert "photo_url" not in data["samples_by_domain"]["vinted.pl"][0]
