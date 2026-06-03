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
from app.scraper.domains import VINTED_DOMAINS
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
    return monitors


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
    return monitor


@router.post("", response_model=MonitorResponse, dependencies=[Depends(require_csrf)])
async def create_monitor(
    request: Request,
    data: MonitorCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Create a new monitor."""
    domains = data.domains
    if not domains:
        domains = extract_domains_from_url(data.url)
        if not domains:
            domains = list(VINTED_DOMAINS.keys())

    # Validate domains
    domains = [d for d in domains if d in VINTED_DOMAINS]
    if not domains:
        raise HTTPException(status_code=422, detail="At least one valid domain is required")

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

    return monitor


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
        valid_domains = [d for d in data.domains if d in VINTED_DOMAINS]
        if valid_domains:
            monitor.domains_json = json.dumps(valid_domains)

    await db.commit()
    await db.refresh(monitor)

    scheduler = get_scheduler(request)
    if scheduler:
        if monitor.is_active:
            scheduler.update_monitor(monitor.id, monitor.interval_sec)
        else:
            scheduler.remove_monitor(monitor.id)

    return monitor


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

    return monitor


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

    return monitor


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
