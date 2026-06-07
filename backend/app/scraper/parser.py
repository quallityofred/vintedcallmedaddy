# app/scraper/parser.py
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

PROMOTED_BADGE_KEYWORDS = {"promoted", "showcase"}


@dataclass
class VintedItem:
    id: int
    title: str
    price: float
    currency: str
    brand: str
    size: str
    condition: str
    photo_url: str
    item_url: str
    domain: str
    seller_id: int
    brand_id: int | None = None
    raw_source: str | None = None


@dataclass(frozen=True)
class VintedItemDetail:
    item_id: int
    listed_at: datetime | None = None
    catalog_ids: frozenset[str] = frozenset()
    category_ids: frozenset[str] = frozenset()


def _is_promoted_item(item: dict) -> bool:
    if item.get("is_promoted") is True:
        return True
    if item.get("promotion_level", 0) > 0:
        return True
    if item.get("content_source") == "showcase":
        return True
    if item.get("item_type") == "showcase":
        return True

    badge = item.get("badge", "")
    if isinstance(badge, str) and badge.lower() in PROMOTED_BADGE_KEYWORDS:
        return True

    return False


def _extract_photo(item: dict) -> str:
    photos = item.get("photos")
    if isinstance(photos, list) and len(photos) > 0:
        first_photo = photos[0]
        if isinstance(first_photo, dict):
            return str(
                first_photo.get("url") or first_photo.get("full_size_url") or ""
            )
    photo = item.get("photo")
    if isinstance(photo, dict):
        return str(photo.get("full_size_url") or photo.get("url") or "")
    return ""


def _extract_price(item: dict) -> tuple[float, str]:
    price_data = item.get("price")
    if isinstance(price_data, dict):
        amount = float(price_data.get("amount", 0))
        currency_code = str(price_data.get("currency_code", "EUR"))
        return amount, currency_code
    if isinstance(price_data, (int, float, str)):
        return float(price_data), "EUR"
    return 0.0, "EUR"


def _extract_brand_id(item: dict) -> int | None:
    candidates = [
        item.get("brand_id"),
        item.get("brand_title_id"),
        item.get("brand", {}).get("id") if isinstance(item.get("brand"), dict) else None,
        item.get("brand_dto", {}).get("id") if isinstance(item.get("brand_dto"), dict) else None,
        item.get("brand_details", {}).get("id") if isinstance(item.get("brand_details"), dict) else None,
    ]
    for candidate in candidates:
        try:
            if candidate is not None and str(candidate).strip():
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            # Vinted timestamps are usually seconds. Treat very large values as ms.
            timestamp = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return _parse_datetime(int(text))
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _walk_values(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_values(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_values(value)


def _extract_detail_time(item: dict) -> datetime | None:
    preferred_keys = (
        "created_at",
        "created_at_ts",
        "listed_at",
        "uploaded_at",
        "publication_date",
        "published_at",
    )
    for key in preferred_keys:
        parsed = _parse_datetime(item.get(key))
        if parsed:
            return parsed

    for obj in _walk_values(item):
        for key, value in obj.items():
            key_text = str(key).lower()
            if any(token in key_text for token in ("created", "listed", "uploaded", "published")):
                parsed = _parse_datetime(value)
                if parsed:
                    return parsed
    return None


def _extract_int_id(value: Any) -> str | None:
    try:
        if value is not None and str(value).strip():
            return str(int(value))
    except (TypeError, ValueError):
        return None
    return None


def _extract_detail_category_ids(item: dict) -> tuple[frozenset[str], frozenset[str]]:
    catalog_ids: set[str] = set()
    category_ids: set[str] = set()

    for key in ("catalog_id", "catalog_ids"):
        values = item.get(key)
        if not isinstance(values, list):
            values = [values]
        for value in values:
            parsed = _extract_int_id(value)
            if parsed:
                catalog_ids.add(parsed)

    for key in ("category_id", "category_ids"):
        values = item.get(key)
        if not isinstance(values, list):
            values = [values]
        for value in values:
            parsed = _extract_int_id(value)
            if parsed:
                category_ids.add(parsed)

    for obj in _walk_values(item):
        if not isinstance(obj, dict):
            continue
        for key, value in obj.items():
            key_text = str(key).lower()
            if key_text == "id":
                continue
            if any(token in key_text for token in ("catalog", "category", "breadcrumb")):
                if isinstance(value, dict):
                    parsed = _extract_int_id(value.get("id"))
                    if parsed:
                        if "catalog" in key_text:
                            catalog_ids.add(parsed)
                        else:
                            category_ids.add(parsed)
                elif isinstance(value, list):
                    for entry in value:
                        if isinstance(entry, dict):
                            parsed = _extract_int_id(entry.get("id"))
                        else:
                            parsed = _extract_int_id(entry)
                        if parsed:
                            if "catalog" in key_text:
                                catalog_ids.add(parsed)
                            else:
                                category_ids.add(parsed)
                else:
                    parsed = _extract_int_id(value)
                    if parsed:
                        if "catalog" in key_text:
                            catalog_ids.add(parsed)
                        else:
                            category_ids.add(parsed)

    return frozenset(catalog_ids), frozenset(category_ids)


def parse_item_detail(data: dict, item_id: int) -> VintedItemDetail:
    item = data.get("item", data) if isinstance(data, dict) else {}
    if not isinstance(item, dict):
        item = {}
    catalog_ids, category_ids = _extract_detail_category_ids(item)
    return VintedItemDetail(
        item_id=item_id,
        listed_at=_extract_detail_time(item),
        catalog_ids=catalog_ids,
        category_ids=category_ids,
    )


def parse_response(data: dict, domain: str) -> list[VintedItem]:
    items: list[VintedItem] = []
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        return items

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        if _is_promoted_item(item):
            continue

        try:
            item_id = int(item.get("id", 0))
            title = str(item.get("title", ""))
            price, currency = _extract_price(item)
            brand = str(item.get("brand_title", item.get("brand", "")))
            brand_id = _extract_brand_id(item)
            size = str(item.get("size_title", item.get("size", "")))
            condition = str(item.get("status_title", item.get("status", "")))
            photo_url = _extract_photo(item)
            item_url = f"https://www.{domain}/items/{item_id}"
            seller_id = int(item.get("user", {}).get("id", 0))

            items.append(
                VintedItem(
                    id=item_id,
                    title=title,
                    price=price,
                    currency=currency,
                    brand=brand,
                    size=size,
                    condition=condition,
                    photo_url=photo_url,
                    item_url=item_url,
                    domain=domain,
                    seller_id=seller_id,
                    brand_id=brand_id,
                )
            )
        except Exception:
            logger.exception("Failed to parse item from domain=%s", domain)
            continue

    return items
