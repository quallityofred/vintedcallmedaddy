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
- `backend/app/telegram/topic_service.py`
- `backend/app/telegram/settings_store.py`
- `backend/app/templates/settings.html`

## Backlog Acknowledgement And Pipeline V2

- `POST /api/v1/diagnostics/notifications/ack-pending-no-notify` is admin/API-CSRF protected and requires a monitor ID. Dry-run reads only; apply mode marks a bounded oldest-first set of pending `FoundItem` rows as notified without calling Telegram.
- Cleanup is idempotent, monitor-scoped, redacted, and does not touch `SeenItem`, monitor state, scraper execution, or notification delivery code. Status: `issue/fixed`.
- `backend/app/telegram/pipeline_v2.py` defines a default-off future delivery contract. It preserves success-only acknowledgement and retryable failures but is not wired into the live worker while `NOTIFICATION_PIPELINE_V2_ENABLED=false`.
- Future durable notification jobs should be DB-backed and restart-safe; no migration or runtime switch is included in the current skeleton.
- `ack-pending-no-notify` changes only `FoundItem.notified`; scheduler dedupe independently consults Found/Seen history, so acknowledging a backlog cannot make those items eligible for rediscovery. No Telegram delivery behavior changed.

## Runtime Flow

- Bot tokens are stored per user.
- `restore_persisted_bot()` restarts polling for users with saved token and chat ID.
- Command handlers update chat IDs, report status, and attempt seller-hiding actions.
- Settings UI token/chat fields are write-only/masked. Blank submitted values keep existing saved credentials.
- Telegram bot token and chat ID are not required backend deployment environment variables.
- New item notifications are sent with the monitor owner's saved Telegram token/chat ID, not deployment-global credentials when user credentials exist.
- Notification messages use safe HTML escaping and include monitor name, item title, price, optional brand/size/condition/seller, source domain, and item URL.
- Failed notification sends leave the `FoundItem` pending for retry instead of marking it notified.
- Telegram forum topic routing has backend foundations only. It is per-user, disabled by default, stores mappings in `monitor_telegram_topics`, and returns only masked chat/thread identifiers through APIs.
- Topic mappings include monitor/user/chat/thread, topic name, status, safe error code/message, created/updated timestamps, and last verification time. `telegram_topics_recreate_deleted` defaults to false to avoid recreating deleted topics without an explicit user choice.
- Topic creation uses a unique `(monitor_id, chat_id)` mapping plus a `creating` status to avoid duplicate DB rows and suppress duplicate Telegram topic creation during concurrent ensure calls. If Telegram creates a topic but the DB commit fails, an orphan Telegram topic can still occur.
- Topic titles are based only on the cleaned monitor name. The service does not append marketplace/domain or `#monitor_id`; empty names fall back to `Monitor`.
- When an active mapping has an old verbose stored name, ensure/sending attempts to rename the Telegram topic with `editForumTopic` while preserving the same `message_thread_id`. Rename failures store a safe error but do not block notification delivery to the existing thread.
- Automatic notification routing now resolves a target in `process_pending_notifications()`: disabled users are skipped; topic-disabled users use the existing main chat with no topic lookup; topic-enabled users ensure/reuse a monitor topic and send with `message_thread_id`; main-chat fallback is used only when `telegram_topics_fallback_to_main_chat` is true.
- Topic send failures are classified back onto the topic row and leave `FoundItem.notified=False` for retry.
- `GET /api/v1/monitors/telegram-topics` is a read-only batch status endpoint for the monitors page. It returns stored current-user topic mappings with masked thread IDs, does not call Telegram, and does not ensure/create topics.
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
- 2026-06-04: Added Telegram forum topic backend foundation: topic settings APIs, forum group verification, monitor topic ensure/test APIs, `message_thread_id` support in low-level sends, and safe classification for missing threads, closed topics, permissions, unreachable chats, and rate limits.
- 2026-06-04: Wired automatic `FoundItem` notification delivery into topic routing behind `telegram_topics_enabled`, with lazy topic creation/reuse, explicit fallback behavior, safe diagnostics, and retry-preserving failures.
- 2026-06-05: Topic name normalization now uses only monitor name text and syncs old active verbose topic names without recreating topics.
- 2026-06-05: Added batch monitor topic status loading for the frontend so `/monitors` no longer issues one topic GET per monitor card.
- 2026-06-05: Item notification price formatting now uses static approximate USD conversion from `app.pricing.currency`. Non-USD messages include the original price/currency plus an approximate USD value, USD prices are not duplicated, and topic routing uses the same formatter unchanged.
- 2026-06-08: The pending notification diagnostic endpoint now returns real scoped counts and bounded redacted samples in dry-run mode. Explicit live batches share the same candidate selection, enforce global 25/sec plus private/unknown 1/sec or group 20/min limits, rate-limit photo and text fallback attempts separately, respect Telegram `retry_after`, and mark `FoundItem.notified=true` only after successful delivery. The periodic worker remains disabled by default.
- 2026-06-08: Fixed `issue/fixed` cross-monitor delivery caused by `check_monitor()` launching an unscoped global pending drain after creating findings. Check-triggered processing now passes the monitor ID, the core live processor rejects missing scope unless an internal caller explicitly opts into all-monitor mode, and async job status retains requested scope plus truthful live side effects. Failed rows and rows owned by other monitors remain pending.
- 2026-06-08: Production core now includes a dedicated "Send All Pending" job for monitors via `POST /api/v1/monitors/{id}/notifications/send-pending-jobs`. This job performs sequential batch processing using the shared `send_all_pending_for_monitor` helper, which loops until the monitor's backlog is cleared or a safety batch limit is hit. Status polling reports progress across batches, total items sent, and pending count.
