---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/telegram
---

# Telegram Bot

## Purpose

- Runs per-user Telegram bots, receives commands, stores chat IDs, and sends notifications.

## Key Files

- `backend/app/telegram/bot.py`
- `backend/app/telegram/handlers.py`
- `backend/app/telegram/notifications.py`
- `backend/app/telegram/settings_store.py`
- `backend/app/templates/settings.html`

## Runtime Flow

- Bot tokens are stored per user.
- `restore_persisted_bot()` restarts polling for users with saved token and chat ID.
- Command handlers update chat IDs, report status, and attempt seller-hiding actions.
- Settings UI token/chat fields are write-only/masked. Blank submitted values keep existing saved credentials.
- Telegram bot token and chat ID are not required backend deployment environment variables.
- New item notifications are sent with the monitor owner's saved Telegram token/chat ID, not deployment-global credentials when user credentials exist.
- Notification messages use safe HTML escaping and include monitor name, item title, price, optional brand/size/condition/seller, source domain, and item URL.
- Failed notification sends leave the `FoundItem` pending for retry instead of marking it notified.
- Telegram long-polling runtime is tracked by live asyncio tasks keyed by bot token. Stop waits for task termination before clearing runtime state; timeout/incomplete stops remain reported as running.
- `backend/scripts/cleanup_telegram_bot_connections.py` can clear Telegram webhook/pending-update state using `TELEGRAM_BOT_TOKEN` from the process environment only. It must not print token/chat values.

## Audit Notes

- Seller hiding is currently broken because the callback writes `HiddenSeller` incorrectly.
- Notification dispatch is guarded so token/chat values are not returned or stored in memory notes.

## Related Issues

- [[Issues/ISS-003 Hide seller flow is broken and not user-scoped|ISS-003]]
- [[Issues/ISS-009 Notification worker can crash on invalid Telegram tokens|ISS-009]]

- 2026-06-02: Hide-seller callbacks now resolve the owning user by bot token and persist `HiddenSeller(user_id, seller_id)` safely.
- 2026-06-03: Fixed [[Issues/ISS-011 Settings page exposes saved Telegram credentials|ISS-011]]; saved Telegram credentials are no longer rendered in full in the Jinja settings page.
- 2026-06-03: Added versioned Telegram JSON APIs for status/start/stop/test and write-only credential updates through `/api/v1/settings/telegram`. Responses return masked/configured state only and state-changing calls require API CSRF.
- 2026-06-04: Fixed [[Issues/ISS-TG-001 Telegram test returns vague 502|ISS-TG-001]]. `/api/v1/telegram/test` now classifies missing credentials, invalid token/chat, chat-not-found, blocked bot, bot busy/polling conflict, rate limit, timeout/unavailable, and unknown failures into safe `code`/`detail` responses without returning token/chat values.
- 2026-06-04: Runtime notification formatting was rebuilt around safe HTML and per-user delivery. `process_pending_notifications()` passes monitor names into the formatter and leaves failed sends unnotified for retry.
- 2026-06-04: Telegram Stop behavior was hardened so UI/status cannot report stopped while a polling task is still alive. `/api/health` now counts live tasks through the same runtime helper.
