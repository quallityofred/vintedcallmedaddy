import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.telegram.settings_store import (
    get_active_telegram_user,
    set_active_telegram_user_id,
)

if TYPE_CHECKING:
    from app.scheduler.tasks import MonitorScheduler

logger = logging.getLogger(__name__)

_scheduler: "MonitorScheduler | None" = None
_bot_instance: Bot | None = None
_bot_task: asyncio.Task | None = None
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


def get_bot() -> Bot | None:
    return _bot_instance


def is_bot_running() -> bool:
    return _bot_task is not None and not _bot_task.done()


async def _persist_active_bot_owner(user_id: int | None) -> None:
    async with AsyncSessionLocal() as db:
        await set_active_telegram_user_id(db, user_id)
        await db.commit()


async def restore_persisted_bot() -> str | None:
    if is_bot_running():
        return None

    async with AsyncSessionLocal() as db:
        user = await get_active_telegram_user(db)

    if user is not None:
        return await start_bot(user.telegram_bot_token, owner_user_id=user.id, persist=False)

    if settings.telegram_bot_token:
        return await start_bot(settings.telegram_bot_token, persist=False)

    return None


async def start_bot(
    token: str,
    owner_user_id: int | None = None,
    persist: bool = True,
) -> str:
    global _bot_instance, _bot_task, _bot_token
    if is_bot_running():
        return "Р‘РѕС‚ СѓР¶Рµ Р·Р°РїСѓС‰РµРЅ"
    try:
        from app.scheduler.tasks import set_telegram_bot
        from app.telegram.bot import get_or_create_bot, start_polling, terminate_all_sessions

        await terminate_all_sessions(token)
        bot, dp = get_or_create_bot(token)
        _bot_instance = bot
        _bot_token = token
        set_telegram_bot(bot)
        _bot_task = asyncio.create_task(start_polling(bot, dp))
        if persist:
            await _persist_active_bot_owner(owner_user_id)
        logger.info("Bot started via settings")
        return "Р‘РѕС‚ СѓСЃРїРµС€РЅРѕ Р·Р°РїСѓС‰РµРЅ"
    except Exception as e:
        logger.exception("Failed to start bot")
        _bot_instance = None
        _bot_token = ""
        return f"РћС€РёР±РєР° Р·Р°РїСѓСЃРєР°: {e}"


async def stop_bot(clear_persisted_state: bool = True) -> str:
    global _bot_instance, _bot_task, _bot_token
    if not is_bot_running():
        if clear_persisted_state:
            await _persist_active_bot_owner(None)
        return "Р‘РѕС‚ РЅРµ Р·Р°РїСѓС‰РµРЅ"
    try:
        from app.scheduler.tasks import set_telegram_bot
        from app.telegram.bot import get_or_create_bot
        from app.telegram.bot import stop_bot as telegram_stop_bot

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
        if clear_persisted_state:
            await _persist_active_bot_owner(None)
        logger.info("Bot stopped via settings")
        return "Р‘РѕС‚ РѕСЃС‚Р°РЅРѕРІР»РµРЅ"
    except Exception as e:
        logger.exception("Failed to stop bot")
        return f"РћС€РёР±РєР° РѕСЃС‚Р°РЅРѕРІРєРё: {e}"


async def send_test_message(token: str, chat_id: str) -> str:
    try:
        from aiogram.client.default import DefaultBotProperties

        test_bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
        await test_bot.send_message(
            chat_id=int(chat_id),
            text="вњ… <b>РўРµСЃС‚РѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ</b>\nVinted Monitor СЂР°Р±РѕС‚Р°РµС‚ РєРѕСЂСЂРµРєС‚РЅРѕ!",
        )
        await test_bot.session.close()
        return "РўРµСЃС‚РѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ РѕС‚РїСЂР°РІР»РµРЅРѕ"
    except Exception as e:
        logger.exception("Test message failed")
        return f"РћС€РёР±РєР°: {e}"