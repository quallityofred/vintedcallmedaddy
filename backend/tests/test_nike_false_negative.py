import pytest
from unittest.mock import MagicMock, patch
from app.scraper.parser import VintedItem
from app.scraper.monitor_filters import MonitorFilters, item_matches_monitor_filters

def test_nike_brand_id_missing_lenient_match():
    # Item with brand_title "Nike" but brand_id None (common in summary API)
    item = VintedItem(
        id=123,
        title="Nike Shoes",
        price=10.0,
        currency="PLN",
        brand="Nike",
        size="43",
        condition="New",
        photo_url="url",
        item_url="url",
        domain="vinted.pl",
        seller_id=1,
        brand_id=None # MISSING ID
    )
    
    # Filter looking for Nike (id 53)
    filters = MonitorFilters(
        brand_ids=frozenset(["53"]),
        catalog_ids=frozenset(),
        size_ids=frozenset(),
        status_ids=frozenset(),
        color_ids=frozenset(),
        price_from=None,
        price_to=None,
        search_text=None,
        order=None
    )
    
    # Should match because we are lenient on missing brand_id
    matches, reason = item_matches_monitor_filters(item, filters)
    assert matches is True
    assert reason is None

def test_wrong_brand_id_still_filtered():
    # Item with brand_id 999 (Not Nike)
    item = VintedItem(
        id=123,
        title="Adidas Shoes",
        price=10.0,
        currency="PLN",
        brand="Adidas",
        size="43",
        condition="New",
        photo_url="url",
        item_url="url",
        domain="vinted.pl",
        seller_id=1,
        brand_id=999 # WRONG ID
    )
    
    # Filter looking for Nike (id 53)
    filters = MonitorFilters(
        brand_ids=frozenset(["53"]),
        catalog_ids=frozenset(),
        size_ids=frozenset(),
        status_ids=frozenset(),
        color_ids=frozenset(),
        price_from=None,
        price_to=None,
        search_text=None,
        order=None
    )
    
    # Should NOT match
    matches, reason = item_matches_monitor_filters(item, filters)
    assert matches is False
    assert reason == "wrong_brand"

def test_unfiltered_monitor_still_matches():
    item = VintedItem(
        id=123,
        title="Random Item",
        price=10.0,
        currency="PLN",
        brand="Random",
        size="L",
        condition="Good",
        photo_url="url",
        item_url="url",
        domain="vinted.pl",
        seller_id=1,
        brand_id=None
    )
    
    # No brand filters
    filters = MonitorFilters(
        brand_ids=frozenset(),
        catalog_ids=frozenset(),
        size_ids=frozenset(),
        status_ids=frozenset(),
        color_ids=frozenset(),
        price_from=None,
        price_to=None,
        search_text=None,
        order=None
    )
    
    matches, reason = item_matches_monitor_filters(item, filters)
    assert matches is True
    assert reason is None
