from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.scraper.parser import VintedItem


ARRAY_PARAM_ALIASES = {
    "brand_ids": ("brand_ids[]", "brand_ids"),
    "catalog_ids": ("catalog[]", "catalog_ids", "catalog_ids[]"),
    "size_ids": ("size_ids[]", "size_ids"),
    "status_ids": ("status_ids[]", "status_ids"),
    "color_ids": ("color_ids[]", "color_ids"),
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

    @property
    def filter_keys(self) -> list[str]:
        keys: list[str] = []
        for key in ("brand_ids", "catalog_ids", "size_ids", "status_ids", "color_ids"):
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


def extract_monitor_filters(params: dict[str, Any]) -> MonitorFilters:
    return MonitorFilters(
        brand_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["brand_ids"]),
        catalog_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["catalog_ids"]),
        size_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["size_ids"]),
        status_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["status_ids"]),
        color_ids=_string_set_from_aliases(params, ARRAY_PARAM_ALIASES["color_ids"]),
        price_from=str(params["price_from"]).strip() if params.get("price_from") not in (None, "") else None,
        price_to=str(params["price_to"]).strip() if params.get("price_to") not in (None, "") else None,
        search_text=str(params["search_text"]).strip() if params.get("search_text") not in (None, "") else None,
        order=str(params["order"]).strip() if params.get("order") not in (None, "") else None,
    )


def item_matches_monitor_filters(item: VintedItem, filters: MonitorFilters) -> tuple[bool, str | None]:
    if filters.brand_ids:
        if item.brand_id is None:
            return False, "missing_brand_id"
        if str(item.brand_id) not in filters.brand_ids:
            return False, "wrong_brand"
    return True, None


def has_restrictive_filters(filters: MonitorFilters) -> bool:
    return bool(
        filters.brand_ids
        or filters.catalog_ids
        or filters.size_ids
        or filters.status_ids
        or filters.color_ids
        or filters.price_from is not None
        or filters.price_to is not None
        or filters.search_text is not None
    )
