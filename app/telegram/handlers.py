# app/telegram/handlers.py
import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import AppSettings, FoundItem, HiddenSeller, Monitor, User
from app.telegram.settings_store import update_user_chat_id_by_bot_token

logger = logging.getLogger(__name__)
router = Router()
AsyncSessionLocal = None


def _new_session() -> AsyncSession:
    session_factory = AsyncSessionLocal or get_session_factory()
    return session_factory()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    chat_id = str(message.chat.id)
    async with _new_session() as db:
        success = await update_user_chat_id_by_bot_token(db, message.bot.token, chat_id)
        await db.commit()
    if success:
        await message.answer("Бот подключен! Уведомления будут приходить сюда.")
    else:
        await message.answer("Ошибка: бот не найден в базе данных.")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    async with _new_session() as db:
        # Find user by token
        user_result = await db.execute(select(User).where(User.telegram_bot_token == message.bot.token))
        user = user_result.scalar_one_or_none()
        if not user:
            await message.answer("Ошибка: пользователь не найден.")
            return

        active_count_result = await db.execute(
            select(func.count(Monitor.id)).where(Monitor.is_active == True, Monitor.user_id == user.id)
        )
        active_count = active_count_result.scalar() or 0

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_items_result = await db.execute(
            select(func.count(FoundItem.id)).where(
                FoundItem.found_at >= today_start,
                FoundItem.monitor_id.in_(select(Monitor.id).where(Monitor.user_id == user.id))
            )
        )
        today_items = today_items_result.scalar() or 0

    await message.answer(
        f"📊 Статус ({user.username}):\n"
        f"Активных мониторов: {active_count}\n"
        f"Товаров найдено сегодня: {today_items}"
    )


@router.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    async with _new_session() as db:
        user_result = await db.execute(select(User).where(User.telegram_bot_token == message.bot.token))
        user = user_result.scalar_one_or_none()
        if not user: return

        result = await db.execute(select(Monitor).where(Monitor.is_active == True, Monitor.user_id == user.id))
        monitors = result.scalars().all()
        for monitor in monitors:
            monitor.is_active = False
        await db.commit()
    await message.answer("Ваши мониторы приостановлены.")



@router.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    async with _new_session() as db:
        user_result = await db.execute(select(User).where(User.telegram_bot_token == message.bot.token))
        user = user_result.scalar_one_or_none()
        if not user: return

        result = await db.execute(select(Monitor).where(Monitor.is_active == False, Monitor.user_id == user.id))
        monitors = result.scalars().all()
        for monitor in monitors:
            monitor.is_active = True
        await db.commit()
    await message.answer("Ваши мониторы возобновлены.")


@router.message(Command("list"))
async def cmd_list(message: Message) -> None:
    async with _new_session() as db:
        user_result = await db.execute(select(User).where(User.telegram_bot_token == message.bot.token))
        user = user_result.scalar_one_or_none()
        if not user: return

        result = await db.execute(select(Monitor).where(Monitor.user_id == user.id).order_by(Monitor.name))
        monitors = result.scalars().all()

    if not monitors:
        await message.answer("У вас нет мониторов.")
        return

    lines = ["📋 Ваши мониторы:"]
    for monitor in monitors:
        status_text = "🟢 активен" if monitor.is_active else "🔴 пауза"
        lines.append(f"• {monitor.name} — {status_text}")
    await message.answer("\n".join(lines))



@router.callback_query(lambda cb: cb.data and cb.data.startswith("hide:"))
async def hide_seller_handler(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    try:
        seller_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных.")
        return

    async with _new_session() as db:
        user_result = await db.execute(
            select(User).where(User.telegram_bot_token == callback.bot.token)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            await callback.answer("РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РЅР°Р№РґРµРЅ.")
            return

        existing_result = await db.execute(
            select(HiddenSeller).where(
                HiddenSeller.user_id == user.id,
                HiddenSeller.seller_id == seller_id,
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is None:
            db.add(HiddenSeller(user_id=user.id, seller_id=seller_id))
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
    await callback.answer("Продавец скрыт.")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
