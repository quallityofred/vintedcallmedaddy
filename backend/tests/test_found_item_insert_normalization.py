from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import FoundItem, Monitor, User
from app.scheduler import tasks
from app.scheduler.dry_run import (
    DryRunItem,
    MonitorDryRunResult,
    perform_monitor_full_cycle_dry_run,
)
from app.scheduler.found_item_values import build_found_item_values
from app.scraper.client import DomainSearchResult
from app.scraper.hydration_parser import (
    _extract_photo_url,
    hydration_record_to_vinted_item,
)
from app.scraper.parser import VintedItem, VintedItemDetail
from app.telegram.notifications import send_item_notification


def make_item(*, photo_url=None) -> VintedItem:
    return VintedItem(
        id=9113341349,
        title="Fresh Nike shoes",
        price=64.0,
        currency="EUR",
        brand="Nike",
        brand_id=53,
        size=None,
        condition=None,
        photo_url=photo_url,
        item_url="https://www.vinted.pl/items/9113341349-fresh-nike-shoes",
        domain="vinted.pl",
        seller_id=0,
        raw_source="hydration",
    )


class DetailClient:
    async def fetch_item_detail(self, domain, item_id):
        return VintedItemDetail(
            item_id=item_id,
            listed_at=datetime.now(timezone.utc),
        )

    async def close(self):
        return None


async def create_monitor(db_session, username: str) -> Monitor:
    user = User(
        username=username,
        password_hash="hash",
        password_salt="salt",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    monitor = Monitor(
        user_id=user.id,
        name="Nike monitor",
        original_url="https://www.vinted.pl/brand/53",
        params_json='{"brand_ids[]":[53]}',
        domains_json='["vinted.pl"]',
        interval_sec=120,
        last_check_at=datetime.now(timezone.utc),
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    return monitor


async def run_missing_photo_check(db_session, monkeypatch, username: str):
    monitor = await create_monitor(db_session, username)
    item = make_item(photo_url=None)
    result = DomainSearchResult(
        domain="vinted.pl",
        items=[item],
        request_count=1,
        duration_ms=1,
    )
    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: db_session)
    monkeypatch.setattr(
        tasks,
        "_fetch_domain_results",
        AsyncMock(return_value=[result]),
    )
    background_coroutines = []

    def close_background_coroutine(coroutine):
        background_coroutines.append(coroutine)
        coroutine.close()
        return MagicMock()

    monkeypatch.setattr(tasks.asyncio, "create_task", close_background_coroutine)
    try:
        await tasks.check_monitor(monitor.id, scraper_client=DetailClient())
    finally:
        tasks.AsyncSessionLocal = None

    found = (
        await db_session.execute(
            select(FoundItem).where(FoundItem.monitor_id == monitor.id)
        )
    ).scalars().all()
    return item, found, background_coroutines


def test_found_item_insert_normalizes_missing_photo_url():
    values = build_found_item_values(
        monitor_id=22,
        item=make_item(photo_url=None),
        found_at=datetime.now(timezone.utc),
    )

    assert values["photo_url"] == ""
    assert values["size"] == ""
    assert values["condition"] == ""


def test_found_item_not_null_fields_are_normalized():
    values = build_found_item_values(
        monitor_id=22,
        item=make_item(photo_url=None),
        found_at=datetime.now(timezone.utc),
    )

    for column in FoundItem.__table__.columns:
        if column.primary_key or column.nullable:
            continue
        assert column.name in values
        assert values[column.name] is not None


@pytest.mark.asyncio
async def test_scheduler_creates_found_item_without_photo_url(db_session, monkeypatch):
    item, found, background_coroutines = await run_missing_photo_check(
        db_session,
        monkeypatch,
        "missing-photo-scheduler-user",
    )

    assert found[0].vinted_item_id == item.id
    assert found[0].photo_url == ""
    assert found[0].notified is False
    assert len(background_coroutines) == 1


@pytest.mark.asyncio
async def test_scheduler_does_not_drop_valid_item_without_photo(
    db_session,
    monkeypatch,
):
    item, found, _ = await run_missing_photo_check(
        db_session,
        monkeypatch,
        "missing-photo-not-dropped-user",
    )

    assert [row.vinted_item_id for row in found] == [item.id]


@pytest.mark.asyncio
async def test_telegram_formatting_handles_missing_photo_url():
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_message = AsyncMock()

    with patch("app.telegram.notifications.asyncio.sleep", AsyncMock()):
        await send_item_notification(bot, 123, make_item(photo_url=None))

    bot.send_photo.assert_not_awaited()
    bot.send_message.assert_awaited_once()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"photo": {"url": "https://img/photo"}}, "https://img/photo"),
        (
            {"photo": {"high_resolution": {"url": "https://img/high"}}},
            "https://img/high",
        ),
        ({"photos": [{"full_size_url": "https://img/full"}]}, "https://img/full"),
        ({"thumbnails": [{"thumbnail_url": "https://img/thumb"}]}, "https://img/thumb"),
        ({"image": {"url": "https://img/image"}}, "https://img/image"),
    ],
)
def test_hydration_parser_extracts_photo_url_from_supported_shapes(payload, expected):
    assert _extract_photo_url(payload) == expected


def test_hydration_parser_allows_missing_photo_url():
    item = hydration_record_to_vinted_item(
        {
            "id": "9113341349",
            "title": "Fresh Nike shoes",
            "brand_title": "Nike",
            "price": 64,
            "currency": "EUR",
            "url": "https://www.vinted.pl/items/9113341349-fresh-nike-shoes",
            "photo_url": None,
        },
        "vinted.pl",
    )

    assert item.photo_url == ""


@pytest.mark.asyncio
async def test_full_cycle_dry_run_reports_found_item_insert_readiness(
    db_session,
    monkeypatch,
):
    monitor = await create_monitor(db_session, "missing-photo-dry-run-user")
    source_result = MonitorDryRunResult(
        monitor_id=monitor.id,
        selected_source="hydration",
        reason="catalog_filter_detected",
        selected_domains=["vinted.pl"],
        dry_run_domains=["vinted.pl"],
        counts_by_domain={"vinted.pl": 1},
        samples_by_domain={
            "vinted.pl": [
                DryRunItem(
                    id="9113341349",
                    title="Fresh Nike shoes",
                    brand_title="Nike",
                    price=64.0,
                    currency="EUR",
                    url="https://www.vinted.pl/items/9113341349-fresh-nike-shoes",
                    domain="vinted.pl",
                    source="hydration",
                    has_photo=False,
                )
            ]
        },
        errors_by_domain={},
        pipeline_counts_by_domain={
            "vinted.pl": {"raw_fetched": 1, "converted": 1, "after_filters": 1}
        },
    )
    monkeypatch.setattr(
        "app.scheduler.dry_run.perform_monitor_dry_run",
        AsyncMock(return_value=source_result),
    )

    result = await perform_monitor_full_cycle_dry_run(
        monitor,
        DetailClient(),
        db_session,
        target_domain="vinted.pl",
    )

    counts = result.counts_by_domain["vinted.pl"]
    assert counts.found_item_insert_ready == 1
    assert counts.found_item_insert_missing_photo_url == 1
    assert counts.would_fail_found_item_insert_before_fix == 1
    assert result.summary["found_item_insert_ready_total"] == 1
    assert result.summary["found_item_insert_missing_photo_url_total"] == 1


def test_diagnostics_router_import_ok():
    from app.web.diagnostics_api_router import router

    assert router is not None


def test_backend_import_ok():
    from app.main import app

    assert app is not None
