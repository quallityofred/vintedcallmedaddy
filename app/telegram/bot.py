# app/telegram/bot.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.telegram.handlers import router

logger = logging.getLogger(__name__)

_bot_instance: Bot | None = None
_dp_instance: Dispatcher | None = None
_polling_started: bool = False


async def terminate_all_sessions(token: str) -> None:
    """Kill ALL bot sessions on Telegram servers before starting a new one."""
    try:
        temp_bot = Bot(token=token)
        await temp_bot.delete_webhook(drop_pending_updates=True)
        await temp_bot.session.close()
        await asyncio.sleep(2.0)
        logger.info("All previous bot sessions terminated")
    except Exception:
        logger.exception("Failed to terminate previous bot sessions")


def get_or_create_bot(token: str) -> tuple[Bot, Dispatcher]:
    """Singleton: returns the same Bot + Dispatcher on every call."""
    global _bot_instance, _dp_instance
    if _bot_instance is not None and _dp_instance is not None:
        return _bot_instance, _dp_instance
    _bot_instance = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    _dp_instance = Dispatcher()
    _dp_instance.include_router(router)
    return _bot_instance, _dp_instance


async def start_polling(bot: Bot, dp: Dispatcher) -> None:
    """Start polling exactly once. Idempotent — safe to call multiple times."""
    global _polling_started
    if _polling_started:
        logger.warning("Polling already running, skipping duplicate start")
        return
    _polling_started = True
    try:
        await dp.start_polling(bot)
    except Exception:
        _polling_started = False
        logger.exception("Telegram polling crashed")
        raise


async def stop_bot(bot: Bot, dp: Dispatcher) -> None:
    """Gracefully stop polling and close session. Resets singletons."""
    global _polling_started, _bot_instance, _dp_instance
    try:
        if _polling_started:
            await dp.stop_polling()
            _polling_started = False
    except Exception:
        logger.exception("Error stopping polling")
    try:
        await bot.session.close()
    except Exception:
        logger.exception("Error closing bot session")
    _bot_instance = None
    _dp_instance = None
