from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.runtime_settings import (
    apply_global_settings_to_runtime,
    load_global_settings,
    mask_secret,
    save_global_settings,
)
from app.web.auth import get_current_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db, get_scraper_client, is_bot_running, start_bot, stop_bot

router = APIRouter(prefix="/api/v1", tags=["settings"])
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramErrorInfo:
    status_code: int
    code: str
    detail: str


class TelegramSettingsUpdate(BaseModel):
    telegram_bot_token: str | None = Field(default=None, max_length=512)
    telegram_chat_id: str | None = Field(default=None, max_length=128)
    clear_token: bool = False
    clear_chat_id: bool = False


class CloudflareWorkerUpdate(BaseModel):
    cf_worker_url: str | None = Field(default=None, max_length=2048)
    cf_worker_block_threshold: int | None = None
    cf_worker_recovery_minutes: int | None = None
    cf_worker_mode: str | None = Field(default=None, pattern="^(auto|direct|worker)$")


class ScraperSettingsUpdate(BaseModel):
    proxies: str | None = Field(default=None, max_length=4096)
    clear_proxies: bool = False
    sessions_per_domain: int | None = None
    rate_limit_per_minute: int | None = None
    check_interval_seconds: int | None = None
    offpeak_interval_multiplier: float | None = None
    night_interval_multiplier: float | None = None
    peak_start_hour: int | None = None
    peak_end_hour: int | None = None


async def require_api_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def require_api_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await require_api_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _coerce_int(value: str) -> int:
    return int(value)


def _coerce_float(value: str) -> float:
    return float(value)


def _telegram_payload(user: User) -> dict[str, object]:
    token = user.telegram_bot_token or ""
    chat_id = user.telegram_chat_id or ""
    return {
        "token_configured": bool(token),
        "token_masked": mask_secret(token),
        "chat_id_configured": bool(chat_id),
        "chat_id_masked": mask_secret(chat_id),
        "bot_running": is_bot_running(token) if token else False,
        "is_telegram_enabled": user.is_telegram_enabled,
    }


def _telegram_error_response(error: TelegramErrorInfo) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "code": error.code, "detail": error.detail},
        status_code=error.status_code,
    )


def _classify_telegram_error(exc: Exception) -> TelegramErrorInfo:
    class_name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    text = f"{class_name}: {message}"

    if "retry after" in text or "too many requests" in text or "rate limit" in text:
        return TelegramErrorInfo(
            status_code=429,
            code="telegram_rate_limited",
            detail="Telegram rate limit reached. Wait a bit before trying again.",
        )

    if any(marker in text for marker in ("conflict", "getupdates", "already running", "webhook", "polling")):
        return TelegramErrorInfo(
            status_code=409,
            code="telegram_bot_busy",
            detail=(
                "Telegram bot is busy or already running elsewhere. "
                "Stop other bot sessions/webhooks and try again. "
                "Another process may already be using this bot token."
            ),
        )

    if "blocked" in text or "forbidden" in text:
        return TelegramErrorInfo(
            status_code=403,
            code="telegram_bot_blocked",
            detail="The bot cannot message this chat. Make sure the bot is not blocked and has access to the chat.",
        )

    if "chat not found" in text or "user not found" in text:
        return TelegramErrorInfo(
            status_code=400,
            code="telegram_chat_not_found",
            detail="Telegram chat was not found. Open Telegram, start the bot, then try again.",
        )

    if isinstance(exc, ValueError) or "invalid chat" in text or "chat id" in text:
        return TelegramErrorInfo(
            status_code=400,
            code="telegram_invalid_chat_id",
            detail="Telegram chat ID looks invalid. Check the chat ID and save it again.",
        )

    if any(marker in text for marker in ("tokenvalidationerror", "unauthorized", "invalid token", "bot token")):
        return TelegramErrorInfo(
            status_code=400,
            code="telegram_invalid_token",
            detail="Telegram bot token looks invalid. Check the token from BotFather and save it again.",
        )

    if any(
        marker in text
        for marker in (
            "telegramnetworkerror",
            "telegramservererror",
            "timeout",
            "timed out",
            "connection",
            "unavailable",
            "bad gateway",
            "server error",
        )
    ):
        return TelegramErrorInfo(
            status_code=503,
            code="telegram_unavailable",
            detail="Telegram is unavailable or timed out. Try again in a moment.",
        )

    return TelegramErrorInfo(
        status_code=502,
        code="telegram_test_failed",
        detail="Telegram test message failed. Check your bot token, chat ID, and bot access, then try again.",
    )


def _global_settings_payload(saved: dict[str, str]) -> dict[str, object]:
    proxies = saved.get("proxies", "")
    return {
        "cloudflare_worker": {
            "url": saved["cf_worker_url"],
            "configured": bool(saved["cf_worker_url"]),
            "block_threshold": _coerce_int(saved["cf_worker_block_threshold"]),
            "recovery_minutes": _coerce_int(saved["cf_worker_recovery_minutes"]),
        },
        "scraper": {
            "proxies_configured": bool(proxies),
            "proxies_masked": mask_secret(proxies, visible=8),
            "sessions_per_domain": _coerce_int(saved["sessions_per_domain"]),
            "rate_limit_per_minute": _coerce_int(saved["rate_limit_per_minute"]),
            "check_interval_seconds": _coerce_int(saved["check_interval_seconds"]),
            "offpeak_interval_multiplier": _coerce_float(saved["offpeak_interval_multiplier"]),
            "night_interval_multiplier": _coerce_float(saved["night_interval_multiplier"]),
            "peak_start_hour": _coerce_int(saved["peak_start_hour"]),
            "peak_end_hour": _coerce_int(saved["peak_end_hour"]),
        },
    }


async def _settings_response(db: AsyncSession, user: User) -> dict[str, object]:
    payload: dict[str, object] = {
        "user": {
            "id": user.id,
            "username": user.username,
            "is_admin": user.is_admin,
        },
        "telegram": _telegram_payload(user),
        "cloudflare_worker": {
            "url": user.cf_worker_url,
            "configured": bool(user.cf_worker_url),
            "block_threshold": user.cf_worker_block_threshold,
            "recovery_minutes": user.cf_worker_recovery_minutes,
            "mode": user.cf_worker_mode,
        },
        "can_edit_global_settings": user.is_admin,
    }
    if user.is_admin:
        payload["global_settings"] = _global_settings_payload(await load_global_settings(db))
    return payload


def _updated_settings(saved: dict[str, str], updates: dict[str, Any]) -> dict[str, object]:
    updated: dict[str, object] = dict(saved)
    for key, value in updates.items():
        if value is not None:
            updated[key] = value
    return updated


@router.get("/settings")
async def get_settings_api(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    return await _settings_response(db, user)


@router.patch("/settings/telegram", dependencies=[Depends(require_api_csrf)])
async def update_telegram_settings(
    request: TelegramSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    old_token = user.telegram_bot_token or ""

    if request.clear_token:
        user.telegram_bot_token = ""
    elif request.telegram_bot_token is not None:
        user.telegram_bot_token = request.telegram_bot_token.strip()

    if request.clear_chat_id:
        user.telegram_chat_id = ""
    elif request.telegram_chat_id is not None:
        user.telegram_chat_id = request.telegram_chat_id.strip()

    await db.commit()

    if old_token and old_token != user.telegram_bot_token:
        await stop_bot(old_token)

    await db.refresh(user)
    return {"telegram": _telegram_payload(user)}


@router.patch("/settings/cloudflare-worker", dependencies=[Depends(require_api_csrf)])
async def update_cloudflare_worker_settings(
    request: CloudflareWorkerUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    if request.cf_worker_url is not None:
        if request.cf_worker_url:
            # Validate URL
            try:
                from urllib.parse import urlparse
                parsed = urlparse(request.cf_worker_url.strip())
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ValueError
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid Worker URL")
            user.cf_worker_url = request.cf_worker_url.strip().rstrip("/")
        else:
            user.cf_worker_url = ""

    if request.cf_worker_block_threshold is not None:
        if not (1 <= request.cf_worker_block_threshold <= 20):
            raise HTTPException(status_code=422, detail="Block threshold must be between 1 and 20")
        user.cf_worker_block_threshold = request.cf_worker_block_threshold
    
    if request.cf_worker_recovery_minutes is not None:
        if not (1 <= request.cf_worker_recovery_minutes <= 1440):
            raise HTTPException(status_code=422, detail="Recovery minutes must be between 1 and 1440")
        user.cf_worker_recovery_minutes = request.cf_worker_recovery_minutes

    if request.cf_worker_mode is not None:
        user.cf_worker_mode = request.cf_worker_mode
        logger.info(f"DEBUG: Setting cf_worker_mode to {user.cf_worker_mode} for user {user.id}")

    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"DEBUG: cf_worker_mode after commit/refresh: {user.cf_worker_mode}")
    return {"cloudflare_worker": {
        "url": user.cf_worker_url,
        "configured": bool(user.cf_worker_url),
        "block_threshold": user.cf_worker_block_threshold,
        "recovery_minutes": user.cf_worker_recovery_minutes,
        "mode": user.cf_worker_mode,
    }}


@router.patch("/settings/scraper", dependencies=[Depends(require_api_csrf)])
async def update_scraper_settings(
    request: ScraperSettingsUpdate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_admin),
):
    saved = await load_global_settings(db)
    proxies = "" if request.clear_proxies else request.proxies
    raw = _updated_settings(
        saved,
        {
            "proxies": proxies,
            "sessions_per_domain": request.sessions_per_domain,
            "rate_limit_per_minute": request.rate_limit_per_minute,
            "check_interval_seconds": request.check_interval_seconds,
            "offpeak_interval_multiplier": request.offpeak_interval_multiplier,
            "night_interval_multiplier": request.night_interval_multiplier,
            "peak_start_hour": request.peak_start_hour,
            "peak_end_hour": request.peak_end_hour,
        },
    )
    try:
        cleaned = await save_global_settings(db, raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    await db.commit()
    await apply_global_settings_to_runtime(cleaned, get_scraper_client(http_request))
    return {"global_settings": _global_settings_payload(cleaned)}


@router.get("/telegram/status")
async def telegram_status(
    user: User = Depends(require_api_user),
):
    return {"telegram": _telegram_payload(user)}


@router.post("/telegram/start", dependencies=[Depends(require_api_csrf)])
async def telegram_start(
    user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    token = user.telegram_bot_token or ""
    if not token:
        raise HTTPException(status_code=400, detail="Telegram bot token is not configured")
    
    user.is_telegram_enabled = True
    await db.commit()
    await db.refresh(user)

    message = await start_bot(token, owner_user_id=user.id)
    return {"ok": True, "message": message, "telegram": _telegram_payload(user)}


@router.post("/telegram/stop", dependencies=[Depends(require_api_csrf)])
async def telegram_stop(
    user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    token = user.telegram_bot_token or ""
    
    user.is_telegram_enabled = False
    await db.commit()
    await db.refresh(user)
    
    result = await stop_bot(token)
    if not result.ok:
        return JSONResponse(
            {
                "ok": False,
                "code": result.state,
                "detail": result.message,
                "telegram": _telegram_payload(user),
            },
            status_code=503,
        )
    return {"ok": True, "message": result.message, "telegram": _telegram_payload(user)}


async def _send_telegram_test_message(token: str, chat_id: str) -> None:
    from app.telegram.bot import get_or_create_bot

    bot, _ = get_or_create_bot(token)
    await bot.send_message(
        int(chat_id),
        "Test message from Vinted Monitor.",
        parse_mode="HTML",
    )


@router.post("/telegram/test", dependencies=[Depends(require_api_csrf)])
async def telegram_test(
    user: User = Depends(require_api_user),
):
    token = user.telegram_bot_token or ""
    chat_id = user.telegram_chat_id or ""
    if not token or not chat_id:
        return _telegram_error_response(
            TelegramErrorInfo(
                status_code=400,
                code="telegram_credentials_missing",
                detail="Telegram credentials are not configured. Add your bot token and chat ID first.",
            )
        )

    try:
        await _send_telegram_test_message(token, chat_id)
    except Exception as exc:
        error = _classify_telegram_error(exc)
        logger.warning("Telegram test message failed for user_id=%s code=%s", user.id, error.code)
        return _telegram_error_response(error)

    return {"ok": True, "message": "Telegram test message sent", "telegram": _telegram_payload(user)}
