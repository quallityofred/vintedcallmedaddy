from decimal import Decimal

from app.pricing.currency import convert_to_usd, format_price_with_usd, parse_amount


def test_pln_converts_to_usd_in_formatted_text():
    assert format_price_with_usd(39, "PLN") == "39 PLN (~$10.00)"


def test_eur_converts_to_usd_in_formatted_text():
    assert format_price_with_usd(18, "EUR") == "18 EUR (~$19.62)"


def test_gbp_converts_to_usd_in_formatted_text():
    assert format_price_with_usd(16.45, "GBP") == "16.45 GBP (~$20.89)"


def test_usd_displays_without_duplicate_conversion():
    assert format_price_with_usd(10, "USD") == "10 USD"


def test_unknown_currency_falls_back_to_original():
    assert format_price_with_usd(39, "XYZ") == "39 XYZ"


def test_missing_currency_falls_back_safely():
    assert format_price_with_usd(39, None) == "39"


def test_missing_amount_returns_not_listed():
    assert format_price_with_usd(None, "PLN") == "Not listed"


def test_malformed_amount_does_not_crash():
    assert format_price_with_usd("not-a-price", "PLN") == "Not listed"


def test_comma_decimal_string_is_handled():
    assert parse_amount("39,99") == Decimal("39.99")
    assert format_price_with_usd("39,99", "PLN") == "39.99 PLN (~$10.25)"


def test_zero_and_negative_amounts_are_not_listed():
    assert format_price_with_usd(0, "PLN") == "Not listed"
    assert format_price_with_usd(-1, "PLN") == "Not listed"


def test_convert_to_usd_returns_none_for_unknown_currency():
    assert convert_to_usd(Decimal("10"), "XYZ") is None
