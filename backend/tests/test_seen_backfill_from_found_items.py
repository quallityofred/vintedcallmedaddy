from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.models import FoundItem, Monitor, SeenItem, User
from app.scheduler import tasks
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.web.diagnostics_api_router import router


def create_app(db_session, *, admin: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_user] = lambda: User(
        id=999,
        username="seen-backfill-admin",
        password_hash="hash",
        password_salt="salt",
        is_admin=admin,
    )
    app.dependency_overrides[require_api_csrf] = lambda: None
    app.dependency_overrides[get_db] = lambda: db_session
    return app


async def seed_monitor_history(db_session, *, username: str, item_ids: list[int]):
    user = User(username=username, password_hash="hash", password_salt="salt")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name="Seen backfill monitor",
        original_url="https://www.vinted.pl/catalog?brand_ids[]=53",
        params_json='{"brand_ids[]":[53]}',
        domains_json='["vinted.pl"]',
        interval_sec=120,
        is_active=False,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    found_items = []
    for item_id in item_ids:
        found = FoundItem(
            monitor_id=monitor.id,
            vinted_item_id=item_id,
            domain="vinted.pl",
            title=f"Item {item_id}",
            price=10.0,
            currency="PLN",
            brand="Nike",
            brand_id=53,
            size="",
            condition="",
            photo_url="",
            item_url=f"https://www.vinted.pl/items/{item_id}-item",
            seller_id=0,
            found_at=datetime.now(timezone.utc),
            notified=True,
        )
        db_session.add(found)
        found_items.append(found)
    await db_session.commit()
    return monitor, found_items


async def post_backfill(app: FastAPI, monitor_id: int, query: str = ""):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            f"/api/v1/diagnostics/monitors/{monitor_id}/backfill-seen-from-found-items{query}"
        )


async def seen_count(db_session, monitor_id: int) -> int:
    return int(
        await db_session.scalar(
            select(func.count(SeenItem.id)).where(SeenItem.monitor_id == monitor_id)
        )
        or 0
    )


@pytest.mark.asyncio
async def test_seen_backfill_dry_run_is_read_only(db_session, monkeypatch):
    monitor, found_items = await seed_monitor_history(
        db_session,
        username="seen_backfill_dry_run",
        item_ids=[9300000001, 9300000002],
    )
    app = create_app(db_session)
    send_mock = AsyncMock(side_effect=AssertionError("backfill must not send Telegram"))
    monkeypatch.setattr(tasks, "send_item_notification", send_mock)

    response = await post_backfill(app, monitor.id, "?dry_run=true")

    assert response.status_code == 200
    data = response.json()
    assert data["found_items_scanned"] == 2
    assert data["would_insert_seen"] == 2
    assert data["inserted_seen"] == 0
    assert data["side_effects"]["writes_seen_items"] is False
    assert await seen_count(db_session, monitor.id) == 0
    for item in found_items:
        await db_session.refresh(item)
        assert item.notified is True
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_seen_backfill_apply_is_monitor_scoped_and_idempotent(db_session):
    monitor, found_items = await seed_monitor_history(
        db_session,
        username="seen_backfill_apply",
        item_ids=[9300000011, 9300000012, 9300000013],
    )
    other_monitor, _ = await seed_monitor_history(
        db_session,
        username="seen_backfill_other",
        item_ids=[9300000021],
    )
    app = create_app(db_session)

    first = await post_backfill(app, monitor.id, "?dry_run=false&limit=2")
    second = await post_backfill(app, monitor.id, "?dry_run=false&limit=2")
    third = await post_backfill(app, monitor.id, "?dry_run=false&limit=2")

    assert first.status_code == 200
    assert first.json()["inserted_seen"] == 2
    assert first.json()["side_effects"]["writes_seen_items"] is True
    assert second.json()["inserted_seen"] == 1
    assert third.json()["inserted_seen"] == 0
    assert await seen_count(db_session, monitor.id) == 3
    assert await seen_count(db_session, other_monitor.id) == 0
    for item in found_items:
        await db_session.refresh(item)
        assert item.notified is True


@pytest.mark.asyncio
async def test_seen_backfill_requires_admin_and_csrf(db_session):
    monitor, _ = await seed_monitor_history(
        db_session,
        username="seen_backfill_guards",
        item_ids=[9300000031],
    )

    non_admin = create_app(db_session, admin=False)
    assert (await post_backfill(non_admin, monitor.id)).status_code == 403

    no_csrf = create_app(db_session)
    no_csrf.dependency_overrides.pop(require_api_csrf)
    assert (await post_backfill(no_csrf, monitor.id)).status_code == 403
