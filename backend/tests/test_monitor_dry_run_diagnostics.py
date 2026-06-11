import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.web.diagnostics_api_router import router
from app.models import User
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
from app.scheduler.dry_run import _safe_collect_literal_marker_diagnostics

def create_test_app():
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.mark.asyncio
async def test_post_monitor_dry_run_source_requires_auth():
    app = create_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-source")
        assert response.status_code == 401

@pytest.mark.asyncio
async def test_post_monitor_dry_run_source_calls_hydration_and_returns_samples():
    app = create_test_app()
    mock_user = User(id=1, username="qwerty")
    app.dependency_overrides[require_api_user] = lambda: mock_user

    mock_db = AsyncMock()
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.user_id = 1
    mock_monitor.name = "Nike Monitor"
    mock_monitor.params_json = '{"catalog[]": ["1231"]}'
    mock_monitor.domains_json = '["vinted.pl"]'
    mock_monitor.original_url = "https://www.vinted.pl/catalog?catalog[]=1231"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_monitor
    mock_db.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.scraper.client.VintedClient") as mock_client_cls, \
         patch("app.web.diagnostics_api_router.get_settings") as mock_settings_func, \
         patch("app.scraper.source_selector.get_settings") as mock_sel_settings_func, \
         patch("app.scheduler.dry_run.analyze_hydration_html") as mock_analyze, \
         patch("app.scheduler.dry_run.get_candidate_samples") as mock_samples, \
         patch("app.scheduler.dry_run.collect_redacted_candidate_structures") as mock_fallback_samples:

        mock_settings = MagicMock()
        mock_settings.monitor_hydration_source_enabled = True
        mock_settings.rate_limit_per_minute = "60"
        mock_settings.monitor_detail_guard_enabled = False
        mock_settings.monitor_detail_category_guard_enabled = False
        mock_settings.monitor_detail_freshness_guard_enabled = False

        mock_settings_func.return_value = mock_settings
        mock_sel_settings_func.return_value = mock_settings

        mock_client = AsyncMock()
        field_sequence = (
            '"id":999,"title":"Nike Air max 95","brand_title":"Nike",'
            '"path":"/items/9106911084-nike-air-max-95",'
            '"amount":"64","currency_code":"EUR"'
        )
        escaped_sequence = field_sequence.replace('"', '\\"')
        mock_client.fetch_catalog_html = AsyncMock(
            return_value=f'self.__next_f.push([1,"{escaped_sequence}"])'
        )
        mock_client_cls.return_value = mock_client

        mock_analyze.return_value = {
            "html_contains_next_f": True,
            "next_f_chunks": 1,
            "chunks_with_item_text_markers": 1,
            "chunks_with_brand_title_marker": 1,
            "chunks_with_price_marker": 1,
            "chunks_with_items_path_marker": 1,
            "candidate_item_objects_count": 1
        }
        # Structured extraction returns empty
        mock_samples.return_value = []
        # Fallback extraction returns samples
        mock_fallback_samples.return_value = [
            {
                "sample_index": 0,
                "chunk_index": 0,
                "candidate_kind": "marker_context",
                "markers_present": {"id": True, "title": True, "path": True, "brand": True},
                "parseability": {"balanced_object_found": False, "json_raw_decode_success": False},
                "redacted_skeleton": {"fragment_contains": ["items_path", "brand_title", "price"], "likely_encoding": "react_flight_string_segment"}
            }
        ]

        mock_client.fetch_catalog_hydration_items = AsyncMock(return_value=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-source", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["selected_source"] == "hydration"
            assert "fetch_diagnostics_by_domain" in data
            diagnostics = data["fetch_diagnostics_by_domain"]["vinted.pl"]
            assert diagnostics["candidate_samples"][0]["candidate_kind"] == "marker_context"
            assert diagnostics["parser_strategy_used"] == "react_flight_field_sequence_path_anchored"
            assert diagnostics["field_sequence_path_markers"] == 1
            assert diagnostics["field_sequence_records_before_validation"] == 1
            assert diagnostics["field_sequence_records_after_validation"] == 1
            assert diagnostics["field_sequence_records_after_dedup"] == 1
            pipeline = data["pipeline_counts_by_domain"]["vinted.pl"]
            assert pipeline["field_sequence_path_markers"] == 1
            assert pipeline["field_sequence_records_after_dedup"] == 1
            assert data["side_effects"] == {
                "runs_scheduler_check": False,
                "writes_seen_items": False,
                "writes_found_items": False,
                "updates_monitor": False,
                "enqueues_notifications": False,
                "sends_telegram": False,
                "calls_vinted": True,
            }


def test_backend_import_ok():
    from app.scheduler.dry_run import perform_monitor_dry_run
    from app.main import app

    assert perform_monitor_dry_run is not None
    assert app is not None


def test_literal_marker_diagnostics_remain_lazy_optional():
    with patch(
        "app.scraper.hydration_parser.collect_literal_marker_diagnostics",
        side_effect=ValueError("synthetic diagnostics failure"),
    ):
        result = _safe_collect_literal_marker_diagnostics("synthetic")

    assert result["safe_error"] == "literal_marker_diagnostics_failed"
    assert result["literal_marker_samples"] == {
        "items_path": [],
        "brand_title": [],
        "price": [],
    }

@pytest.mark.asyncio
async def test_post_monitor_dry_run_source_ssr_html_photo_no_name_error():
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
        response = await client.post(
            f"/api/v1/diagnostics/monitors/{mock_monitor.id}/dry-run-source?source=ssr_html_photo",
            headers={"Authorization": "Bearer secret"}
        )
        # We expect a failure because Vinted client/network is not mocked,
        # but we are testing for a NameError.
        assert response.status_code != 500 or "NameError" not in response.json().get("detail", "")
