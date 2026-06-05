import asyncio
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from unittest.mock import MagicMock

from app.models import User, Monitor, FoundItem, SeenItem
from app.scraper.client import VintedClient, DomainSearchResult
from app.scraper.parser import VintedItem, VintedItemDetail

from app.scheduler import tasks

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

    async def fetch_item_detail(self, domain, item_id):
        return VintedItemDetail(item_id=item_id, listed_at=datetime.now(timezone.utc))
    
    async def close(self):
        pass

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
    # Item 777 was seen on vinted.fr, so it should NOT be found on vinted.fr.
    # But it should be found on vinted.de because it's a DIFFERENT domain boundary.
    assert [(item.vinted_item_id, item.domain) for item in found] == [(777, "vinted.de")]
