from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import FoundItem, Monitor, User
from app.scheduler import tasks
from app.scheduler.tasks import TelegramDeliveryTarget
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.diagnostics_api_router import router


def create_test_app(*, admin: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_user] = lambda: User(
        id=999,
        username="diagnostic-admin",
        password_hash="hash",
        password_salt="salt",
        is_admin=admin,
    )
    app.dependency_overrides[require_api_csrf] = lambda: None
    return app


async def seed_pending_items(db_session: AsyncSession, *, count: int = 3):
    user = User(
        username=f"pending-user-{datetime.now(timezone.utc).timestamp()}",
        password_hash="hash",
        password_salt="salt",
        telegram_bot_token="secret-test-token",
        telegram_chat_id="123456",
        is_telegram_enabled=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitors = []
    for index in range(2):
        monitor = Monitor(
            user_id=user.id,
            name=f"Pending monitor {index}",
            original_url="https://www.vinted.pl/catalog?brand_ids[]=53",
            params_json='{"brand_ids[]":[53]}',
            domains_json='["vinted.pl"]',
            interval_sec=120,
            is_active=False,
        )
        db_session.add(monitor)
        monitors.append(monitor)
    await db_session.commit()
    for monitor in monitors:
        await db_session.refresh(monitor)

    items = []
    for index in range(count):
        monitor = monitors[index % len(monitors)]
        item = FoundItem(
            monitor_id=monitor.id,
            vinted_item_id=9200000000 + index,
            domain="vinted.pl",
            title=f"Pending item {index}",
            price=100 + index,
            currency="PLN",
            brand="Nike",
            size="42",
            condition="new",
            photo_url=f"https://images.example.invalid/{index}.jpg" if index != 1 else "",
            item_url=f"https://www.vinted.pl/items/{9200000000 + index}",
            seller_id=1000 + index,
            found_at=datetime.now(timezone.utc),
            notified=False,
        )
        db_session.add(item)
        items.append(item)
    await db_session.commit()
    for item in items:
        await db_session.refresh(item)
    return user, monitors, items


@pytest.fixture
def notification_session_factory(engine, monkeypatch):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", factory)
    yield factory
    tasks.AsyncSessionLocal = None


async def post_process(app: FastAPI, query: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/api/v1/diagnostics/notifications/process-pending{query}")


@pytest.mark.asyncio
async def test_process_notifications_diagnostic_dry_run_full_shape(
    db_session, notification_session_factory, monkeypatch
):
    _, monitors, items = await seed_pending_items(db_session)
    send_mock = AsyncMock(side_effect=AssertionError("dry run must not send Telegram"))
    monkeypatch.setattr(tasks, "send_item_notification", send_mock)

    response = await post_process(
        create_test_app(),
        f"?dry_run=true&monitor_id={monitors[0].id}&limit=10&sample_limit=10",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["monitor_id"] == monitors[0].id
    assert data["pending_total"] == 2
    assert data["selected_for_processing"] == 2
    assert data["with_photo_url"] == 2
    assert data["without_photo_url"] == 0
    assert data["estimated_seconds_private_chat"] == 2
    assert data["telegram_bot_configured"] is True
    assert data["telegram_chat_configured"] is True
    assert data["side_effects"] == {
        "reads_database": True,
        "writes_found_items": False,
        "sends_telegram": False,
    }
    send_mock.assert_not_awaited()
    await db_session.refresh(items[0])
    assert items[0].notified is False

    serialized = json.dumps(data)
    assert "secret-test-token" not in serialized
    assert "123456" not in serialized
    assert "images.example.invalid" not in serialized


@pytest.mark.asyncio
async def test_process_notifications_diagnostic_dry_run_applies_limit(
    db_session, notification_session_factory
):
    _, monitors, _ = await seed_pending_items(db_session, count=4)

    response = await post_process(
        create_test_app(),
        f"?dry_run=true&monitor_id={monitors[0].id}&limit=1",
    )

    data = response.json()
    assert data["pending_total"] == 2
    assert data["selected_for_processing"] == 1
    assert len(data["samples"]) == 1


@pytest.mark.asyncio
async def test_process_notifications_diagnostic_executes_limited_successful_batch(
    db_session, notification_session_factory, monkeypatch
):
    _, monitors, items = await seed_pending_items(db_session)
    bot = object()
    monkeypatch.setattr(
        tasks,
        "resolve_telegram_delivery_target",
        AsyncMock(
            return_value=TelegramDeliveryTarget(
                ok=True,
                code="main_chat",
                message="configured",
                bot=bot,
                chat_id=123456,
            )
        ),
    )
    send_mock = AsyncMock(return_value="photo")
    monkeypatch.setattr(tasks, "send_item_notification", send_mock)

    response = await post_process(
        create_test_app(),
        f"?dry_run=false&monitor_id={monitors[0].id}&limit=1",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["selected_for_processing"] == 1
    assert data["sent_photo_count"] == 1
    assert data["marked_notified_count"] == 1
    assert data["pending_after"] == 1
    assert data["side_effects"]["writes_found_items"] is True
    assert data["side_effects"]["sends_telegram"] is True
    send_mock.assert_awaited_once()

    await db_session.refresh(items[0])
    await db_session.refresh(items[1])
    await db_session.refresh(items[2])
    notified_for_monitor = [item.notified for item in items if item.monitor_id == monitors[0].id]
    assert notified_for_monitor.count(True) == 1
    assert items[1].notified is False


@pytest.mark.asyncio
async def test_process_notifications_failure_remains_retryable(
    db_session, notification_session_factory, monkeypatch
):
    _, monitors, items = await seed_pending_items(db_session, count=1)
    monkeypatch.setattr(
        tasks,
        "resolve_telegram_delivery_target",
        AsyncMock(
            return_value=TelegramDeliveryTarget(
                ok=True,
                code="main_chat",
                message="configured",
                bot=object(),
                chat_id=123456,
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "send_item_notification",
        AsyncMock(side_effect=RuntimeError("secret raw failure message")),
    )

    response = await post_process(
        create_test_app(),
        f"?dry_run=false&monitor_id={monitors[0].id}&limit=1",
    )

    data = response.json()
    assert data["failed_count"] == 1
    assert data["marked_notified_count"] == 0
    assert data["pending_after"] == 1
    assert "secret raw failure message" not in json.dumps(data)
    await db_session.refresh(items[0])
    assert items[0].notified is False


@pytest.mark.asyncio
async def test_process_notifications_reports_fallback_text(
    db_session, notification_session_factory, monkeypatch
):
    _, monitors, _ = await seed_pending_items(db_session, count=1)
    monkeypatch.setattr(
        tasks,
        "resolve_telegram_delivery_target",
        AsyncMock(
            return_value=TelegramDeliveryTarget(
                ok=True,
                code="main_chat",
                message="configured",
                bot=object(),
                chat_id=123456,
            )
        ),
    )
    monkeypatch.setattr(tasks, "send_item_notification", AsyncMock(return_value="fallback_text"))

    response = await post_process(
        create_test_app(),
        f"?dry_run=false&monitor_id={monitors[0].id}&limit=1",
    )

    assert response.json()["fallback_text_count"] == 1


@pytest.mark.asyncio
async def test_process_notifications_diagnostic_requires_admin():
    response = await post_process(create_test_app(admin=False), "?dry_run=true")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_process_notifications_diagnostic_requires_csrf():
    app = create_test_app()
    app.dependency_overrides.pop(require_api_csrf)

    response = await post_process(app, "?dry_run=true")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_process_notifications_diagnostic_limit_cap():
    response = await post_process(create_test_app(), "?dry_run=true&limit=201")
    assert response.status_code == 422


def test_pending_worker_disabled_by_default():
    from app.config import Settings

    assert Settings().pending_notifications_worker_enabled is False


def test_pending_worker_registration_is_flag_guarded():
    import inspect

    source = inspect.getsource(tasks.MonitorScheduler.start)
    assert "if settings.pending_notifications_worker_enabled" in source
    assert 'id="pending_notifications_processor"' in source


@pytest.mark.asyncio
async def test_pending_worker_registered_only_when_enabled(monkeypatch):
    class EmptyScalars:
        def all(self):
            return []

    class EmptyResult:
        def scalars(self):
            return EmptyScalars()

    class FakeDb:
        async def execute(self, statement):
            return EmptyResult()

    class FakeContext:
        async def __aenter__(self):
            return FakeDb()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    scheduler = tasks.MonitorScheduler()
    scheduler.scheduler = MagicMock()
    scheduler.scheduler.add_job = MagicMock(return_value=None)
    monkeypatch.setattr(tasks, "_new_session", lambda: FakeContext())
    monkeypatch.setattr(tasks.settings, "pending_notifications_worker_enabled", True)

    await scheduler.start()

    assert any(
        call.kwargs.get("id") == "pending_notifications_processor"
        for call in scheduler.scheduler.add_job.call_args_list
    )


@pytest.mark.asyncio
async def test_pending_processors_do_not_overlap(monkeypatch):
    active = 0
    max_active = 0

    async def fake_collect(*, monitor_id=None, limit=50):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return [], {
            "pending_total": 0,
            "telegram_bot_configured": False,
            "telegram_chat_configured": False,
            "uses_group_rate": False,
        }

    monkeypatch.setattr(tasks, "collect_pending_notification_candidates", fake_collect)

    await asyncio.gather(
        tasks.process_pending_notifications(dry_run=True),
        tasks.process_pending_notifications(dry_run=True),
    )

    assert max_active == 1
