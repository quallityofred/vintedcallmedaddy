# app/main.py
"""
FastAPI application entry point for Vinted Monitor.

Startup sequence:
  1. Initialize database (create tables, run lightweight migrations)
  2. Create VintedClient
  3. Start MonitorScheduler
  4. Restore persisted Telegram bots for all users
  5. Mount static files and Jinja2 templates
  6. Register routers and exception handlers

Shutdown sequence:
  1. Stop all Telegram bots
  2. Stop scheduler
  3. Close scraper sessions
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import init_db
from app.logger import log_manager
from app.web.dependencies import RequireLoginException, restore_persisted_bot

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Jinja2 custom filters
# ---------------------------------------------------------------------------

def _from_json_filter(value: str):
    """Jinja2 filter: parse a JSON string to a Python object."""
    import json
    try:
        return json.loads(value)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("Starting Vinted Monitor...")

    # 1. Database
    try:
        await init_db()
        logger.info("Database ready")
    except Exception:
        logger.exception("Database init failed")
        raise

    # 2. VintedClient
    from app.scraper.client import VintedClient, CloudflareFallback
    from app.scraper.rate_limiter import TokenBucketLimiter

    rate_limiter = TokenBucketLimiter(
        rate=float(settings.rate_limit_per_minute),
        per=60.0,
    )
    cf_fallback = (
        CloudflareFallback(
            worker_url=settings.cf_worker_url,
            block_threshold=settings.cf_worker_block_threshold,
            recovery_minutes=settings.cf_worker_recovery_minutes,
        )
        if settings.cf_worker_url
        else None
    )

    scraper_client = VintedClient(rate_limiter=rate_limiter, cf_fallback=cf_fallback)
    app.state.scraper_client = scraper_client
    logger.info("Scraper client created")

    # 3. Scheduler
    from app.scheduler.tasks import MonitorScheduler
    scheduler = MonitorScheduler(scraper_client)
    app.state.scheduler = scheduler
    try:
        await scheduler.start()
        logger.info("Scheduler started")
    except Exception:
        logger.exception("Scheduler start failed")

    # 4. Restore Telegram bots for all users
    try:
        await restore_persisted_bot(app.state)
    except Exception:
        logger.exception("Bot restore failed")

    yield  # ── Application running ──────────────────────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────────
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
        logger.info("All bots stopped")
    except Exception:
        logger.exception("Bot shutdown error")

    # Stop scheduler
    try:
        await scheduler.stop()
        logger.info("Scheduler stopped")
    except Exception:
        logger.exception("Scheduler stop error")

    # Close scraper sessions
    try:
        await scraper_client.close()
        logger.info("Scraper client closed")
    except Exception:
        pass


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

    # ── Middleware ────────────────────────────────────────────────────────
    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # ── Static files ──────────────────────────────────────────────────────
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # ── Templates ────────────────────────────────────────────────────────
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    templates = Jinja2Templates(directory=templates_dir)
    templates.env.filters["from_json"] = _from_json_filter
    app.state.templates = templates

    # ── Routers ───────────────────────────────────────────────────────────
    from app.web.auth_router import router as auth_router
    from app.web.router import router as web_router

    app.include_router(auth_router)
    app.include_router(web_router)

    # Admin router (if it exists)
    try:
        from app.web.admin_router import router as admin_router  # type: ignore
        app.include_router(admin_router, prefix="/admin")
    except ImportError:
        pass

    # ── Exception handlers ────────────────────────────────────────────────
    @app.exception_handler(RequireLoginException)
    async def require_login_handler(request: Request, exc: RequireLoginException):
        return RedirectResponse(url="/login", status_code=303)

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return templates.TemplateResponse(
            request, "404.html", {"request": request}, status_code=404
        ) if _template_exists(templates_dir, "404.html") else JSONResponse(
            {"detail": "Not found"}, status_code=404
        )

    @app.exception_handler(500)
    async def server_error_handler(request: Request, exc):
        logger.exception("Unhandled server error for %s", request.url)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Internal server error"}, status_code=500)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    # ── Health check ──────────────────────────────────────────────────────
    @app.get("/health")
    async def health_check():
        """Liveness probe – used by Railway / Docker healthchecks."""
        return {"status": "ok", "service": "vinted-monitor"}

    @app.get("/api/health")
    async def api_health(request: Request):
        """Extended health with scheduler + bot status."""
        scheduler = getattr(request.app.state, "scheduler", None)
        job_count = len(scheduler.job_ids) if scheduler else 0
        from app.telegram.bot import _polling_tasks
        bots_running = sum(1 for t in _polling_tasks.values() if not t.done())
        return {
            "status": "ok",
            "scheduler_jobs": job_count,
            "bots_running": bots_running,
        }

    return app


def _template_exists(templates_dir: str, name: str) -> bool:
    return os.path.isfile(os.path.join(templates_dir, name))


# Module-level app instance (used by uvicorn / gunicorn)
app = create_app()


# ---------------------------------------------------------------------------
# clean_startup_reset – exported for use by tests and lifespan
# ---------------------------------------------------------------------------

async def clean_startup_reset() -> None:
    """
    Reset application state to a cold-start baseline.

    * Deletes all ``FoundItem`` and ``SeenItem`` rows so the first polling
      cycle treats every listing as unseen (but silenced – no notification
      on cold start).
    * Resets ``last_check_at = None`` and ``items_found_count = 0`` on every
      monitor so ``check_monitor`` knows it is a cold start.

    Uses ``app.database.AsyncSessionLocal`` via the module reference so that
    test-time patches of that attribute are correctly respected.
    """
    import app.database as _db_module
    from app.models import FoundItem, Monitor, SeenItem
    from sqlalchemy import delete, update

    async with _db_module.AsyncSessionLocal() as db:
        await db.execute(delete(FoundItem))
        await db.execute(delete(SeenItem))
        await db.execute(update(Monitor).values(last_check_at=None, items_found_count=0))
        await db.commit()
    logger.info("clean_startup_reset: all monitors reset, FoundItem/SeenItem cleared")
