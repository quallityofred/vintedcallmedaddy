import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import FoundItem, Monitor, SeenItem, User
from app.scheduler import tasks
from app.scraper.client import DomainSearchResult
from app.scraper.parser import VintedItem


@pytest.fixture(autouse=True)
def reset_scheduler_state(monkeypatch):
    monkeypatch.setattr(tasks.settings, "monitor_check_global_concurrency", 2)
    monkeypatch.setattr(tasks.settings, "monitor_check_per_user_concurrency", 1)
    monkeypatch.setattr(tasks.settings, "monitor_check_acquire_timeout_seconds", 0.05)
    monkeypatch.setattr(tasks.settings, "monitor_check_max_pages_per_domain", 1)
    tasks.reset_backpressure_state_for_tests()
    yield
    tasks.reset_backpressure_state_for_tests()


def _item(
    item_id: int,
    *,
    domain: str = "vinted.fr",
    brand_id: int | None = 123,
    seller_id: int | None = None,
) -> VintedItem:
    return VintedItem(
        id=item_id,
        title=f"Item {item_id}",
        price=10.0,
        currency="EUR",
        brand="Target" if brand_id == 123 else "Other",
        size="M",
        condition="New",
        photo_url="",
        item_url=f"https://www.{domain}/items/{item_id}",
        domain=domain,
        seller_id=seller_id or item_id,
        brand_id=brand_id,
    )


async def _user(db_session, username: str = "delta_user") -> User:
    user = User(username=username, telegram_bot_token="", telegram_chat_id="")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _monitor(
    db_session,
    user: User,
    *,
    name: str = "Delta",
    domains: list[str] | None = None,
    cold_start: bool = False,
    params: dict | None = None,
) -> Monitor:
    monitor = Monitor(
        user_id=user.id,
        name=name,
        original_url="https://www.vinted.fr/catalog?brand_ids[]=123",
        params_json=json.dumps(params or {"brand_ids[]": [123], "order": "relevance", "page": 2}),
        domains_json=json.dumps(domains or ["vinted.fr"]),
        interval_sec=120,
        is_active=True,
        last_check_at=None if cold_start else datetime.now(timezone.utc),
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    return monitor


class FakeDomainClient:
    def __init__(self, results: dict[str, list[VintedItem]]):
        self.results = results
        self.calls: list[tuple[dict, list[str], str]] = []

    async def search_domains(self, params, domains, mode="auto"):
        self.calls.append((dict(params), list(domains), mode))
        return [
            DomainSearchResult(domain=domain, items=list(self.results.get(domain, [])), request_count=1)
            for domain in domains
        ]


async def _run_check(db_session, monitor: Monitor, client: FakeDomainClient):
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()):
        await tasks.check_monitor(monitor.id, scraper_client=client)


@pytest.mark.asyncio
async def test_delta_stops_at_first_seen_item_for_single_domain(db_session):
    user = await _user(db_session, "delta_boundary_user")
    monitor = await _monitor(db_session, user)
    db_session.add(SeenItem(user_id=user.id, vinted_item_id=2, domain="vinted.fr"))
    await db_session.commit()

    client = FakeDomainClient({"vinted.fr": [_item(1), _item(2), _item(3)]})
    await _run_check(db_session, monitor, client)

    found = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    seen = (await db_session.execute(select(SeenItem).where(SeenItem.user_id == user.id))).scalars().all()

    assert [item.vinted_item_id for item in found] == [1]
    assert sorted(item.vinted_item_id for item in seen) == [1, 2]


@pytest.mark.asyncio
async def test_delta_wrong_brand_and_missing_brand_do_not_count_as_boundary(db_session):
    user = await _user(db_session, "delta_filter_boundary_user")
    monitor = await _monitor(db_session, user)
    db_session.add_all([
        SeenItem(user_id=user.id, vinted_item_id=20, domain="vinted.fr"),
        SeenItem(user_id=user.id, vinted_item_id=21, domain="vinted.fr"),
    ])
    await db_session.commit()

    client = FakeDomainClient({
        "vinted.fr": [
            _item(20, brand_id=999),
            _item(21, brand_id=None),
            _item(22, brand_id=123),
        ]
    })
    await _run_check(db_session, monitor, client)

    found = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    assert [item.vinted_item_id for item in found] == [22]


@pytest.mark.asyncio
async def test_cold_start_multiple_domains_seeds_each_domain_without_found_items(db_session):
    user = await _user(db_session, "delta_cold_multi_user")
    monitor = await _monitor(db_session, user, domains=["vinted.fr", "vinted.de"], cold_start=True)

    client = FakeDomainClient({
        "vinted.fr": [_item(1, domain="vinted.fr"), _item(2, domain="vinted.fr")],
        "vinted.de": [_item(3, domain="vinted.de")],
    })
    await _run_check(db_session, monitor, client)

    found_count = (await db_session.execute(select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id))).scalar_one()
    seen = (await db_session.execute(select(SeenItem).where(SeenItem.user_id == user.id))).scalars().all()

    assert found_count == 0
    assert sorted((item.vinted_item_id, item.domain) for item in seen) == [
        (1, "vinted.fr"),
        (2, "vinted.fr"),
        (3, "vinted.de"),
    ]


@pytest.mark.asyncio
async def test_all_selected_domains_are_checked_and_boundaries_are_per_domain(db_session):
    user = await _user(db_session, "delta_all_domains_user")
    monitor = await _monitor(db_session, user, domains=["vinted.fr", "vinted.de"])
    db_session.add_all([
        SeenItem(user_id=user.id, vinted_item_id=100, domain="vinted.fr"),
        SeenItem(user_id=user.id, vinted_item_id=200, domain="vinted.de"),
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
    assert [(item.vinted_item_id, item.domain) for item in found] == [
        (190, "vinted.de"),
        (191, "vinted.de"),
        (90, "vinted.fr"),
    ]


@pytest.mark.asyncio
async def test_runtime_params_force_newest_first_and_first_page_only(db_session):
    user = await _user(db_session, "delta_params_user")
    monitor = await _monitor(
        db_session,
        user,
        params={"brand_ids[]": [123], "order": "relevance", "page": 5, "_original_interval": 120},
    )

    client = FakeDomainClient({"vinted.fr": []})
    await _run_check(db_session, monitor, client)

    params, domains, _ = client.calls[0]
    assert domains == ["vinted.fr"]
    assert params["order"] == "newest_first"
    assert "page" not in params
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_seen_lookup_is_domain_aware(db_session):
    user = await _user(db_session, "delta_domain_seen_user")
    monitor = await _monitor(db_session, user, domains=["vinted.fr", "vinted.de"])
    db_session.add(SeenItem(user_id=user.id, vinted_item_id=777, domain="vinted.fr"))
    await db_session.commit()

    client = FakeDomainClient({
        "vinted.fr": [_item(777, domain="vinted.fr")],
        "vinted.de": [_item(777, domain="vinted.de")],
    })
    await _run_check(db_session, monitor, client)

    found = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    assert [(item.vinted_item_id, item.domain) for item in found] == [(777, "vinted.de")]
