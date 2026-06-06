import pytest
from app.scraper.hydration_parser import extract_next_f_chunks, extract_hydration_items

def test_extract_next_f_chunks_finds_multiple_chunks():
    html = 'self.__next_f.push([1,"chunk1"]); some stuff; self.__next_f.push([1,"chunk2"]);'
    chunks = extract_next_f_chunks(html)
    assert chunks == ["chunk1", "chunk2"]

def test_extract_hydration_items_from_items_items_payload():
    # Synthetic payload
    html = 'self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":123,\\\"title\\":\\\"Item 1\\\"},{\\"id\\":456,\\\"title\\":\\\"Item 2\\"}]}}"])'
    items = extract_hydration_items(html)
    assert len(items) == 2
    assert items[0]["id"] == "123"
    assert items[1]["id"] == "456"

def test_extract_hydration_items_preserves_order():
    html = 'self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":1},{\\"id\\":2}]}}"])'
    items = extract_hydration_items(html)
    assert [i["id"] for i in items] == ["1", "2"]

def test_extract_hydration_items_deduplicates_by_id():
    html = 'self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":1},{\\"id\\":1}]}}"])'
    items = extract_hydration_items(html)
    assert len(items) == 1

def test_extract_hydration_item_core_fields():
    html = 'self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":123,\\\"title\\":\\\"T\\\",\\\"brand_title\\":\\\"B\\\",\\\"path\\":\\\"/p\\\",\\\"price\\":{\\"amount\\":\\\"10\\\",\\\"currency_code\\":\\\"PLN\\\"},\\\"user\\":{\\"id\\":7,\\\"login\\":\\\"U\\\"}}]}}"])'
    items = extract_hydration_items(html)
    item = items[0]
    assert item["id"] == "123"
    assert item["title"] == "T"
    assert item["brand_title"] == "B"
    assert item["url"] == "https://www.vinted.pl/p"
    assert item["price"] == 10.0
    assert item["currency"] == "PLN"
    assert item["user_id"] == "7"
    assert item["user_login"] == "U"

def test_extract_hydration_item_builds_full_url():
    html = 'self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":1,\\\"path\\":\\\"/p\\\"}]}}"])'
    items = extract_hydration_items(html, domain="vinted.de")
    assert items[0]["url"] == "https://www.vinted.de/p"

def test_extract_hydration_item_tolerates_missing_optional_fields():
    html = 'self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":1,\\\"title\\":\\\"T\\"}]}}"])'
    items = extract_hydration_items(html)
    item = items[0]
    assert item["price"] == 0.0
    assert item["photo_url"] is None
    assert item["user_id"] is None

def test_extract_hydration_items_ignores_unrelated_chunks():
    html = 'self.__next_f.push([1,"unrelated"]); self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":1}]}}"])'
    items = extract_hydration_items(html)
    assert len(items) == 1

def test_parser_does_not_require_css_classes():
    # Only the script payload matters
    html = '<html><body><script>self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":1}]}}"])</script></body></html>'
    items = extract_hydration_items(html)
    assert len(items) == 1
