# app/main.py
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import init_db
from app.scraper.client import CloudflareFallback, VintedClient
from app.scraper.rate_limiter import TokenBucketLimiter
from app.scheduler.tasks import MonitorScheduler, set_telegram_bot
from app.telegram.bot import get_or_create_bot, start_polling, stop_bot, terminate_all_sessions
from app.web.dependencies import set_scheduler
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

_bot_task: asyncio.Task | None = None
_initialized: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot_task, _initialized

    if _initialized:
        logger.warning("Lifespan already executed, skipping duplicate init")
        yield
        return
    _initialized = True

    logger.info("Starting Vinted Monitor...")
    await init_db()
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

    await terminate_all_sessions(settings.telegram_bot_token)
    bot, dp = get_or_create_bot(settings.telegram_bot_token)
    set_telegram_bot(bot)
    _bot_task = asyncio.create_task(start_polling(bot, dp))
    logger.info("Telegram bot polling started")

    app.state.templates = templates
    app.state.scheduler = scheduler
    app.state.bot = bot

    yield

    logger.info("Shutting down...")
    if _bot_task:
        await stop_bot(bot, dp)
        _bot_task.cancel()
        try:
            await _bot_task
        except asyncio.CancelledError:
            pass
    await scheduler.stop()
    logger.info("Shutdown complete")


app = FastAPI(title="Vinted Monitor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")
app.include_router(web_router)
