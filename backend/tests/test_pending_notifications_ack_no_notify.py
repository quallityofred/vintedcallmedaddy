import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete
import uuid

from app.models import FoundItem, Monitor, User, utc_now
from app.scheduler.pending_diagnostics import run_pending_notifications_ack_no_notify

async def _create_test_user(db_session):
    username = f"user_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username, 
        password_hash="fake_hash",
        password_salt="fake_salt",
        telegram_bot_token="", 
        telegram_chat_id=""
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

@pytest_asyncio.fixture(autouse=True)
async def cleanup_each_test(db_session):
    await db_session.execute(delete(FoundItem))
    await db_session.execute(delete(Monitor))
    await db_session.execute(delete(User))
    await db_session.commit()
    yield

@pytest.mark.asyncio
async def test_ack_no_mutation_dry_run(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(user_id=user.id, name="Test M", original_url="U", params_json="{}", domains_json='["vinted.fr"]', is_active=False)
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Pending item
    item = FoundItem(
        monitor_id=monitor.id, vinted_item_id=1, domain="vinted.fr", title="T", price=1, currency="E",
        brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1,
        found_at=utc_now() - timedelta(days=2), notified=False
    )
    db_session.add(item)
    await db_session.commit()

    # Dry-run
    result = await run_pending_notifications_ack_no_notify(db=db_session, dry_run=True, include_inactive=True)
    
    assert result["eligible_to_ack"] == 1
    assert result["acked_count"] == 0
    assert result["side_effects"]["marks_notified"] is False
    
    # Check item still pending
    item_after = await db_session.get(FoundItem, item.id)
    assert item_after.notified is False

@pytest.mark.asyncio
async def test_ack_live_mutation(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(user_id=user.id, name="Test M", original_url="U", params_json="{}", domains_json='["vinted.fr"]', is_active=False)
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Pending item
    item = FoundItem(
        monitor_id=monitor.id, vinted_item_id=1, domain="vinted.fr", title="T", price=1, currency="E",
        brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1,
        found_at=utc_now() - timedelta(days=2), notified=False
    )
    db_session.add(item)
    await db_session.commit()

    # Live ack
    result = await run_pending_notifications_ack_no_notify(db=db_session, dry_run=False, include_inactive=True, older_than_minutes=1)
    
    assert result["eligible_to_ack"] == 1
    assert result["acked_count"] == 1
    assert result["side_effects"]["marks_notified"] is True
    
    # Check item acked
    item_after = await db_session.get(FoundItem, item.id)
    assert item_after.notified is True

@pytest.mark.asyncio
async def test_active_monitor_excluded_by_default(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(user_id=user.id, name="Test M", original_url="U", params_json="{}", domains_json='["vinted.fr"]', is_active=True)
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Pending item
    item = FoundItem(
        monitor_id=monitor.id, vinted_item_id=1, domain="vinted.fr", title="T", price=1, currency="E",
        brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1,
        found_at=utc_now() - timedelta(days=2), notified=False
    )
    db_session.add(item)
    await db_session.commit()

    # Attempt to ack (include_active=False default)
    result = await run_pending_notifications_ack_no_notify(db=db_session, dry_run=False, include_inactive=True, include_active=False, older_than_minutes=1)
    
    assert result["eligible_to_ack"] == 0
    assert result["acked_count"] == 0
    
    # Check item still pending
    item_after = await db_session.get(FoundItem, item.id)
    assert item_after.notified is False
