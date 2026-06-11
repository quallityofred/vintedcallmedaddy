import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models import FoundItem, Monitor, MonitorFilterBaseline, SeenItem, User
from app.scheduler import tasks
from app.scraper.client import DomainSearchResult
from app.scraper.parser import VintedItem


async def _user(db_session, username: str = "fingerprint_user") -> User:
    user = User(username=username, password_hash="hash", password_salt="salt")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _monitor(
    db_session,
    user: User,
    *,
    name: str = "kapital",
    domains: list[str] | None = None,
    params: dict | None = None,
    last_check_at: datetime | None = None,
) -> Monitor:
    monitor = Monitor(
        user_id=user.id,
        name=name,
        original_url="https://www.vinted.de/brand/999-kapital",
        params_json=json.dumps(params or {"brand_ids[]": [999], "order": "newest_first"}),
        domains_json=json.dumps(domains or ["vinted.de"]),
        interval_sec=120,
        last_check_at=last_check_at if last_check_at is not None else datetime.now(timezone.utc),
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    return monitor


def _item(
    item_id: int,
    *,
    domain: str = "vinted.de",
    brand_id: int | None = 999,
    brand: str = "Kapital",
    listed_at: datetime | None = None,
) -> VintedItem:
    return VintedItem(
        id=item_id,
        title=f"Kapital item {item_id}",
        price=10.0,
        currency="EUR",
        brand=brand,
        brand_id=brand_id,
        size="M",
        condition="Very good",
        photo_url="https://example.invalid/photo.jpg",
        item_url=f"https://www.{domain}/items/{item_id}-kapital",
        domain=domain,
        seller_id=51023772,
        raw_source="hydration",
        listed_at=listed_at,
        timestamp_source="fixture" if listed_at else None,
    )


class FakeDomainClient:
    def __init__(self, results: dict[str, list[VintedItem]]):
        self.results = results
        self.calls = []

    async def search_all_domains(self, params, domains, mode="auto"):
        self.calls.append((params, domains, mode))
        items: list[VintedItem] = []
        for domain in domains:
            items.extend(self.results.get(domain, []))
        return items

    async def search_domains(self, params, domains, mode="auto"):
        self.calls.append((params, domains, mode))
        return [
            DomainSearchResult(domain=domain, items=self.results.get(domain, []), request_count=1, duration_ms=10)
            for domain in domains
        ]

    async def close(self):
        pass


async def _run_check(db_session, monitor: Monitor, client: FakeDomainClient, monkeypatch):
    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: db_session)
    monkeypatch.setattr(tasks, "process_pending_notifications", AsyncMock())
    try:
        await tasks.check_monitor(monitor.id, scraper_client=client)
    finally:
        monkeypatch.setattr(tasks, "AsyncSessionLocal", None)


async def _found_ids(db_session, monitor_id: int) -> list[int]:
    result = await db_session.execute(
        select(FoundItem.vinted_item_id).where(FoundItem.monitor_id == monitor_id).order_by(FoundItem.vinted_item_id)
    )
    return [int(row[0]) for row in result.fetchall()]


async def _seen_ids(db_session, monitor_id: int, domain: str = "vinted.de") -> list[int]:
    result = await db_session.execute(
        select(SeenItem.vinted_item_id)
        .where(SeenItem.monitor_id == monitor_id, SeenItem.domain == domain)
        .order_by(SeenItem.vinted_item_id)
    )
    return [int(row[0]) for row in result.fetchall()]


@pytest.mark.asyncio
async def test_missing_brand_timestampless_window_is_baselined_no_notify(db_session, monkeypatch):
    user = await _user(db_session, "fingerprint_missing_brand_user")
    monitor = await _monitor(db_session, user)

    client = FakeDomainClient({"vinted.de": [_item(item_id, brand_id=None, listed_at=None) for item_id in range(1, 6)]})
    await _run_check(db_session, monitor, client, monkeypatch)

    assert await _found_ids(db_session, monitor.id) == []
    assert await _seen_ids(db_session, monitor.id) == [1, 2, 3, 4, 5]
    baseline = (
        await db_session.execute(
            select(MonitorFilterBaseline).where(
                MonitorFilterBaseline.monitor_id == monitor.id,
                MonitorFilterBaseline.domain == "vinted.de",
            )
        )
    ).scalar_one()
    assert baseline.filter_contract_version == tasks.FILTER_CONTRACT_VERSION
    assert baseline.source_strategy == "api"


@pytest.mark.asyncio
async def test_after_fingerprint_baseline_new_leading_item_notifies_until_seen_boundary(db_session, monkeypatch):
    user = await _user(db_session, "fingerprint_delta_user")
    monitor = await _monitor(db_session, user)

    first_client = FakeDomainClient({"vinted.de": [_item(item_id, brand_id=None) for item_id in [10, 11, 12]]})
    await _run_check(db_session, monitor, first_client, monkeypatch)

    second_client = FakeDomainClient({"vinted.de": [_item(9, brand_id=None), _item(10, brand_id=None), _item(8, brand_id=None)]})
    await _run_check(db_session, monitor, second_client, monkeypatch)

    assert await _found_ids(db_session, monitor.id) == [9]
    assert await _seen_ids(db_session, monitor.id) == [9, 10, 11, 12]


@pytest.mark.asyncio
async def test_source_listed_at_stale_item_is_seen_only_not_notified(db_session, monkeypatch):
    user = await _user(db_session, "fingerprint_stale_user")
    last_check_at = datetime.now(timezone.utc)
    monitor = await _monitor(db_session, user, last_check_at=last_check_at)

    old_item = _item(9062601700, listed_at=last_check_at - timedelta(days=7))
    client = FakeDomainClient({"vinted.de": [old_item]})
    await _run_check(db_session, monitor, client, monkeypatch)

    assert await _found_ids(db_session, monitor.id) == []
    assert await _seen_ids(db_session, monitor.id) == [9062601700]


@pytest.mark.asyncio
async def test_source_listed_at_fresh_item_can_notify(db_session, monkeypatch):
    user = await _user(db_session, "fingerprint_fresh_user")
    last_check_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    monitor = await _monitor(db_session, user, last_check_at=last_check_at)

    fresh_item = _item(1001, listed_at=datetime.now(timezone.utc))
    client = FakeDomainClient({"vinted.de": [fresh_item]})
    await _run_check(db_session, monitor, client, monkeypatch)

    assert await _found_ids(db_session, monitor.id) == [1001]
    assert await _seen_ids(db_session, monitor.id) == [1001]


@pytest.mark.asyncio
async def test_filter_fingerprint_baseline_is_domain_aware(db_session, monkeypatch):
    user = await _user(db_session, "fingerprint_domain_user")
    monitor = await _monitor(db_session, user, domains=["vinted.de", "vinted.pl"])

    client = FakeDomainClient({
        "vinted.de": [_item(1, domain="vinted.de", brand_id=None)],
        "vinted.pl": [_item(1, domain="vinted.pl", brand_id=None)],
    })
    await _run_check(db_session, monitor, client, monkeypatch)

    assert await _found_ids(db_session, monitor.id) == []
    assert await _seen_ids(db_session, monitor.id, "vinted.de") == [1]
    assert await _seen_ids(db_session, monitor.id, "vinted.pl") == [1]
    baselines = (
        await db_session.execute(
            select(MonitorFilterBaseline.domain).where(MonitorFilterBaseline.monitor_id == monitor.id)
        )
    ).fetchall()
    assert sorted(row[0] for row in baselines) == ["vinted.de", "vinted.pl"]
