import html
from app.pricing.currency import format_price_with_usd
from app.scraper.parser import VintedItem

def escape_telegram_html(value: object, *, limit: int = 180) -> str:
    text = str(value or "")
    if len(text) > limit:
        text = f"{text[: max(limit - 3, 0)]}..."
    return html.escape(text, quote=False)

def format_price(item: VintedItem) -> str:
    try:
        return format_price_with_usd(item.price, item.currency)
    except Exception:
        if item.price <= 0:
            return "Not listed"
    return f"{item.price:g} {escape_telegram_html(item.currency)}".strip()

def optional_line(label: str, value: object) -> str | None:
    text = escape_telegram_html(value).strip()
    if not text or text == "None":
        return None
    return f"<b>{label}:</b> {text}"

def build_found_item_caption(item: VintedItem, monitor_name: str | None = None) -> str:
    lines = ["🆕 <b>New Vinted item found</b>"]

    monitor_line = optional_line("Monitor", monitor_name)
    if monitor_line:
        lines.append(monitor_line)

    lines.append(f"<b>Item:</b> {escape_telegram_html(item.title) or 'Untitled'}")
    lines.append(f"<b>Price:</b> {format_price(item)}")

    for label, value in (
        ("Brand", item.brand),
        ("Size", item.size),
        ("Condition", item.condition),
        ("Seller ID", item.seller_id if item.seller_id else None),
        ("Source", item.domain),
    ):
        line = optional_line(label, value)
        if line:
            lines.append(line)

    return "\n".join(lines)

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def build_found_item_keyboard(item: VintedItem) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text="Open on Vinted", url=item.item_url)]
    if item.seller_id:
        buttons.append(
            InlineKeyboardButton(
                text="Hide seller",
                callback_data=f"hide:{item.seller_id}",
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
