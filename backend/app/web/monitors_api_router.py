from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Monitor, User
from app.scraper.domains import (
    get_unique_vinted_marketplaces,
    validate_selected_domains,
)
from app.scraper.url_parser import extract_domains_from_url, parse_vinted_url
from app.web.auth import get_current_user
from app.web.csrf import require_csrf
from app.web.dependencies import get_db, get_scheduler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/monitors", tags=["monitors"])


class MonitorResponse(BaseModel):
    id: int
    name: str
    original_url: str
    interval_sec: int
    is_active: bool
    last_check_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    items_found_count: int
    domains: List[str]

    model_config = ConfigDict(from_attributes=True)


class MonitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., pattern=r"^https?://")
    interval_sec: int = Field(120, ge=60, le=3600)
    domains: Optional[List[str]] = None


class MonitorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    url: Optional[str] = Field(None, pattern=r"^https?://")
    interval_sec: Optional[int] = Field(None, ge=60, le=3600)
    is_active: Optional[bool] = None
    domains: Optional[List[str]] = None


class BulkDeleteRequest(BaseModel):
    monitor_ids: List[int] = Field(..., min_length=1, max_length=100)


class BulkDeleteResponse(BaseModel):
    deleted_count: int
    not_found_or_forbidden_ids: List[int]


async def require_api_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _monitor_domains(monitor: Monitor) -> List[str]:
    try:
        domains = json.loads(monitor.domains_json or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(domains, list):
        return []

    return [domain for domain in domains if isinstance(domain, str)]


def _monitor_response(monitor: Monitor) -> dict[str, object]:
    return {
        "id": monitor.id,
        "name": monitor.name,
        "original_url": monitor.original_url,
        "interval_sec": monitor.interval_sec,
        "is_active": monitor.is_active,
        "last_check_at": monitor.last_check_at,
        "created_at": monitor.created_at,
        "updated_at": monitor.updated_at,
        "items_found_count": monitor.items_found_count,
        "domains": _monitor_domains(monitor),
    }


@router.get("", response_model=List[MonitorResponse])
async def list_monitors(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """List all monitors for the current user."""
    result = await db.execute(
        select(Monitor)
        .where(Monitor.user_id == user.id)
        .order_by(Monitor.created_at.desc())
    )
    monitors = result.scalars().all()
    return [_monitor_response(monitor) for monitor in monitors]


@router.get("/domains")
async def list_supported_domains():
    """List user-selectable unique Vinted marketplace representatives."""
    return get_unique_vinted_marketplaces()


@router.get("/{monitor_id}", response_model=MonitorResponse)
async def get_monitor(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Get details of a specific monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return _monitor_response(monitor)


@router.post("", response_model=MonitorResponse, dependencies=[Depends(require_csrf)])
async def create_monitor(
    request: Request,
    data: MonitorCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Create a new monitor."""
    try:
        if data.domains is None:
            domains = validate_selected_domains(extract_domains_from_url(data.url))
        else:
            domains = validate_selected_domains(data.domains)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        params = parse_vinted_url(data.url)
    except Exception as exc:
        logger.warning("URL parse error: %s", exc)
        params = {}

    params["_original_interval"] = data.interval_sec

    monitor = Monitor(
        user_id=user.id,
        name=data.name.strip(),
        original_url=data.url,
        params_json=json.dumps(params),
        domains_json=json.dumps(domains),
        interval_sec=data.interval_sec,
        is_active=True,
    )
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)

    scheduler = get_scheduler(request)
    if scheduler:
        scheduler.add_monitor(monitor.id, monitor.interval_sec)

    return _monitor_response(monitor)


@router.patch("/{monitor_id}", response_model=MonitorResponse, dependencies=[Depends(require_csrf)])
async def update_monitor(
    request: Request,
    monitor_id: int,
    data: MonitorUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Update an existing monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    if data.name is not None:
        monitor.name = data.name.strip()
    
    if data.url is not None:
        monitor.original_url = data.url
        try:
            params = parse_vinted_url(data.url)
            params["_original_interval"] = data.interval_sec or monitor.interval_sec
            monitor.params_json = json.dumps(params)
        except Exception:
            pass
    
    if data.interval_sec is not None:
        monitor.interval_sec = data.interval_sec
        try:
            params = json.loads(monitor.params_json)
            params["_original_interval"] = data.interval_sec
            monitor.params_json = json.dumps(params)
        except Exception:
            pass

    if data.is_active is not None:
        monitor.is_active = data.is_active

    if data.domains is not None:
        try:
            monitor.domains_json = json.dumps(validate_selected_domains(data.domains))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(monitor)

    scheduler = get_scheduler(request)
    if scheduler:
        if monitor.is_active:
            scheduler.update_monitor(monitor.id, monitor.interval_sec)
        else:
            scheduler.remove_monitor(monitor.id)

    return _monitor_response(monitor)


@router.delete("/{monitor_id}", status_code=204, dependencies=[Depends(require_csrf)])
async def delete_monitor(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Delete a monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    scheduler = get_scheduler(request)
    if scheduler:
        scheduler.remove_monitor(monitor_id)

    await db.delete(monitor)
    await db.commit()
    return None


@router.post("/bulk-delete", response_model=BulkDeleteResponse, dependencies=[Depends(require_csrf)])
async def bulk_delete_monitors(
    request: Request,
    data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Delete multiple monitors at once."""
    result = await db.execute(
        select(Monitor).where(
            Monitor.id.in_(data.monitor_ids),
            Monitor.user_id == user.id
        )
    )
    monitors = result.scalars().all()
    
    found_ids = {m.id for m in monitors}
    not_found_or_forbidden_ids = [id for id in data.monitor_ids if id not in found_ids]
    
    scheduler = get_scheduler(request)
    for monitor in monitors:
        if scheduler:
            scheduler.remove_monitor(monitor.id)
        await db.delete(monitor)
    
    await db.commit()
    
    return {
        "deleted_count": len(monitors),
        "not_found_or_forbidden_ids": not_found_or_forbidden_ids
    }


@router.post("/{monitor_id}/pause", response_model=MonitorResponse, dependencies=[Depends(require_csrf)])
async def pause_monitor(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Deactivate a monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    monitor.is_active = False
    await db.commit()
    await db.refresh(monitor)

    scheduler = get_scheduler(request)
    if scheduler:
        scheduler.remove_monitor(monitor_id)

    return _monitor_response(monitor)


@router.post("/{monitor_id}/resume", response_model=MonitorResponse, dependencies=[Depends(require_csrf)])
async def resume_monitor(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Activate a monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    monitor.is_active = True
    await db.commit()
    await db.refresh(monitor)

    scheduler = get_scheduler(request)
    if scheduler:
        scheduler.add_monitor(monitor.id, monitor.interval_sec)

    return _monitor_response(monitor)



@router.post("/{monitor_id}/check-now", dependencies=[Depends(require_csrf)])
async def check_monitor_now(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Manually trigger an immediate check."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    if not monitor.is_active:
        raise HTTPException(status_code=400, detail="Cannot check an inactive monitor")

    scheduler = get_scheduler(request)
    if scheduler and scheduler.trigger_now(monitor_id):
        return {"ok": True, "message": "Check triggered"}
    
    raise HTTPException(status_code=503, detail="Scheduler unavailable or monitor not scheduled")


@router.get("/{monitor_id}/debug")
async def debug_monitor(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Get diagnostic info for a specific monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    scheduler = get_scheduler(request)
    job_info = {"job_exists": False}
    if scheduler:
        job_id = scheduler.job_ids.get(monitor.id)
        if job_id:
            job = scheduler.scheduler.get_job(job_id)
            if job:
                job_info = {
                    "job_exists": True,
                    "job_id": job.id,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
                }
    
    status_notes = {
        None: "This monitor has not been checked yet.",
        "running": "Check is currently running.",
        "baseline_created": "Tracking baseline initialized. Future new items will appear here.",
        "success_zero_items": "Checked successfully, but scraper returned 0 items.",
        "success_no_new_items": "Checked successfully. No new items found.",
        "success_new_items": "Checked successfully. New items were found.",
        "failed": f"Check failed: {monitor.last_error or 'Unknown error'}",
    }

    return {
        "monitor_id": monitor.id,
        "name": monitor.name,
        "is_active": monitor.is_active,
        "interval_sec": monitor.interval_sec,
        "domains": _monitor_domains(monitor),
        "last_check_at": monitor.last_check_at,
        "last_check_started_at": monitor.last_check_started_at,
        "last_check_completed_at": monitor.last_check_completed_at,
        "last_check_status": monitor.last_check_status,
        "last_error": monitor.last_error,
        "items_found_count": monitor.items_found_count,
        "scheduler": job_info,
        "explanation": status_notes.get(monitor.last_check_status, "Status unknown."),
    }
