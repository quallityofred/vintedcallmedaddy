from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
from app.models import User, Monitor
from app.scheduler.diagnostics import registry
from app.scraper.source_selector import should_use_hydration_source
from app.config import get_settings

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])

@router.get("/monitors/{monitor_id}/source-selection")
async def get_monitor_source_selection(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Get diagnostic info for hydration source selection."""
    settings = get_settings()
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
        
    import json
    try:
        params = json.loads(monitor.params_json)
    except Exception:
        params = {}
    
    # Check selector logic
    used = should_use_hydration_source(params)
    
    # Determine reason
    reason = "api"
    if not settings.monitor_hydration_source_enabled:
        reason = "flag_disabled"
    elif not any(key in params for key in ["catalog[]", "catalog_ids[]", "catalog_id", "catalog"]):
        reason = "brand_only_api_path"
    else:
        reason = "catalog_filter_detected"
        
    # Get last check data if available
    diag = await registry.get_check(monitor_id)
    
    return {
        "monitor_id": monitor_id,
        "hydration_enabled_effective": settings.monitor_hydration_source_enabled,
        "selected_source": "hydration" if used else "api",
        "reason": reason,
        "has_catalog_filter": any(key in params for key in ["catalog[]", "catalog_ids[]", "catalog_id", "catalog"]),
        "has_brand_filter": "brand_ids[]" in params or "brand_ids" in params,
        "detail_guards": {
            "enabled": settings.monitor_detail_guard_enabled,
            "category_guard_enabled": settings.monitor_detail_category_guard_enabled,
            "freshness_guard_enabled": settings.monitor_detail_freshness_guard_enabled,
        },
        "last_check": {
            "at": diag.last_check_at if diag else None,
            "source": diag.last_check_source if diag else None,
            "items_found_count_by_domain": diag.items_found_count_by_domain if diag else {},
        },
        "side_effects": {
            "runs_monitor_check": False,
            "writes_seen_items": False,
            "writes_found_items": False,
            "sends_telegram": False,
            "calls_vinted": False
        }
    }
