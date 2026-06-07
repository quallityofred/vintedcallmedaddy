import pytest
from app.scraper.catalog_ssr_parser import parse_catalog_ssr_photo_map

def test_ssr_photo_map_extracts_item_id_to_photo():
    html = """
    <div class="feed-grid__item">
        <a href="/items/12345-nike-shoes">
            <img src="https://images1.vinted.net/t/05_01851.webp">
        </a>
    </div>
    """
    photo_map = parse_catalog_ssr_photo_map(html)
    assert len(photo_map) == 1
    assert photo_map["12345"] == "https://images1.vinted.net/t/05_01851.webp"

def test_ssr_photo_map_deduplicates_by_item_id():
    html = """
    <div class="feed-grid__item">
        <a href="/items/1-a">
            <img src="https://images1.vinted.net/1.webp">
        </a>
    </div>
    <div class="feed-grid__item">
        <a href="/items/1-a">
            <img src="https://images1.vinted.net/1.webp">
        </a>
    </div>
    """
    photo_map = parse_catalog_ssr_photo_map(html)
    assert len(photo_map) == 1
    assert photo_map["1"] == "https://images1.vinted.net/1.webp"

def test_ssr_photo_map_requires_same_card_photo():
    html = """
    <div class="feed-grid__item">
        <a href="/items/1-a"></a>
    </div>
    <img src="https://images1.vinted.net/unrelated.webp">
    """
    photo_map = parse_catalog_ssr_photo_map(html)
    assert len(photo_map) == 0
    assert "1" not in photo_map
