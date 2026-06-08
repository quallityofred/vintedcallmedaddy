from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.scheduler.retention import run_history_retention_dry_run
from app.scheduler.pending_diagnostics import run_pending_notifications_dry_run, run_pending_notifications_ack_no_notify
from app.config import get_settings

# ... (existing setup)

@router.post("/pending-notifications/ack-no-notify", dependencies=[Depends(require_api_csrf)])
async def post_pending_notifications_ack_no_notify(
    monitor_ids: Optional[List[int]] = Query(None),
    domains: Optional[List[str]] = Query(None),
    older_than_minutes: int = Query(default=1440, ge=0),
    include_inactive: bool = Query(default=True),
    include_active: bool = Query(default=False),
    sample_limit: int = Query(default=10, ge=0, le=20),
    dry_run: bool = Query(default=True),
    reason: Optional[str] = Query(None),
    confirm: Optional[str] = Query(None),
    extra_confirm: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """
    Perform a safe acknowledgement of pending FoundItems without notification.
    """
    if not dry_run:
        if not reason:
            raise HTTPException(status_code=400, detail="Reason required for live ack.")
        if confirm != "ACK_PENDING_NO_NOTIFY":
            raise HTTPException(status_code=400, detail="Invalid confirmation string.")

        # Extra confirmation rules
        extra = extra_confirm or []
        if include_active and "ACK_ACTIVE_PENDING_NO_NOTIFY" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation ACK_ACTIVE_PENDING_NO_NOTIFY required.")
        if not monitor_ids and "ACK_ALL_SELECTED_PENDING_NO_NOTIFY" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation ACK_ALL_SELECTED_PENDING_NO_NOTIFY required.")
        if older_than_minutes < 60 and "ACK_FRESH_PENDING_NO_NOTIFY" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation ACK_FRESH_PENDING_NO_NOTIFY required.")

    try:
        result = await run_pending_notifications_ack_no_notify(
            db=db,
            dry_run=dry_run,
            monitor_ids=monitor_ids,
            domains=domains,
            older_than_minutes=older_than_minutes,
            include_inactive=include_inactive,
            include_active=include_active,
            sample_limit=sample_limit
        )
        return result
    except Exception as e:
        logger.exception("Failed to run pending notifications ack")
        raise HTTPException(status_code=500, detail=str(e))

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

@router.post("/pending-notifications/dry-run", dependencies=[Depends(require_api_csrf)])
async def post_pending_notifications_dry_run(
    monitor_ids: Optional[List[int]] = Query(None),
    domains: Optional[List[str]] = Query(None),
    older_than_minutes: Optional[int] = Query(None, ge=0),
    include_inactive: bool = True,
    sample_limit: int = Query(default=10, ge=0, le=20),
    dry_run: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """
    Perform a dry-run pending notification analysis.
    This endpoint reports pending backlog counts and samples, without mutating any items.
    """
    if not dry_run:
        raise HTTPException(
            status_code=400, 
            detail="live_pending_ack_not_enabled: Only dry_run=true is supported in this phase."
        )

    try:
        result = await run_pending_notifications_dry_run(
            db=db,
            monitor_ids=monitor_ids,
            domains=domains,
            older_than_minutes=older_than_minutes,
            include_inactive=include_inactive,
            sample_limit=sample_limit
        )
        return result
    except Exception as e:
        logger.exception("Failed to run pending notifications dry-run")
        raise HTTPException(status_code=500, detail=str(e))
