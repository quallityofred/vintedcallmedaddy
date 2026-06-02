# app/telegram/bot.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.telegram.handlers import router

logger = logging.getLogger(__name__)

_bots: dict[str, Bot] = {}
_shared_dispatcher: Dispatcher | None = None
_polling_tasks: dict[str, asyncio.Task] = {}


def get_shared_dispatcher() -> Dispatcher:
    global _shared_dispatcher
    if _shared_dispatcher is None:
        _shared_dispatcher = Dispatcher()
        _shared_dispatcher.include_router(router)
    return _shared_dispatcher

async def terminate_all_sessions(token: str) -> None:
    """Kill ALL bot sessions on Telegram servers before starting a new one."""
    try:
        # Use context manager for temporary bot to ensure session closure
        bot = Bot(token=token)
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.session.close()
        await asyncio.sleep(1.0)
        logger.info("All previous bot sessions terminated")
    except Exception:
        logger.exception("Failed to terminate previous bot sessions")


def get_or_create_bot(token: str) -> tuple[Bot, Dispatcher]:
    """Returns the Bot + Shared Dispatcher for a specific token."""
    global _bots
    if token in _bots:
        return _bots[token], get_shared_dispatcher()
    
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    _bots[token] = bot
    return bot, get_shared_dispatcher()


async def start_polling(bot: Bot, dp: Dispatcher) -> None:
    """Start polling for a specific bot."""
    token = bot.token
    if token in _polling_tasks and not _polling_tasks[token].done():
        logger.warning("Polling already running for this token, skipping")
        return

    # In Aiogram 3, you can call start_polling on the same dispatcher multiple times with different bots
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
        task = _polling_tasks.get(token)
        if task and not task.done():
            # In aiogram 3, we don't have a simple way to stop polling for a SINGLE bot 
            # if multiple bots are running on the same dispatcher, 
            # unless we manage the tasks ourselves.
            # Cancelling the task is the most direct way for individual bots.
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    except Exception:
        logger.exception("Error stopping polling")
    
    try:
        await bot.session.close()
    except Exception:
        logger.exception("Error closing bot session")
    
    _bots.pop(token, None)
    _polling_tasks.pop(token, None)

