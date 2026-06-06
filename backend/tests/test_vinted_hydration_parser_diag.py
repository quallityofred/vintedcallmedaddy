import pytest
from app.scraper.hydration_parser import analyze_hydration_html

def test_analyze_hydration_html_no_chunks():
    html = "<html><body>No hydration here</body></html>"
    analysis = analyze_hydration_html(html)
    assert analysis["html_contains_next_f"] is False
    assert analysis["next_f_chunks"] == 0

def test_analyze_hydration_html_with_items():
    # Synthetic payload with items
    html = 'self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":123,\\"title\\":\\"Nike Shox\\",\\"brand_title\\":\\"Nike\\",\\"path\\":\\"p\\",\\"price\\":{\\"amount\\":\\"100\\",\\"currency_code\\":\\"PLN\\"}}],\\"total\\":1}}"])'
    analysis = analyze_hydration_html(html)
    assert analysis["html_contains_next_f"] is True
    assert analysis["next_f_chunks"] == 1
    assert analysis["chunks_with_item_text_markers"] >= 1
    assert analysis["candidate_item_objects_count"] >= 1
