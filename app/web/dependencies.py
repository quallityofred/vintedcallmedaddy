import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import User
from app.telegram.settings_store import (
    get_active_telegram_user,
    set_active_telegram_user_id,
)

if TYPE_CHECKING:
    from app.scheduler.tasks import MonitorScheduler

logger = logging.getLogger(__name__)

_scheduler: "MonitorScheduler | None" = None
_bot_token: str = ""

settings = get_settings()


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


def get_bot(token: str | None = None) -> Bot | None:
    from app.telegram.bot import _bots
    if token:
        return _bots.get(token)
    return None


def is_bot_running(token: str | None = None) -> bool:
    from app.telegram.bot import _polling_tasks
    if token:
        task = _polling_tasks.get(token)
        return task is not None and not task.done()
    return False


async def restore_persisted_bot() -> str | None:
    """Restores ALL user-configured bots on startup."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.telegram_bot_token != "")
        )
        users = result.scalars().all()

    started_count = 0
    for user in users:
        res = await start_bot(user.telegram_bot_token, owner_user_id=user.id)
        if "успешно" in res:
            started_count += 1

    return f"Восстановлено {started_count} ботов"


async def start_bot(
    token: str,
    owner_user_id: int | None = None,
) -> str:
    if is_bot_running(token):
        return "Бот уже запущен"

    try:
        from app.telegram.bot import get_or_create_bot, start_polling, terminate_all_sessions

        # Terminate other sessions for THIS token
        await terminate_all_sessions(token)
        bot, dp = get_or_create_bot(token)
        
        # Start polling in background
        asyncio.create_task(start_polling(bot, dp))
        
        logger.info(f"Bot started for user_id={owner_user_id}")
        return "Бот успешно запущен"
    except Exception as e:
        logger.exception(f"Failed to start bot for user_id={owner_user_id}")
        return f"Ошибка запуска: {e}"


async def stop_bot(token: str) -> str:
    if not is_bot_running(token):
        return "Бот не запущен"
    try:
        from app.telegram.bot import get_or_create_bot
        from app.telegram.bot import stop_bot as telegram_stop_bot

        bot, dp = get_or_create_bot(token)
        await telegram_stop_bot(bot, dp)
        logger.info(f"Bot stopped for token {token[:10]}...")
        return "Бот остановлен"
    except Exception as e:
        logger.exception(f"Failed to stop bot for token {token[:10]}...")
        return f"Ошибка остановки: {e}"


async def stop_all_bots() -> None:
    from app.telegram.bot import _bots, get_shared_dispatcher, stop_bot as telegram_stop_bot
    tokens = list(_bots.keys())
    dp = get_shared_dispatcher()
    for token in tokens:
        bot = _bots.get(token)
        if bot:
            await telegram_stop_bot(bot, dp)
    logger.info("All bots stopped")





async def send_test_message(token: str, chat_id: str) -> str:
    try:
        from aiogram.client.default import DefaultBotProperties

        test_bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
        await test_bot.send_message(
            chat_id=int(chat_id),
            text="✅ <b>Тестовое сообщение</b>\nVinted Monitor работает корректно!",
        )
        await test_bot.session.close()
        return "Тестовое сообщение отправлено"
    except Exception as e:
        logger.exception("Test message failed")
        return f"Ошибка: {e}"