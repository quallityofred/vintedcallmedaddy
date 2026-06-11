from __future__ import annotations

from datetime import datetime
from typing import Any

from app.scraper.parser import VintedItem


def _string_value(value: Any) -> str:
    return str(value) if value is not None else ""


def build_found_item_values(
    *,
    monitor_id: int,
    item: VintedItem,
    found_at: datetime,
    notified: bool = False,
) -> dict[str, Any]:
    """Build values compatible with every non-null FoundItem column."""
    return {
        "monitor_id": int(monitor_id),
        "vinted_item_id": int(item.id),
        "domain": _string_value(item.domain),
        "title": _string_value(item.title),
        "price": float(item.price or 0.0),
        "currency": _string_value(item.currency),
        "brand": _string_value(item.brand),
        "brand_id": item.brand_id,
        "size": _string_value(item.size),
        "condition": _string_value(item.condition),
        # Empty means "no image". Telegram already treats it as text-only.
        "photo_url": _string_value(item.photo_url),
        "item_url": _string_value(item.item_url),
        "seller_id": int(item.seller_id or 0),
        "found_at": found_at,
        "notified": notified,
    }


def inspect_found_item_insert_readiness(item: Any) -> dict[str, bool]:
    """Return safe field-presence diagnostics without exposing item values."""
    photo_url = getattr(item, "photo_url", None)
    missing_photo = (
        not bool(photo_url)
        if photo_url is not None
        else not bool(getattr(item, "has_photo", False))
    )
    missing_title = not bool(getattr(item, "title", None))
    missing_url = not bool(
        getattr(item, "item_url", None) or getattr(item, "url", None)
    )
    missing_price = getattr(item, "price", None) is None
    missing_currency = not bool(getattr(item, "currency", None))
    return {
        "ready": not (
            missing_title or missing_url or missing_price or missing_currency
        ),
        "missing_photo_url": missing_photo,
        "missing_title": missing_title,
        "missing_url": missing_url,
        "missing_price": missing_price,
        "missing_currency": missing_currency,
        "would_fail_before_fix": missing_photo,
    }
