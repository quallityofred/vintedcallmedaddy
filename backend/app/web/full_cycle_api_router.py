from __future__ import annotations
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.models import User, Monitor
from app.scheduler.diagnostics import registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/monitors", tags=["monitors"])

@router.post("/{monitor_id}/full-cycle-jobs", dependencies=[Depends(require_api_csrf)])
async def post_monitor_full_cycle_job(
    monitor_id: int,
    background_tasks: BackgroundTasks,
    dry_run: bool = True,
    cleanup_existing_pending: bool = False,
    cold_baseline: bool = False,
    run_check: bool = True,
    send_pending: bool = False,
    pause_before: bool = True,
    pause_after: bool = True,
    max_items_per_domain: int = Query(default=96, ge=1, le=120),
    notification_batch_limit: int = Query(default=20, ge=1, le=100),
    max_notification_batches: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Start an asynchronous background job for a full monitor cycle."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    job_id = f"full_{monitor_id}_{uuid.uuid4().hex[:12]}"
    await registry.start_job(
        job_id,
        monitor_id,
        "full_cycle_production",
        request_metadata={
            "dry_run": dry_run,
            "cleanup_existing_pending": cleanup_existing_pending,
            "cold_baseline": cold_baseline,
            "run_check": run_check,
            "send_pending": send_pending,
            "pause_before": pause_before,
            "pause_after": pause_after,
            "max_items_per_domain": max_items_per_domain,
            "notification_batch_limit": notification_batch_limit,
            "max_notification_batches": max_notification_batches,
        },
    )

    from app.scheduler.tasks import run_monitor_full_cycle_job_task
    background_tasks.add_task(
        run_monitor_full_cycle_job_task,
        job_id,
        monitor_id=monitor_id,
        dry_run=dry_run,
        cleanup_existing_pending=cleanup_existing_pending,
        cold_baseline=cold_baseline,
        run_check=run_check,
        send_pending=send_pending,
        pause_before=pause_before,
        pause_after=pause_after,
        max_items_per_domain=max_items_per_domain,
        notification_batch_limit=notification_batch_limit,
        max_notification_batches=max_notification_batches,
    )

    return {
        "job_id": job_id,
        "status": "running",
        "monitor_id": monitor_id,
    }

@router.get("/{monitor_id}/full-cycle-jobs/{job_id}")
async def get_monitor_full_cycle_job_status(
    monitor_id: int,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Get status of a full monitor cycle job."""
    monitor_result = await db.execute(
        select(Monitor.id).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    if monitor_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    job = await registry.get_job(job_id, monitor_id)
    if job is None:
        return JSONResponse(status_code=404, content={"job_id": job_id, "status": "not_found"})

    if job.status == "completed" and job.result is not None:
        res = dict(job.result)
        res["job_id"] = job_id
        res["status"] = "completed"
        return JSONResponse(status_code=200, content=jsonable_encoder(res))
    
    if job.status == "failed":
        return {
            "job_id": job_id,
            "status": "failed",
            "safe_error": job.safe_error,
        }

    return {
        "job_id": job_id,
        "status": "running",
        "started_at": job.started_at.isoformat(),
    }

@router.post("/{monitor_id}/notifications/send-pending-jobs", dependencies=[Depends(require_api_csrf)])
async def post_monitor_send_pending_job(
    monitor_id: int,
    background_tasks: BackgroundTasks,
    dry_run: bool = True,
    batch_limit: int = Query(default=20, ge=1, le=100),
    max_batches: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Start an asynchronous background job to send all pending notifications for a monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    job_id = f"send_{monitor_id}_{uuid.uuid4().hex[:12]}"
    await registry.start_job(
        job_id,
        monitor_id,
        "send_all_pending",
        request_metadata={
            "dry_run": dry_run,
            "batch_limit": batch_limit,
            "max_batches": max_batches,
        },
    )

    from app.scheduler.tasks import run_monitor_send_all_pending_job_task
    background_tasks.add_task(
        run_monitor_send_all_pending_job_task,
        job_id,
        monitor_id=monitor_id,
        dry_run=dry_run,
        batch_limit=batch_limit,
        max_batches=max_batches,
    )

    return {
        "job_id": job_id,
        "status": "running",
        "monitor_id": monitor_id,
    }

@router.get("/{monitor_id}/notifications/send-pending-jobs/{job_id}")
async def get_monitor_send_pending_job_status(
    monitor_id: int,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Get status of a send-pending job."""
    monitor_result = await db.execute(
        select(Monitor.id).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    if monitor_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    job = await registry.get_job(job_id, monitor_id)
    if job is None:
        return JSONResponse(status_code=404, content={"job_id": job_id, "status": "not_found"})

    if job.status == "completed" and job.result is not None:
        res = dict(job.result)
        res["job_id"] = job_id
        res["status"] = "completed"
        return JSONResponse(status_code=200, content=jsonable_encoder(res))
    
    if job.status == "failed":
        return {
            "job_id": job_id,
            "status": "failed",
            "safe_error": job.safe_error,
        }

    return {
        "job_id": job_id,
        "status": "running",
        "started_at": job.started_at.isoformat(),
    }
