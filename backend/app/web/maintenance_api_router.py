from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.models import User
from app.scheduler.retention import run_history_retention_dry_run, run_history_retention_cleanup
from app.scheduler.pending_diagnostics import run_pending_notifications_dry_run, run_pending_notifications_ack_no_notify
from app.scheduler.cold_start_reset import run_monitor_cold_start_reset
from app.config import get_settings
from app.schemas.pending_ack import AckNoNotifyRequest, RetentionCleanupRequest, ColdStartResetRequest

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])

@router.post("/monitors/{monitor_id}/reset-cold-start", dependencies=[Depends(require_api_csrf)])
async def post_monitor_cold_start_reset(
    monitor_id: int,
    request: ColdStartResetRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """
    Safely reset a monitor to a cold-start state.
    """
    if not request.dry_run:
        if not request.reason:
            raise HTTPException(status_code=400, detail="Reason required for live reset.")
        if request.confirm != "RESET_MONITOR_COLD_START":
            raise HTTPException(status_code=400, detail="Invalid confirmation string.")

        # Extra confirmation rules
        extra = request.extra_confirm or []
        if request.clear_seen_items and "CLEAR_SEEN_ITEMS_NO_NOTIFY_BASELINE" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation CLEAR_SEEN_ITEMS_NO_NOTIFY_BASELINE required.")
        
        if request.clear_found_items:
            if "CLEAR_FOUND_ITEMS_HISTORY" not in extra:
                raise HTTPException(status_code=400, detail="Extra confirmation CLEAR_FOUND_ITEMS_HISTORY required.")
            
            # Check for pending items if we want to clear found items
            # We do a quick check here or let the service return it in dry run.
            # But for live mode, we must be sure.
            # We'll run the service in dry-run mode first to check for pending items if not already checked.
            res_check = await run_monitor_cold_start_reset(
                db=db, monitor_id=monitor_id, dry_run=True, domains=request.domains, 
                clear_found_items=True, clear_seen_items=False, reset_last_checked=False
            )
            if res_check.get("pending_found_items_count", 0) > 0:
                if "CLEAR_PENDING_FOUND_ITEMS_HISTORY_TOO" not in extra:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Monitor has {res_check['pending_found_items_count']} pending items. CLEAR_PENDING_FOUND_ITEMS_HISTORY_TOO required."
                    )

    try:
        result = await run_monitor_cold_start_reset(
            db=db,
            monitor_id=monitor_id,
            dry_run=request.dry_run,
            domains=request.domains,
            clear_seen_items=request.clear_seen_items,
            clear_found_items=request.clear_found_items,
            reset_last_checked=request.reset_last_checked,
            require_monitor_inactive=request.require_monitor_inactive,
            sample_limit=request.sample_limit
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Failed to run monitor cold-start reset")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/pending-notifications/ack-no-notify", dependencies=[Depends(require_api_csrf)])
async def post_pending_notifications_ack_no_notify(
    request: AckNoNotifyRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """
    Perform a safe acknowledgement of pending FoundItems without notification.
    """
    if not request.dry_run:
        if not request.reason:
            raise HTTPException(status_code=400, detail="Reason required for live ack.")
        if request.confirm != "ACK_PENDING_NO_NOTIFY":
            raise HTTPException(status_code=400, detail="Invalid confirmation string.")

        # Extra confirmation rules
        extra = request.extra_confirm or []
        if request.include_active and "ACK_ACTIVE_PENDING_NO_NOTIFY" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation ACK_ACTIVE_PENDING_NO_NOTIFY required.")
        if not request.monitor_ids and "ACK_ALL_SELECTED_PENDING_NO_NOTIFY" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation ACK_ALL_SELECTED_PENDING_NO_NOTIFY required.")
        if request.older_than_minutes < 60 and "ACK_FRESH_PENDING_NO_NOTIFY" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation ACK_FRESH_PENDING_NO_NOTIFY required.")

    try:
        result = await run_pending_notifications_ack_no_notify(
            db=db,
            dry_run=request.dry_run,
            monitor_ids=request.monitor_ids,
            domains=request.domains,
            older_than_minutes=request.older_than_minutes,
            include_inactive=request.include_inactive,
            include_active=request.include_active,
            sample_limit=request.sample_limit
        )
        return result
    except Exception as e:
        logger.exception("Failed to run pending notifications ack")
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

@router.post("/history-retention/cleanup", dependencies=[Depends(require_api_csrf)])
async def post_history_retention_cleanup(
    request: RetentionCleanupRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """
    Perform history retention cleanup.
    """
    if not request.dry_run:
        if not request.reason:
            raise HTTPException(status_code=400, detail="Reason required for live cleanup.")
        if request.confirm != "CLEANUP_OLD_HISTORY":
            raise HTTPException(status_code=400, detail="Invalid confirmation string.")

        # Extra confirmation rules
        extra = request.extra_confirm or []
        if not request.monitor_ids and "CLEANUP_ALL_MONITORS_HISTORY" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation CLEANUP_ALL_MONITORS_HISTORY required.")
        if request.seen_items_max_per_monitor_domain < 192 and "CLEANUP_LOW_SEEN_BUFFER" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation CLEANUP_LOW_SEEN_BUFFER required.")
        if request.found_items_max_per_monitor_domain < 96 and "CLEANUP_LOW_FOUND_BUFFER" not in extra:
             raise HTTPException(status_code=400, detail="Extra confirmation CLEANUP_LOW_FOUND_BUFFER required.")

    try:
        result = await run_history_retention_cleanup(
            db=db,
            dry_run=request.dry_run,
            monitor_ids=request.monitor_ids,
            domains=request.domains,
            include_found_items=request.include_found_items,
            include_seen_items=request.include_seen_items,
            found_items_retention_days=request.found_items_retention_days,
            found_items_max_per_monitor_domain=request.found_items_max_per_monitor_domain,
            seen_items_max_per_monitor_domain=request.seen_items_max_per_monitor_domain,
            sample_limit=request.sample_limit,
            reason=request.reason
        )
        return result
    except Exception as e:
        logger.exception("Failed to run history retention cleanup")
        raise HTTPException(status_code=500, detail=str(e))
