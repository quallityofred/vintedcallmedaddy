# app/main.py
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import init_db
from app.scraper.client import CloudflareFallback, VintedClient
from app.scraper.rate_limiter import TokenBucketLimiter
from app.scheduler.tasks import MonitorScheduler
from app.web.auth import RequireLoginException
from app.web.auth_router import router as auth_router
from app.web.dependencies import restore_persisted_bot, set_scheduler
from app.web.router import router as web_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

_BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
templates.env.filters["from_json"] = json.loads

_initialized: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _initialized

    if _initialized:
        logger.warning("Lifespan already executed, skipping duplicate init")
        yield
        return
    _initialized = True

    logger.info("Starting Vinted Monitor...")
    await init_db()
    
    # Run admin and schema setup
    from app.scripts.setup_admin import setup_admin
    try:
        await setup_admin()
        logger.info("Admin setup and schema verification complete")
    except Exception:
        logger.exception("Failed to run admin setup")

    logger.info("Database initialized")

    rate_limiter = TokenBucketLimiter(
        rate=float(settings.rate_limit_per_minute),
        per=60.0,
    )

    cf_fallback = None
    if settings.cf_worker_url:
        cf_fallback = CloudflareFallback(
            worker_url=settings.cf_worker_url,
            block_threshold=settings.cf_worker_block_threshold,
            recovery_minutes=settings.cf_worker_recovery_minutes,
        )
        logger.info("Cloudflare Workers fallback enabled: %s", settings.cf_worker_url)

    client = VintedClient(rate_limiter=rate_limiter, cf_fallback=cf_fallback)

    scheduler = MonitorScheduler(client=client)
    set_scheduler(scheduler)
    await scheduler.start()
    restore_result = await restore_persisted_bot()

    app.state.templates = templates
    app.state.scheduler = scheduler
    app.state.client = client
    if restore_result:
        logger.info("Telegram bot restore result: %s", restore_result)
    else:
        logger.info("Bot not started — use /settings to configure and start")

    yield

    logger.info("Shutting down...")
    from app.web.dependencies import stop_bot as deps_stop_bot
    await deps_stop_bot(clear_persisted_state=False)
    await scheduler.stop()
    await client.close()
    logger.info("Shutdown complete")


from app.logger import log_manager
from app.web.auth import require_user
from app.models import User

app = FastAPI(title="Vinted Monitor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

@app.get("/api/logs")
async def get_logs(user: User = Depends(require_user)):
    return {"logs": log_manager.get_user_logs(user.id)}

app.include_router(auth_router)
app.include_router(web_router)


@app.exception_handler(RequireLoginException)
async def require_login_handler(request: Request, exc: RequireLoginException):
    return RedirectResponse(url="/login", status_code=303)
