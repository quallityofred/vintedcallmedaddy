# app/web/dependencies.py
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

if TYPE_CHECKING:
    from app.scheduler.tasks import MonitorScheduler

_scheduler: "MonitorScheduler | None" = None


def set_scheduler(scheduler: "MonitorScheduler") -> None:
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> "MonitorScheduler":
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized")
    return _scheduler


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
