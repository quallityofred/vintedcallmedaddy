from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Monitor, User
from app.web.auth import get_current_user
from app.web.dependencies import get_db

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

    class Config:
        from_attributes = True


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
