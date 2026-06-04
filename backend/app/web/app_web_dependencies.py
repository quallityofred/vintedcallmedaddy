# app/web/dependencies.py
"""
FastAPI dependency injection functions.

Provides:
  - get_db()                 → async DB session
  - get_current_user()       → User | None
  - require_user()           → User  (redirects to /login)
  - require_admin()          → User  (403 if not admin)
  - get_scheduler()          → MonitorScheduler | None
  - get_scraper_client()     → VintedClient | None
  - start_bot()              → start Telegram polling for a token
  - stop_bot()               → stop polling for a token
  - is_bot_running()         → bool
  - restore_persisted_bot()  → re-attach bots from DB on startup
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import User, UserSession

if TYPE_CHECKING:
    from app.scheduler.tasks import MonitorScheduler
    from app.scraper.client import VintedClient

logger = logging.getLogger(__name__)

SESSION_COOKIE = "session_token"


@dataclass(frozen=True)
class BotLifecycleResult:
    ok: bool
    state: str
    message: str
    running: bool


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the logged-in User or None if no valid session cookie exists."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    result = await db.execute(
        select(UserSession).where(UserSession.token == token)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    user_result = await db.execute(
        select(User).where(User.id == session.user_id)
    )
    return user_result.scalar_one_or_none()


async def require_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Return the current user or redirect to /login.

    Raises :class:`RequireLoginException` when unauthenticated so that the
    exception handler in ``main.py`` can issue the redirect.
    """
    user = await get_current_user(request, db)
    if user is None:
        raise RequireLoginException()
    return user


async def require_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Return the current user only if they are an admin."""
    user = await require_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class RequireLoginException(Exception):
    """Raised by require_user() to trigger a redirect to /login."""


# ---------------------------------------------------------------------------
# Application-state accessors
# ---------------------------------------------------------------------------

def get_scheduler(request: Request) -> "MonitorScheduler | None":
    """Return the MonitorScheduler stored on app.state, or None."""
    return getattr(request.app.state, "scheduler", None)


def get_scraper_client(request: Request) -> "VintedClient | None":
    """Return the VintedClient stored on app.state, or None."""
    return getattr(request.app.state, "scraper_client", None)


# ---------------------------------------------------------------------------
# Bot lifecycle helpers
# ---------------------------------------------------------------------------

def _live_polling_task(token: str) -> asyncio.Task | None:
    """Return the active polling task for *token*, pruning stale completed tasks."""
    from app.telegram.bot import _polling_tasks

    task = _polling_tasks.get(token)
    if task is not None and task.done():
        _polling_tasks.pop(token, None)
        return None
    return task


def is_bot_running(token: str) -> bool:
    """Return True if there is an active polling task for *token*."""
    from app.telegram.bot import _polling_errors
    if token in _polling_errors:
        return False
    return _live_polling_task(token) is not None


def count_running_bots() -> int:
    """Return the number of active polling tasks, pruning completed tasks first."""
    from app.telegram.bot import _polling_tasks

    running = 0
    for token, task in list(_polling_tasks.items()):
        if task.done():
            _polling_tasks.pop(token, None)
        else:
            running += 1
    return running


async def _polling_wrapper(bot, dp, token: str) -> None:
    """Internal coroutine that runs polling and cleans up _polling_tasks on exit."""
    import app.telegram.bot as bot_module
    current_task = asyncio.current_task()
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        error_msg = f"Polling crashed: {type(e).__name__}"
        bot_module._polling_errors[token] = error_msg
        logger.exception("Telegram polling crashed for token=...%s", token[-6:])
    finally:
        if bot_module._polling_tasks.get(token) is current_task:
            bot_module._polling_tasks.pop(token, None)


async def start_bot(token: str, owner_user_id: int | None = None) -> str:
    """
    Start Telegram long-polling for *token*.

    Stores the polling asyncio.Task directly in bot._polling_tasks so that
    is_bot_running() returns True as soon as the task is created — without
    depending on the internal task-registration inside start_polling().

    If a polling task already exists and is alive the call is a no-op.
    Returns a human-readable result string (Russian, for the UI).
    """
    if not token or not token.strip():
        return "Ошибка: неверный формат токена"

    if is_bot_running(token):
        return "Бот уже запущен"

    try:
        import app.telegram.bot as bot_module
        from app.telegram.bot import get_or_create_bot, terminate_all_sessions
        
        bot_module._polling_errors.pop(token, None)
        await terminate_all_sessions(token)
        bot, dp = get_or_create_bot(token)

        # Create the task and register it BEFORE the first await so that
        # is_bot_running() is True immediately after this function returns.
        task = asyncio.create_task(_polling_wrapper(bot, dp, token))
        bot_module._polling_tasks[token] = task

        # Yield control so the task can start running
        await asyncio.sleep(0.1)
        
        if task.done():
            exc = task.exception()
            if exc:
                raise exc
            raise Exception("Polling task exited immediately")

        logger.info("Telegram bot polling started for user_id=%s", owner_user_id)
        return "Бот успешно запущен"
    except Exception as exc:
        logger.exception("Failed to start bot")
        try:
            import app.telegram.bot as bot_module
            bot_module._polling_tasks.pop(token, None)
        except Exception:
            pass
        return f"Ошибка запуска: {exc}"


async def stop_bot(token: str, timeout: float = 5.0) -> BotLifecycleResult:
    """Cancel the polling task for *token* and close the bot session."""
    from app.telegram.bot import _polling_tasks, _bots

    task = _live_polling_task(token)
    if task is None:
        bot = _bots.pop(token, None)
        if bot:
            try:
                await bot.session.close()
            except Exception:
                logger.debug("Ignoring error while closing stopped Telegram bot session", exc_info=True)
        return BotLifecycleResult(
            ok=True,
            state="already_stopped",
            message="Telegram bot is already stopped",
            running=False,
        )

    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        return BotLifecycleResult(
            ok=False,
            state="stop_timeout",
            message="Telegram bot did not stop within the timeout. It may still be shutting down.",
            running=True,
        )
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Telegram polling task ended with an error during stop")

    if not task.done():
        return BotLifecycleResult(
            ok=False,
            state="stop_incomplete",
            message="Telegram bot stop did not complete. Try again in a moment.",
            running=True,
        )

    if _polling_tasks.get(token) is task:
        _polling_tasks.pop(token, None)

    bot = _bots.pop(token, None)
    if bot:
        try:
            await bot.session.close()
        except Exception:
            logger.debug("Ignoring error while closing Telegram bot session", exc_info=True)

    logger.info("Telegram bot polling stopped")
    return BotLifecycleResult(
        ok=True,
        state="stopped",
        message="Telegram bot stopped",
        running=False,
    )


async def restore_persisted_bot(app_state) -> None:
    """
    On application startup, re-start Telegram polling for every user that
    has a configured bot token.  Called from the FastAPI lifespan handler.
    """
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(User).where(
                    User.telegram_bot_token != "",
                    User.telegram_chat_id != "",
                    User.is_telegram_enabled == True,
                )
            )
            users = result.scalars().all()

        for user in users:
            if user.telegram_bot_token and user.is_telegram_enabled:
                try:
                    result = await start_bot(user.telegram_bot_token, owner_user_id=user.id)
                    logger.info(
                        "Restored bot for user %s: %s", user.username, result
                    )
                except Exception:
                    logger.exception("Failed to restore bot for user %s", user.username)
    except Exception:
        logger.exception("restore_persisted_bot failed")
