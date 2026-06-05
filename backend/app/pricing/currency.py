from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


STATIC_USD_RATES: dict[str, Decimal] = {
    "USD": Decimal("1"),
    "PLN": Decimal("0.2564"),
    "EUR": Decimal("1.09"),
    "GBP": Decimal("1.27"),
    "SEK": Decimal("0.095"),
    "DKK": Decimal("0.146"),
    "CZK": Decimal("0.044"),
    "HUF": Decimal("0.0028"),
    "RON": Decimal("0.219"),
    "BGN": Decimal("0.557"),
}


def parse_amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        elif "," in text and "." in text:
            text = text.replace(",", "")
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
    return None


def convert_to_usd(amount: Decimal, currency: str) -> Decimal | None:
    rate = STATIC_USD_RATES.get(currency.strip().upper())
    if rate is None:
        return None
    return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _format_amount(amount: Decimal) -> str:
    normalized = amount.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def format_price_with_usd(price: Any, currency: str | None) -> str:
    amount = parse_amount(price)
    if amount is None or not amount.is_finite() or amount <= 0:
        return "Not listed"

    currency_code = str(currency or "").strip().upper()
    original = _format_amount(amount)
    if not currency_code:
        return original

    original_with_currency = f"{original} {currency_code}".strip()
    if currency_code == "USD":
        return original_with_currency

    usd_amount = convert_to_usd(amount, currency_code)
    if usd_amount is None:
        return original_with_currency

    return f"{original_with_currency} (~${usd_amount:.2f})"
