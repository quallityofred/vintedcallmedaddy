import pytest
from app.scraper.catalog_ssr_parser import parse_catalog_ssr_html

def test_ssr_parser_extracts_item_id_url_title_price_currency_photo():
    html = """
    <div data-testid="item-card">
        <a href="/items/12345-nike-shoes?referrer=catalog">
            <img src="https://images1.vinted.net/t/05_01851.webp">
        </a>
        <div data-testid="item-title">Nike Air Max</div>
        <div data-testid="item-price">250,00 PLN</div>
    </div>
    """
    items = parse_catalog_ssr_html(html)
    assert len(items) == 1
    assert items[0]["id"] == "12345"
    assert items[0]["title"] == "Nike Air Max"
    assert items[0]["price"] == 250.0
    assert items[0]["currency"] == "PLN"
    assert items[0]["url"] == "https://www.vinted.pl/items/12345-nike-shoes?referrer=catalog"
    assert items[0]["photo_url"] == "https://images1.vinted.net/t/05_01851.webp"

def test_ssr_parser_handles_missing_photo_without_dropping_item():
    html = """
    <div data-testid="item-card">
        <a href="/items/67890-nike-shoes?referrer=catalog">
        </a>
        <div data-testid="item-title">Nike Air Max</div>
        <div data-testid="item-price">250,00 PLN</div>
    </div>
    """
    items = parse_catalog_ssr_html(html)
    assert len(items) == 1
    assert items[0]["id"] == "67890"
    assert items[0]["photo_url"] == ""

def test_ssr_parser_preserves_order():
    html = """
    <div data-testid="item-card">
        <a href="/items/1-a"></a>
    </div>
    <div data-testid="item-card">
        <a href="/items/2-b"></a>
    </div>
    """
    items = parse_catalog_ssr_html(html)
    assert len(items) == 2
    assert items[0]["id"] == "1"
    assert items[1]["id"] == "2"
