from __future__ import annotations
from app.config import get_settings

def should_use_hydration_source(params: dict[str, Any]) -> bool:
    """
    Determine if a monitor check should use the hydration source.
    Enabled only if flag is set AND params contain category/catalog filters.
    """
    settings = get_settings()
    if not settings.monitor_hydration_source_enabled:
        return False
        
    # Check for category indicators: catalog, catalog_ids, or their bracketed variants
    category_keys = ["catalog[]", "catalog_ids[]", "catalog_id", "catalog"]
    return any(key in params for key in category_keys)
