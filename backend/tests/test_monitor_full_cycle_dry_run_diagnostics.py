from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models import Monitor, User
from app.scheduler.dry_run import (
    DryRunItem,
    FullCycleDomainCounts,
    FullCycleSimulationSamples,
    MonitorDryRunResult,
    MonitorFullCycleDryRunResult,
    perform_monitor_full_cycle_dry_run,
)
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
from app.web.diagnostics_api_router import router


def create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def make_monitor(*, cold_start: bool = False, domains: list[str] | None = None) -> Monitor:
    selected_domains = domains or ["vinted.pl"]
    return Monitor(
        id=22,
        user_id=1,
        name="Nike shoes",
        original_url="https://www.vinted.pl/catalog?brand_ids[]=53&catalog[]=1231",
        params_json='{"brand_ids[]":["53"],"catalog[]":["1231"]}',
        domains_json=str(selected_domains).replace("'", '"'),
        interval_sec=120,
        last_check_at=None if cold_start else datetime.now(timezone.utc),
    )


def make_item(item_id: int, domain: str = "vinted.pl") -> DryRunItem:
    return DryRunItem(
        id=str(item_id),
        title=f"Item {item_id}",
        brand_title="Nike",
        price=10.0,
        currency="EUR",
        url=f"https://www.{domain}/items/{item_id}-item",
        domain=domain,
        source="hydration",
    )


def make_source_result(items_by_domain: dict[str, list[DryRunItem]]) -> MonitorDryRunResult:
    domains = list(items_by_domain)
    return MonitorDryRunResult(
        monitor_id=22,
        selected_source="hydration",
        reason="catalog_filter_detected",
        selected_domains=domains,
        dry_run_domains=domains,
        counts_by_domain={domain: len(items) for domain, items in items_by_domain.items()},
        samples_by_domain=items_by_domain,
        errors_by_domain={},
        pipeline_counts_by_domain={
            domain: {
                "raw_fetched": len(items),
                "converted": len(items),
                "after_filters": len(items),
                "field_sequence_records_after_dedup": len(items),
            }
            for domain, items in items_by_domain.items()
        },
    )


def configure_endpoint_dependencies(app: FastAPI):
    user = User(id=1, username="qwerty")
    user.is_telegram_enabled = False
    app.dependency_overrides[require_api_user] = lambda: user

    db = AsyncMock()
    monitor = make_monitor()
    result = MagicMock()
    result.scalar_one_or_none.return_value = monitor
    db.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_db] = lambda: db
    return db, monitor


def test_diagnostics_router_import_ok():
    from app.web.diagnostics_api_router import router as imported_router

    assert imported_router is not None


def test_full_cycle_import_ok():
    from app.scheduler.dry_run import perform_monitor_full_cycle_dry_run as imported

    assert imported is not None


def test_backend_import_ok():
    from app.main import app

    assert app is not None


def test_diagnostics_router_does_not_import_private_failed_result_helper():
    router_path = Path(__file__).parents[1] / "app" / "web" / "diagnostics_api_router.py"
    source = router_path.read_text(encoding="utf-8")

    assert "_create_failed_full_cycle_result" not in source
    assert "def _create_failed_full_cycle_response" in source


def test_startup_independent_of_private_full_cycle_helpers():
    import app.scheduler.dry_run as dry_run
    from app.main import app

    assert not hasattr(dry_run, "_create_failed_full_cycle_result")
    assert app is not None


@pytest.mark.asyncio
async def test_full_cycle_dry_run_requires_auth():
    app = create_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-full-cycle")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_full_cycle_top_level_exception_returns_json():
    app = create_test_app()
    configure_endpoint_dependencies(app)

    with patch("app.web.diagnostics_api_router.VintedClient") as client_class, patch(
        "app.web.diagnostics_api_router.perform_monitor_full_cycle_dry_run",
        side_effect=RuntimeError("secret raw message"),
    ):
        client_class.return_value.close = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-full-cycle")

    assert response.status_code == 200
    data = response.json()
    assert data["safe_error"] == "full_cycle_dry_run_failed"
    assert data["errors_by_domain"]["__global__"] == "RuntimeError"
    assert "secret raw message" not in response.text
    assert data["side_effects"] == {
        "runs_scheduler_check": False,
        "writes_seen_items": False,
        "writes_found_items": False,
        "updates_monitor": False,
        "enqueues_notifications": False,
        "sends_telegram": False,
        "calls_vinted": False,
        "reads_database": True,
    }


@pytest.mark.asyncio
async def test_full_cycle_per_domain_exception_returns_json_and_continues():
    source_result = make_source_result(
        {"vinted.pl": [make_item(101)], "vinted.de": [make_item(201, "vinted.de")]}
    )
    db = AsyncMock()
    empty_seen = MagicMock()
    empty_seen.fetchall.return_value = []
    empty_found = MagicMock()
    empty_found.fetchall.return_value = []
    db.execute.side_effect = [RuntimeError("private DB detail"), empty_seen, empty_found]

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result):
        result = await perform_monitor_full_cycle_dry_run(
            make_monitor(domains=["vinted.pl", "vinted.de"]),
            AsyncMock(),
            db,
        )

    assert result.errors_by_domain == {"vinted.pl": "RuntimeError"}
    assert result.counts_by_domain["vinted.de"].would_create_found_items == 1
    assert result.side_effects["writes_found_items"] is False


@pytest.mark.asyncio
async def test_full_cycle_response_json_serializable():
    app = create_test_app()
    configure_endpoint_dependencies(app)
    result = MonitorFullCycleDryRunResult(
        monitor_id=22,
        selected_source="hydration",
        reason="catalog_filter_detected",
        selected_domains=["vinted.pl"],
        dry_run_domains=["vinted.pl"],
        summary={"domains_checked": 1},
        counts_by_domain={
            "vinted.pl": FullCycleDomainCounts(raw_fetched=1, converted=1, after_filters=1)
        },
        pipeline_counts_by_domain={
            "vinted.pl": {
                "checked_at": datetime(2026, 6, 7, tzinfo=timezone.utc),
                "ids": {"1"},
            }
        },
        seen_found_simulation_by_domain={
            "vinted.pl": FullCycleSimulationSamples()
        },
        samples_by_domain={
            "vinted.pl": [
                DryRunItem(
                    id="1",
                    title="Safe item",
                    brand_title="Nike",
                    price=Decimal("10.25"),
                    currency="EUR",
                    url="https://www.vinted.pl/items/1-safe-item",
                    domain="vinted.pl",
                    source="hydration",
                )
            ]
        },
        errors_by_domain={},
    )

    with patch("app.web.diagnostics_api_router.VintedClient") as client_class, patch(
        "app.web.diagnostics_api_router.perform_monitor_full_cycle_dry_run",
        return_value=result,
    ):
        client_class.return_value.close = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-full-cycle")

    assert response.status_code == 200
    assert response.json()["samples_by_domain"]["vinted.pl"][0]["price"] == 10.25


@pytest.mark.asyncio
async def test_full_cycle_reads_seen_found_without_writing():
    source_result = make_source_result({"vinted.pl": [make_item(301), make_item(302)]})
    db = AsyncMock()
    seen_result = MagicMock()
    seen_result.fetchall.return_value = [(302,)]
    found_result = MagicMock()
    found_result.fetchall.return_value = []
    db.execute.side_effect = [seen_result, found_result]
    db.add.side_effect = AssertionError("dry-run must not add")
    db.delete.side_effect = AssertionError("dry-run must not delete")
    db.flush.side_effect = AssertionError("dry-run must not flush")
    db.commit.side_effect = AssertionError("dry-run must not commit")

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result):
        result = await perform_monitor_full_cycle_dry_run(make_monitor(), AsyncMock(), db)

    counts = result.counts_by_domain["vinted.pl"]
    assert counts.already_seen == 1
    assert counts.would_create_seen_items == 1
    assert counts.would_create_found_items == 1
    db.add.assert_not_called()
    db.delete.assert_not_called()
    db.flush.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_full_cycle_does_not_update_monitor_or_call_telegram():
    monitor = make_monitor()
    original_last_check_at = monitor.last_check_at
    original_items_found_count = monitor.items_found_count
    source_result = make_source_result({"vinted.pl": [make_item(401)]})
    db = AsyncMock()
    empty = MagicMock()
    empty.fetchall.return_value = []
    db.execute.side_effect = [empty, empty]

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result), patch(
        "app.scheduler.tasks.send_item_notification",
        side_effect=AssertionError("Telegram must not be called"),
    ) as send_mock:
        result = await perform_monitor_full_cycle_dry_run(monitor, AsyncMock(), db)

    assert monitor.last_check_at == original_last_check_at
    assert monitor.items_found_count == original_items_found_count
    assert result.side_effects["sends_telegram"] is False
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_full_cycle_domain_aware_seen_lookup():
    source_result = make_source_result({"vinted.pl": [make_item(501)]})
    db = AsyncMock()
    empty = MagicMock()
    empty.fetchall.return_value = []
    db.execute.side_effect = [empty, empty]

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result):
        await perform_monitor_full_cycle_dry_run(make_monitor(), AsyncMock(), db)

    statement_text = str(db.execute.await_args_list[0].args[0])
    assert "seen_items.monitor_id" in statement_text
    assert "seen_items.domain" in statement_text
