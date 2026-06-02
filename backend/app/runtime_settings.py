from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AppSettings

logger = logging.getLogger(__name__)
settings = get_settings()

GLOBAL_SETTING_KEYS = {
    "proxies",
    "sessions_per_domain",
    "rate_limit_per_minute",
    "cf_worker_url",
    "cf_worker_block_threshold",
    "cf_worker_recovery_minutes",
    "check_interval_seconds",
    "offpeak_interval_multiplier",
    "night_interval_multiplier",
    "peak_start_hour",
    "peak_end_hour",
}


def mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    suffix = value[-visible:] if len(value) > visible else value
    return f"******{suffix}"


async def get_db_setting(db: AsyncSession, key: str, default: str = "") -> str:
    result = await db.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


async def set_db_setting(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
        return
    db.add(AppSettings(key=key, value=value))


async def load_global_settings(db: AsyncSession) -> dict[str, str]:
    return {
        "proxies": await get_db_setting(db, "proxies", settings.proxies),
        "sessions_per_domain": await get_db_setting(
            db, "sessions_per_domain", str(settings.sessions_per_domain)
        ),
        "rate_limit_per_minute": await get_db_setting(
            db, "rate_limit_per_minute", str(settings.rate_limit_per_minute)
        ),
        "cf_worker_url": await get_db_setting(db, "cf_worker_url", settings.cf_worker_url),
        "cf_worker_block_threshold": await get_db_setting(
            db, "cf_worker_block_threshold", str(settings.cf_worker_block_threshold)
        ),
        "cf_worker_recovery_minutes": await get_db_setting(
            db, "cf_worker_recovery_minutes", str(settings.cf_worker_recovery_minutes)
        ),
        "check_interval_seconds": await get_db_setting(
            db, "check_interval_seconds", str(settings.check_interval_seconds)
        ),
        "offpeak_interval_multiplier": await get_db_setting(
            db, "offpeak_interval_multiplier", str(settings.offpeak_interval_multiplier)
        ),
        "night_interval_multiplier": await get_db_setting(
            db, "night_interval_multiplier", str(settings.night_interval_multiplier)
        ),
        "peak_start_hour": await get_db_setting(
            db, "peak_start_hour", str(settings.peak_start_hour)
        ),
        "peak_end_hour": await get_db_setting(
            db, "peak_end_hour", str(settings.peak_end_hour)
        ),
    }


def _bounded_int(value: int | str, minimum: int, maximum: int) -> str:
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"Value must be between {minimum} and {maximum}")
    return str(parsed)


def _bounded_float(value: float | str, minimum: float, maximum: float) -> str:
    parsed = float(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"Value must be between {minimum:g} and {maximum:g}")
    return f"{parsed:g}"


def _clean_url(value: str) -> str:
    url = value.strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Cloudflare Worker URL must be a valid http(s) URL")
    return url.rstrip("/")


def validate_global_settings(raw: dict[str, object]) -> dict[str, str]:
    return {
        "proxies": str(raw.get("proxies", "")).strip(),
        "sessions_per_domain": _bounded_int(raw.get("sessions_per_domain", 3), 1, 10),
        "rate_limit_per_minute": _bounded_int(raw.get("rate_limit_per_minute", 8), 1, 30),
        "cf_worker_url": _clean_url(str(raw.get("cf_worker_url", ""))),
        "cf_worker_block_threshold": _bounded_int(
            raw.get("cf_worker_block_threshold", 2), 1, 20
        ),
        "cf_worker_recovery_minutes": _bounded_int(
            raw.get("cf_worker_recovery_minutes", 10), 1, 1440
        ),
        "check_interval_seconds": _bounded_int(raw.get("check_interval_seconds", 120), 30, 86400),
        "offpeak_interval_multiplier": _bounded_float(
            raw.get("offpeak_interval_multiplier", 2.5), 1.0, 24.0
        ),
        "night_interval_multiplier": _bounded_float(
            raw.get("night_interval_multiplier", 5.0), 1.0, 24.0
        ),
        "peak_start_hour": _bounded_int(raw.get("peak_start_hour", 8), 0, 23),
        "peak_end_hour": _bounded_int(raw.get("peak_end_hour", 23), 0, 23),
    }


async def save_global_settings(db: AsyncSession, raw: dict[str, object]) -> dict[str, str]:
    cleaned = validate_global_settings(raw)
    for key, value in cleaned.items():
        await set_db_setting(db, key, value)
    return cleaned


def apply_settings_values(saved: dict[str, str]) -> None:
    settings.proxies = saved["proxies"]
    settings.sessions_per_domain = int(saved["sessions_per_domain"])
    settings.rate_limit_per_minute = int(saved["rate_limit_per_minute"])
    settings.cf_worker_url = saved["cf_worker_url"]
    settings.cf_worker_block_threshold = int(saved["cf_worker_block_threshold"])
    settings.cf_worker_recovery_minutes = int(saved["cf_worker_recovery_minutes"])
    settings.check_interval_seconds = int(saved["check_interval_seconds"])
    settings.offpeak_interval_multiplier = float(saved["offpeak_interval_multiplier"])
    settings.night_interval_multiplier = float(saved["night_interval_multiplier"])
    settings.peak_start_hour = int(saved["peak_start_hour"])
    settings.peak_end_hour = int(saved["peak_end_hour"])


async def apply_global_settings_to_runtime(saved: dict[str, str], scraper_client=None) -> None:
    apply_settings_values(saved)

    if scraper_client is not None:
        scraper_client.rate_limiter.rate = float(settings.rate_limit_per_minute)
        try:
            from app.scraper.client import CloudflareFallback

            scraper_client.cf_fallback = (
                CloudflareFallback(
                    worker_url=settings.cf_worker_url,
                    block_threshold=settings.cf_worker_block_threshold,
                    recovery_minutes=settings.cf_worker_recovery_minutes,
                )
                if settings.cf_worker_url
                else None
            )
        except Exception:
            logger.exception("Failed to refresh Cloudflare Worker fallback settings")
        try:
            await scraper_client.close()
        except Exception:
            logger.exception("Failed to refresh scraper sessions after settings update")

    try:
        import app.scheduler.tasks as scheduler_tasks
        import app.scraper.client as scraper_client_module

        scheduler_tasks.settings = settings
        scraper_client_module.settings.proxies = settings.proxies
        scraper_client_module.settings.sessions_per_domain = settings.sessions_per_domain
        scraper_client_module.settings.rate_limit_per_minute = settings.rate_limit_per_minute
        scraper_client_module.settings.cf_worker_url = settings.cf_worker_url
        scraper_client_module.MAX_CONCURRENT_DOMAINS = settings.sessions_per_domain
        scraper_client_module._domain_semaphore = asyncio.Semaphore(settings.sessions_per_domain)
    except Exception:
        logger.exception("Failed to apply scraper concurrency settings")


async def apply_db_runtime_settings() -> None:
    from app.database import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as db:
        saved = await load_global_settings(db)
    await apply_global_settings_to_runtime(saved)
