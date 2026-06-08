import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.models import Monitor, FoundItem, SeenItem, User, utc_now
from app.scheduler.retention import run_history_retention_dry_run
from sqlalchemy import delete
import uuid

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
    await db_session.execute(delete(SeenItem))
    await db_session.execute(delete(Monitor))
    await db_session.execute(delete(User))
    await db_session.commit()
    yield

@pytest.mark.asyncio
async def test_retention_dry_run_no_mutation(db_session):
    user = await _create_test_user(db_session)
    # Setup: Create a monitor and some items
    monitor = Monitor(
        user_id=user.id,
        name="Test Monitor",
        original_url="https://vinted.fr/items",
        params_json="{}",
        domains_json='["vinted.fr"]'
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    old_date = utc_now() - timedelta(days=20)
    
    found_item = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=123,
        domain="vinted.fr",
        title="Old Item",
        price=10.0,
        currency="EUR",
        brand="Brand",
        size="M",
        condition="New",
        photo_url="http://photo.com",
        item_url="http://item.com",
        seller_id=456,
        found_at=old_date,
        notified=True
    )
    db_session.add(found_item)
    
    seen_item = SeenItem(
        monitor_id=monitor.id,
        vinted_item_id=123,
        domain="vinted.fr",
        seen_at=old_date
    )
    db_session.add(seen_item)
    await db_session.commit()

    # Run dry-run
    result = await run_history_retention_dry_run(
        db=db_session,
        found_items_retention_days=14,
        found_items_max_per_monitor_domain=10,
        seen_items_max_per_monitor_domain=10
    )

    assert result["found_items_would_delete_total"] == 1
    assert result["seen_items_would_delete_total"] == 0 # Cap is 10, only 1 item exists

    # Verify no deletion
    found_items_after = await db_session.execute(select(FoundItem))
    assert len(found_items_after.all()) == 1
    
    seen_items_after = await db_session.execute(select(SeenItem))
    assert len(seen_items_after.all()) == 1

@pytest.mark.asyncio
async def test_found_item_retention_logic(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="Test Monitor",
        original_url="https://vinted.fr/items",
        params_json="{}",
        domains_json='["vinted.fr"]'
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    now = utc_now()
    
    # 1. Old notified item (should be deleted by TTL)
    db_session.add(FoundItem(
        monitor_id=monitor.id, vinted_item_id=1, domain="vinted.fr", title="T1", price=1, currency="E",
        brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1,
        found_at=now - timedelta(days=20), notified=True
    ))
    
    # 2. Recent notified item (should be kept)
    db_session.add(FoundItem(
        monitor_id=monitor.id, vinted_item_id=2, domain="vinted.fr", title="T2", price=1, currency="E",
        brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1,
        found_at=now - timedelta(days=1), notified=True
    ))
    
    # 3. Old pending item (should be preserved regardless of age)
    db_session.add(FoundItem(
        monitor_id=monitor.id, vinted_item_id=3, domain="vinted.fr", title="T3", price=1, currency="E",
        brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1,
        found_at=now - timedelta(days=20), notified=False
    ))
    
    # 4. Beyond cap items (Recent but over cap)
    # We set cap to 1 for notified items
    db_session.add(FoundItem(
        monitor_id=monitor.id, vinted_item_id=4, domain="vinted.fr", title="T4", price=1, currency="E",
        brand="B", size="S", condition="C", photo_url="P", item_url="U", seller_id=1,
        found_at=now - timedelta(minutes=10), notified=True
    ))
    # Item 4 is newest notified, Item 2 is older notified. 
    # If cap=1, Item 2 should be deleted even if recent.
    
    await db_session.commit()

    result = await run_history_retention_dry_run(
        db=db_session,
        found_items_retention_days=14,
        found_items_max_per_monitor_domain=1
    )

    assert result["found_items_total"] == 4
    assert result["found_items_pending_total"] == 1
    assert result["found_items_notified_total"] == 3
    
    # Expected deletions: 
    # - Item 1 (TTL)
    # - Item 2 (Cap, because Item 4 is newer)
    assert result["found_items_would_delete_total"] == 2
    assert result["found_items_would_keep_total"] == 2 # Item 3 (Pending), Item 4 (Newest notified)

@pytest.mark.asyncio
async def test_seen_item_retention_logic(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="Test Monitor",
        original_url="https://vinted.fr/items",
        params_json="{}",
        domains_json='["vinted.fr"]'
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    now = utc_now()
    
    # Create 5 seen items, cap=2
    for i in range(1, 6):
        db_session.add(SeenItem(
            monitor_id=monitor.id,
            vinted_item_id=i,
            domain="vinted.fr",
            seen_at=now - timedelta(minutes=i)
        ))
    
    await db_session.commit()

    result = await run_history_retention_dry_run(
        db=db_session,
        seen_items_max_per_monitor_domain=2
    )

    assert result["seen_items_total"] == 5
    assert result["seen_items_would_delete_total"] == 3 # 5 - 2
    assert result["seen_items_would_keep_total"] == 2

@pytest.mark.asyncio
async def test_retention_monitor_filtering(db_session):
    user = await _create_test_user(db_session)
    m1 = Monitor(user_id=user.id, name="M1", original_url="U", params_json="{}", domains_json='["vinted.fr"]')
    m2 = Monitor(user_id=user.id, name="M2", original_url="U", params_json="{}", domains_json='["vinted.fr"]')
    db_session.add_all([m1, m2])
    await db_session.commit()
    await db_session.refresh(m1)
    await db_session.refresh(m2)

    db_session.add(SeenItem(monitor_id=m1.id, vinted_item_id=1, domain="vinted.fr"))
    db_session.add(SeenItem(monitor_id=m2.id, vinted_item_id=2, domain="vinted.fr"))
    await db_session.commit()

    # Dry-run for m1 only
    result = await run_history_retention_dry_run(db=db_session, monitor_ids=[m1.id])
    
    assert result["monitors_considered"] == [m1.id]
    assert result["seen_items_total"] == 1
