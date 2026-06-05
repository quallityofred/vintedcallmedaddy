# app/main.py
"""
FastAPI application entry point for Vinted Monitor.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.logger import log_manager
from app.web.dependencies import RequireLoginException, restore_persisted_bot

logger = logging.getLogger(__name__)
settings = get_settings()


def _is_production_runtime() -> bool:
    return settings.environment.lower() in {"production", "prod"} or bool(
        os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER")
    )


def _backend_root_payload() -> dict[str, object]:
    return {
        "service": "vintedbot-backend",
        "status": "ok",
        "frontend": settings.frontend_url or None,
        "health": "/health",
        "api_health": "/api/health",
        "api": "/api/v1",
    }


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    startup_started = time.monotonic()
    logger.info("Starting Vinted Monitor...")

    # 1. Database
    try:
        phase_started = time.monotonic()
        await init_db()
        logger.info("Database ready in %.2fs", time.monotonic() - phase_started)
        from app.runtime_settings import apply_db_runtime_settings
        phase_started = time.monotonic()
        await apply_db_runtime_settings()
        logger.info("Runtime settings loaded in %.2fs", time.monotonic() - phase_started)
    except Exception:
        logger.exception("Database init failed")
        raise

    # 2. VintedClient
    # Note: Scraper client is now created per-user inside check_monitor
    logger.info("Scraper client ready (per-user)")

    # 3. Scheduler
    from app.scheduler.tasks import MonitorScheduler
    scheduler = MonitorScheduler()
    app.state.scheduler = scheduler
    try:
        phase_started = time.monotonic()
        await scheduler.start()
        logger.info("Scheduler started in %.2fs", time.monotonic() - phase_started)
    except Exception:
        logger.exception("Scheduler start failed")

    # 4. Restore Telegram bots for all users
    try:
        phase_started = time.monotonic()
        await restore_persisted_bot(app.state)
        logger.info("Telegram bot restore completed in %.2fs", time.monotonic() - phase_started)
    except Exception:
        logger.exception("Bot restore failed")

    logger.info("Application startup completed in %.2fs", time.monotonic() - startup_started)

    yield

    # в”Ђв”Ђ Shutdown в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    logger.info("Shutting down Vinted Monitor...")

    # Stop all bots
    try:
        from app.telegram.bot import _polling_tasks, _bots
        import asyncio
        for token, task in list(_polling_tasks.items()):
            if not task.done():
                task.cancel()
        if _polling_tasks:
            await asyncio.gather(*_polling_tasks.values(), return_exceptions=True)
        for bot in list(_bots.values()):
            try:
                await bot.session.close()
            except Exception:
                pass
        _polling_tasks.clear()
        _bots.clear()
        logger.info("All bots stopped")
    except Exception:
        logger.exception("Bot shutdown error")

    # Stop scheduler
    try:
        await scheduler.stop()
        logger.info("Scheduler stopped")
    except Exception:
        logger.exception("Scheduler stop error")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="Vinted Monitor",
        description="Telegram-powered Vinted listing tracker with web dashboard",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if os.getenv("DEBUG") else None,
        redoc_url=None,
    )

    # в”Ђв”Ђ Middleware в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    if settings.frontend_url:
        origins.append(settings.frontend_url.strip())
    origins = list(dict.fromkeys(origins)) or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # в”Ђв”Ђ Static files в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # в”Ђв”Ђ Routers в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    from app.web.admin_api_router import router as admin_api_router
    from app.web.auth_api_router import router as auth_api_router
    from app.web.dashboard_api_router import router as dashboard_api_router
    from app.web.items_api_router import router as items_api_router
    from app.web.monitors_api_router import router as monitors_api_router
    from app.web.settings_api_router import router as settings_api_router
    from app.web.system_api_router import router as system_api_router

    app.include_router(admin_api_router)
    app.include_router(auth_api_router)
    app.include_router(dashboard_api_router)
    app.include_router(items_api_router)
    app.include_router(monitors_api_router)
    app.include_router(settings_api_router)
    app.include_router(system_api_router)

    # в”Ђв”Ђ Exception handlers в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    @app.exception_handler(RequireLoginException)
    async def require_login_handler(request: Request, exc: RequireLoginException):
        return RedirectResponse(url="/login", status_code=303)

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.exception_handler(500)
    async def server_error_handler(request: Request, exc):
        logger.exception("Unhandled server error for %s", request.url)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    # в”Ђв”Ђ Health check в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    @app.get("/health")
    async def health_check():
        """Liveness probe – used by Railway / Docker healthchecks."""
        return {"status": "ok", "service": "vinted-monitor"}

    @app.get("/")
    async def backend_root():
        if _is_production_runtime() and settings.frontend_url:
            return RedirectResponse(url=settings.frontend_url, status_code=307)
        return JSONResponse(_backend_root_payload())

    @app.get("/api/health")
    async def api_health(request: Request):
        """Extended health with scheduler + bot status."""
        scheduler = getattr(request.app.state, "scheduler", None)
        job_count = len(getattr(scheduler, "job_ids", [])) if scheduler else 0
        from app.web.dependencies import count_running_bots
        bots_running = count_running_bots()
        return {
            "status": "ok",
            "scheduler_jobs": job_count,
            "bots_running": bots_running,
        }

    return app

app = create_app()

async def clean_startup_reset() -> None:
    """
    Reset application state to a cold-start baseline.
    """
    import app.database as _db_module
    from app.models import FoundItem, Monitor, SeenItem
    from sqlalchemy import delete, update

    session_factory = _db_module.AsyncSessionLocal or _db_module.get_session_factory()
    async with session_factory() as db:
        await db.execute(delete(FoundItem))
        await db.execute(delete(SeenItem))
        await db.execute(update(Monitor).values(last_check_at=None, items_found_count=0))
        await db.commit()
    logger.info("clean_startup_reset: all monitors reset, FoundItem/SeenItem cleared")
