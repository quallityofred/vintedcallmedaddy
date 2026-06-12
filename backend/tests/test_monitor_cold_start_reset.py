import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, delete
from app.models import Monitor, FoundItem, SeenItem, User, utc_now
from app.scheduler.cold_start_reset import run_monitor_cold_start_reset
from app.scheduler.tasks import is_monitor_check_running
import uuid
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.web.dependencies import get_db
from unittest.mock import patch

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

@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_cold_start_reset_dry_run(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="Test Monitor",
        original_url="https://vinted.fr/items",
        params_json="{}",
        domains_json='["vinted.fr", "vinted.pl"]',
        last_check_at=utc_now()
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Add some seen items
    db_session.add(SeenItem(monitor_id=monitor.id, vinted_item_id=1, domain="vinted.fr"))
    db_session.add(SeenItem(monitor_id=monitor.id, vinted_item_id=2, domain="vinted.pl"))
    await db_session.commit()

    result = await run_monitor_cold_start_reset(
        db=db_session,
        monitor_id=monitor.id,
        dry_run=True,
        domains=["vinted.fr"]
    )

    assert result["dry_run"] is True
    assert result["would_delete_seen_items"] == 1
    assert result["would_reset_last_checked"] is True
    assert result["cold_start_mode_after_reset"] is True
    assert len(result["samples"]) == 1
    assert result["samples"][0]["domain"] == "vinted.fr"

    # Verify no mutation
    res = await db_session.execute(select(SeenItem))
    assert len(res.all()) == 2
    await db_session.refresh(monitor)
    assert monitor.last_check_at is not None

@pytest.mark.asyncio
async def test_cold_start_reset_live_inactive(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="Test Monitor",
        original_url="https://vinted.fr/items",
        params_json="{}",
        domains_json='["vinted.fr"]',
        last_check_at=utc_now()
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    db_session.add(SeenItem(monitor_id=monitor.id, vinted_item_id=1, domain="vinted.fr"))
    await db_session.commit()

    result = await run_monitor_cold_start_reset(
        db=db_session,
        monitor_id=monitor.id,
        dry_run=False,
        require_monitor_inactive=True
    )

    assert result["deleted_seen_items"] == 1
    assert result["reset_last_checked"] is True
    assert result["cold_start_mode_after_reset"] is True

    # Verify DB mutation
    res = await db_session.execute(select(SeenItem))
    assert len(res.all()) == 0
    await db_session.refresh(monitor)
    assert monitor.last_check_at is None
    assert monitor.last_check_status == "reset"

@pytest.mark.asyncio
async def test_cold_start_reset_domain_filter(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="Test Monitor",
        original_url="https://vinted.fr/items",
        params_json="{}",
        domains_json='["vinted.fr", "vinted.pl"]',
        last_check_at=utc_now()
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    db_session.add(SeenItem(monitor_id=monitor.id, vinted_item_id=1, domain="vinted.fr"))
    db_session.add(SeenItem(monitor_id=monitor.id, vinted_item_id=2, domain="vinted.pl"))
    await db_session.commit()

    result = await run_monitor_cold_start_reset(
        db=db_session,
        monitor_id=monitor.id,
        dry_run=False,
        domains=["vinted.fr"]
    )

    assert result["deleted_seen_items"] == 1
    
    # vinted.pl should remain
    res = await db_session.execute(select(SeenItem))
    rows = res.all()
    assert len(rows) == 1
    assert rows[0][0].domain == "vinted.pl"

@pytest.mark.asyncio
async def test_cold_start_reset_other_monitor_preserved(db_session):
    user = await _create_test_user(db_session)
    m1 = Monitor(user_id=user.id, name="M1", original_url="U1", params_json="{}", domains_json='["vinted.fr"]')
    m2 = Monitor(user_id=user.id, name="M2", original_url="U2", params_json="{}", domains_json='["vinted.fr"]')
    db_session.add_all([m1, m2])
    await db_session.commit()
    await db_session.refresh(m1)
    await db_session.refresh(m2)

    db_session.add(SeenItem(monitor_id=m1.id, vinted_item_id=1, domain="vinted.fr"))
    db_session.add(SeenItem(monitor_id=m2.id, vinted_item_id=2, domain="vinted.fr"))
    await db_session.commit()

    result = await run_monitor_cold_start_reset(
        db=db_session,
        monitor_id=m1.id,
        dry_run=False
    )

    assert result["deleted_seen_items"] == 1
    
    # m2 items should remain
    res = await db_session.execute(select(SeenItem))
    rows = res.all()
    assert len(rows) == 1
    assert rows[0][0].monitor_id == m2.id

@pytest.mark.asyncio
async def test_cold_start_reset_endpoint_guards(db_session, client):
    user = await _create_test_user(db_session)
    monitor = Monitor(user_id=user.id, name="M", original_url="U", params_json="{}", domains_json='["vinted.fr"]')
    db_session.add(monitor)
    await db_session.commit()

    from app.web.api_dependencies import require_api_user, require_api_admin
    from app.web.csrf import require_api_csrf
    user.is_admin = True
    await db_session.commit()
    
    app.dependency_overrides[require_api_user] = lambda: user
    app.dependency_overrides[require_api_admin] = lambda: user
    app.dependency_overrides[require_api_csrf] = lambda: None

    # 1. No reason
    payload = {
        "dry_run": False,
        "confirm": "RESET_MONITOR_COLD_START",
        "extra_confirm": ["CLEAR_SEEN_ITEMS_NO_NOTIFY_BASELINE"]
    }
    response = await client.post(f"/api/v1/maintenance/monitors/{monitor.id}/reset-cold-start", json=payload)
    assert response.status_code == 400
    assert "Reason required" in response.json()["detail"]

    # 2. Invalid confirm
    payload["reason"] = "test"
    payload["confirm"] = "WRONG"
    response = await client.post(f"/api/v1/maintenance/monitors/{monitor.id}/reset-cold-start", json=payload)
    assert response.status_code == 400
    assert "Invalid confirmation string" in response.json()["detail"]

    # 3. Missing extra_confirm
    payload["confirm"] = "RESET_MONITOR_COLD_START"
    payload["extra_confirm"] = []
    response = await client.post(f"/api/v1/maintenance/monitors/{monitor.id}/reset-cold-start", json=payload)
    assert response.status_code == 400
    assert "CLEAR_SEEN_ITEMS_NO_NOTIFY_BASELINE" in response.json()["detail"]

    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_cold_start_reset_active_guard_failure(db_session):
    user = await _create_test_user(db_session)
    monitor = Monitor(
        user_id=user.id,
        name="M",
        original_url="U",
        params_json="{}",
        domains_json='["vinted.fr"]',
        is_active=True,
        last_check_at=utc_now()
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Mock is_monitor_check_running to return True
    with patch("app.scheduler.cold_start_reset.is_monitor_check_running", return_value=True):
        with pytest.raises(ValueError, match="is currently running a check"):
            await run_monitor_cold_start_reset(
                db=db_session,
                monitor_id=monitor.id,
                dry_run=False,
                require_monitor_inactive=True
            )

    # Verify no mutation
    await db_session.refresh(monitor)
    assert monitor.last_check_at is not None
