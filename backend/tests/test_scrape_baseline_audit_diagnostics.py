import pytest
import uuid
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.models import User, Monitor, MonitorFilterBaseline, SeenItem, FoundItem
from app.main import app
from app.web.api_dependencies import require_api_admin, get_db
from sqlalchemy import select

@pytest.fixture
async def admin_user(db_session):
    unique_id = uuid.uuid4().hex[:8]
    user = User(
        username=f"admin_diag_{unique_id}", 
        is_admin=True,
        password_hash="hash",
        password_salt="salt"
    )
    db_session.add(user)
    await db_session.commit()
    return user

@pytest.fixture
async def test_monitor(db_session, admin_user):
    unique_id = uuid.uuid4().hex[:8]
    monitor = Monitor(
        name=f"Test Monitor Diag {unique_id}",
        user_id=admin_user.id,
        original_url="https://www.vinted.pl/catalog?search_text=test",
        params_json='{"search_text": "test", "order": "newest_first"}',
        domains_json='["vinted.pl"]'
    )
    db_session.add(monitor)
    await db_session.commit()
    return monitor

@pytest.mark.anyio
async def test_scrape_baseline_audit_requires_admin(db_session, test_monitor):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # No auth
            response = await ac.get(f"/api/v1/diagnostics/monitors/{test_monitor.id}/scrape-baseline-audit")
            assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()

@pytest.mark.anyio
async def test_scrape_baseline_audit_fetch_false_is_readonly(db_session, test_monitor, admin_user):
    # Setup baseline
    baseline = MonitorFilterBaseline(
        monitor_id=test_monitor.id,
        domain="vinted.pl",
        filter_fingerprint="fp1",
        filter_contract_version="v1",
        source_strategy="api",
        max_vinted_item_id=1000
    )
    db_session.add(baseline)
    await db_session.commit()

    app.dependency_overrides[require_api_admin] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(f"/api/v1/diagnostics/monitors/{test_monitor.id}/scrape-baseline-audit?fetch_catalog=false")
            assert response.status_code == 200
            data = response.json()
            assert data["monitor_id"] == test_monitor.id
            domain_data = data["domains"]["vinted.pl"]
            assert domain_data["current_baseline_max_vinted_item_id"] == 1000
            
            # Verify no side effects
            res = await db_session.execute(select(SeenItem))
            assert len(res.scalars().all()) == 0
    finally:
        app.dependency_overrides.clear()

@pytest.mark.anyio
async def test_scrape_baseline_audit_fetch_true_is_readonly(db_session, test_monitor, admin_user):
    # Mock items structured as they would appear in Vinted's hydration data
    mock_items = [
        {
            "id": 1005, 
            "title": "Item 1", 
            "price": "10.0", 
            "currency": "PLN",
            "user": {"id": 1}, 
            "photos": [], 
            "path": "/items/1005", 
            "brand_title": "B1", 
            "size_title": "S", 
            "status": "New"
        },
        {
            "id": 990, 
            "title": "Item 2", 
            "price": "10.0", 
            "currency": "PLN",
            "user": {"id": 1}, 
            "photos": [], 
            "path": "/items/990", 
            "brand_title": "B1", 
            "size_title": "S", 
            "status": "New"
        }
    ]

    with patch("app.scraper.client.VintedClient.fetch_catalog_hydration_items", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_items
        
        # We need the fingerprint from the actual response or mock it
        app.dependency_overrides[require_api_admin] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db_session
        
        # First call to get the fingerprint
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            init_res = await ac.get(f"/api/v1/diagnostics/monitors/{test_monitor.id}/scrape-baseline-audit")
            fingerprint = init_res.json()["domains"]["vinted.pl"]["filter_fingerprint"]

            # Setup baseline with CORRECT fingerprint
            baseline = MonitorFilterBaseline(
                monitor_id=test_monitor.id,
                domain="vinted.pl",
                filter_fingerprint=fingerprint,
                filter_contract_version="v1",
                source_strategy="api",
                max_vinted_item_id=1000
            )
            db_session.add(baseline)
            await db_session.commit()

            response = await ac.get(f"/api/v1/diagnostics/monitors/{test_monitor.id}/scrape-baseline-audit?fetch_catalog=true")
            assert response.status_code == 200
            data = response.json()
            domain_data = data["domains"]["vinted.pl"]

            assert domain_data["max_fetched_item_id"] == 1005
            assert domain_data["would_suppress_count"] == 1 # 990 <= 1000
            assert domain_data["would_create_sendable_found_count"] == 1 # 1005 > 1000
            
            # Verify no side effects
            res_seen = await db_session.execute(select(SeenItem))
            assert len(res_seen.scalars().all()) == 0
            res_found = await db_session.execute(select(FoundItem))
            assert len(res_found.scalars().all()) == 0
            
            # Verify baseline was not updated
            await db_session.refresh(baseline)
            assert baseline.max_vinted_item_id == 1000
        app.dependency_overrides.clear()

@pytest.mark.anyio
async def test_scrape_baseline_audit_cap_validation(db_session, test_monitor, admin_user):
    app.dependency_overrides[require_api_admin] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(f"/api/v1/diagnostics/monitors/{test_monitor.id}/scrape-baseline-audit?max_items_per_domain=101")
            assert response.status_code == 422 # Pydantic Query le=100 returns 422
    finally:
        app.dependency_overrides.clear()
