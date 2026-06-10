import pytest
import pytest_asyncio
import uuid
from sqlalchemy import select, func, delete
from app.models import Monitor, FoundItem, SeenItem, User, utc_now
from app.scheduler.cold_start_reset import run_monitor_cold_start_reset

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
async def test_cold_start_reset_pending_guard(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="M",
        original_url="U",
        params_json="{}",
        domains_json='["vinted.fr"]'
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    
    # Create a pending item (notified=False)
    pending_item = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=99999,
        domain="vinted.fr",
        title="Pending Item",
        price=10.0,
        currency="EUR",
        brand="Brand",
        size="M",
        condition="New",
        photo_url="http://photo",
        item_url="http://item",
        seller_id=123,
        notified=False
    )
    db_session.add(pending_item)
    await db_session.commit()

    # 1. Dry run should report pending items
    res = await run_monitor_cold_start_reset(
        db=db_session,
        monitor_id=monitor.id,
        dry_run=True,
        clear_found_items=True
    )
    assert res["pending_found_items_count"] == 1
    assert res["would_delete_found_items"] > 0

    # 2. Live reset
    res_live = await run_monitor_cold_start_reset(
        db=db_session,
        monitor_id=monitor.id,
        dry_run=False,
        clear_found_items=True
    )
    assert res_live["deleted_found_items"] >= 1
    
    # Verify items are gone
    stmt = select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id)
    count = await db_session.scalar(stmt)
    assert count == 0

@pytest.mark.asyncio
async def test_cold_start_reset_items_found_count_update(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="M",
        original_url="U",
        params_json="{}",
        domains_json='["vinted.fr"]',
        items_found_count=10
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Live reset with clear_found_items
    await run_monitor_cold_start_reset(
        db=db_session,
        monitor_id=monitor.id,
        dry_run=False,
        clear_found_items=True
    )
    
    await db_session.refresh(monitor)
    assert monitor.items_found_count == 0

@pytest.mark.asyncio
async def test_cold_start_reset_filtered_found_count_no_update(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="M",
        original_url="U",
        params_json="{}",
        domains_json='["vinted.fr", "vinted.pl"]',
        items_found_count=10
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Live reset with clear_found_items BUT domain filter
    await run_monitor_cold_start_reset(
        db=db_session,
        monitor_id=monitor.id,
        dry_run=False,
        clear_found_items=True,
        domains=["vinted.fr"]
    )
    
    await db_session.refresh(monitor)
    # If domains filter is present, we don't reset total count
    assert monitor.items_found_count == 10
