from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FoundItem, Monitor, User
from app.web.auth import get_current_user
from app.web.dependencies import get_db, is_bot_running

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


async def require_api_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """JSON stats for the Next.js dashboard."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Active monitors
    active_count_q = await db.execute(
        select(func.count()).select_from(Monitor)
        .where(Monitor.user_id == user.id, Monitor.is_active == True)  # noqa: E712
    )
    active_count = active_count_q.scalar() or 0

    # Paused monitors
    paused_count_q = await db.execute(
        select(func.count()).select_from(Monitor)
        .where(Monitor.user_id == user.id, Monitor.is_active == False)  # noqa: E712
    )
    paused_count = paused_count_q.scalar() or 0

    # Items today
    today_items_q = await db.execute(
        select(func.count()).select_from(FoundItem)
        .join(Monitor, FoundItem.monitor_id == Monitor.id)
        .where(Monitor.user_id == user.id, FoundItem.found_at >= today_start)
    )
    today_items = today_items_q.scalar() or 0

    # Total items
    total_items_q = await db.execute(
        select(func.count()).select_from(FoundItem)
        .join(Monitor, FoundItem.monitor_id == Monitor.id)
        .where(Monitor.user_id == user.id)
    )
    total_items = total_items_q.scalar() or 0

    # Last found at
    last_found_q = await db.execute(
        select(func.max(FoundItem.found_at))
        .join(Monitor, FoundItem.monitor_id == Monitor.id)
        .where(Monitor.user_id == user.id)
    )
    last_found = last_found_q.scalar()

    return {
        "active_monitors_count": active_count,
        "paused_monitors_count": paused_count,
        "items_today_count": today_items,
        "total_items_count": total_items,
        "last_found_at": last_found.isoformat() if last_found else None,
        "telegram_status": {
            "configured": bool(user.telegram_bot_token),
            "running": is_bot_running(user.telegram_bot_token) if user.telegram_bot_token else False,
        },
    }
