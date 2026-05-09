# app/telegram/handlers.py
import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models import AppSettings, FoundItem, HiddenSeller, Monitor
from app.telegram.settings_store import update_user_chat_id_by_bot_token

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    chat_id = str(message.chat.id)
    async with AsyncSessionLocal() as db:
        await update_user_chat_id_by_bot_token(db, message.bot.token, chat_id)
        setting = await db.get(AppSettings, "telegram_chat_id")
        if setting is None:
            setting = AppSettings(key="telegram_chat_id", value=chat_id)
            db.add(setting)
        else:
            setting.value = chat_id
        await db.commit()
    await message.answer("Бот подключен! Уведомления будут приходить сюда.")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    async with AsyncSessionLocal() as db:
        active_count_result = await db.execute(
            select(func.count(Monitor.id)).where(Monitor.is_active == True)
        )
        active_count = active_count_result.scalar() or 0

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_items_result = await db.execute(
            select(func.count(FoundItem.id)).where(FoundItem.found_at >= today_start)
        )
        today_items = today_items_result.scalar() or 0

    await message.answer(
        f"📊 Статус:\n"
        f"Активных мониторов: {active_count}\n"
        f"Товаров найдено сегодня: {today_items}"
    )


@router.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Monitor).where(Monitor.is_active == True))
        monitors = result.scalars().all()
        for monitor in monitors:
            monitor.is_active = False
        await db.commit()
    await message.answer("Все мониторы приостановлены.")


@router.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Monitor).where(Monitor.is_active == False))
        monitors = result.scalars().all()
        for monitor in monitors:
            monitor.is_active = True
        await db.commit()
    await message.answer("Все мониторы возобновлены.")


@router.message(Command("list"))
async def cmd_list(message: Message) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Monitor).order_by(Monitor.name))
        monitors = result.scalars().all()

    if not monitors:
        await message.answer("Нет мониторов.")
        return

    lines = ["📋 Список мониторов:"]
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

    async with AsyncSessionLocal() as db:
        existing = await db.get(HiddenSeller, seller_id)
        if existing is None:
            hidden = HiddenSeller(seller_id=seller_id)
            db.add(hidden)
            await db.commit()
    await callback.answer("Продавец скрыт.")
    await callback.message.edit_reply_markup(reply_markup=None)
