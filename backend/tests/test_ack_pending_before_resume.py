import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from app.models import FoundItem, Monitor, User, utc_now
from app.scheduler.pending_diagnostics import run_ack_pending_before_resume

import uuid

from sqlalchemy import delete

@pytest_asyncio.fixture(autouse=True)
async def clean_db(db_session):
    # Explicitly clear tables to ensure isolation
    await db_session.execute(delete(FoundItem))
    await db_session.execute(delete(Monitor))
    await db_session.execute(delete(User))
    await db_session.commit()

@pytest_asyncio.fixture
async def sample_data(db_session):
    # Create an admin user
    username = f"admin_user_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username, 
        is_admin=True, 
        telegram_bot_token="t", 
        telegram_chat_id="c",
        password_hash="h",
        password_salt="s"
    )
    db_session.add(user)
    await db_session.flush()
    
    # Create a monitor
    monitor_name = f"Test Monitor {uuid.uuid4().hex[:8]}"
    monitor = Monitor(
        name=monitor_name, 
        user_id=user.id, 
        is_active=True, 
        domains_json='["vinted.fr"]', 
        params_json='{"brand_ids": ["123"]}',
        original_url=f"https://vinted.fr/items?brand_ids[]=123&{uuid.uuid4().hex[:4]}"
    )
    db_session.add(monitor)
    await db_session.flush()
    
    now = utc_now()
    base_id = int(str(uuid.uuid4().int)[:10]) # Get a large unique integer base
    
    # Item 1: Valid brand evidence, old
    item1 = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=base_id + 1,
        domain="vinted.fr",
        title="Kapital Jacket",
        price=100.0,
        currency="EUR",
        brand="Kapital",
        brand_id=123,
        size="L",
        condition="New",
        photo_url="https://images.vinted.net/1",
        item_url="https://vinted.fr/items/1",
        seller_id=1,
        found_at=now - timedelta(hours=2),
        notified=False
    )
    
    # Item 2: Valid brand evidence, new
    item2 = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=base_id + 2,
        domain="vinted.fr",
        title="Kapital Pants",
        price=50.0,
        currency="EUR",
        brand="Kapital",
        brand_id=123,
        size="M",
        condition="Good",
        photo_url="https://images.vinted.net/2",
        item_url="https://vinted.fr/items/2",
        seller_id=2,
        found_at=now - timedelta(minutes=10),
        notified=False
    )
    
    # Item 3: Unknown cause (no brand match), old
    item3 = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=base_id + 3,
        domain="vinted.fr",
        title="Unknown Brand",
        price=30.0,
        currency="EUR",
        brand="Unknown",
        size="S",
        condition="Fair",
        photo_url="https://images.vinted.net/3",
        item_url="https://vinted.fr/items/3",
        seller_id=3,
        found_at=now - timedelta(hours=3),
        notified=False
    )
    
    db_session.add_all([item1, item2, item3])
    await db_session.commit()
    
    return {
        "user": user,
        "monitor": monitor,
        "item1": item1,
        "item2": item2,
        "item3": item3,
        "now": now,
        "base_id": base_id
    }

@pytest.mark.asyncio
async def test_ack_pending_before_resume_dry_run(db_session, sample_data):
    res = await run_ack_pending_before_resume(
        db=db_session,
        dry_run=True,
        reason="test dry run"
    )
    
    assert res["dry_run"] is True
    assert res["matched_pending_count"] == 3
    # item1=valid, item2=valid, item3=unknown_brand_from_unverified_source
    # By default: 
    #   include_valid_positive_brand_evidence=False
    #   include_unknown_cause=False
    # item3 is ELIGIBLE because it's "unknown_brand_from_unverified_source" 
    # (which is different from "unknown" cause)
    assert res["eligible_count"] == 1 
    assert res["acked_count"] == 0
    
    # Verify no changes in DB
    result = await db_session.execute(select(func.count(FoundItem.id)).where(FoundItem.notified == False))
    assert result.scalar() == 3

@pytest.mark.asyncio
async def test_ack_pending_before_resume_include_valid(db_session, sample_data):
    res = await run_ack_pending_before_resume(
        db=db_session,
        dry_run=True,
        include_valid_positive_brand_evidence=True,
        reason="test include valid"
    )
    
    # item1, item2 (valid) + item3 (unknown_brand_from_unverified_source)
    assert res["eligible_count"] == 3 
    assert res["excluded_valid_positive_brand_evidence_count"] == 0
    assert res["excluded_unknown_cause_count"] == 0

@pytest.mark.asyncio
async def test_ack_pending_before_resume_cutoff(db_session, sample_data):
    cutoff = sample_data["now"] - timedelta(hours=1)
    res = await run_ack_pending_before_resume(
        db=db_session,
        dry_run=True,
        include_valid_positive_brand_evidence=True,
        cutoff_found_before=cutoff,
        reason="test cutoff"
    )
    
    # item1 is old enough (valid), item2 is too new
    # item3 is old enough (unknown_brand_from_unverified_source)
    assert res["matched_pending_count"] == 2 # item1, item3
    assert res["eligible_count"] == 2 # item1, item3
    assert res["excluded_valid_positive_brand_evidence_count"] == 0

@pytest.mark.asyncio
async def test_ack_pending_before_resume_live(db_session, sample_data):
    cutoff = sample_data["now"] - timedelta(hours=1)
    res = await run_ack_pending_before_resume(
        db=db_session,
        dry_run=False,
        include_valid_positive_brand_evidence=True,
        include_unknown_cause=True,
        cutoff_found_before=cutoff,
        reason="test live"
    )
    
    assert res["dry_run"] is False
    assert res["acked_count"] == 2 # item1, item3
    
    # Verify changes in DB
    result = await db_session.execute(select(FoundItem).where(FoundItem.notified == True))
    acked = result.scalars().all()
    assert len(acked) == 2
    acked_ids = {i.vinted_item_id for i in acked}
    base_id = sample_data["base_id"]
    assert base_id + 1 in acked_ids
    assert base_id + 3 in acked_ids
    assert base_id + 2 not in acked_ids # item2 was after cutoff
