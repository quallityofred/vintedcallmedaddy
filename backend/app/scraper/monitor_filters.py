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


def item_matches_monitor_filters(item: VintedItem, filters: MonitorFilters) -> tuple[bool, str | None]:
    if filters.brand_ids:
        if item.brand_id is not None:
            if str(item.brand_id) not in filters.brand_ids:
                return False, "wrong_brand"
        elif item.raw_source == "hydration":
            # For hydration source, we tolerate missing brand_id because hydration payload doesn't have it.
            # HOWEVER, if we have brand names in our filters (from search_text or monitor name),
            # we should verify that the item's brand title matches at least one of them.
            if filters.allowed_brand_names:
                item_brand_lower = (item.brand or "").lower()
                if not any(name in item_brand_lower or item_brand_lower in name for name in filters.allowed_brand_names):
                    return False, "wrong_brand"
            
            # If we have no brand names to check against, we trust the source page (which was brand-filtered).
            return True, None
        else:
            return False, "missing_brand_id"
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
