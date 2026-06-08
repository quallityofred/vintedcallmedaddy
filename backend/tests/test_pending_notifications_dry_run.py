import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select
import uuid

from app.models import FoundItem, Monitor, MonitorTelegramTopic, User, utc_now
from app.scheduler.pending_diagnostics import run_pending_notifications_dry_run

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
    await db_session.execute(delete(MonitorTelegramTopic))
    await db_session.execute(delete(Monitor))
    await db_session.execute(delete(User))
    await db_session.commit()
    yield

@pytest.mark.asyncio
async def test_pending_notifications_dry_run_no_mutation(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(user_id=user.id, name="Test M", original_url="U", params_json="{}", domains_json='["vinted.fr"]', is_active=True)
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Pending item
    item = FoundItem(
        monitor_id=monitor.id, vinted_item_id=1, domain="vinted.fr", title="T", price=1, currency="E",
        brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1,
        found_at=utc_now(), notified=False
    )
    db_session.add(item)
    await db_session.commit()

    # Run dry-run
    result = await run_pending_notifications_dry_run(db=db_session)
    
    assert result["pending_total"] == 1
    assert result["side_effects"]["marks_notified"] is False
    
    # Check item still pending
    item_after = await db_session.get(FoundItem, item.id)
    assert item_after.notified is False

@pytest.mark.asyncio
async def test_age_buckets(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(user_id=user.id, name="Test M", original_url="U", params_json="{}", domains_json='["vinted.fr"]', is_active=True)
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    
    now = utc_now()
    
    # Buckets: lt_1h, h_1_to_6, h_6_to_24, d_1_to_3, d_3_to_7, gt_7d
    deltas = [
        timedelta(minutes=30),
        timedelta(hours=3),
        timedelta(hours=10),
        timedelta(days=2),
        timedelta(days=5),
        timedelta(days=10)
    ]
    
    for i, delta in enumerate(deltas):
        db_session.add(FoundItem(
            monitor_id=monitor.id, vinted_item_id=i, domain="vinted.fr", title=f"T{i}", price=1, currency="E",
            brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1,
            found_at=now - delta, notified=False
        ))
        
    await db_session.commit()
    
    result = await run_pending_notifications_dry_run(db=db_session)
    
    # Access as dict
    stats = result["by_monitor"][0]["stats"]
    assert stats["lt_1h"] == 1
    assert stats["h_1_to_6"] == 1
    assert stats["h_6_to_24"] == 1
    assert stats["d_1_to_3"] == 1
    assert stats["d_3_to_7"] == 1
    assert stats["gt_7d"] == 1

@pytest.mark.asyncio
async def test_monitor_domain_filtering_and_active_status(db_session):
    user = await _create_test_user(db_session)
    active_m = Monitor(user_id=user.id, name="Active", original_url="U", params_json="{}", domains_json='["vinted.fr"]', is_active=True)
    inactive_m = Monitor(user_id=user.id, name="Inactive", original_url="U", params_json="{}", domains_json='["vinted.fr"]', is_active=False)
    db_session.add_all([active_m, inactive_m])
    await db_session.commit()
    await db_session.refresh(active_m)
    await db_session.refresh(inactive_m)
    
    # Both have pending
    db_session.add(FoundItem(monitor_id=active_m.id, vinted_item_id=1, domain="vinted.fr", title="T", price=1, currency="E", brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1, found_at=utc_now(), notified=False))
    db_session.add(FoundItem(monitor_id=inactive_m.id, vinted_item_id=2, domain="vinted.fr", title="T", price=1, currency="E", brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1, found_at=utc_now(), notified=False))
    await db_session.commit()
    
    # 1. Test inactive exclusion
    result = await run_pending_notifications_dry_run(db=db_session, include_inactive=False)
    assert result["pending_total"] == 1
    assert result["by_monitor"][0]["monitor_id"] == active_m.id
    
    # 2. Test monitor_ids filter
    result = await run_pending_notifications_dry_run(db=db_session, monitor_ids=[inactive_m.id])
    assert result["pending_total"] == 1
    assert result["by_monitor"][0]["monitor_id"] == inactive_m.id

@pytest.mark.asyncio
async def test_topic_mapping_detection(db_session):
    user = await _create_test_user(db_session)
    m_with_topic = Monitor(user_id=user.id, name="WithTopic", original_url="U", params_json="{}", domains_json='["vinted.fr"]', is_active=True)
    m_no_topic = Monitor(user_id=user.id, name="NoTopic", original_url="U", params_json="{}", domains_json='["vinted.fr"]', is_active=True)
    db_session.add_all([m_with_topic, m_no_topic])
    await db_session.commit()
    await db_session.refresh(m_with_topic)
    # ...
    db_session.add(MonitorTelegramTopic(monitor_id=m_with_topic.id, user_id=user.id, chat_id="123", message_thread_id=456, topic_name="Topic"))

    # Ensure items have UTC timezone-aware found_at
    # utc_now() returns timezone-aware datetime.
    now = utc_now()
    db_session.add(FoundItem(monitor_id=m_with_topic.id, vinted_item_id=1, domain="vinted.fr", title="T", price=1, currency="E", brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1, found_at=now, notified=False))
    db_session.add(FoundItem(monitor_id=m_no_topic.id, vinted_item_id=2, domain="vinted.fr", title="T", price=1, currency="E", brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1, found_at=now, notified=False))
    await db_session.commit()
    # ...

    result = await run_pending_notifications_dry_run(db=db_session)
    
    # Find monitor stats
    m_with_topic_stats = next(m for m in result["by_monitor"] if m["monitor_id"] == m_with_topic.id)
    m_no_topic_stats = next(m for m in result["by_monitor"] if m["monitor_id"] == m_no_topic.id)
    
    assert m_with_topic_stats["has_topic"] is True
    assert m_no_topic_stats["has_topic"] is False
