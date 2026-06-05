---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/scheduler
---

# Scheduler

## Purpose

- Periodically checks monitors, writes deduplicated items, and triggers Telegram notifications.

## Key Files

- `app/scheduler/tasks.py`
- `app/scheduler/app_scheduler_tasks.py`
- `app/models.py`

## Runtime Flow

- `app.app_main` creates `MonitorScheduler`.
- Scheduler loads active monitors and registers APScheduler interval jobs.
- `check_monitor()` performs scraping, deduplication, hidden-seller filtering, and notification enqueueing.
- `process_pending_notifications()` sends unsent items.
- Cold-start checks write only `SeenItem` baseline rows; they do not create user-visible `FoundItem` rows or Telegram notifications.
- Post-baseline checks treat stable Vinted item ID as the per-user seen identity across selected domains. Repeated item IDs do not create duplicate found items or notifications.
- `FoundItem(notified=False)` represents a genuinely new post-baseline finding ready for Telegram delivery.

## Audit Notes

- DB-level deduplication is preserved for both `SeenItem` and `FoundItem`.
- Existing schema uniqueness still includes domain, but runtime checks `SeenItem(user_id, vinted_item_id)` before inserting so cross-domain repeats are suppressed.
- Hidden-seller filtering is only as correct as the callback that writes `HiddenSeller`.
- There is a duplicate scheduler implementation file that can drift from the canonical one.

## Related Issues

- [[Issues/ISS-003 Hide seller flow is broken and not user-scoped|ISS-003]]
- [[Issues/ISS-005 Duplicate implementation modules shadow runtime behavior|ISS-005]]
- [[Issues/ISS-009 Notification worker can crash on invalid Telegram tokens|ISS-009]]

- 2026-06-02: Notification worker now guards bot acquisition and chat-id parsing; `app.scheduler.tasks` is canonical and `app_scheduler_tasks.py` re-exports it.
- 2026-06-04: Runtime verification tightened cold-start and cross-domain dedup behavior. Telegram send failures no longer mark items notified; pending items remain retryable.
- 2026-06-05: Scheduler checks now apply a post-fetch monitor-filter guard before writing `SeenItem` or `FoundItem`. For brand-filtered monitors, items with non-matching `brand_id` or missing `brand_id` are skipped to prevent unrelated-brand notifications. Check logs include safe raw/accepted/skipped counts and cold-start state.
