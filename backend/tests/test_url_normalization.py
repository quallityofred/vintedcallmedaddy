import pytest

from app.scraper.monitor_filters import extract_monitor_filters, item_matches_monitor_filters
from app.scraper.parser import VintedItem, parse_response
from app.scraper.url_parser import parse_vinted_url, normalize_vinted_monitor_url

def test_parse_vinted_url_normalization():
    # Example 1: vinted.co.uk with page and time
    url1 = "https://www.vinted.co.uk/catalog?brand_ids[]=308270&page=1&time=1780601052"
    params1 = parse_vinted_url(url1)
    
    assert "page" not in params1
    assert "time" not in params1
    assert params1["order"] == "newest_first"
    assert params1["brand_ids[]"] == [308270]

    # Example 2: vinted.pl with dirty params and relevance order
    url2 = "https://www.vinted.pl/catalog?search_text=nike&search_by_image_uuid=&search_by_image_id=&catalog[]=5&page=1&time=1780535470&order=relevance"
    params2 = parse_vinted_url(url2)
    
    assert "page" not in params2
    assert "time" not in params2
    assert "search_by_image_uuid" not in params2
    assert "search_by_image_id" not in params2
    assert params2["order"] == "newest_first"
    assert params2["search_text"] == "nike"
    assert params2["catalog[]"] == [5]

def test_normalize_vinted_monitor_url():
    # Canonical order: order, scalar (sorted), array (sorted), other (sorted)
    
    # Example 1: Basic cleaning
    url1 = "https://www.vinted.co.uk/catalog?brand_ids[]=308270&page=1&time=1780601052"
    norm1 = normalize_vinted_monitor_url(url1)
    assert norm1 == "https://www.vinted.co.uk/catalog?order=newest_first&brand_ids[]=308270"

    # Example 2: Complex cleaning
    url2 = "https://www.vinted.pl/catalog?search_text=nike&search_by_image_uuid=&search_by_image_id=&catalog[]=5&page=1&time=1780535470&order=relevance"
    norm2 = normalize_vinted_monitor_url(url2)
    assert norm2 == "https://www.vinted.pl/catalog?order=newest_first&search_text=nike&catalog[]=5"

    # Example 3: Multiple array values and sorting
    url3 = "https://www.vinted.fr/catalog?brand_ids[]=2&brand_ids[]=1"
    norm3 = normalize_vinted_monitor_url(url3)
    assert norm3 == "https://www.vinted.fr/catalog?order=newest_first&brand_ids[]=1&brand_ids[]=2"

    # Example 4: Duplicate order params
    url4 = "https://www.vinted.fr/catalog?order=relevance&order=price_low_to_high"
    norm4 = normalize_vinted_monitor_url(url4)
    assert norm4 == "https://www.vinted.fr/catalog?order=newest_first"

    # Example 5: Invalid URL
    url5 = "not-a-url"
    assert normalize_vinted_monitor_url(url5) == "not-a-url"

    # Example 6: Cross-domain (different Vinted domain)
    url6 = "https://www.vinted.be/catalog?brand_ids[]=1"
    assert normalize_vinted_monitor_url(url6) == "https://www.vinted.be/catalog?order=newest_first&brand_ids[]=1"

def test_parse_vinted_url_preserves_arrays():
    url = "https://www.vinted.fr/catalog?brand_ids[]=1&brand_ids[]=2"
    params = parse_vinted_url(url)
    assert params["brand_ids[]"] == [1, 2]


def test_url_normalization_preserves_multiple_brand_ids():
    url = "https://www.vinted.fr/catalog?brand_ids[]=50&brand_ids[]=10&page=1&time=123"

    normalized = normalize_vinted_monitor_url(url)
    params = parse_vinted_url(normalized)

    assert normalized == "https://www.vinted.fr/catalog?order=newest_first&brand_ids[]=10&brand_ids[]=50"
    assert params["brand_ids[]"] == [10, 50]


def test_monitor_filter_extracts_brand_ids_aliases():
    filters = extract_monitor_filters({"brand_ids": ["10", 20], "order": "newest_first"})

    assert filters.brand_ids == frozenset({"10", "20"})
    assert "brand_ids" in filters.filter_keys


def test_item_filter_accepts_matching_brand_and_skips_wrong_brand():
    filters = extract_monitor_filters({"brand_ids[]": [123]})
    matching = VintedItem(
        id=1,
        title="Matching",
        price=1.0,
        currency="EUR",
        brand="Brand",
        size="",
        condition="",
        photo_url="",
        item_url="",
        domain="vinted.fr",
        seller_id=1,
        brand_id=123,
    )
    wrong = VintedItem(
        id=2,
        title="Wrong",
        price=1.0,
        currency="EUR",
        brand="Other",
        size="",
        condition="",
        photo_url="",
        item_url="",
        domain="vinted.fr",
        seller_id=2,
        brand_id=999,
    )

    assert item_matches_monitor_filters(matching, filters) == (True, None)
    assert item_matches_monitor_filters(wrong, filters) == (False, "wrong_brand")


def test_missing_brand_id_is_handled_safely_for_brand_monitor():
    filters = extract_monitor_filters({"brand_ids[]": [123]})
    item = VintedItem(
        id=3,
        title="Unknown Brand",
        price=1.0,
        currency="EUR",
        brand="",
        size="",
        condition="",
        photo_url="",
        item_url="",
        domain="vinted.fr",
        seller_id=3,
    )

    assert item_matches_monitor_filters(item, filters) == (False, "missing_brand_id")


def test_parse_response_extracts_brand_id():
    items = parse_response(
        {
            "items": [
                {
                    "id": 10,
                    "title": "Item",
                    "brand_id": "123",
                    "brand_title": "Brand",
                    "photo": {"url": "https://example.test/photo.jpg"},
                    "url": "https://www.vinted.fr/items/10",
                    "user": {"id": 7},
                    "price": {"amount": "12.50", "currency_code": "EUR"},
                }
            ]
        },
        "vinted.fr",
    )

    assert len(items) == 1
    assert items[0].brand_id == 123
