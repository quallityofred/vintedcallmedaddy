from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models import FoundItem, Monitor, SeenItem, User
from app.scheduler.dry_run import (
    DryRunItem,
    MonitorDryRunResult,
    perform_monitor_full_cycle_dry_run,
)
from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
from app.web.diagnostics_api_router import router


def create_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


def make_monitor(*, cold_start: bool = False) -> Monitor:
    return Monitor(
        id=22,
        user_id=1,
        name="Nike shoes",
        original_url="https://www.vinted.pl/catalog?brand_ids[]=53&catalog[]=1231",
        params_json='{"brand_ids[]":["53"],"catalog[]":["1231"]}',
        domains_json='["vinted.pl"]',
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


def make_source_result(items: list[DryRunItem]) -> MonitorDryRunResult:
    return MonitorDryRunResult(
        monitor_id=22,
        selected_source="hydration",
        reason="catalog_filter_detected",
        selected_domains=["vinted.pl"],
        dry_run_domains=["vinted.pl"],
        counts_by_domain={"vinted.pl": len(items)},
        samples_by_domain={"vinted.pl": items},
        errors_by_domain={},
        pipeline_counts_by_domain={
            "vinted.pl": {
                "raw_fetched": len(items),
                "converted": len(items),
                "after_filters": len(items),
                "field_sequence_path_markers": len(items),
                "field_sequence_records_before_validation": len(items),
                "field_sequence_records_after_validation": len(items),
                "field_sequence_records_after_dedup": len(items),
            }
        },
    )


@pytest.mark.asyncio
async def test_full_cycle_dry_run_requires_auth():
    app = create_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/diagnostics/monitors/22/dry-run-full-cycle")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_full_cycle_dry_run_rejects_unselected_domain():
    db = AsyncMock()
    client = AsyncMock()
    with patch(
        "app.scheduler.dry_run.perform_monitor_dry_run",
        side_effect=ValueError("Domain vinted.de is not selected by this monitor"),
    ):
        with pytest.raises(ValueError, match="not selected"):
            await perform_monitor_full_cycle_dry_run(
                make_monitor(), client, db, target_domain="vinted.de"
            )


@pytest.mark.asyncio
async def test_full_cycle_dry_run_reads_seen_found_and_reports_new_without_writing():
    items = [make_item(101), make_item(102), make_item(103)]
    source_result = make_source_result(items)
    db = AsyncMock()
    seen_result = MagicMock()
    seen_result.fetchall.return_value = [(102,)]
    found_result = MagicMock()
    found_result.fetchall.return_value = []
    db.execute.side_effect = [seen_result, found_result]
    db.add.side_effect = AssertionError("dry-run must not add")
    db.delete.side_effect = AssertionError("dry-run must not delete")
    db.flush.side_effect = AssertionError("dry-run must not flush")
    db.commit.side_effect = AssertionError("dry-run must not commit")

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result):
        result = await perform_monitor_full_cycle_dry_run(
            make_monitor(), AsyncMock(), db, telegram_enabled=True
        )

    counts = result.counts_by_domain["vinted.pl"]
    assert counts.already_seen == 1
    assert counts.seen_boundary_hit is True
    assert counts.would_create_seen_items == 1
    assert counts.would_create_found_items == 1
    assert counts.would_enqueue_notifications == 1
    assert counts.would_send_telegram == 1
    assert [item.id for item in result.seen_found_simulation_by_domain["vinted.pl"].sample_would_be_new] == ["101"]
    db.add.assert_not_called()
    db.delete.assert_not_called()
    db.flush.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_full_cycle_dry_run_reads_found_without_writing():
    source_result = make_source_result([make_item(201)])
    db = AsyncMock()
    seen_result = MagicMock()
    seen_result.fetchall.return_value = []
    found_result = MagicMock()
    found_result.fetchall.return_value = [(201,)]
    db.execute.side_effect = [seen_result, found_result]

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result):
        result = await perform_monitor_full_cycle_dry_run(make_monitor(), AsyncMock(), db)

    counts = result.counts_by_domain["vinted.pl"]
    assert counts.already_found == 1
    assert counts.would_create_seen_items == 1
    assert counts.would_create_found_items == 0
    assert result.seen_found_simulation_by_domain["vinted.pl"].sample_already_found[0].id == "201"


@pytest.mark.asyncio
async def test_full_cycle_dry_run_cold_start_reports_seen_only():
    source_result = make_source_result([make_item(301), make_item(302)])
    db = AsyncMock()
    empty = MagicMock()
    empty.fetchall.return_value = []
    db.execute.side_effect = [empty, empty]

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result):
        result = await perform_monitor_full_cycle_dry_run(
            make_monitor(cold_start=True), AsyncMock(), db, telegram_enabled=True
        )

    counts = result.counts_by_domain["vinted.pl"]
    assert counts.would_create_seen_items == 2
    assert counts.would_create_found_items == 0
    assert counts.would_enqueue_notifications == 0
    assert counts.would_send_telegram == 0


@pytest.mark.asyncio
async def test_full_cycle_dry_run_does_not_update_monitor():
    monitor = make_monitor()
    original_last_check_at = monitor.last_check_at
    original_items_found_count = monitor.items_found_count
    source_result = make_source_result([make_item(351)])
    db = AsyncMock()
    empty = MagicMock()
    empty.fetchall.return_value = []
    db.execute.side_effect = [empty, empty]

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result):
        await perform_monitor_full_cycle_dry_run(monitor, AsyncMock(), db)

    assert monitor.last_check_at == original_last_check_at
    assert monitor.items_found_count == original_items_found_count
    db.commit.assert_not_called()
    db.flush.assert_not_called()


@pytest.mark.asyncio
async def test_full_cycle_dry_run_domain_aware_seen_lookup():
    source_result = make_source_result([make_item(401)])
    db = AsyncMock()
    empty = MagicMock()
    empty.fetchall.return_value = []
    db.execute.side_effect = [empty, empty]

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result):
        await perform_monitor_full_cycle_dry_run(make_monitor(), AsyncMock(), db)

    statement_text = str(db.execute.await_args_list[0].args[0])
    assert "seen_items.monitor_id" in statement_text
    assert "seen_items.domain" in statement_text


@pytest.mark.asyncio
async def test_full_cycle_dry_run_side_effect_flags_false_and_pipeline_counts_present():
    source_result = make_source_result([make_item(501)])
    db = AsyncMock()
    empty = MagicMock()
    empty.fetchall.return_value = []
    db.execute.side_effect = [empty, empty]

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result):
        result = await perform_monitor_full_cycle_dry_run(make_monitor(), AsyncMock(), db)

    assert result.pipeline_counts_by_domain["vinted.pl"]["field_sequence_records_after_dedup"] == 1
    assert result.side_effects == {
        "runs_scheduler_check": False,
        "writes_seen_items": False,
        "writes_found_items": False,
        "updates_monitor": False,
        "enqueues_notifications": False,
        "sends_telegram": False,
        "calls_vinted": True,
        "reads_database": True,
    }


@pytest.mark.asyncio
async def test_full_cycle_dry_run_does_not_call_telegram():
    source_result = make_source_result([make_item(601)])
    db = AsyncMock()
    empty = MagicMock()
    empty.fetchall.return_value = []
    db.execute.side_effect = [empty, empty]

    with patch("app.scheduler.dry_run.perform_monitor_dry_run", return_value=source_result), patch(
        "app.scheduler.tasks.send_item_notification",
        side_effect=AssertionError("Telegram must not be called"),
    ) as send_mock:
        await perform_monitor_full_cycle_dry_run(make_monitor(), AsyncMock(), db)

    send_mock.assert_not_called()


def test_full_cycle_dry_run_import_ok():
    from app.scheduler.dry_run import perform_monitor_dry_run
    from app.main import app

    assert perform_monitor_dry_run is not None
    assert app is not None
