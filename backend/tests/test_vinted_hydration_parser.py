import json

from app.scraper.hydration_parser import extract_hydration_items, extract_next_f_chunks


def _hydration_html(payload: object) -> str:
    encoded = json.dumps(payload, separators=(",", ":")).replace('"', '\\"')
    return f'self.__next_f.push([1,"{encoded}"])'


def _structured_item(item_id: int, title: str) -> dict:
    return {
        "id": item_id,
        "title": title,
        "brand_title": "Brand",
        "path": f"/items/{item_id}-{title.lower().replace(' ', '-')}",
        "price": {"amount": "10", "currency_code": "EUR"},
    }


def test_extract_next_f_chunks_finds_multiple_chunks():
    html = 'self.__next_f.push([1,"chunk1"]); some stuff; self.__next_f.push([1,"chunk2"]);'
    chunks = extract_next_f_chunks(html)
    assert chunks == ["chunk1", "chunk2"]


def test_extract_hydration_items_from_items_items_payload():
    html = _hydration_html({"items": {"items": [_structured_item(123, "Item 1"), _structured_item(456, "Item 2")]}})
    items = extract_hydration_items(html)
    assert len(items) == 2
    assert items[0]["id"] == "123"
    assert items[1]["id"] == "456"


def test_extract_hydration_items_preserves_order():
    html = _hydration_html({"items": {"items": [_structured_item(1, "One"), _structured_item(2, "Two")]}})
    items = extract_hydration_items(html)
    assert [item["id"] for item in items] == ["1", "2"]


def test_extract_hydration_items_deduplicates_by_id():
    item = _structured_item(1, "One")
    html = _hydration_html({"items": {"items": [item, item]}})
    items = extract_hydration_items(html)
    assert len(items) == 1


def test_extract_hydration_item_core_fields():
    item = _structured_item(123, "T")
    item["brand_title"] = "B"
    item["path"] = "/p"
    item["price"] = {"amount": "10", "currency_code": "PLN"}
    item["user"] = {"id": 7, "login": "U"}
    items = extract_hydration_items(_hydration_html({"items": {"items": [item]}}))
    normalized = items[0]
    assert normalized["id"] == "123"
    assert normalized["title"] == "T"
    assert normalized["brand_title"] == "B"
    assert normalized["url"] == "https://www.vinted.pl/p"
    assert normalized["price"] == 10.0
    assert normalized["currency"] == "PLN"
    assert normalized["user_id"] == "7"
    assert normalized["user_login"] == "U"


def test_extract_hydration_item_builds_full_url():
    item = _structured_item(1, "T")
    item["path"] = "/p"
    items = extract_hydration_items(_hydration_html({"items": {"items": [item]}}), domain="vinted.de")
    assert items[0]["url"] == "https://www.vinted.de/p"


def test_extract_hydration_item_tolerates_missing_optional_fields():
    item = _structured_item(1, "T")
    item.pop("price")
    items = extract_hydration_items(_hydration_html({"items": {"items": [item]}}))
    normalized = items[0]
    assert normalized["price"] == 0.0
    assert normalized["photo_url"] == ""
    assert normalized["user_id"] is None


def test_hydration_field_diagnostics_reports_missing_photo():
    diagnostics = {}
    items = extract_hydration_items(
        _hydration_html({"items": {"items": [_structured_item(101, "No photo")]}}),
        diagnostics=diagnostics,
    )

    assert items[0]["photo_url"] == ""
    fields = diagnostics["item_field_diagnostics"]
    assert fields["sampled_items"] == 1
    assert fields["photo_url_present"] == 0
    assert fields["photo_url_missing"] == 1


def test_hydration_field_diagnostics_reports_supported_photo_shapes():
    direct = _structured_item(102, "Direct photo")
    direct["photo_url"] = "https://images.example/direct.jpg"
    nested = _structured_item(103, "Nested photo")
    nested["photo"] = {"high_resolution": {"url": "https://images.example/high.jpg"}}
    diagnostics = {}

    items = extract_hydration_items(
        _hydration_html({"items": {"items": [direct, nested]}}),
        diagnostics=diagnostics,
    )

    assert all(item["photo_url"] for item in items)
    fields = diagnostics["item_field_diagnostics"]
    assert fields["photo_url_present"] == 2
    assert fields["photo_field_presence"]["direct.photo_url"] == 1
    assert fields["photo_field_presence"]["photo.high_resolution.url"] == 1


def test_hydration_field_diagnostics_reports_timestamp_presence_when_available():
    item = _structured_item(104, "Timestamped")
    item["listed_at"] = "2026-06-07T12:34:56Z"
    diagnostics = {}

    items = extract_hydration_items(
        _hydration_html({"items": {"items": [item]}}),
        diagnostics=diagnostics,
    )

    assert items[0]["listed_at"] == "2026-06-07T12:34:56+00:00"
    assert items[0]["timestamp_source"] == "listed_at"
    fields = diagnostics["item_field_diagnostics"]
    assert fields["timestamp_field_presence"]["listed_at"] == 1
    assert fields["timestamp_parsed"] == 1


def test_hydration_field_diagnostics_does_not_expose_raw_payload():
    secret_title = "sensitive synthetic title"
    image_url = "https://images.example/private-looking-path.jpg"
    item = _structured_item(105, secret_title)
    item["photo"] = {"url": image_url}
    diagnostics = {}

    extract_hydration_items(
        _hydration_html({"items": {"items": [item]}}),
        diagnostics=diagnostics,
    )

    serialized = json.dumps(diagnostics)
    assert secret_title not in serialized
    assert image_url not in serialized
    assert "private-looking-path" not in serialized


def test_extract_hydration_items_ignores_unrelated_chunks():
    html = 'self.__next_f.push([1,"unrelated"]); ' + _hydration_html({"items": {"items": [_structured_item(1, "T")]}})
    items = extract_hydration_items(html)
    assert len(items) == 1


def test_parser_does_not_require_css_classes():
    html = f'<html><body><script>{_hydration_html({"items": {"items": [_structured_item(1, "T")]}})}</script></body></html>'
    items = extract_hydration_items(html)
    assert len(items) == 1
