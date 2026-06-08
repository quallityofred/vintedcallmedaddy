from __future__ import annotations
from typing import Any

from app.config import get_settings


_CATEGORY_KEYS = ("catalog[]", "catalog_ids[]", "catalog_id", "catalog")

def should_use_hydration_source(params: dict[str, Any]) -> bool:
    """
    Determine if a monitor check should use the hydration source.
    Enabled only if flag is set AND params contain category/catalog filters.
    """
    settings = get_settings()
    if not settings.monitor_hydration_source_enabled:
        return False
        
    # Check for category indicators: catalog, catalog_ids, or their bracketed variants
    return any(key in params for key in _CATEGORY_KEYS)


def should_use_hydration_ssr_photo_merge(params: dict[str, Any]) -> bool:
    """Return whether the default-off SSR photo enrichment path is eligible."""
    settings = get_settings()
    return (
        settings.monitor_ssr_photo_merge_enabled
        and settings.monitor_hydration_source_enabled
        and any(key in params for key in _CATEGORY_KEYS)
    )
