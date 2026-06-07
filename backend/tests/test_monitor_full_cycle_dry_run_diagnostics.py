import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.web.diagnostics_api_router import router
from app.models import User, Monitor
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
import json

from app.scheduler.dry_run import perform_monitor_dry_run

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


@pytest.mark.asyncio
async def test_full_cycle_dry_run_exposes_safe_hydration_field_diagnostics():
    item = {
        "id": 9100000001,
        "title": "Synthetic Nike shoe",
        "brand_title": "Nike",
        "path": "/items/9100000001-synthetic-nike-shoe",
        "price": {"amount": "64", "currency_code": "PLN"},
        "listed_at": "2026-06-07T12:34:56Z",
    }
    encoded = json.dumps({"items": {"items": [item]}}, separators=(",", ":")).replace('"', '\\"')
    html = f'self.__next_f.push([1,"{encoded}"])'

    class ClientStub:
        async def fetch_catalog_html(self, url, *, domain):
            return html

    monitor = Monitor(
        id=22,
        user_id=1,
        name="Nike shoes",
        original_url="https://www.vinted.pl/catalog?brand_ids[]=53&catalog[]=1231",
        params_json=json.dumps({"brand_ids[]": ["53"], "catalog[]": ["1231"]}),
        domains_json=json.dumps(["vinted.pl"]),
        is_active=False,
    )

    with patch("app.scheduler.dry_run.should_use_hydration_source", return_value=True):
        result = await perform_monitor_dry_run(
            monitor,
            ClientStub(),
            target_domain="vinted.pl",
            max_items_per_domain=10,
            include_media_diagnostics=True,
        )

    fields = result.pipeline_counts_by_domain["vinted.pl"]["item_field_diagnostics"]
    media = result.pipeline_counts_by_domain["vinted.pl"]["media_token_diagnostics"]
    assert fields["photo_url_missing"] == 1
    assert fields["timestamp_field_presence"]["listed_at"] == 1
    assert media["enabled"] is True
    assert media["chunks_scanned"] == 1
    assert media["chunks_with_item_paths"] == 1
    assert media["chunks_with_timestamp_tokens"] == 1
    assert media["sample_anchor_windows"][0]["item_id"] == "9100000001"
    sample = result.samples_by_domain["vinted.pl"][0]
    assert sample.has_photo is False
    assert sample.timestamp == "2026-06-07T12:34:56+00:00"
    serialized = json.dumps(result, default=lambda value: value.__dict__)
    assert "self.__next_f" not in serialized
    assert "Synthetic Nike shoe" in serialized
    assert "https://images" not in serialized

@pytest.mark.asyncio
async def test_full_cycle_dry_run_media_diagnostics_disabled_by_default():
    app = create_test_app()
    mock_user = User(id=1, username='qwerty')
    app.dependency_overrides[require_api_user] = lambda: mock_user
    
    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.domains_json = json.dumps(['vinted.pl'])
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db
    
    with patch("app.web.diagnostics_api_router.perform_monitor_full_cycle_dry_run", new_callable=AsyncMock) as mock_helper:
        mock_helper.return_value = MagicMock()
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url='http://test') as client:
            response = await client.post('/api/v1/diagnostics/monitors/22/dry-run-full-cycle?max_domains=1')

            # Print response text if it failed
            if response.status_code != 200:
                print(response.text)
            assert response.status_code == 200

            mock_helper.assert_called_once()
            _, kwargs = mock_helper.call_args
            assert kwargs['include_media_diagnostics'] is False

@pytest.mark.asyncio
async def test_full_cycle_dry_run_media_diagnostics_enabled_with_caps():
    app = create_test_app()
    mock_user = User(id=1, username='qwerty')
    app.dependency_overrides[require_api_user] = lambda: mock_user
    
    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.domains_json = json.dumps(['vinted.pl'])
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db
    
    with patch("app.web.diagnostics_api_router.perform_monitor_full_cycle_dry_run", new_callable=AsyncMock) as mock_helper:
        mock_helper.return_value = MagicMock()
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url='http://test') as client:
            response = await client.post('/api/v1/diagnostics/monitors/22/dry-run-full-cycle?include_media_diagnostics=true&max_domains=1&media_diag_max_items=5&media_diag_max_chunks=10')

            if response.status_code != 200:
                print(response.text)
            assert response.status_code == 200

            mock_helper.assert_called_once()
            _, kwargs = mock_helper.call_args
            assert kwargs['include_media_diagnostics'] is True
            assert kwargs['media_diag_max_items'] == 5
            assert kwargs['media_diag_max_chunks'] == 10

