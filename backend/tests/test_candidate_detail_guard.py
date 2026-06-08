from datetime import datetime, timedelta, timezone
from json import dumps

import pytest
from sqlalchemy import select

from app.models import FoundItem, Monitor, SeenItem, User
from app.scheduler import tasks
from app.scraper.client import DomainSearchResult
from app.scraper.parser import VintedItem, VintedItemDetail


async def _user(db_session, username: str) -> User:
    user = User(username=username, password_hash="hash", password_salt="salt")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _monitor(
    db_session,
    user: User,
    *,
    params: dict | None = None,
    domains: list[str] | None = None,
    cold_start: bool = False,
) -> Monitor:
    if params is None:
        params = {"brand_ids[]": [123]}
    monitor = Monitor(
        user_id=user.id,
        name="detail guard monitor",
        original_url="https://www.vinted.fr/catalog?brand_ids[]=123",
        params_json=dumps(params),
        domains_json=dumps(domains or ["vinted.fr"]),
        interval_sec=120,
        last_check_at=None if cold_start else datetime.now(timezone.utc),
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    return monitor


def _item(item_id: int, *, brand_id: int = 123, domain: str = "vinted.fr") -> VintedItem:
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
        item_url=f"https://www.{domain}/items/{item_id}",
        domain=domain,
        seller_id=1,
    )


class DetailGuardClient:
    def __init__(self, results: dict[str, list[VintedItem]], details: dict[int, VintedItemDetail | None]):
        self.results = results
        self.details = details
        self.search_calls = []
        self.detail_calls = []

    async def search_domains(self, params, domains, mode="auto"):
        self.search_calls.append((params, list(domains)))
        return [
            DomainSearchResult(domain=domain, items=self.results.get(domain, []), request_count=1, duration_ms=5)
            for domain in domains
        ]

    async def search_all_domains(self, params, domains, mode="auto"):
        results = await self.search_domains(params, domains, mode=mode)
        unique_items: list[VintedItem] = []
        seen_ids: set[int] = set()
        for result in results:
            for item in result.items:
                if item.id in seen_ids:
                    continue
                seen_ids.add(item.id)
                unique_items.append(item)
        return unique_items

    async def fetch_item_detail(self, domain, item_id):
        self.detail_calls.append((domain, item_id))
        return self.details.get(item_id)

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def detail_guard_settings():
    previous = {
        "monitor_detail_guard_enabled": tasks.settings.monitor_detail_guard_enabled,
        "monitor_detail_category_guard_enabled": tasks.settings.monitor_detail_category_guard_enabled,
        "monitor_detail_freshness_guard_enabled": tasks.settings.monitor_detail_freshness_guard_enabled,
        "monitor_candidate_detail_max_per_check": tasks.settings.monitor_candidate_detail_max_per_check,
        "monitor_freshness_grace_seconds": tasks.settings.monitor_freshness_grace_seconds,
    }
    tasks.settings.monitor_detail_guard_enabled = True
    tasks.settings.monitor_detail_category_guard_enabled = True
    tasks.settings.monitor_detail_freshness_guard_enabled = True
    tasks.settings.monitor_candidate_detail_max_per_check = 10
    tasks.settings.monitor_freshness_grace_seconds = 600
    yield
    for key, value in previous.items():
        setattr(tasks.settings, key, value)


async def _run_check(db_session, monitor: Monitor, client: DetailGuardClient):
    tasks.AsyncSessionLocal = lambda: db_session
    try:
        await tasks.check_monitor(monitor.id, scraper_client=client)
    finally:
        tasks.AsyncSessionLocal = None


async def _found_ids(db_session, monitor: Monitor) -> list[int]:
    result = await db_session.execute(
        select(FoundItem).where(FoundItem.monitor_id == monitor.id).order_by(FoundItem.vinted_item_id)
    )
    return [item.vinted_item_id for item in result.scalars().all()]


async def _seen_ids(db_session, monitor: Monitor) -> list[int]:
    result = await db_session.execute(
        select(SeenItem).where(SeenItem.monitor_id == monitor.id).order_by(SeenItem.vinted_item_id)
    )
    return [item.vinted_item_id for item in result.scalars().all()]


@pytest.mark.asyncio
async def test_detail_fetch_only_for_unseen_candidates_before_seen_boundary(db_session):
    user = await _user(db_session, "detail_guard_fetch_scope")
    monitor = await _monitor(db_session, user)
    db_session.add(SeenItem(user_id=user.id, monitor_id=monitor.id, vinted_item_id=2, domain="vinted.fr"))
    await db_session.commit()
    client = DetailGuardClient(
        {"vinted.fr": [_item(1), _item(2), _item(3)]},
        {1: VintedItemDetail(item_id=1, listed_at=datetime.now(timezone.utc))},
    )

    await _run_check(db_session, monitor, client)

    assert client.detail_calls == [("vinted.fr", 1)]
    assert await _found_ids(db_session, monitor) == [1]


@pytest.mark.asyncio
async def test_old_detail_timestamp_creates_seen_only_not_found(db_session):
    user = await _user(db_session, "detail_guard_stale")
    monitor = await _monitor(db_session, user)
    client = DetailGuardClient(
        {"vinted.fr": [_item(10)]},
        {10: VintedItemDetail(item_id=10, listed_at=datetime.now(timezone.utc) - timedelta(days=5))},
    )

    await _run_check(db_session, monitor, client)

    assert await _found_ids(db_session, monitor) == []
    assert await _seen_ids(db_session, monitor) == [10]


@pytest.mark.asyncio
async def test_fresh_detail_timestamp_creates_found_item(db_session):
    user = await _user(db_session, "detail_guard_fresh")
    monitor = await _monitor(db_session, user)
    client = DetailGuardClient(
        {"vinted.fr": [_item(11)]},
        {11: VintedItemDetail(item_id=11, listed_at=datetime.now(timezone.utc))},
    )

    await _run_check(db_session, monitor, client)

    assert await _found_ids(db_session, monitor) == [11]


@pytest.mark.asyncio
async def test_missing_detail_timestamp_creates_seen_only_without_crashing(db_session):
    user = await _user(db_session, "detail_guard_missing_timestamp")
    monitor = await _monitor(db_session, user)
    client = DetailGuardClient(
        {"vinted.fr": [_item(12)]},
        {12: VintedItemDetail(item_id=12, listed_at=None)},
    )

    await _run_check(db_session, monitor, client)

    assert await _found_ids(db_session, monitor) == []
    assert await _seen_ids(db_session, monitor) == [12]


@pytest.mark.asyncio
async def test_detail_category_mismatch_skips_before_found_item(db_session):
    user = await _user(db_session, "detail_guard_category_mismatch")
    monitor = await _monitor(db_session, user, params={"brand_ids[]": [123], "catalog[]": [1231]})
    client = DetailGuardClient(
        {"vinted.fr": [_item(20)]},
        {20: VintedItemDetail(item_id=20, listed_at=datetime.now(timezone.utc), catalog_ids=frozenset({"999"}))},
    )

    await _run_check(db_session, monitor, client)

    assert await _found_ids(db_session, monitor) == []
    assert await _seen_ids(db_session, monitor) == []


@pytest.mark.asyncio
async def test_detail_category_match_allows_found_item(db_session):
    user = await _user(db_session, "detail_guard_category_match")
    monitor = await _monitor(db_session, user, params={"brand_ids[]": [123], "catalog[]": [1231]})
    client = DetailGuardClient(
        {"vinted.fr": [_item(21)]},
        {21: VintedItemDetail(item_id=21, listed_at=datetime.now(timezone.utc), catalog_ids=frozenset({"1231"}))},
    )

    await _run_check(db_session, monitor, client)

    assert await _found_ids(db_session, monitor) == [21]


@pytest.mark.asyncio
async def test_seen_wrong_category_summary_item_does_not_stop_later_matching_candidate(db_session):
    user = await _user(db_session, "detail_guard_wrong_category_boundary")
    monitor = await _monitor(db_session, user, params={"brand_ids[]": [123], "catalog[]": [1231]})
    db_session.add(SeenItem(user_id=user.id, monitor_id=monitor.id, vinted_item_id=30, domain="vinted.fr"))
    await db_session.commit()
    client = DetailGuardClient(
        {"vinted.fr": [_item(30), _item(31)]},
        {31: VintedItemDetail(item_id=31, listed_at=datetime.now(timezone.utc), catalog_ids=frozenset({"1231"}))},
    )

    await _run_check(db_session, monitor, client)

    assert await _found_ids(db_session, monitor) == [31]


@pytest.mark.asyncio
async def test_detail_cap_exceeded_does_not_create_unchecked_found_items(db_session):
    user = await _user(db_session, "detail_guard_cap")
    monitor = await _monitor(db_session, user)
    tasks.settings.monitor_candidate_detail_max_per_check = 1
    client = DetailGuardClient(
        {"vinted.fr": [_item(40), _item(41)]},
        {
            40: VintedItemDetail(item_id=40, listed_at=datetime.now(timezone.utc)),
            41: VintedItemDetail(item_id=41, listed_at=datetime.now(timezone.utc)),
        },
    )

    await _run_check(db_session, monitor, client)

    assert client.detail_calls == [("vinted.fr", 40)]
    assert await _found_ids(db_session, monitor) == [40]
    assert 41 not in await _seen_ids(db_session, monitor)


@pytest.mark.asyncio
async def test_cold_start_still_seeds_seen_only(db_session):
    user = await _user(db_session, "detail_guard_cold")
    monitor = await _monitor(db_session, user, cold_start=True)
    client = DetailGuardClient({"vinted.fr": [_item(50)]}, {})

    await _run_check(db_session, monitor, client)

    assert client.detail_calls == []
    assert await _found_ids(db_session, monitor) == []
    assert await _seen_ids(db_session, monitor) == [50]
