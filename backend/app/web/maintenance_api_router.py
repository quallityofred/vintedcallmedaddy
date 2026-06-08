from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.models import User
from app.scheduler.retention import run_history_retention_dry_run
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])

@router.post("/history-retention/dry-run", dependencies=[Depends(require_api_csrf)])
async def post_history_retention_dry_run(
    monitor_ids: Optional[List[int]] = Query(None),
    include_found_items: bool = True,
    include_seen_items: bool = True,
    found_items_days: Optional[int] = Query(None, ge=1, le=365),
    found_items_cap: Optional[int] = Query(None, ge=1, le=1000),
    seen_items_cap: Optional[int] = Query(None, ge=1, le=1000),
    sample_limit: Optional[int] = Query(None, ge=0, le=50),
    dry_run: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """
    Perform a dry-run history retention analysis.
    This endpoint reports what would be pruned but does NOT delete anything.
    """
    if not dry_run:
        raise HTTPException(
            status_code=400, 
            detail="live_retention_not_enabled: Only dry_run=true is supported in this phase."
        )

    try:
        result = await run_history_retention_dry_run(
            db=db,
            monitor_ids=monitor_ids,
            include_found_items=include_found_items,
            include_seen_items=include_seen_items,
            found_items_retention_days=found_items_days or settings.history_retention_found_items_days_default,
            found_items_max_per_monitor_domain=found_items_cap or settings.history_retention_found_items_max_per_monitor_domain_default,
            seen_items_max_per_monitor_domain=seen_items_cap or settings.history_retention_seen_items_max_per_monitor_domain_default,
            sample_limit=sample_limit if sample_limit is not None else settings.history_retention_sample_limit_default
        )
        return result
    except Exception as e:
        logger.exception("Failed to run history retention dry-run")
        raise HTTPException(status_code=500, detail=str(e))
