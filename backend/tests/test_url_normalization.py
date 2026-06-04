import pytest
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
