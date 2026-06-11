import pytest
import json
from datetime import datetime, timezone
from app.scraper.app_scraper_url_parser import parse_vinted_url, normalize_catalog_search_params
from app.scraper.monitor_filters import extract_monitor_filters, has_restrictive_filters
from app.scheduler.tasks import MonitorCheckContext, _load_monitor_check_context
from app.models import Monitor, User
from sqlalchemy import select

@pytest.mark.asyncio
async def test_url_normalization_newest_first():
    # 1. /catalog?newest_first
    url1 = "https://www.vinted.fr/catalog?newest_first"
    params1 = parse_vinted_url(url1)
    assert params1["order"] == "newest_first"
    
    filters1 = extract_monitor_filters(params1)
    assert not has_restrictive_filters(filters1)
    
    # 2. /catalog?order=newest_first
    url2 = "https://www.vinted.fr/catalog?order=newest_first"
    params2 = parse_vinted_url(url2)
    assert params2["order"] == "newest_first"
    
    # 3. /catalog?order[]=newest_first
    url3 = "https://www.vinted.fr/catalog?order[]=newest_first"
    params3 = parse_vinted_url(url3)
    assert params3["order"] == "newest_first"

@pytest.mark.asyncio
async def test_brand_extraction_with_newest_first():
    # 4. /brand/14217-vivienne-westwood?newest_first
    url = "https://www.vinted.fr/brand/14217-vivienne-westwood?newest_first"
    params = parse_vinted_url(url)
    assert params["order"] == "newest_first"
    assert 14217 in params["brand_ids[]"]
    
    filters = extract_monitor_filters(params)
    assert has_restrictive_filters(filters)
    assert filters.brand_ids == {"14217"}

@pytest.mark.asyncio
async def test_broad_risk_monitor_detection(db_session, engine):
    # Override AsyncSessionLocal to use test engine
    from app.scheduler import tasks
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    tasks.AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    # Setup a user
    user = User(username="test_user", password_hash="...", password_salt="...", is_admin=True)
    db_session.add(user)
    await db_session.commit()
    
    # Setup a broad monitor
    monitor = Monitor(
        name="Broad Monitor",
        original_url="https://www.vinted.fr/catalog?order=newest_first",
        params_json=json.dumps({"order": "newest_first"}),
        domains_json=json.dumps(["vinted.fr"]),
        user_id=user.id,
        is_active=True,
        interval_sec=60
    )
    db_session.add(monitor)
    await db_session.commit()
    
    # Load context
    from app.scheduler.tasks import _load_monitor_check_context
    context = await _load_monitor_check_context(monitor.id)
    assert context is not None
    assert context.is_broad_risk is True

@pytest.mark.asyncio
async def test_restricted_monitor_not_broad_risk(db_session, engine):
    # Override AsyncSessionLocal to use test engine
    from app.scheduler import tasks
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    tasks.AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    # Setup a user
    user = User(username="test_user_2", password_hash="...", password_salt="...", is_admin=True)
    db_session.add(user)
    await db_session.commit()
    
    # Setup a restricted monitor
    monitor = Monitor(
        name="Restricted Monitor",
        original_url="https://www.vinted.fr/catalog?brand_ids[]=14217",
        params_json=json.dumps({"brand_ids[]": [14217]}),
        domains_json=json.dumps(["vinted.fr"]),
        user_id=user.id,
        is_active=True,
        interval_sec=60
    )
    db_session.add(monitor)
    await db_session.commit()
    
    # Load context
    from app.scheduler.tasks import _load_monitor_check_context
    context = await _load_monitor_check_context(monitor.id)
    assert context is not None
    assert context.is_broad_risk is False

@pytest.mark.asyncio
async def test_diagnostics_router_imports():
    from app.web.diagnostics_api_router import router
    assert router.prefix == "/api/v1/diagnostics"
    
    # Check if new routes are registered
    paths = [r.path for r in router.routes]
    assert any("monitors/url-normalization-audit" in p for p in paths)
    assert any("pending-notifications/backlog-classification" in p for p in paths)

@pytest.mark.asyncio
async def test_maintenance_router_imports():
    from app.web.maintenance_api_router import router
    assert router.prefix == "/api/v1/maintenance"
    
    # Check if new route is registered
    paths = [r.path for r in router.routes]
    assert any("pending-notifications/ack-bad-url-backlog" in p for p in paths)
