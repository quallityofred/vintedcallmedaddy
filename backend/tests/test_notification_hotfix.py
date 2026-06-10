from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import FoundItem, Monitor, User, MonitorTelegramTopic
from app.scheduler import tasks
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

async def seed_pending_items(db_session: AsyncSession, *, count: int = 1):
    fixture_id = uuid4().hex
    user = User(
        username=f"hotfix-user-{fixture_id}",
        password_hash="hash",
        password_salt="salt",
        telegram_bot_token="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ123456789", # Valid-looking token
        telegram_chat_id="123456",
        is_telegram_enabled=True,
        telegram_topics_enabled=True,
        telegram_topics_chat_id="-100123456789",
        telegram_topics_auto_create=True,
        telegram_topics_recreate_deleted=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name=f"Hotfix monitor-{fixture_id}",
        original_url="https://www.vinted.fr/catalog?search_text=test",
        params_json='{"search_text":"test"}',
        domains_json='["vinted.fr"]',
        interval_sec=120,
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    topic = MonitorTelegramTopic(
        user_id=user.id,
        monitor_id=monitor.id,
        chat_id="-100123456789",
        topic_name=monitor.name,
        message_thread_id=123,
        status="active",
    )
    db_session.add(topic)
    await db_session.commit()
    await db_session.refresh(topic)

    items = []
    for index in range(count):
        item = FoundItem(
            monitor_id=monitor.id,
            vinted_item_id=9300000000 + index,
            domain="vinted.fr",
            title=f"Hotfix item {index}",
            price=10.0,
            currency="EUR",
            brand="Test",
            size="M",
            condition="good",
            photo_url="https://images.example.invalid/1.jpg",
            item_url="https://www.vinted.fr/items/9300000000",
            seller_id=2000,
            found_at=datetime.now(timezone.utc),
            notified=False,
        )
        db_session.add(item)
        items.append(item)
    await db_session.commit()
    return user, monitor, topic, items

@pytest.fixture
def hotfix_session_factory(engine, monkeypatch):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", factory)
    yield factory
    tasks.AsyncSessionLocal = None

async def post_process(app: FastAPI, body: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/diagnostics/notifications/process-pending", json=body)

async def post_process_job(app: FastAPI, body: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/diagnostics/notifications/process-pending-jobs", json=body)

async def wait_for_job(app: FastAPI, job_id: str, timeout: int = 5):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            response = await client.get(f"/api/v1/diagnostics/notifications/process-pending-jobs/{job_id}")
            assert response.status_code == 200
            data = response.json()
            if data["status"] == "completed":
                return data
            if data["status"] == "failed":
                raise RuntimeError(f"Job failed: {data.get('safe_error')}")
            await asyncio.sleep(0.1)
    raise TimeoutError("Job timed out")

@pytest.mark.asyncio
async def test_process_pending_respects_json_body(db_session, hotfix_session_factory):
    _, monitor, _, _ = await seed_pending_items(db_session, count=1)
    app = create_test_app(db_session=db_session)
    
    # Verify dry_run=true is default and respected
    res = await post_process(app, {"monitor_id": monitor.id})
    assert res.status_code == 200
    assert res.json()["dry_run"] is True
    
    # Verify monitor_id in body scopes the candidates
    _, monitor2, _, _ = await seed_pending_items(db_session, count=1)
    res = await post_process(app, {"monitor_id": monitor2.id})
    assert res.status_code == 200
    assert res.json()["selected_for_processing"] == 1
    assert res.json()["samples"][0]["title_preview"].startswith("Hotfix item 0")

@pytest.mark.asyncio
async def test_stale_topic_recreation_and_retry(db_session, hotfix_session_factory, monkeypatch):
    user, monitor, topic, items = await seed_pending_items(db_session, count=1)
    
    # Mock Telegram to fail with "message thread not found" on first call, succeed on second
    send_mock = AsyncMock()
    # first call raises, second call returns "photo"
    send_mock.side_effect = [
        RuntimeError("Bad Request: message thread not found"),
        "photo"
    ]
    monkeypatch.setattr(tasks, "send_item_notification", send_mock)
    
    # Mock bot.create_forum_topic for recreation
    from app.telegram import topic_service
    fake_topic = MagicMock()
    fake_topic.message_thread_id = 456
    monkeypatch.setattr(tasks.Bot, "create_forum_topic", AsyncMock(return_value=fake_topic))
    monkeypatch.setattr(topic_service.Bot, "create_forum_topic", AsyncMock(return_value=fake_topic))
    # Mock get_chat and get_me for verify_forum_group (called during ensure_monitor_topic)
    monkeypatch.setattr(topic_service.Bot, "get_chat", AsyncMock(return_value=MagicMock(type="supergroup", is_forum=True)))
    monkeypatch.setattr(topic_service.Bot, "get_me", AsyncMock(return_value=MagicMock(id=123)))
    monkeypatch.setattr(topic_service.Bot, "get_chat_member", AsyncMock(return_value=MagicMock(status="administrator", can_manage_topics=True)))

    app = create_test_app(db_session=db_session)
    
    # Use the job endpoint for live processing
    res = await post_process_job(app, {"dry_run": False, "monitor_id": monitor.id, "limit": 1})
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    
    data = await wait_for_job(app, job_id)
    summary = data["summary"]
    
    # We expect:
    # 1. First send failed
    # 2. Re-resolve triggered recreation
    # 3. Second send succeeded
    # 4. marked_notified_count == 1
    assert summary["marked_notified_count"] == 1
    assert summary["sent_photo_count"] == 1
    assert send_mock.call_count == 2
    
    # Verify DB state: topic should have new thread ID
    await db_session.refresh(topic)
    assert topic.message_thread_id == 456
    assert topic.status == "active"
    
    # Verify item is notified
    await db_session.refresh(items[0])
    assert items[0].notified is True
