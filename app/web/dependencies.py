# app/web/dependencies.py
import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

if TYPE_CHECKING:
    from app.scheduler.tasks import MonitorScheduler

logger = logging.getLogger(__name__)

_scheduler: "MonitorScheduler | None" = None
_bot_instance: Bot | None = None
_bot_task: asyncio.Task | None = None
_bot_token: str = ""


def set_scheduler(scheduler: "MonitorScheduler") -> None:
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> "MonitorScheduler":
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized")
    return _scheduler


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_bot() -> Bot | None:
    return _bot_instance


def is_bot_running() -> bool:
    return _bot_task is not None and not _bot_task.done()


async def start_bot(token: str) -> str:
    global _bot_instance, _bot_task, _bot_token
    if is_bot_running():
        return "Бот уже запущен"
    try:
        from app.telegram.bot import get_or_create_bot, start_polling, terminate_all_sessions
        from app.scheduler.tasks import set_telegram_bot
        await terminate_all_sessions(token)
        bot, dp = get_or_create_bot(token)
        _bot_instance = bot
        _bot_token = token
        set_telegram_bot(bot)
        _bot_task = asyncio.create_task(start_polling(bot, dp))
        logger.info("Bot started via settings")
        return "Бот успешно запущен"
    except Exception as e:
        logger.exception("Failed to start bot")
        _bot_instance = None
        _bot_token = ""
        return f"Ошибка запуска: {e}"


async def stop_bot() -> str:
    global _bot_instance, _bot_task, _bot_token
    if not is_bot_running():
        return "Бот не запущен"
    try:
        from app.telegram.bot import stop_bot as telegram_stop_bot
        from app.telegram.bot import get_or_create_bot
        from app.scheduler.tasks import set_telegram_bot
        bot, dp = get_or_create_bot(_bot_token)
        await telegram_stop_bot(bot, dp)
        if _bot_task:
            _bot_task.cancel()
            try:
                await _bot_task
            except asyncio.CancelledError:
                pass
        _bot_instance = None
        _bot_task = None
        _bot_token = ""
        set_telegram_bot(None)
        logger.info("Bot stopped via settings")
        return "Бот остановлен"
    except Exception as e:
        logger.exception("Failed to stop bot")
        return f"Ошибка остановки: {e}"


async def send_test_message(token: str, chat_id: str) -> str:
    try:
        from aiogram.client.default import DefaultBotProperties
        test_bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
        await test_bot.send_message(
            chat_id=int(chat_id),
            text="✅ <b>Тестовое сообщение</b>\nVinted Monitor работает корректно!"
        )
        await test_bot.session.close()
        return "Тестовое сообщение отправлено"
    except Exception as e:
        logger.exception("Test message failed")
        return f"Ошибка: {e}"
