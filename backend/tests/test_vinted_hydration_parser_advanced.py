import json

from app.scraper.hydration_parser import _normalize_items, extract_hydration_items


def _flight_chunk(chunk: str) -> str:
    return 'self.__next_f.push([1,"{}"])'.format(chunk.replace('"', '\\"'))


def _sequence(
    *,
    path: str,
    title: str | None = "Nike Shoe",
    brand: str | None = "Nike",
    amount: str | None = "64",
    currency: str | None = "EUR",
    generic_id: str = "3160891502",
) -> str:
    fields = [f'"id":{generic_id}']
    if title is not None:
        fields.append(f'"title":"{title}"')
    if brand is not None:
        fields.append(f'"brand_title":"{brand}"')
    fields.append(f'"path":"{path}"')
    if amount is not None:
        fields.append(f'"amount":"{amount}"')
    if currency is not None:
        fields.append(f'"currency_code":"{currency}"')
    return ",".join(fields)


def test_extract_hydration_items_recursive_search():
    data = {
        "id": 123,
        "title": "Nike Shox",
        "brand_title": "Nike",
        "path": "p",
        "price": {"amount": "100", "currency_code": "PLN"},
    }
    payload = json.dumps(data)
    html = 'self.__next_f.push([1,"{}"])'.format(payload.replace('"', '\\"'))
    items = extract_hydration_items(html, domain="vinted.pl")

    assert len(items) == 1
    assert items[0]["id"] == "123"
    assert items[0]["title"] == "Nike Shox"


def test_extract_hydration_items_react_flight_escaped_text():
    html = (
        'self.__next_f.push([1,"{\\"other\\":\\"...\\"}"]); '
        'self.__next_f.push([1,"{\\"id\\":124,\\"title\\":\\"Adidas Shoes\\",'
        '\\"brand_title\\":\\"Adidas\\",\\"path\\":\\"a\\",'
        '\\"price\\":{\\"amount\\":\\"50\\",\\"currency_code\\":\\"PLN\\"}}"] )'
    ).replace('"] )', '"])')
    items = extract_hydration_items(html, domain="vinted.pl")

    assert len(items) == 1
    assert items[0]["id"] == "124"
    assert items[0]["title"] == "Adidas Shoes"


def test_field_sequence_uses_item_id_from_path():
    html = _flight_chunk(
        _sequence(path="/items/9106911726-nike-sb-dunk", generic_id="3160891502")
    )

    items = extract_hydration_items(html)

    assert [item["id"] for item in items] == ["9106911726"]
    assert items[0]["url"].endswith("/items/9106911726-nike-sb-dunk")


def test_field_sequence_ignores_generic_id_mismatch():
    diagnostics = {}
    html = _flight_chunk(
        _sequence(path="/items/9106911726-nike-sb-dunk", generic_id="3160891502")
    )

    items = extract_hydration_items(html, diagnostics=diagnostics)

    assert len(items) == 1
    assert diagnostics["field_sequence_rejections"]["generic_id_mismatch_ignored"] == 1


def test_field_sequence_deduplicates_by_path_id():
    record = _sequence(path="/items/123-nike-shoe")
    diagnostics = {}

    items = extract_hydration_items(
        _flight_chunk(f"{record},{record}"),
        diagnostics=diagnostics,
    )

    assert len(items) == 1
    assert diagnostics["field_sequence_rejections"]["duplicate_path_id"] == 1


def test_field_sequence_deduplicates_by_url():
    first = _sequence(
        path="https://www.vinted.pl/items/123-nike-shoe",
        generic_id="1",
    )
    second = _sequence(
        path="https://www.vinted.pl/items/123-nike-shoe",
        generic_id="2",
    )

    items = extract_hydration_items(_flight_chunk(f"{first},{second}"))

    assert len(items) == 1
    assert items[0]["id"] == "123"


def test_field_sequence_rejects_path_only_false_positive():
    items = extract_hydration_items(_flight_chunk('"path":"/items/123-no-fields"'))
    assert items == []


def test_field_sequence_rejects_missing_brand():
    html = _flight_chunk(_sequence(path="/items/123-no-brand", brand=None))
    assert extract_hydration_items(html) == []


def test_field_sequence_rejects_missing_price():
    html = _flight_chunk(
        _sequence(path="/items/123-no-price", amount=None, currency=None)
    )
    assert extract_hydration_items(html) == []


def test_field_sequence_rejects_missing_currency():
    html = _flight_chunk(
        _sequence(path="/items/123-no-currency", currency=None)
    )
    assert extract_hydration_items(html) == []


def test_field_sequence_malformed_amount_does_not_crash():
    html = _flight_chunk(
        _sequence(path="/items/123-bad-price", amount="not-a-number")
    )
    assert extract_hydration_items(html) == []


def test_field_sequence_rejects_unknown_title_when_no_real_title():
    html = _flight_chunk(_sequence(path="/items/123-unknown", title="Unknown"))
    assert extract_hydration_items(html) == []


def test_field_sequence_extracts_real_like_nike_shoe_record():
    html = _flight_chunk(
        _sequence(
            path="/items/9106911084-nike-air-max-95",
            title="Nike Air max 95",
            brand="Nike",
            amount="64",
            currency="EUR",
        )
    )

    items = extract_hydration_items(html)

    assert items == [{
        "id": "9106911084",
        "title": "Nike Air max 95",
        "brand_title": "Nike",
        "url": "https://www.vinted.pl/items/9106911084-nike-air-max-95",
        "path": "/items/9106911084-nike-air-max-95",
        "price": 64.0,
        "currency": "EUR",
        "photo_url": "",
        "listed_at": None,
        "timestamp_source": None,
        "user_id": None,
        "user_login": None,
        "raw_source": "hydration",
    }]


def test_field_sequence_extracts_multiple_records_in_order():
    first = _sequence(path="/items/101-first", title="First")
    second = _sequence(path="/items/202-second", title="Second")

    items = extract_hydration_items(_flight_chunk(f"{first},{second}"))

    assert [item["id"] for item in items] == ["101", "202"]
    assert [item["title"] for item in items] == ["First", "Second"]


def test_existing_json_object_parser_still_works():
    payload = {
        "id": 77,
        "title": "Structured",
        "brand_title": "Nike",
        "path": "/items/77-structured",
        "price": {"amount": "12", "currency_code": "EUR"},
    }

    items = extract_hydration_items(_flight_chunk(json.dumps(payload)))

    assert len(items) == 1
    assert items[0]["id"] == "77"


def test_normalizer_prefers_path_id_over_generic_id():
    items = _normalize_items([{
        "id": "999",
        "title": "Canonical",
        "brand_title": "Nike",
        "path": "/items/123-canonical",
        "price": {"amount": "10", "currency_code": "EUR"},
    }], "vinted.pl")

    assert items[0]["id"] == "123"


def test_normalizer_rejects_id_path_mismatch_or_canonicalizes_consistently():
    items = _normalize_items([
        {
            "id": "999",
            "title": "First",
            "brand_title": "Nike",
            "path": "/items/123-canonical",
            "price": {"amount": "10", "currency_code": "EUR"},
        },
        {
            "id": "123",
            "title": "Duplicate",
            "brand_title": "Nike",
            "path": "/items/123-canonical",
            "price": {"amount": "10", "currency_code": "EUR"},
        },
    ], "vinted.pl")

    assert len(items) == 1
    assert items[0]["id"] == "123"
