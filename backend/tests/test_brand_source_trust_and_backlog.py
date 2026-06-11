import json
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.main import app
from app.models import FoundItem, Monitor, User, utc_now
from app.scheduler.pending_diagnostics import run_suspect_brand_filter_backlog_ack
from app.scraper.monitor_filters import (
    MISSING_BRAND_ID_UNVERIFIED_SOURCE,
    extract_monitor_filters,
    item_matches_monitor_filters,
)
from app.scraper.parser import VintedItem
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db


async def _user(db_session, username_prefix: str = "brand_trust") -> User:
    user = User(
        username=f"{username_prefix}_{uuid.uuid4().hex[:8]}",
        password_hash="hash",
        password_salt="salt",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _monitor(
    db_session,
    user: User,
    *,
    name: str,
    params: dict,
    original_url: str,
) -> Monitor:
    monitor = Monitor(
        user_id=user.id,
        name=name,
        original_url=original_url,
        params_json=json.dumps(params),
        domains_json=json.dumps(["vinted.de"]),
        is_active=False,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    return monitor


def _found(
    monitor: Monitor,
    item_id: int,
    *,
    brand: str = "unknown",
    brand_id: int | None = None,
) -> FoundItem:
    return FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=item_id,
        domain="vinted.de",
        title=f"Item {item_id}",
        price=10.0,
        currency="EUR",
        brand=brand,
        brand_id=brand_id,
        size="M",
        condition="Very good",
        photo_url="",
        item_url=f"https://www.vinted.de/items/{item_id}",
        seller_id=51023772,
        found_at=utc_now() - timedelta(hours=1),
        notified=False,
    )


@pytest_asyncio.fixture(autouse=True)
async def cleanup_each_test(db_session):
    await db_session.execute(delete(FoundItem))
    await db_session.execute(delete(Monitor))
    await db_session.execute(delete(User))
    await db_session.commit()
    yield


@pytest.mark.asyncio
async def test_brand_filter_rejects_unknown_brand_from_unverified_source_params():
    filters = extract_monitor_filters({"brand_ids[]": ["576107"], "order": "newest_first"}, monitor_name="kapital")
    item = VintedItem(
        id=9062601700,
        title="Dante's Inferno Xbox 360",
        price=10.0,
        currency="EUR",
        brand="unknown",
        size="M",
        condition="Very good",
        photo_url="",
        item_url="https://www.vinted.de/items/9062601700",
        domain="vinted.de",
        seller_id=51023772,
        brand_id=None,
    )

    assert item_matches_monitor_filters(item, filters) == (False, MISSING_BRAND_ID_UNVERIFIED_SOURCE)


@pytest.mark.asyncio
async def test_brand_filter_still_accepts_matching_brand_title_and_brand_id():
    filters = extract_monitor_filters({"brand_ids[]": ["576107"], "order": "newest_first"}, monitor_name="kapital")
    title_match = VintedItem(
        id=1,
        title="T shirt oversize originale Kapital",
        price=10.0,
        currency="EUR",
        brand="Kapital",
        size="M",
        condition="Very good",
        photo_url="",
        item_url="https://www.vinted.de/items/1",
        domain="vinted.de",
        seller_id=1,
        brand_id=None,
    )
    id_match = VintedItem(
        id=2,
        title="Unknown title",
        price=10.0,
        currency="EUR",
        brand="unknown",
        size="M",
        condition="Very good",
        photo_url="",
        item_url="https://www.vinted.de/items/2",
        domain="vinted.de",
        seller_id=2,
        brand_id=576107,
    )

    assert item_matches_monitor_filters(title_match, filters) == (True, None)
    assert item_matches_monitor_filters(id_match, filters) == (True, None)


@pytest.mark.asyncio
async def test_suspect_brand_backlog_dry_run_is_read_only_and_excludes_verified_brand_rows(db_session):
    user = await _user(db_session)
    kapital = await _monitor(
        db_session,
        user,
        name="kapital",
        params={"brand_ids[]": [576107], "order": "newest_first"},
        original_url="https://www.vinted.de/brand/576107-kapital",
    )
    unfiltered = await _monitor(
        db_session,
        user,
        name="unfiltered",
        params={"order": "newest_first"},
        original_url="https://www.vinted.de/catalog",
    )
    suspect = _found(kapital, 10, brand="unknown", brand_id=None)
    matching_title = _found(kapital, 11, brand="Kapital", brand_id=None)
    matching_id = _found(kapital, 12, brand="unknown", brand_id=576107)
    no_brand_filter = _found(unfiltered, 13, brand="unknown", brand_id=None)
    db_session.add_all([suspect, matching_title, matching_id, no_brand_filter])
    await db_session.commit()

    result = await run_suspect_brand_filter_backlog_ack(db_session, dry_run=True, sample_limit=20)

    assert result["dry_run"] is True
    assert result["eligible_count"] == 1
    assert result["acked_count"] == 0
    assert result["excluded_matching_brand_count"] == 2
    assert result["excluded_no_brand_filter_count"] == 1
    assert result["side_effects"]["sends_telegram"] is False
    assert result["side_effects"]["marks_notified"] is False
    assert result["samples"][0]["vinted_item_id"] == 10
    assert "photo_url" not in result["samples"][0]

    await db_session.refresh(suspect)
    await db_session.refresh(matching_title)
    assert suspect.notified is False
    assert matching_title.notified is False


@pytest.mark.asyncio
async def test_suspect_brand_backlog_live_acks_only_suspect_rows_without_telegram(db_session):
    user = await _user(db_session)
    monitor = await _monitor(
        db_session,
        user,
        name="kapital",
        params={"brand_ids[]": [576107], "order": "newest_first"},
        original_url="https://www.vinted.de/brand/576107-kapital",
    )
    suspect = _found(monitor, 20, brand="unknown", brand_id=None)
    verified = _found(monitor, 21, brand="Kapital", brand_id=None)
    db_session.add_all([suspect, verified])
    await db_session.commit()

    result = await run_suspect_brand_filter_backlog_ack(db_session, dry_run=False, sample_limit=20)

    assert result["eligible_count"] == 1
    assert result["acked_count"] == 1
    assert result["side_effects"]["sends_telegram"] is False
    await db_session.refresh(suspect)
    await db_session.refresh(verified)
    assert suspect.notified is True
    assert verified.notified is False


@pytest.mark.asyncio
async def test_suspect_brand_backlog_route_requires_live_confirmations(db_session):
    user = await _user(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_api_user] = lambda: user
    app.dependency_overrides[require_api_csrf] = lambda: None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/maintenance/pending-notifications/ack-suspect-brand-filter-backlog",
                json={"dry_run": False},
            )
            assert response.status_code == 400
            assert "Reason required" in response.json()["detail"]

            response = await client.post(
                "/api/v1/maintenance/pending-notifications/ack-suspect-brand-filter-backlog",
                json={"dry_run": False, "reason": "test", "confirm": "WRONG"},
            )
            assert response.status_code == 400
            assert "Invalid confirmation" in response.json()["detail"]

            response = await client.post(
                "/api/v1/maintenance/pending-notifications/ack-suspect-brand-filter-backlog",
                json={
                    "dry_run": False,
                    "reason": "test",
                    "confirm": "ACK_SUSPECT_BRAND_FILTER_BACKLOG_NO_NOTIFY",
                    "extra_confirm": [],
                },
            )
            assert response.status_code == 400
            assert "I_UNDERSTAND_THIS_WILL_NOT_SEND_TELEGRAM" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
