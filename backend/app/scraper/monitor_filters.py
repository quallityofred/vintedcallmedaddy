from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.scraper.parser import VintedItem


ARRAY_PARAM_ALIASES = {
    "brand_ids": ("brand_ids[]", "brand_ids"),
    "catalog_ids": ("catalog[]", "catalog_ids", "catalog_ids[]"),
    "size_ids": ("size_ids[]", "size_ids"),
    "status_ids": ("status_ids[]", "status_ids"),
    "color_ids": ("color_ids[]", "color_ids"),
    "gender_ids": ("gender_ids[]", "gender_ids"),
}

MISSING_BRAND_ID_UNVERIFIED_SOURCE = "missing_brand_id_unverified_source"
_UNKNOWN_BRAND_TOKENS = {
    "",
    "unknown",
    "none",
    "null",
    "n/a",
    "na",
    "no brand",
    "no-brand",
    "unbranded",
    "brand unknown",
}


@dataclass(frozen=True)
class MonitorFilters:
    brand_ids: frozenset[str]
    catalog_ids: frozenset[str]
    size_ids: frozenset[str]
    status_ids: frozenset[str]
    color_ids: frozenset[str]
    price_from: str | None
    price_to: str | None
    search_text: str | None
    order: str | None
    gender_ids: frozenset[str] = frozenset()
    allowed_brand_names: frozenset[str] = frozenset()

    @property
    def filter_keys(self) -> list[str]:
        keys: list[str] = []
        for key in ("brand_ids", "catalog_ids", "size_ids", "status_ids", "color_ids", "gender_ids"):
            if getattr(self, key):
                keys.append(key)
        for key in ("price_from", "price_to", "search_text", "order"):
            if getattr(self, key) is not None:
                keys.append(key)
        return keys


def _as_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _string_set_from_aliases(params: dict[str, Any], aliases: tuple[str, ...]) -> frozenset[str]:
    values: set[str] = set()
    for alias in aliases:
        for value in _as_values(params.get(alias)):
            text = str(value).strip()
            if text:
                values.add(text)
    return frozenset(values)


def extract_monitor_filters(params: dict[str, Any], monitor_name: str | None = None) -> MonitorFilters:
    brand_names: set[str] = set()
    
    # Extract brand names from search_text if present
    search_text = params.get("search_text")
    if search_text:
        brand_names.add(str(search_text).strip().lower())
        
    # Extract brand names from monitor_name if present
    if monitor_name:
        # Simple heuristic: treat each word in monitor name as a potential brand name
        for word in re.findall(r"\w+", monitor_name):
            if len(word) > 2:
                brand_names.add(word.lower())

    return MonitorFilters(
        brand_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["brand_ids"]),
        catalog_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["catalog_ids"]),
        size_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["size_ids"]),
        status_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["status_ids"]),
        color_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["color_ids"]),
        gender_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["gender_ids"]),
        price_from=str(params["price_from"]).strip() if params.get("price_from") not in (None, "") else None,
        price_to=str(params["price_to"]).strip() if params.get("price_to") not in (None, "") else None,
        search_text=str(params["search_text"]).strip() if params.get("search_text") not in (None, "") else None,
        order=str(params["order"]).strip() if params.get("order") not in (None, "") else None,
        allowed_brand_names=frozenset(brand_names),
    )


def normalize_brand_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def has_positive_brand_text(value: str | None) -> bool:
    return normalize_brand_text(value) not in _UNKNOWN_BRAND_TOKENS


def brand_text_matches_allowed(value: str | None, allowed_names: frozenset[str]) -> bool:
    item_brand = normalize_brand_text(value)
    if not item_brand or not has_positive_brand_text(item_brand):
        return False
    for allowed in allowed_names:
        allowed_brand = normalize_brand_text(allowed)
        if not allowed_brand or allowed_brand in _UNKNOWN_BRAND_TOKENS:
            continue
        if item_brand == allowed_brand:
            return True
        if len(allowed_brand) >= 4 and (allowed_brand in item_brand or item_brand in allowed_brand):
            return True
    return False


def item_matches_monitor_filters(item: VintedItem, filters: MonitorFilters) -> tuple[bool, str | None]:
    if filters.brand_ids:
        if item.brand_id is not None:
            if str(item.brand_id) not in filters.brand_ids:
                return False, "wrong_brand"
            return True, None

        if not has_positive_brand_text(item.brand):
            return False, MISSING_BRAND_ID_UNVERIFIED_SOURCE
        if not filters.allowed_brand_names:
            return False, MISSING_BRAND_ID_UNVERIFIED_SOURCE
        if brand_text_matches_allowed(item.brand, filters.allowed_brand_names):
            return True, None
        return False, "wrong_brand"
    return True, None


def has_restrictive_filters(filters: MonitorFilters) -> bool:
    return bool(
        filters.brand_ids
        or filters.catalog_ids
        or filters.size_ids
        or filters.status_ids
        or filters.color_ids
        or filters.gender_ids
        or filters.price_from is not None
        or filters.price_to is not None
        or filters.search_text is not None
    )
