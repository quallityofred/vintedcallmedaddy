from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import FoundItem, Monitor, SeenItem, User
from app.scheduler import tasks
from app.scheduler.diagnostics import registry
from app.scheduler.tasks import TelegramDeliveryTarget
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.web.diagnostics_api_router import router


def create_test_app(*, admin: bool = True, db_session: AsyncSession | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_user] = lambda: User(
        id=999,
        username=f"admin-{datetime.now(timezone.utc).timestamp()}",
        password_hash="hash",
        password_salt="salt",
        is_admin=admin,
    )
    app.dependency_overrides[require_api_csrf] = lambda: None
    if db_session is not None:
        app.dependency_overrides[get_db] = lambda: db_session
    return app


async def seed_pending_items(db_session: AsyncSession, *, count: int = 3):
    fixture_id = uuid4().hex
    user = User(
        username=f"pending-user-{fixture_id}",
        password_hash="hash",
        password_salt="salt",
        telegram_bot_token="secret-test-token",
        telegram_chat_id="123456",
        is_telegram_enabled=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name=f"Pending monitor-{fixture_id}",
        original_url="https://www.vinted.pl/catalog?brand_ids[]=53",
        params_json='{"brand_ids[]":[53]}',
        domains_json='["vinted.pl"]',
        interval_sec=120,
        is_active=False,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    items = []
    for index in range(count):
        item = FoundItem(
            monitor_id=monitor.id,
            vinted_item_id=9200000000 + int(datetime.now(timezone.utc).timestamp()) + index,
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
    return user, [monitor], items


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


async def post_process_job(app: FastAPI, query: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/api/v1/diagnostics/notifications/process-pending-jobs{query}")

async def post_ack(app: FastAPI, query: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/api/v1/diagnostics/notifications/ack-pending-no-notify{query}")


async def get_job_status(app: FastAPI, job_id: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/api/v1/diagnostics/notifications/process-pending-jobs/{job_id}")


async def wait_for_job(app: FastAPI, job_id: str, timeout: int = 5):
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < timeout:
        response = await get_job_status(app, job_id)
        assert response.status_code == 200
        data = response.json()
        if data["status"] == "completed":
            return data
        if data["status"] == "failed":
            raise RuntimeError(f"Job failed: {data.get('safe_error')}")
        await asyncio.sleep(0.1)
    raise TimeoutError("Job timed out")


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
    assert data["pending_total"] == 3
    assert data["selected_for_processing"] == 3
    assert data["with_photo_url"] == 2
    assert data["without_photo_url"] == 1
    assert data["estimated_seconds_private_chat"] == 3
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
    assert data["pending_total"] == 4
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

    # 1. Assert sync endpoint rejects dry_run=false
    sync_response = await post_process(
        create_test_app(),
        f"?dry_run=false&monitor_id={monitors[0].id}&limit=1",
    )
    assert sync_response.status_code == 400
    assert "async_notification_job_required" in sync_response.json()["detail"]

    # 2. Run via async job
    app = create_test_app()
    job_response = await post_process_job(
        app,
        f"?dry_run=false&monitor_id={monitors[0].id}&limit=1",
    )
    assert job_response.status_code == 200
    job_id = job_response.json()["job_id"]

    data = await wait_for_job(app, job_id)
    summary = data["summary"]
    assert summary["selected_for_processing"] == 1
    assert summary["sent_photo_count"] == 1
    assert summary["marked_notified_count"] == 1
    assert summary["pending_after"] == 2
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
async def test_process_notifications_job_is_monitor_scoped(
    db_session, notification_session_factory, monkeypatch
):
    _, first_monitors, first_items = await seed_pending_items(db_session, count=2)
    _, second_monitors, second_items = await seed_pending_items(db_session, count=2)
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
    send_mock = AsyncMock(return_value="photo")
    monkeypatch.setattr(tasks, "send_item_notification", send_mock)

    app = create_test_app()
    dry_response = await post_process(
        app,
        f"?dry_run=true&monitor_id={first_monitors[0].id}&limit=10&sample_limit=10",
    )
    assert dry_response.status_code == 200
    dry_selected_ids = {
        sample["vinted_item_id"] for sample in dry_response.json()["samples"]
    }
    response = await post_process_job(
        app,
        f"?dry_run=false&monitor_id={first_monitors[0].id}&limit=10",
    )
    assert response.status_code == 200
    result = await wait_for_job(app, response.json()["job_id"])

    assert result["requested_monitor_id"] == first_monitors[0].id
    assert result["summary"]["selected_monitor_ids"] == [first_monitors[0].id]
    assert result["summary"]["selected_for_processing"] == 2
    assert send_mock.await_count == 2
    live_selected_ids = {str(call.args[2].id) for call in send_mock.await_args_list}
    assert live_selected_ids == dry_selected_ids
    for item in first_items + second_items:
        await db_session.refresh(item)
    assert all(item.notified is True for item in first_items)
    assert all(item.notified is False for item in second_items)
    assert first_monitors[0].id != second_monitors[0].id


@pytest.mark.asyncio
async def test_process_notifications_direct_live_requires_explicit_scope():
    with pytest.raises(ValueError, match="monitor_id_required"):
        await tasks.process_pending_notifications(dry_run=False)


@pytest.mark.asyncio
async def test_process_notifications_job_rejects_unscoped_live():
    response = await post_process_job(create_test_app(), "?dry_run=false&limit=1")
    assert response.status_code == 400
    assert response.json()["detail"] == "monitor_id_required_for_live_notification_processing"


@pytest.mark.asyncio
async def test_process_notifications_running_status_reports_request_and_live_side_effects():
    job_id = f"notify-running-{uuid4().hex}"
    await registry.start_job(
        job_id,
        0,
        "pending_notifications",
        request_metadata={
            "requested_monitor_id": 22,
            "requested_limit": 10,
            "requested_sample_limit": 5,
            "requested_dry_run": False,
            "all_monitors": False,
        },
    )

    response = await get_job_status(create_test_app(), job_id)
    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "running"
    assert data["requested_monitor_id"] == 22
    assert data["summary"]["selected_for_processing"] is None
    assert data["side_effects"]["sends_telegram"] is True
    assert data["side_effects"]["calls_vinted"] is False


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

    app = create_test_app()
    job_response = await post_process_job(
        app,
        f"?dry_run=false&monitor_id={monitors[0].id}&limit=1",
    )
    assert job_response.status_code == 200
    job_id = job_response.json()["job_id"]

    data = await wait_for_job(app, job_id)
    summary = data["summary"]
    assert summary.get("failed_count", 0) == 1

    assert summary["marked_notified_count"] == 0
    assert summary["pending_after"] == 1
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

    app = create_test_app()
    job_response = await post_process_job(
        app,
        f"?dry_run=false&monitor_id={monitors[0].id}&limit=1",
    )
    assert job_response.status_code == 200
    job_id = job_response.json()["job_id"]

    data = await wait_for_job(app, job_id)
    assert data["summary"].get("fallback_text_count", 0) == 1

@pytest.mark.asyncio
async def test_process_notifications_diagnostic_requires_admin():
    response = await post_process(create_test_app(admin=False), "?dry_run=true")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_process_notifications_diagnostic_requires_csrf():
    from app.web.csrf import require_api_csrf
    app = create_test_app()

    app_with_csrf = FastAPI()
    app_with_csrf.include_router(router)
    app_with_csrf.dependency_overrides[require_api_user] = lambda: User(
        id=999,
        username="diagnostic-admin",
        password_hash="hash",
        password_salt="salt",
        is_admin=True,
    )
    # DO NOT override require_api_csrf

    response = await post_process(app_with_csrf, "?dry_run=true")

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

    # 1. Dry-run diagnostics CAN overlap (responsiveness fix)
    await asyncio.gather(
        tasks.process_pending_notifications(dry_run=True),
        tasks.process_pending_notifications(dry_run=True),
    )
    assert max_active == 2
    max_active = 0

    # 2. Actual processors MUST NOT overlap (lock protection)
    # We mock _count_pending_notifications to avoid DB call in the finally block
    monkeypatch.setattr(tasks, "_count_pending_notifications", AsyncMock(return_value=0))

    await asyncio.gather(
        tasks.process_pending_notifications(dry_run=False, allow_all_monitors=True),
        tasks.process_pending_notifications(dry_run=False, allow_all_monitors=True),
    )

    assert max_active == 1


def test_monitor_check_triggers_only_monitor_scoped_notification_processing():
    import inspect

    source = inspect.getsource(tasks.check_monitor)
    assert "process_pending_notifications(monitor_id=monitor_id)" in source
    assert "create_task(process_pending_notifications())" not in source


@pytest.mark.asyncio
async def test_ack_pending_no_notify_requires_admin(db_session):
    _, monitors, _ = await seed_pending_items(db_session, count=1)
    app = create_test_app(admin=False, db_session=db_session)

    response = await post_ack(app, f"?monitor_id={monitors[0].id}")
    assert response.status_code == 403

@pytest.mark.asyncio
async def test_ack_pending_no_notify_dry_run_is_read_only(db_session, monkeypatch):
    _, monitors, items = await seed_pending_items(db_session, count=5)
    app = create_test_app(db_session=db_session)
    send_mock = AsyncMock(side_effect=AssertionError("ack endpoint must not send Telegram"))
    monkeypatch.setattr(tasks, "send_item_notification", send_mock)

    response = await post_ack(app, f"?monitor_id={monitors[0].id}&dry_run=true")
    assert response.status_code == 200
    data = response.json()
    assert data["selected_for_ack"] == 5
    assert data["would_mark_notified_count"] == 5
    assert data["marked_notified_count"] == 0
    assert data["pending_after_if_applied"] == 0
    assert data["pending_after"] == 5
    assert data["side_effects"]["marks_notified"] is False

    await db_session.refresh(items[0])
    assert items[0].notified is False
    send_mock.assert_not_awaited()

    serialized = json.dumps(data)
    assert "images.example.invalid" not in serialized
    assert "secret-test-token" not in serialized
    assert "123456" not in serialized


@pytest.mark.asyncio
async def test_ack_pending_no_notify_mutates_on_false(db_session, monkeypatch):
    _, monitors, items = await seed_pending_items(db_session, count=5)
    app = create_test_app(db_session=db_session)
    send_mock = AsyncMock(side_effect=AssertionError("ack endpoint must not send Telegram"))
    monkeypatch.setattr(tasks, "send_item_notification", send_mock)
    monitor_last_check = monitors[0].last_check_at
    seen_before = int((await db_session.execute(select(func.count(SeenItem.id)))).scalar_one())

    response = await post_ack(app, f"?monitor_id={monitors[0].id}&dry_run=false")
    assert response.status_code == 200
    data = response.json()
    assert data["selected_for_ack"] == 5
    assert data["marked_notified_count"] == 5
    assert data["pending_after"] == 0
    assert data["side_effects"]["marks_notified"] is True

    await db_session.refresh(items[0])
    assert items[0].notified is True
    assert items[4].notified is True
    await db_session.refresh(monitors[0])
    assert monitors[0].last_check_at == monitor_last_check
    seen_after = int((await db_session.execute(select(func.count(SeenItem.id)))).scalar_one())
    assert seen_after == seen_before
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_ack_pending_no_notify_idempotent(db_session):
    _, monitors, _ = await seed_pending_items(db_session, count=5)
    app = create_test_app(db_session=db_session)

    # First run
    await post_ack(app, f"?monitor_id={monitors[0].id}&dry_run=false")

    # Second run
    response = await post_ack(app, f"?monitor_id={monitors[0].id}&dry_run=false")
    data = response.json()
    assert data["selected_for_ack"] == 0
    assert data["marked_notified_count"] == 0
    assert data["pending_after"] == 0

@pytest.mark.asyncio
async def test_ack_pending_no_notify_requires_monitor_id():
    app = create_test_app()
    response = await post_ack(app, "")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ack_pending_no_notify_requires_csrf(db_session):
    _, monitors, _ = await seed_pending_items(db_session, count=1)
    app = create_test_app(db_session=db_session)
    app.dependency_overrides.pop(require_api_csrf)

    response = await post_ack(app, f"?monitor_id={monitors[0].id}")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ack_pending_no_notify_respects_limit_and_monitor_scope(db_session):
    _, first_monitors, first_items = await seed_pending_items(db_session, count=5)
    _, second_monitors, second_items = await seed_pending_items(db_session, count=3)
    app = create_test_app(db_session=db_session)

    response = await post_ack(
        app,
        f"?monitor_id={first_monitors[0].id}&limit=2&sample_limit=1&dry_run=false",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["pending_before"] == 5
    assert data["selected_for_ack"] == 2
    assert data["marked_notified_count"] == 2
    assert data["pending_after"] == 3
    assert len(data["samples"]) == 1
    for item in first_items:
        await db_session.refresh(item)
    for item in second_items:
        await db_session.refresh(item)
    assert sum(item.notified for item in first_items) == 2
    assert all(item.notified is False for item in second_items)
    assert first_monitors[0].id != second_monitors[0].id


@pytest.mark.asyncio
async def test_ack_pending_no_notify_reason_is_bounded(db_session):
    _, monitors, _ = await seed_pending_items(db_session, count=1)
    app = create_test_app(db_session=db_session)

    response = await post_ack(
        app,
        f"?monitor_id={monitors[0].id}&reason={'x' * 81}",
    )

    assert response.status_code == 422
