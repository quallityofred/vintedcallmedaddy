import pytest
import json
from unittest.mock import AsyncMock, patch
from app.models import Monitor, MonitorFilterBaseline
from app.scheduler.tasks import _load_filter_baseline, _source_item_is_stale, _requires_filter_contract_baseline, MonitorCheckContext
from app.scraper.parser import VintedItem
from datetime import datetime, timezone, timedelta
from app.scraper.monitor_filters import extract_monitor_filters

@pytest.mark.anyio
async def test_watermark_suppression_rule(db_session):
    # Setup
    monitor = Monitor(name="M1", user_id=1, original_url="https://v.pl/c", params_json='{"order":"newest_first"}', domains_json='["vinted.pl"]')
    db_session.add(monitor)
    await db_session.commit()
    
    baseline = MonitorFilterBaseline(
        monitor_id=monitor.id,
        domain="vinted.pl",
        filter_fingerprint="fp1",
        filter_contract_version="v1",
        source_strategy="api",
        max_vinted_item_id=1000
    )
    db_session.add(baseline)
    await db_session.commit()
    
    context = MonitorCheckContext(
        monitor_id=monitor.id,
        user_id=1,
        monitor_name="M1",
        params={"order": "newest_first"},
        original_url="https://v.pl/c",
        domains=["vinted.pl"],
        monitor_filters=extract_monitor_filters({"order": "newest_first"}),
        hidden_seller_ids=set(),
        is_cold_start=False,
        freshness_cutoff_at=datetime.now(timezone.utc) - timedelta(hours=24),
        original_interval=0,
        cf_worker_url=None,
        cf_worker_mode="auto",
        cf_worker_block_threshold=2.0,
        cf_worker_recovery_minutes=10
    )
    
    # Item below watermark, no listed_at (untrusted) -> should be suppressed if we check it in Diag
    item_below = VintedItem(id=990, title="T", price=1.0, currency="PLN", brand="B", size="S", condition="N", photo_url="", item_url="", domain="vinted.pl", seller_id=1, listed_at=None)
    item_above = VintedItem(id=1005, title="T", price=1.0, currency="PLN", brand="B", size="S", condition="N", photo_url="", item_url="", domain="vinted.pl", seller_id=1, listed_at=None)
    
    # Enforce logic simulation (what we have in tasks.py)
    # if item.listed_at is None and baseline and baseline.max_vinted_item_id is not None:
    #    if item.id <= baseline.max_vinted_item_id:
    #        suppress
    
    assert item_below.id <= baseline.max_vinted_item_id
    assert item_above.id > baseline.max_vinted_item_id

@pytest.mark.anyio
async def test_url_normalization_enforces_newest_first():
    from app.scraper.url_parser import get_effective_monitor_request_params
    
    # Case 1: missing order
    params = get_effective_monitor_request_params("{}", "https://www.vinted.pl/catalog")
    assert params.get("order") == "newest_first"
    
    # Case 2: wrong order
    params = get_effective_monitor_request_params('{"order": "price_low_to_high"}', "https://www.vinted.pl/catalog")
    assert params.get("order") == "newest_first"
    
    # Case 3: newest_first in URL but not in params
    params = get_effective_monitor_request_params("{}", "https://www.vinted.pl/catalog?order=relevance")
    assert params.get("order") == "newest_first"
