from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.web.dependencies import get_db, get_scheduler, require_user
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/system", tags=["system"])


class SystemStatusResponse(BaseModel):
    scheduler_running: bool
    active_jobs_count: int
    bots_running_count: int
    database_status: str


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    """Return non-secret system status."""
    scheduler = get_scheduler(request)
    
    # Scheduler info
    scheduler_running = False
    active_jobs_count = 0
    if scheduler and scheduler.scheduler.running:
        scheduler_running = True
        active_jobs_count = len(scheduler.scheduler.get_jobs())

    # Bots info
    from app.telegram.bot import _polling_tasks
    bots_running_count = len([t for t in _polling_tasks.values() if not t.done()])

    # DB status
    database_status = "error"
    try:
        await db.execute(text("SELECT 1"))
        database_status = "ok"
    except Exception:
        logger.exception("Database status check failed")

    return {
        "scheduler_running": scheduler_running,
        "active_jobs_count": active_jobs_count,
        "bots_running_count": bots_running_count,
        "database_status": database_status,
    }
