import pytest
from app.scraper.hydration_parser import extract_hydration_items

def test_extract_hydration_items_recursive_search():
    # Synthetic payload with items nested deeply, NOT in items.items[]
    html = 'self.__next_f.push([1,"{\\"some_root\\":{\\"data\\":{\\"items\\":[{\\"id\\":123,\\"title\\":\\"Nike Shox\\",\\"brand_title\\":\\"Nike\\",\\"path\\":\\"p\\",\\"price\\":{\\"amount\\":\\"100\\",\\"currency_code\\":\\"PLN\\"}}]}}"])'
    items = extract_hydration_items(html, domain="vinted.pl")
    
    assert len(items) == 1
    assert items[0]["id"] == "123"
    assert items[0]["title"] == "Nike Shox"

def test_extract_hydration_items_react_flight_escaped_text():
    # Synthetic payload with items in escaped string blocks
    html = 'self.__next_f.push([1,"{\\"other\\":\\"...\\"}"]); self.__next_f.push([1,"{\\"id\\":124,\\"title\\":\\"Adidas Shoes\\",\\"brand_title\\":\\"Adidas\\",\\"path\\":\\"a\\",\\"price\\":{\\"amount\\":\\"50\\",\\"currency_code\\":\\"PLN\\"}}"])'
    items = extract_hydration_items(html, domain="vinted.pl")
    
    assert len(items) == 1
    assert items[0]["id"] == "124"
    assert items[0]["title"] == "Adidas Shoes"
