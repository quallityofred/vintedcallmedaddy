# app/telegram/notifications.py
import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.scraper.parser import VintedItem

logger = logging.getLogger(__name__)

COUNTRY_FLAGS: dict[str, str] = {
    "vinted.fr": "🇫🇷",
    "vinted.de": "🇩🇪",
    "vinted.co.uk": "🇬🇧",
    "vinted.it": "🇮🇹",
    "vinted.es": "🇪🇸",
    "vinted.pl": "🇵🇱",
    "vinted.nl": "🇳🇱",
    "vinted.be": "🇧🇪",
    "vinted.cz": "🇨🇿",
    "vinted.lt": "🇱🇹",
    "vinted.pt": "🇵🇹",
    "vinted.at": "🇦🇹",
    "vinted.lu": "🇱🇺",
    "vinted.sk": "🇸🇰",
    "vinted.dk": "🇩🇰",
    "vinted.fi": "🇫🇮",
    "vinted.se": "🇸🇪",
    "vinted.ro": "🇷🇴",
    "vinted.hu": "🇭🇺",
    "vinted.hr": "🇭🇷",
    "vinted.gr": "🇬🇷",
    "vinted.com": "🌍",
}


def _build_keyboard(item: VintedItem) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Открыть на Vinted", url=item.item_url),
                InlineKeyboardButton(
                    text="Скрыть продавца",
                    callback_data=f"hide:{item.seller_id}",
                ),
            ]
        ]
    )


async def send_item_notification(bot: Bot, chat_id: int, item: VintedItem) -> None:
    flag = COUNTRY_FLAGS.get(item.domain, "🌍")
    caption = (
        f"🆕 <b>Новый товар!</b>\n"
        f"Название: {item.title}\n"
        f"Цена: {item.price} {item.currency}\n"
        f"Размер: {item.size}\n"
        f"Бренд: {item.brand}\n"
        f"Состояние: {item.condition}\n"
        f"Домен: {flag} {item.domain}"
    )
    keyboard = _build_keyboard(item)

    try:
        if item.photo_url:
            await bot.send_photo(
                chat_id=chat_id,
                photo=item.photo_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )
    except Exception:
        logger.exception("Failed to send notification for item_id=%d", item.id)


async def send_batch(
    bot: Bot, chat_id: int, items: list[VintedItem]
) -> None:
    if not items:
        return

    if len(items) > 5:
        lines = ["🆕 <b>Найдены новые товары:</b>\n"]
        for item in items:
            lines.append(
                f"• <a href=\"{item.item_url}\">{item.title}</a> — "
                f"{item.price} {item.currency}"
            )
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="\n".join(lines),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Failed to send batch notification")
        return

    for item in items:
        await send_item_notification(bot, chat_id, item)
        await asyncio.sleep(0.5)
