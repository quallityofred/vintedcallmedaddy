import pytest
from app.scraper.parser import VintedItem
from app.scraper.monitor_filters import (
    MISSING_BRAND_ID_UNVERIFIED_SOURCE,
    MonitorFilters,
    item_matches_monitor_filters,
    extract_monitor_filters,
)

def test_hydration_item_missing_brand_id_matching_brand_title_passes():
    # monitor name "Nike Shoes" should allow "Nike"
    params = {
        "brand_ids[]": ["53"],
        "catalog[]": ["1231"]
    }
    filters = extract_monitor_filters(params, monitor_name="Nike Shoes")
    
    # item has brand_id=None, brand="Nike", raw_source="hydration"
    item = VintedItem(
        id=123,
        title="Nike Shox",
        price=100.0,
        currency="PLN",
        brand="Nike",
        size="42",
        condition="New",
        photo_url="url",
        item_url="url",
        domain="vinted.pl",
        seller_id=1,
        brand_id=None,
        raw_source="hydration"
    )
    
    matches, reason = item_matches_monitor_filters(item, filters)
    assert matches is True
    assert reason is None

def test_hydration_item_missing_brand_id_wrong_brand_title_is_rejected():
    # Nike monitor
    params = {
        "brand_ids[]": ["53"]
    }
    filters = extract_monitor_filters(params, monitor_name="Nike Shoes")
    
    # item has brand_id=None, brand="Adidas", raw_source="hydration"
    item = VintedItem(
        id=124,
        title="Adidas Shoes",
        price=100.0,
        currency="PLN",
        brand="Adidas",
        size="42",
        condition="New",
        photo_url="url",
        item_url="url",
        domain="vinted.pl",
        seller_id=1,
        brand_id=None,
        raw_source="hydration"
    )
    
    matches, reason = item_matches_monitor_filters(item, filters)
    assert matches is False
    assert reason == "wrong_brand"

def test_hydration_item_wrong_brand_id_rejected_even_with_hydration_source():
    # Nike monitor
    params = {
        "brand_ids[]": ["53"]
    }
    filters = extract_monitor_filters(params, monitor_name="Nike Shoes")
    
    # item has brand_id=999 (wrong), brand="Nike", raw_source="hydration"
    item = VintedItem(
        id=125,
        title="Nike Shox",
        price=100.0,
        currency="PLN",
        brand="Nike",
        size="42",
        condition="New",
        photo_url="url",
        item_url="url",
        domain="vinted.pl",
        seller_id=1,
        brand_id=999,
        raw_source="hydration"
    )
    
    matches, reason = item_matches_monitor_filters(item, filters)
    assert matches is False
    assert reason == "wrong_brand"

def test_api_item_missing_brand_id_matching_brand_title_passes():
    # Nike monitor
    params = {
        "brand_ids[]": ["53"]
    }
    filters = extract_monitor_filters(params, monitor_name="Nike Shoes")
    
    # item has brand_id=None, brand="Nike", raw_source=None (API)
    item = VintedItem(
        id=126,
        title="Nike Shox",
        price=100.0,
        currency="PLN",
        brand="Nike",
        size="42",
        condition="New",
        photo_url="url",
        item_url="url",
        domain="vinted.pl",
        seller_id=1,
        brand_id=None,
        raw_source=None
    )
    
    matches, reason = item_matches_monitor_filters(item, filters)
    assert matches is True
    assert reason is None

def test_hydration_item_missing_brand_id_passes_without_monitor_name_if_search_text_matches():
    params = {
        "brand_ids[]": ["53"],
        "search_text": "Nike"
    }
    filters = extract_monitor_filters(params)
    
    item = VintedItem(
        id=127,
        title="Shoes",
        price=10.0,
        currency="EUR",
        brand="Nike",
        size="L",
        condition="New",
        photo_url="p",
        item_url="u",
        domain="v",
        seller_id=1,
        brand_id=None,
        raw_source="hydration"
    )
    
    matches, reason = item_matches_monitor_filters(item, filters)
    assert matches is True
    assert reason is None

def test_hydration_item_missing_brand_id_rejects_without_positive_brand_evidence():
    # No search_text, no monitor_name
    params = {
        "brand_ids[]": ["53"]
    }
    filters = extract_monitor_filters(params)
    
    item = VintedItem(
        id=128,
        title="Some Shoes",
        price=10.0,
        currency="EUR",
        brand="Some Brand",
        size="L",
        condition="New",
        photo_url="p",
        item_url="u",
        domain="v",
        seller_id=1,
        brand_id=None,
        raw_source="hydration"
    )
    
    matches, reason = item_matches_monitor_filters(item, filters)
    assert matches is False
    assert reason == MISSING_BRAND_ID_UNVERIFIED_SOURCE


def test_brand_filtered_unknown_brand_title_is_not_trusted_from_request_params():
    filters = extract_monitor_filters({"brand_ids[]": ["576107"]}, monitor_name="kapital")
    item = VintedItem(
        id=9062601700,
        title="Dante's Inferno Xbox 360",
        price=10.0,
        currency="EUR",
        brand="unknown",
        size="M",
        condition="Very good",
        photo_url="p",
        item_url="u",
        domain="vinted.de",
        seller_id=51023772,
        brand_id=None,
        raw_source="hydration",
    )

    assert item_matches_monitor_filters(item, filters) == (False, MISSING_BRAND_ID_UNVERIFIED_SOURCE)
