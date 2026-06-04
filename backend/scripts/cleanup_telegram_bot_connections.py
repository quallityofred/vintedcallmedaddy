"""Safely clear Telegram webhook/pending-update state for one bot token.

Usage:
    Set-Location backend
    $env:TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
    poetry run python scripts/cleanup_telegram_bot_connections.py

The script reads credentials from environment variables only and never prints
the token, chat ID, or raw Telegram payloads.
"""
from __future__ import annotations

import asyncio
import os
import sys

from aiogram import Bot


async def cleanup_telegram_connections() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set.")
        return 2

    bot = Bot(token=token)
    try:
        webhook_info = await bot.get_webhook_info()
        webhook_present = bool(getattr(webhook_info, "url", ""))
        print(f"Webhook present: {'yes' if webhook_present else 'no'}")

        await bot.delete_webhook(drop_pending_updates=True)
        print("Webhook deleted and pending webhook updates dropped.")

        try:
            await bot.get_updates(offset=-1, limit=1, timeout=0)
            print("Pending long-poll updates cleanup attempted.")
        except Exception:
            print("Pending long-poll updates cleanup could not complete; another polling process may be active.")
        return 0
    except Exception:
        print("Telegram cleanup failed. Check the token and try again.")
        return 1
    finally:
        await bot.session.close()


def main() -> int:
    return asyncio.run(cleanup_telegram_connections())


if __name__ == "__main__":
    raise SystemExit(main())
