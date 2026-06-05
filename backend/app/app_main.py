# app/main.py
"""
FastAPI application entry point for Vinted Monitor.
"""
from __future__ import annotations

import logging
import os
import time
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import DatabaseTemporarilyUnavailable, init_db, is_db_capacity_error, is_db_disconnect_error
from app.logger import log_manager
from app.web.dependencies import RequireLoginException, restore_persisted_bot

logger = logging.getLogger(__name__)
settings = get_settings()
HEALTH_SCHEMA_VERSION = 2
CODE_VERSION = "readiness-v3"


def _is_production_runtime() -> bool:
    return settings.environment.lower() in {"production", "prod"} or bool(
        os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER")
    )


def _backend_root_payload() -> dict[str, object]:
    return {
        "service": "vintedbot-backend",
        "status": "ok",
        "health_schema_version": HEALTH_SCHEMA_VERSION,
        "code_version": CODE_VERSION,
        "frontend": settings.frontend_url or None,
        "health": "/health",
        "api_health": "/api/health",
        "api": "/api/v1",
    }


def _safe_commit_marker() -> str | None:
    for name in ("RAILWAY_GIT_COMMIT_SHA", "GITHUB_SHA", "COMMIT_SHA"):
        value = os.getenv(name, "").strip()
        if value:
            return value[:7]
    return None


def _database_pool_mode() -> str:
    if settings.is_sqlite():
        return "static"
    return "null" if settings.db_use_null_pool else "queue"


def _database_pool_settings() -> dict[str, int | None]:
    if settings.is_sqlite():
        return {
            "database_pool_size": None,
            "database_max_overflow": None,
            "database_pool_timeout_seconds": None,
            "database_pool_recycle_seconds": None,
        }
    return {
        "database_pool_size": None if settings.db_use_null_pool else settings.db_pool_size,
        "database_max_overflow": None if settings.db_use_null_pool else settings.db_max_overflow,
        "database_pool_timeout_seconds": settings.db_pool_timeout,
        "database_pool_recycle_seconds": settings.db_pool_recycle_seconds,
    }


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

async def _run_startup_services(app: FastAPI) -> None:
    """Run DB repair and optional runtime services without blocking liveness."""
    startup_started = time.monotonic()
    app.state.startup_status = "starting"
    app.state.db_ready = False
    app.state.startup_error = None

    db_ready = False
    for attempt in range(1, settings.startup_db_max_attempts + 1):
        try:
            phase_started = time.monotonic()
            logger.info(
                "Database startup phase starting: attempt=%s/%s timeout=%ss",
                attempt,
                settings.startup_db_max_attempts,
                settings.startup_db_timeout_seconds,
            )
            await asyncio.wait_for(init_db(), timeout=settings.startup_db_timeout_seconds)
            logger.info("Database ready in %.2fs", time.monotonic() - phase_started)
            db_ready = True
            app.state.db_ready = True
            break
        except asyncio.TimeoutError:
            app.state.startup_error = "database_startup_timeout"
            logger.exception("Database startup timed out after %ss", settings.startup_db_timeout_seconds)
        except Exception:
            app.state.startup_error = "database_startup_failed"
            logger.exception("Database startup failed")

        if attempt < settings.startup_db_max_attempts:
            await asyncio.sleep(settings.startup_db_retry_interval_seconds)

    if not db_ready:
        app.state.startup_status = "degraded"
        logger.error(
            "Application started degraded: database startup did not complete after %s attempts",
            settings.startup_db_max_attempts,
        )
        return

    try:
        from app.runtime_settings import apply_db_runtime_settings

        phase_started = time.monotonic()
        await asyncio.wait_for(
            apply_db_runtime_settings(),
            timeout=settings.startup_optional_timeout_seconds,
        )
        logger.info("Runtime settings loaded in %.2fs", time.monotonic() - phase_started)
    except asyncio.TimeoutError:
        logger.exception("Runtime settings load timed out after %ss", settings.startup_optional_timeout_seconds)
    except Exception:
        logger.exception("Runtime settings load failed")

    logger.info("Scraper client ready (per-user)")

    from app.scheduler.tasks import MonitorScheduler

    scheduler = MonitorScheduler()
    app.state.scheduler = scheduler
    try:
        phase_started = time.monotonic()
        await asyncio.wait_for(scheduler.start(), timeout=settings.startup_optional_timeout_seconds)
        app.state.scheduler_ready = True
        logger.info("Scheduler started in %.2fs", time.monotonic() - phase_started)
    except asyncio.TimeoutError:
        app.state.scheduler_ready = False
        logger.exception("Scheduler start timed out after %ss", settings.startup_optional_timeout_seconds)
    except Exception:
        app.state.scheduler_ready = False
        logger.exception("Scheduler start failed")

    try:
        phase_started = time.monotonic()
        await asyncio.wait_for(
            restore_persisted_bot(app.state),
            timeout=settings.startup_optional_timeout_seconds,
        )
        logger.info("Telegram bot restore completed in %.2fs", time.monotonic() - phase_started)
    except asyncio.TimeoutError:
        logger.exception("Telegram bot restore timed out after %ss", settings.startup_optional_timeout_seconds)
    except Exception:
        logger.exception("Bot restore failed")

    app.state.startup_status = "ready"
    logger.info("Application background startup completed in %.2fs", time.monotonic() - startup_started)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    startup_started = time.monotonic()
    logger.info("Starting Vinted Monitor...")
    app.state.db_ready = False
    app.state.scheduler_ready = False
    app.state.startup_status = "starting"
    app.state.startup_error = None
    app.state.scheduler = None
    app.state.startup_task = asyncio.create_task(_run_startup_services(app))
    logger.info("HTTP liveness released in %.2fs; background startup continues", time.monotonic() - startup_started)

    yield

    # в”Ђв”Ђ Shutdown в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    logger.info("Shutting down Vinted Monitor...")

    startup_task = getattr(app.state, "startup_task", None)
    if startup_task and not startup_task.done():
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass

    # Stop all bots
    try:
        from app.telegram.bot import _polling_tasks, _bots
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
    scheduler = getattr(app.state, "scheduler", None)
    try:
        if scheduler:
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

    @app.exception_handler(DatabaseTemporarilyUnavailable)
    async def database_temporarily_unavailable_handler(request: Request, exc: DatabaseTemporarilyUnavailable):
        logger.warning("Database temporarily unavailable during request: %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
        if is_db_capacity_error(exc):
            logger.warning("Known database capacity error during request: %s %s", request.method, request.url.path)
            return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)
        if is_db_disconnect_error(exc):
            logger.warning("Known database disconnect during request: %s %s", request.method, request.url.path)
            return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)
        logger.exception("Unhandled SQLAlchemy error for %s", request.url)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.exception_handler(500)
    async def server_error_handler(request: Request, exc):
        if is_db_capacity_error(exc):
            logger.warning("Known database capacity error reached 500 handler: %s %s", request.method, request.url.path)
            return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)
        if is_db_disconnect_error(exc):
            logger.warning("Known database disconnect reached 500 handler: %s %s", request.method, request.url.path)
            return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)
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
            "health_schema_version": HEALTH_SCHEMA_VERSION,
            "code_version": CODE_VERSION,
            "commit": _safe_commit_marker(),
            "startup_status": getattr(request.app.state, "startup_status", "unknown"),
            "database_status": "ready" if getattr(request.app.state, "db_ready", False) else "not_ready",
            "database_pool_mode": _database_pool_mode(),
            **_database_pool_settings(),
            "scheduler_ready": bool(getattr(request.app.state, "scheduler_ready", False)),
            "startup_error": getattr(request.app.state, "startup_error", None),
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
