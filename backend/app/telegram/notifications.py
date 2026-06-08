import asyncio
import html
import logging
from typing import Literal, NoReturn

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.pricing.currency import format_price_with_usd
from app.scraper.parser import VintedItem

from app.telegram.rate_limiter import TelegramRateLimiter

logger = logging.getLogger(__name__)

# Initialize rate limiter
rate_limiter = TelegramRateLimiter()

# ... (rest of the file)


from app.telegram.formatter import (
    build_found_item_caption,
    build_found_item_keyboard,
)

from app.telegram.rate_limiter import TelegramRateLimiter

logger = logging.getLogger(__name__)

# Initialize rate limiter
rate_limiter = TelegramRateLimiter()

def _raise_last_failure(exc: BaseException | None) -> NoReturn:
    if exc is None:
        raise RuntimeError("Telegram notification failed")
    raise exc

async def send_item_notification(
    bot: Bot,
    chat_id: int,
    item: VintedItem,
    *,
    monitor_name: str | None = None,
    message_thread_id: int | None = None,
) -> Literal["photo", "text", "fallback_text"]:
    from aiogram.exceptions import TelegramRetryAfter

    caption = build_found_item_caption(item, monitor_name=monitor_name)
    keyboard = build_found_item_keyboard(item)
    is_group = message_thread_id is not None or chat_id < 0

    async def send_text(*, fallback: bool) -> Literal["text", "fallback_text"]:
        last_error: BaseException | None = None
        for _attempt in range(3):
            try:
                await rate_limiter.acquire(chat_id, is_group=is_group)
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                    disable_web_page_preview=True, # Button exists, no raw URL preview needed
                    **thread_kwargs,
                )
                return "fallback_text" if fallback else "text"
            except TelegramRetryAfter as exc:
                last_error = exc
                logger.warning("Telegram flood control, retrying after %d seconds", exc.retry_after)
                await asyncio.sleep(exc.retry_after)
            except Exception as exc:
                logger.warning(
                    "Telegram text notification failed item_id=%d exception_type=%s",
                    item.id,
                    type(exc).__name__,
                )
                raise
        _raise_last_failure(last_error)

    thread_kwargs = {"message_thread_id": message_thread_id} if message_thread_id is not None else {}
    if not item.photo_url:
        return await send_text(fallback=False)

    last_error: BaseException | None = None
    for _attempt in range(3):
        try:
            await rate_limiter.acquire(chat_id, is_group=is_group)
            await bot.send_photo(
                chat_id=chat_id,
                photo=item.photo_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
                **thread_kwargs,
            )
            return "photo"
        except TelegramRetryAfter as exc:
            last_error = exc
            logger.warning("Telegram flood control, retrying after %d seconds", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
        except Exception as exc:
            logger.warning(
                "Telegram photo notification failed; using text fallback item_id=%d exception_type=%s",
                item.id,
                type(exc).__name__,
            )
            return await send_text(fallback=True)

    _raise_last_failure(last_error)


async def send_batch(
    bot: Bot, chat_id: int, items: list[VintedItem], *, message_thread_id: int | None = None
) -> None:
    if not items:
        return

    for item in items:
        await send_item_notification(bot, chat_id, item, message_thread_id=message_thread_id)
        await asyncio.sleep(0.5)
