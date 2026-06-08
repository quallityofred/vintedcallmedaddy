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
from app.scheduler.retention import run_history_retention_dry_run
from app.scheduler.pending_diagnostics import run_pending_notifications_dry_run, run_pending_notifications_ack_no_notify
from app.config import get_settings
from app.schemas.pending_ack import AckNoNotifyRequest

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])

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
