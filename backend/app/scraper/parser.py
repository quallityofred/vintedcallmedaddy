# app/scraper/parser.py
import logging
from dataclasses import dataclass

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
            return first_photo.get("url", first_photo.get("full_size_url", ""))
    photo = item.get("photo")
    if isinstance(photo, dict):
        return photo.get("full_size_url", photo.get("url", ""))
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
        item.get("brand", {}).get("id") if isinstance(item.get("brand"), dict) else None,
    ]
    for candidate in candidates:
        try:
            if candidate is not None and str(candidate).strip():
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


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
