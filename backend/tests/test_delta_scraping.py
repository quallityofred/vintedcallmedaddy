import asyncio
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from unittest.mock import MagicMock

from app.models import User, Monitor, FoundItem, SeenItem
from app.scraper.client import VintedClient, DomainSearchResult
from app.scraper.parser import VintedItem, VintedItemDetail

from app.scheduler import tasks
from app.scraper.monitor_filters import extract_monitor_filters

async def _user(db_session, username: str) -> User:
    user = User(username=username, password_hash="hash", password_salt="salt")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

async def _monitor(db_session, user: User, domains: list[str] = ["vinted.fr"], cold_start: bool = False) -> Monitor:
    from json import dumps
    monitor = Monitor(
        user_id=user.id,
        name="test monitor",
        original_url="https://www.vinted.fr/brand/123",
        params_json=dumps({"brand_ids[]": [123]}),
        domains_json=dumps(domains),
        interval_sec=120,
        last_check_at=datetime.now(timezone.utc) if not cold_start else None
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    return monitor

def _item(item_id: int, brand_id: int = 123, domain: str = "vinted.fr") -> VintedItem:
    return VintedItem(
        id=item_id,
        title=f"Item {item_id}",
        price=10.0,
        currency="EUR",
        brand="Brand",
        brand_id=brand_id,
        size="L",
        condition="New",
        photo_url="url",
        item_url="url",
        domain=domain,
        seller_id=1,
    )

class FakeDomainClient:
    def __init__(self, results: dict[str, list[VintedItem]]):
        self.results = results
        self.calls = []

    async def search_domains(self, params, domains, mode="auto"):
        self.calls.append((params, domains))
        return [
            DomainSearchResult(domain=d, items=self.results.get(d, []), request_count=1, duration_ms=10)
            for d in domains
        ]

    async def search_all_domains(self, params, domains, mode="auto"):
        results = await self.search_domains(params, domains, mode=mode)
        unique_items: list[VintedItem] = []
        seen_ids: set[int] = set()
        for result in results:
            for item in result.items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    unique_items.append(item)
        return unique_items

    async def fetch_item_detail(self, domain, item_id):
        return VintedItemDetail(item_id=item_id, listed_at=datetime.now(timezone.utc))
    
    async def close(self):
        pass


class FakeHydrationClient:
    def __init__(self):
        self.calls = []

    async def fetch_catalog_hydration_items(self, url, *, domain):
        self.calls.append((url, domain))
        return []

async def _run_check(db_session, monitor, client):
    # Ensure tasks uses our db_session
    from app.scheduler import tasks
    tasks.AsyncSessionLocal = lambda: db_session
    try:
        await tasks.check_monitor(monitor.id, scraper_client=client)
    finally:
        tasks.AsyncSessionLocal = None

@pytest.mark.asyncio
async def test_delta_scraping_persists_all_selected_domains(db_session):
    user = await _user(db_session, "delta_user_1")
    monitor = await _monitor(db_session, user, domains=["vinted.fr", "vinted.pl"])
    
    client = FakeDomainClient({
        "vinted.fr": [_item(1, domain="vinted.fr")],
        "vinted.pl": [_item(2, domain="vinted.pl")]
    })
    
    await _run_check(db_session, monitor, client)
    
    found = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    seen = (await db_session.execute(select(SeenItem).where(SeenItem.monitor_id == monitor.id))).scalars().all()
    
    assert sorted([item.vinted_item_id for item in found]) == [1, 2]
    assert sorted(item.vinted_item_id for item in seen) == [1, 2]

@pytest.mark.asyncio
async def test_delta_stops_at_first_seen_item_for_single_domain(db_session):
    user = await _user(db_session, "delta_boundary_user")
    monitor = await _monitor(db_session, user)
    db_session.add(SeenItem(user_id=user.id, monitor_id=monitor.id, vinted_item_id=2, domain="vinted.fr"))
    await db_session.commit()

    client = FakeDomainClient({"vinted.fr": [_item(1), _item(2), _item(3)]})
    await _run_check(db_session, monitor, client)

    found = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    assert [item.vinted_item_id for item in found] == [1]

@pytest.mark.asyncio
async def test_delta_wrong_brand_and_missing_brand_behavior(db_session):
    user = await _user(db_session, "delta_filter_behavior_user")
    monitor = await _monitor(db_session, user)
    # We've seen items 20 and 21
    db_session.add_all([
        SeenItem(user_id=user.id, monitor_id=monitor.id, vinted_item_id=20, domain="vinted.fr"),
        SeenItem(user_id=user.id, monitor_id=monitor.id, vinted_item_id=21, domain="vinted.fr"),
    ])
    await db_session.commit()

    client = FakeDomainClient({
        "vinted.fr": [
            _item(19, brand_id=123),   # NEW, matches
            _item(20, brand_id=999),   # SEEN, WRONG BRAND -> Skipped, NOT boundary
            _item(21, brand_id=None),  # SEEN, MISSING BRAND -> Skipped, NOT boundary
            _item(22, brand_id=123),   # NEW, matches
        ]
    })
    await _run_check(db_session, monitor, client)

    found = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    assert [item.vinted_item_id for item in found] == [19, 22]

@pytest.mark.asyncio
async def test_cold_start_multiple_domains_seeds_each_domain_without_found_items(db_session):
    user = await _user(db_session, "delta_cold_multi_user")
    monitor = await _monitor(db_session, user, domains=["vinted.fr", "vinted.de"], cold_start=True)
    
    client = FakeDomainClient({
        "vinted.fr": [_item(1, domain="vinted.fr")],
        "vinted.de": [_item(2, domain="vinted.de")],
    })
    await _run_check(db_session, monitor, client)

    found = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    seen = (await db_session.execute(select(SeenItem).where(SeenItem.monitor_id == monitor.id))).scalars().all()

    assert len(found) == 0
    assert sorted(item.vinted_item_id for item in seen) == [1, 2]

@pytest.mark.asyncio
async def test_all_selected_domains_are_checked_and_boundaries_are_per_domain(db_session):
    user = await _user(db_session, "delta_all_domains_user")
    monitor = await _monitor(db_session, user, domains=["vinted.fr", "vinted.de"])
    db_session.add_all([
        SeenItem(user_id=user.id, monitor_id=monitor.id, vinted_item_id=100, domain="vinted.fr"),
        SeenItem(user_id=user.id, monitor_id=monitor.id, vinted_item_id=200, domain="vinted.de"),
    ])
    await db_session.commit()

    client = FakeDomainClient({
        "vinted.fr": [_item(90, domain="vinted.fr"), _item(100, domain="vinted.fr"), _item(91, domain="vinted.fr")],
        "vinted.de": [_item(190, domain="vinted.de"), _item(191, domain="vinted.de"), _item(200, domain="vinted.de")],
    })
    await _run_check(db_session, monitor, client)

    found = (
        await db_session.execute(
            select(FoundItem).where(FoundItem.monitor_id == monitor.id).order_by(FoundItem.domain, FoundItem.vinted_item_id)
        )
    ).scalars().all()

    assert client.calls[0][1] == ["vinted.fr", "vinted.de"]
    
    # Extract tuples for easier comparison
    found_tuples = sorted([(item.vinted_item_id, item.domain) for item in found])
    expected_tuples = sorted([(90, "vinted.fr"), (190, "vinted.de"), (191, "vinted.de")])
    assert found_tuples == expected_tuples

@pytest.mark.asyncio
async def test_seen_lookup_is_domain_aware(db_session):
    user = await _user(db_session, "delta_domain_seen_user")
    monitor = await _monitor(db_session, user, domains=["vinted.fr", "vinted.de"])
    db_session.add(SeenItem(user_id=user.id, monitor_id=monitor.id, vinted_item_id=777, domain="vinted.fr"))
    await db_session.commit()

    client = FakeDomainClient({
        "vinted.fr": [_item(777, domain="vinted.fr")],
        "vinted.de": [_item(777, domain="vinted.de")],
    })
    await _run_check(db_session, monitor, client)

    found = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    # Stable Vinted IDs are deduped per monitor for FoundItem history even when seen
    # boundaries remain domain-scoped.
    assert [(item.vinted_item_id, item.domain) for item in found] == []


@pytest.mark.asyncio
async def test_existing_found_without_seen_is_not_requeued_and_backfills_seen(db_session):
    user = await _user(db_session, "delta_found_without_seen_user")
    monitor = await _monitor(db_session, user)
    existing = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=888,
        domain="vinted.fr",
        title="Already found item",
        price=12.0,
        currency="EUR",
        brand="Brand",
        brand_id=123,
        size="L",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/888-item",
        seller_id=1,
        notified=True,
    )
    db_session.add(existing)
    await db_session.commit()

    client = FakeDomainClient({"vinted.fr": [_item(888), _item(889)]})
    await _run_check(db_session, monitor, client)

    found = (
        await db_session.execute(
            select(FoundItem).where(FoundItem.monitor_id == monitor.id).order_by(FoundItem.vinted_item_id)
        )
    ).scalars().all()
    seen = (
        await db_session.execute(
            select(SeenItem).where(SeenItem.monitor_id == monitor.id).order_by(SeenItem.vinted_item_id)
        )
    ).scalars().all()

    assert [(item.vinted_item_id, item.notified) for item in found] == [(888, True)]
    assert [(item.vinted_item_id, item.domain) for item in seen] == [(888, "vinted.fr")]


@pytest.mark.asyncio
async def test_hydration_fetch_uses_effective_catalog_filters_for_every_domain(monkeypatch):
    params = {"brand_ids[]": [53], "catalog[]": [1231], "order": "newest_first"}
    context = tasks.MonitorCheckContext(
        monitor_id=22,
        user_id=1,
        monitor_name="nike",
        params=params,
        original_url="https://www.vinted.pl/catalog?brand_ids[]=53",
        domains=["vinted.fr", "vinted.de"],
        monitor_filters=extract_monitor_filters(params, monitor_name="nike"),
        hidden_seller_ids=set(),
        is_cold_start=False,
        freshness_cutoff_at=datetime.now(timezone.utc),
        original_interval=120,
        cf_worker_url="",
        cf_worker_mode="auto",
        cf_worker_block_threshold=2,
        cf_worker_recovery_minutes=10,
    )
    client = FakeHydrationClient()
    settings = MagicMock()
    settings.monitor_hydration_source_enabled = True
    settings.monitor_ssr_photo_merge_enabled = False
    monkeypatch.setattr("app.scraper.source_selector.get_settings", lambda: settings)

    results = await tasks._fetch_domain_results(client, context=context, mode="auto")

    assert [result.domain for result in results] == ["vinted.fr", "vinted.de"]
    assert [domain for _, domain in client.calls] == ["vinted.fr", "vinted.de"]
    for url, domain in client.calls:
        assert f"www.{domain}" in url
        assert "brand_ids[]=53" in url
        assert "catalog_ids[]=1231" in url
        assert "order=newest_first" in url
