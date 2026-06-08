import pytest
from app.scraper.parser import VintedItem
from app.telegram.formatter import build_found_item_caption, build_found_item_keyboard

@pytest.fixture
def sample_item():
    return VintedItem(
        id=123,
        title="Nike Air Max Plus",
        price=45.0,
        currency="EUR",
        brand="Nike",
        size="43",
        condition="Very good",
        photo_url="http://photo.com",
        item_url="http://vinted.fr/items/123",
        domain="vinted.fr",
        seller_id=123456
    )

def test_build_found_item_caption(sample_item):
    caption = build_found_item_caption(sample_item, monitor_name="nike")
    
    assert "🆕 <b>NEW VINTED ITEM</b>" in caption
    assert "━━━━━━━━━━━━━━" in caption
    assert "🔎 <b>Monitor:</b> nike" in caption
    assert "👟 <b>Nike Air Max Plus</b>" in caption
    assert "💰 <b>Price:</b> 45 EUR" in caption
    assert "🏷 <b>Brand:</b> Nike" in caption
    assert "📏 <b>Size:</b> 43" in caption
    assert "✨ <b>Condition:</b> Very good" in caption
    assert "👤 <b>Seller ID:</b> 123456" in caption
    assert "🌍 <b>Source:</b> vinted.fr" in caption
    
    # Verify no raw URL
    assert "http://vinted.fr/items/123" not in caption

def test_build_found_item_keyboard(sample_item):
    keyboard = build_found_item_keyboard(sample_item)
    
    buttons = keyboard.inline_keyboard[0]
    assert len(buttons) == 2
    assert buttons[0].text == "Open on Vinted"
    assert buttons[0].url == sample_item.item_url
    assert buttons[1].text == "Hide seller"
    assert buttons[1].callback_data == "hide:123456"

def test_caption_omits_missing_fields(sample_item):
    sample_item.brand = None
    sample_item.size = ""
    caption = build_found_item_caption(sample_item)
    
    assert "🏷 <b>Brand:</b>" not in caption
    assert "📏 <b>Size:</b>" not in caption
    assert "✨ <b>Condition:</b> Very good" in caption

def test_caption_escapes_html(sample_item):
    sample_item.title = "Air & Max <Drop>"
    caption = build_found_item_caption(sample_item)
    
    # Title escaped
    assert "Air &amp; Max &lt;Drop&gt;" in caption
    # But tags for formatting are OK
    assert "<b>" in caption
    # Title should not contain unescaped < >
    assert "Air & Max <Drop>" not in caption
