---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/database
---

# Database

## Purpose

- Defines models, async engine/session setup, lightweight migrations, and dedup constraints.

## Key Files

- `backend/app/app_database.py`
- `backend/app/models.py`
- `backend/app/runtime_settings.py`

## Runtime Flow

- `init_db()` creates tables and performs lightweight migrations.
- `validate_and_migrate_db()` ensures dedup indexes exist.
- `validate_and_migrate_db()` also applies lightweight user-column migrations for per-user Telegram/CF Worker runtime settings when production databases predate the current model.
- Async sessions are created through `get_session_factory()`, which resolves the current initialized factory from `app.app_database`.
- `AsyncSessionLocal` remains a compatibility export, but runtime code should avoid importing it by value before initialization.
- `AppSettings` stores admin/global scraper and Cloudflare Worker settings.
- Per-user Telegram bot token and chat ID remain on `User` and are never rendered back in full by the settings UI.

## Audit Notes

- `FoundItem` and `SeenItem` uniqueness constraints are present and aligned with dedup goals.
- `HiddenSeller` requires `user_id`, which makes the current Telegram callback failure easy to reason about.
- Invite-code usage is validated in application logic, but not consumed atomically under concurrency.

## Related Issues

- [[Issues/ISS-003 Hide seller flow is broken and not user-scoped|ISS-003]]
- [[Issues/ISS-007 Invite code consumption is race-prone|ISS-007]]
- [[Issues/ISS-RWY-002 AsyncSessionLocal None after startup|ISS-RWY-002]]

- 2026-06-02: Invite code consumption now uses a guarded SQLAlchemy `UPDATE` before user creation to preserve max-use limits.
- 2026-06-02: Railway PostgreSQL startup failure was confirmed to be caused by database service unavailability, not source code. Operational recovery should focus on Railway PostgreSQL service health and `DATABASE_URL` wiring. See [[Issues/ISS-RWY-001 Railway PostgreSQL startup failure|ISS-RWY-001]].
- 2026-06-02: Runtime database session access now uses dynamic session-factory accessors to avoid stale `AsyncSessionLocal = None` imports after startup. See [[Fixes/FIX-RWY-002 Database session dependency initialization|FIX-RWY-002]].
- 2026-06-03: Runtime settings are loaded from `AppSettings` on backend startup and can be updated by admins from the Jinja settings UI without requiring Railway env changes.
- 2026-06-04: Added startup migration coverage for missing `users.cf_worker_url`, `users.cf_worker_block_threshold`, `users.cf_worker_recovery_minutes`, `users.is_telegram_enabled`, and `users.cf_worker_mode`; invalid/null `cf_worker_mode` values normalize to `auto`.
- 2026-06-05: Scheduler monitor checks no longer hold an async DB session while waiting on Vinted network calls. This is paired with global/per-user scheduler backpressure to keep the small Supabase Session pooler connection budget from being consumed by long-running scraper operations.

