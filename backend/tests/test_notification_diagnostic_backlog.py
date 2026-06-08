from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models import FoundItem, Monitor, User
from app.scheduler import tasks
from app.web.dependencies import get_db
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.web.diagnostics_api_router import router

def create_test_app(db_session) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_user] = lambda: User(
        id=999,
        username=f"admin-{datetime.now(timezone.utc).timestamp()}",
        password_hash="hash",
        password_salt="salt",
        is_admin=True,
    )
    app.dependency_overrides[require_api_csrf] = lambda: None
    app.dependency_overrides[get_db] = lambda: db_session
    return app

async def seed_backlog(db_session, monitor_id, count=636):
    items = []
    now = datetime.now(timezone.utc)
    for i in range(count):
        items.append(FoundItem(
            monitor_id=monitor_id,
            vinted_item_id=2000000 + i,
            domain="vinted.pl",
            title=f"Backlog item {i}",
            price=10.0,
            currency="PLN",
            brand="Nike",
            size="M",
            condition="New",
            photo_url="http://example.com/photo.jpg",
            item_url="http://example.com/item",
            seller_id=3000000 + i,
            found_at=now,
            notified=False,
        ))
    db_session.add_all(items)
    await db_session.commit()

@pytest.mark.asyncio
async def test_notification_dry_run_large_backlog(db_session, engine, monkeypatch):
    # Monkeypatch tasks session factory to use test DB
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", factory)

    # Setup: User and Monitor
    user = User(
        username=f"backlog-user-{datetime.now(timezone.utc).timestamp()}", 
        password_hash="h", 
        password_salt="s", 
        is_admin=True
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    monitor = Monitor(
        user_id=user.id, 
        name="nike-backlog", 
        original_url="http://vinted.pl/nike", 
        params_json='{}', 
        domains_json='["vinted.pl"]', 
        is_active=True
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    
    # Seed 636 pending items
    await seed_backlog(db_session, monitor.id, 636)
    
    app = create_test_app(db_session)
    transport = ASGITransport(app=app)
    
    # Mock Telegram send to ensure it's not called
    send_mock = AsyncMock()
    monkeypatch.setattr(tasks, "send_item_notification", send_mock)
    
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Call process-pending with dry_run=true
        start_time = asyncio.get_event_loop().time()
        response = await client.post(f"/api/v1/diagnostics/notifications/process-pending?monitor_id={monitor.id}&limit=20&sample_limit=10&dry_run=true")
        duration = asyncio.get_event_loop().time() - start_time
        
    assert response.status_code == 200
    data = response.json()
    assert data["pending_total"] == 636
    assert data["selected_for_processing"] == 20
    assert len(data["samples"]) == 10
    assert data["side_effects"]["sends_telegram"] is False
    assert data["marked_notified_count"] == 0
    
    # Assert it was fast (should be well under 1s, definitely not 30s)
    assert duration < 5.0 
    
    # Verify no mutation for OUR monitor
    count = await db_session.scalar(
        tasks.select(tasks.func.count(FoundItem.id))
        .where(FoundItem.notified == True, FoundItem.monitor_id == monitor.id)
    )
    assert count == 0
    send_mock.assert_not_called()
