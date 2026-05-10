# app/telegram/bot.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.telegram.handlers import router

logger = logging.getLogger(__name__)

_bots: dict[str, Bot] = {}
_dispatchers: dict[str, Dispatcher] = {}
_polling_tasks: dict[str, asyncio.Task] = {}


async def terminate_all_sessions(token: str) -> None:
    """Kill ALL bot sessions on Telegram servers before starting a new one."""
    try:
        async with Bot(token=token).context() as temp_bot:
            await temp_bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(1.0)
        logger.info("All previous bot sessions terminated")
    except Exception:
        logger.exception("Failed to terminate previous bot sessions")


def get_or_create_bot(token: str) -> tuple[Bot, Dispatcher]:
    """Returns the Bot + Dispatcher for a specific token."""
    global _bots, _dispatchers
    if token in _bots and token in _dispatchers:
        return _bots[token], _dispatchers[token]
    
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    
    _bots[token] = bot
    _dispatchers[token] = dp
    return bot, dp


async def start_polling(bot: Bot, dp: Dispatcher) -> None:
    """Start polling for a specific bot."""
    token = bot.token
    if token in _polling_tasks and not _polling_tasks[token].done():
        logger.warning("Polling already running for this token, skipping")
        return

    task = asyncio.create_task(dp.start_polling(bot))
    _polling_tasks[token] = task
    try:
        await task
    except Exception:
        logger.exception("Telegram polling crashed for bot")
    finally:
        _polling_tasks.pop(token, None)


async def stop_bot(bot: Bot, dp: Dispatcher) -> None:
    """Gracefully stop polling and close session for a specific bot."""
    token = bot.token
    try:
        if token in _polling_tasks:
            await dp.stop_polling()
            task = _polling_tasks.get(token)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
    except Exception:
        logger.exception("Error stopping polling")
    
    try:
        await bot.session.close()
    except Exception:
        logger.exception("Error closing bot session")
    
    _bots.pop(token, None)
    _dispatchers.pop(token, None)
    _polling_tasks.pop(token, None)
