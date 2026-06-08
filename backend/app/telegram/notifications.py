import asyncio
import html
import logging
from typing import NoReturn

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.pricing.currency import format_price_with_usd
from app.scraper.parser import VintedItem

from app.telegram.rate_limiter import TelegramRateLimiter

logger = logging.getLogger(__name__)

# Initialize rate limiter
rate_limiter = TelegramRateLimiter()

# ... (rest of the file)


def _escape(value: object, *, limit: int = 180) -> str:
    text = str(value or "")
    if len(text) > limit:
        text = f"{text[: max(limit - 3, 0)]}..."
    return html.escape(text, quote=False)


def _format_price(item: VintedItem) -> str:
    try:
        return format_price_with_usd(item.price, item.currency)
    except Exception:
        logger.exception("Failed to format price for item_id=%d", item.id)
    try:
        if item.price <= 0:
            return "Not listed"
    except Exception:
        return "Not listed"
    return f"{item.price:g} {_escape(item.currency)}".strip()


def _optional_line(label: str, value: object) -> str | None:
    text = _escape(value).strip()
    if not text:
        return None
    return f"<b>{label}:</b> {text}"


def _build_caption(item: VintedItem, monitor_name: str | None = None) -> str:
    lines = ["🆕 <b>New Vinted item found</b>"]

    monitor_line = _optional_line("Monitor", monitor_name)
    if monitor_line:
        lines.append(monitor_line)

    lines.append(f"<b>Item:</b> {_escape(item.title) or 'Untitled'}")
    lines.append(f"<b>Price:</b> {_format_price(item)}")

    for label, value in (
        ("Brand", item.brand),
        ("Size", item.size),
        ("Condition", item.condition),
        ("Seller", item.seller_id if item.seller_id else None),
        ("Source", item.domain),
    ):
        line = _optional_line(label, value)
        if line:
            lines.append(line)

    if item.item_url:
        safe_url = html.escape(item.item_url, quote=True)
        lines.append(f'<a href="{safe_url}">Open item</a>')

    return "\n".join(lines)


def _build_keyboard(item: VintedItem) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text="Open on Vinted", url=item.item_url)]
    if item.seller_id:
        buttons.append(
            InlineKeyboardButton(
                text="Hide seller",
                callback_data=f"hide:{item.seller_id}",
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


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
) -> None:
    from aiogram.exceptions import TelegramRetryAfter

    caption = _build_caption(item, monitor_name=monitor_name)
    keyboard = _build_keyboard(item)
    last_error: BaseException | None = None

    for _attempt in range(3):
        try:
            # Apply rate limiting before sending
            await rate_limiter.acquire(chat_id)

            thread_kwargs = {"message_thread_id": message_thread_id} if message_thread_id is not None else {}
            if item.photo_url:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=item.photo_url,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                    **thread_kwargs,
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                    disable_web_page_preview=False,
                    **thread_kwargs,
                )
            return
        except TelegramRetryAfter as exc:
            last_error = exc
            logger.warning("Telegram flood control, retrying after %d seconds", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
        except Exception as exc:
            logger.exception("Failed to send Telegram notification for item_id=%d", item.id)
            raise exc

    _raise_last_failure(last_error)


async def send_batch(
    bot: Bot, chat_id: int, items: list[VintedItem], *, message_thread_id: int | None = None
) -> None:
    if not items:
        return

    for item in items:
        await send_item_notification(bot, chat_id, item, message_thread_id=message_thread_id)
        await asyncio.sleep(0.5)
