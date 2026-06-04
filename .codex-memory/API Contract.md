---
type: contract
project: vintedbot
status: draft
severity: high
tags:
  - vintedbot
  - core/api-contract
  - status/draft
  - severity/high
  - component/api
  - component/frontend
  - component/backend
created: 2026-06-03
updated: 2026-06-04
---

# API Contract

Source verified against `Projects/vintedbot` on 2026-06-03. This note inventories the current backend/frontend API state for the split FastAPI + Next.js app. It intentionally stores no secrets.

## API Principles

- Frontend browser code should call relative `/api/...` paths.
- `frontend/next.config.ts` rewrites `/api/:path*` to `${BACKEND_URL}/api/:path*`.
- FastAPI owns auth, sessions, CSRF, database access, scheduler state, scraper state, Telegram integration, and user isolation.
- New Next-ready endpoints should use versioned `/api/v1/...` paths.
- Legacy Jinja/HTMX route modules were removed after Next replacements and API-first tests existed. Do not reintroduce them without an explicit compatibility decision and tests.
- State-changing JSON endpoints must require `X-CSRF-Token`.
- Token-like values must be masked or write-only; never return Telegram tokens, password hashes/salts, proxy credentials, cookies, or session values.

## Current Frontend API Usage

- `frontend/src/components/login-form.tsx`
  - `GET /api/v1/auth/csrf`
  - `POST /api/v1/auth/login`
- `frontend/src/components/register-form.tsx`
  - `GET /api/v1/auth/csrf`
  - `POST /api/v1/auth/register`
- `frontend/src/lib/auth.ts`
  - `GET /api/v1/auth/me`
- `frontend/src/components/backend-health-card.tsx`
  - `GET /api/health`
- `frontend/src/app/dashboard/page.tsx`
  - guarded by `GET /api/v1/auth/me`
  - uses `/api/v1/dashboard/stats`, `/api/v1/monitors`, `/api/v1/items`, `/api/v1/hidden-sellers`, `/api/v1/system/status`, and monitor mutation/control endpoints.
- `frontend/src/app/settings/page.tsx`
  - guarded by `GET /api/v1/auth/me`
  - uses `/api/v1/telegram/status`, `/api/v1/settings/telegram`, and Telegram control endpoints.
- `frontend/src/app/admin/page.tsx`
  - guarded by `GET /api/v1/auth/me` and `user.is_admin`
  - uses `/api/v1/admin/invites`.

## Existing Endpoints

### System Status

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | JSON | public | Liveness response: `status`, `service`. |
| `GET` | `/api/health` | JSON | public | Extended health: `status`, `scheduler_jobs`, `bots_running`. Used by Next dashboard health card. |
| `GET` | `/` | redirect/JSON | public | Production redirects to `FRONTEND_URL` when configured; otherwise minimal JSON backend status. Development returns safe JSON backend status. |

### Auth, CSRF, Me, Logout

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/auth/csrf` | JSON | public | Returns CSRF token. Uses session token when logged in; sets anonymous HttpOnly API CSRF seed cookie before login. |
| `GET` | `/api/v1/auth/me` | JSON | session | Returns `user.id`, `user.username`, `user.is_admin`. Returns `401` when unauthenticated. |
| `POST` | `/api/v1/auth/login` | JSON | CSRF | Accepts JSON username/password. Creates existing `session_token` HttpOnly cookie. Returns safe user payload and session CSRF token. |
| `POST` | `/api/v1/auth/register` | JSON | CSRF | Accepts JSON username/password confirmation/invite code. Consumes invite code atomically, creates user and session cookie, returns safe user payload and session CSRF token. |
| `POST` | `/api/v1/auth/logout` | JSON | session + CSRF | Deletes DB session and clears cookies. |

### Registration and Invites

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/admin/invites` | JSON | admin | Lists invite codes without exposing secrets. |
| `POST` | `/api/v1/admin/invites` | JSON | admin + CSRF | Creates invite code. |
| `DELETE` | `/api/v1/admin/invites/{invite_id}` | JSON | admin + CSRF | Deletes invite code. |

### Dashboard and Logs

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/dashboard/stats` | JSON | session | User-scoped counts for monitors, items, last found, and Telegram status. |
| `GET` | `/api/v1/admin/logs` | JSON | admin | Admin-only safe log summary. |

### Monitors

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/monitors/domains` | JSON | public | Returns unique user-selectable Vinted marketplace representatives plus alias metadata. Aliases are not selectable monitor targets. |
| `GET` | `/api/v1/monitors` | JSON | session | User-scoped monitor list. Returns selected representative `domains` for each monitor. |
| `POST` | `/api/v1/monitors` | JSON | session + CSRF | Creates user-scoped monitor and schedules job. |
| `GET` | `/api/v1/monitors/{monitor_id}` | JSON | session | User-scoped monitor detail. Returns selected representative `domains`. |
| `PATCH` | `/api/v1/monitors/{monitor_id}` | JSON | session + CSRF | Updates user-scoped monitor, selected representative `domains`, and scheduler job. |
| `DELETE` | `/api/v1/monitors/{monitor_id}` | JSON | session + CSRF | Deletes user-scoped monitor and removes scheduler job. |
| `POST` | `/api/v1/monitors/bulk-delete` | JSON | session + CSRF | User-scoped bulk delete. |
| `POST` | `/api/v1/monitors/{monitor_id}/pause` | JSON | session + CSRF | Pauses user-scoped monitor. |
| `POST` | `/api/v1/monitors/{monitor_id}/resume` | JSON | session + CSRF | Resumes user-scoped monitor. |
| `POST` | `/api/v1/monitors/{monitor_id}/check-now` | JSON | session + CSRF | Triggers user-scoped monitor check. |

### Settings, Telegram, CF Worker, Scraper Settings

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/settings` | JSON | session | Returns safe user payload, masked Telegram state, and admin-only global settings. Proxy values are masked/configured-only. |
| `PATCH` | `/api/v1/settings/telegram` | JSON | session + CSRF | Write-only per-user Telegram token/chat ID update. Supports explicit clearing. Returns masked Telegram state only. |
| `PATCH` | `/api/v1/settings/cloudflare-worker` | JSON | session + CSRF | Updates the current user's CF Worker URL, block threshold, recovery minutes, and routing mode. Accepts `cf_worker_mode` values `auto`, `direct`, and `worker`; `worker` requires a configured Worker URL. |
| `PATCH` | `/api/v1/settings/scraper` | JSON | admin + CSRF | Updates admin/global scraper defaults such as sessions, rate limit, intervals, peak hours, and write-only/masked proxies; applies runtime settings. |
| `GET` | `/api/v1/telegram/status` | JSON | session | Returns masked/configured Telegram state and whether the current user's bot is running. |
| `POST` | `/api/v1/telegram/start` | JSON | session + CSRF | Starts the current user's saved Telegram bot token without returning the token. |
| `POST` | `/api/v1/telegram/stop` | JSON | session + CSRF | Stops the current user's Telegram bot without returning the token. Successful stops return masked state. Stop timeout/incomplete cases return safe `ok: false`, `code`, and `detail` while leaving `bot_running: true`. |
| `POST` | `/api/v1/telegram/test` | JSON | session + CSRF | Sends a test message using saved per-user credentials; failures return safe structured `code` and `detail` fields without exposing token/chat values. |

Telegram API error codes currently used by the frontend:

- `telegram_credentials_missing`
- `telegram_invalid_token`
- `telegram_invalid_chat_id`
- `telegram_chat_not_found`
- `telegram_bot_blocked`
- `telegram_bot_busy`
- `telegram_unavailable`
- `telegram_rate_limited`
- `telegram_test_failed`
- `stop_timeout`
- `stop_incomplete`

Current settings ownership:

- Telegram token/chat ID: per-user `User` columns; UI masks saved values.
- CF Worker URL, block threshold, recovery minutes, and routing mode: per-user `User` columns.
- Scraper defaults: global admin `AppSettings` for proxies, sessions per domain, rate limit, check interval, off-peak/night multipliers, peak hours.
- Runtime settings apply to scraper client and scheduler where implemented.

### Items and Hidden Sellers

| Capability | Current State |
| --- | --- |
| Found items | Stored in `FoundItem`; exposed through `GET /api/v1/items` and `GET /api/v1/items/{item_id}` with user scoping. Cold-start baseline items are not inserted as user-visible found items; only genuinely new post-baseline items are stored here. |
| Seen items | Stored in `SeenItem`, used by scheduler dedup/cold-start behavior. Runtime treats stable Vinted item ID as user-level seen identity across selected domains; no direct public JSON API is currently needed. |
| Hidden sellers | Stored in `HiddenSeller`; exposed through `GET /api/v1/hidden-sellers`, `POST /api/v1/hidden-sellers`, and `DELETE /api/v1/hidden-sellers/{seller_id}` with user scoping and CSRF on mutations. |

## Missing or Follow-up Next-Ready Endpoints

Core Next-ready endpoints are implemented for auth/register/CSRF, settings/Telegram/CF Worker/scraper, monitors, dashboard stats, items, hidden sellers, system status, and admin invites. Remaining API follow-up is mostly polish and expansion:

- `GET /api/v1/dashboard/activity` for recent user-scoped activity/log rows.
- `POST /api/v1/monitors/import`, `GET /api/v1/monitors/export.json`, and `GET /api/v1/monitors/export.txt` if import/export is migrated to Next.
- `PATCH /api/v1/admin/invites/{invite_id}` if the Next admin UI needs toggle/edit semantics beyond create/delete.
- `GET /api/v1/system/logs` as admin-only if the Next admin UI needs system log viewing.

## Frontend Pages Needing APIs

- `/login`
  - has JSON login and sanitized `next` redirect handling.
- `/register`
  - has JSON registration and sanitized `next` redirect handling.
- `/dashboard`
  - uses current dashboard/monitor/item/system APIs; follow-up is UI polish and API client extraction.
- `/settings`
  - uses current Telegram and per-user CF Worker settings APIs; follow-up is full admin/global scraper form integration if needed in Next.
- Monitor pages
  - core CRUD/control exists; import/export remains optional follow-up.
- Items/logs pages
  - item history/detail exists; user activity feed and admin-only system logs remain optional follow-up.
- Admin pages
  - invite list/create/delete exists; invite toggle/edit remains optional follow-up.

## Safest Implementation Order

1. Auth/register/CSRF phase is complete for backend JSON endpoints: CSRF, me, login, register, logout.
2. Settings/Telegram/CF Worker/scraper phase is complete for backend JSON endpoints.
3. Monitors CRUD/control phase is complete for list/detail/create/update/delete/bulk delete/pause/resume/check-now.
4. Dashboard stats, item history/detail, hidden seller APIs, safe system status, and admin invite list/create/delete are complete.
5. Next phase: frontend API client extraction, UI polish, optional monitor import/export, optional dashboard activity feed, and optional admin invite toggle/edit.

## Related

- [[Issues/ISS-API-001 Full Next frontend API contract missing]]
- [[Components/FastAPI Routes]]
- [[Components/Frontend Next.js]]
- [[Components/Web Dashboard]]
- [[Components/Configuration and Deployment]]
- [[Components/Tests]]



## [2026-06-03] Update: Monitors Read API implemented.
- GET /api/v1/monitors
- GET /api/v1/monitors/{id}


## [2026-06-03] Update: Monitor Mutation APIs implemented.
- POST /api/v1/monitors
- PATCH /api/v1/monitors/{id}
- DELETE /api/v1/monitors/{id}
- POST /api/v1/monitors/bulk-delete
- POST /api/v1/monitors/{id}/pause
- POST /api/v1/monitors/{id}/resume
- POST /api/v1/monitors/{id}/check-now

## [2026-06-04] Update: Unique Vinted domain registry

- Fixed `GET /api/v1/monitors/domains` so it returns 200 instead of a backend 500.
- The endpoint now returns only curated representative marketplaces: `vinted.fr`, `vinted.de`, `vinted.pl`, `vinted.es`, `vinted.it`, `vinted.nl`, `vinted.pt`, and `vinted.co.uk`.
- Alias examples are exposed as metadata only, not user-selectable targets: `vinted.cz`, `vinted.sk`, `vinted.lt`, `vinted.hu`, `vinted.ro`, and `vinted.hr` map to `vinted.pl`; `vinted.at` maps to `vinted.de`; `vinted.ie` maps to `vinted.co.uk`; `vinted.be` and `vinted.lu` map to `vinted.fr`.
- Monitor create/update validates selected domains against representatives and rejects empty or unknown selections with clean `400` responses.
- Pasted Vinted URLs from known aliases resolve to the representative marketplace when deriving domains.
- URL parsing removes unstable `page`, `time`, `search_id`, and `utm_*` params while preserving stable catalog/brand/order filters.
- Scheduler processing now dedupes scraper results by stable Vinted item ID before DB inserts, protecting cross-domain notification behavior even if a scraper returns duplicate IDs.

## [2026-06-04] Update: Telegram test error contract

- `POST /api/v1/telegram/test` now classifies common Telegram setup/runtime failures into safe user-facing errors instead of returning one vague `502`.
- Missing credentials, invalid token, invalid chat ID, chat-not-found, blocked bot, bot busy/polling conflict, upstream timeout/unavailable, rate limit, and unknown failures are covered.
- Responses include only safe `code` and `detail` fields plus `ok: false`; token/chat values and raw upstream payloads are not returned.

## [2026-06-04] Update: Monitor selected domains response

- Monitor list/detail/create/update/pause/resume responses now include selected representative `domains`.
- The Next `/monitors` edit dialog uses those persisted domains to initialize a local draft and only sends updates on explicit submit.
- Closing the edit dialog with Escape/outside click/close discards unsaved draft changes and does not call `PATCH`.

## [2026-06-04] Update: Monitor runtime and Telegram notifications

- Cold-start monitor checks now establish `SeenItem` baseline state without creating `FoundItem` rows or Telegram notifications for existing catalog items.
- Repeat checks and cross-domain repeats use stable Vinted item ID per user to avoid duplicate `SeenItem`, `FoundItem`, and Telegram notifications.
- Truly new post-baseline items create `FoundItem(notified=False)` and are picked up by the notification worker.
- Notification delivery uses the monitor owner's saved Telegram token/chat ID. Message text uses safe HTML escaping and includes monitor name, item title, price, optional brand/size/condition/seller, source domain, and item URL.
- Failed Telegram sends leave the item pending instead of marking it notified.

## [2026-06-04] Update: Telegram bot stop/status contract

- Telegram long-polling stop now waits for the polling task to finish before removing runtime state.
- If stop times out or remains incomplete, `/api/v1/telegram/stop` returns a safe failure response instead of reporting stopped.
- `GET /api/v1/telegram/status` and `/api/health` count only live polling tasks and prune completed stale tasks.
- Telegram long polling remains a single-process/replica runtime. Multiple Railway replicas or another environment using the same token can still cause stop/status mismatch until a webhook or distributed-lock architecture is introduced.

## [2026-06-04] Update: CF Worker routing mode persistence

- `GET /api/v1/settings` and `PATCH /api/v1/settings/cloudflare-worker` expose `cloudflare_worker.mode` with safe fallback to `auto`.
- PATCH payload field is flat `cf_worker_mode`; frontend must not send nested `mode` or `cf_worker.mode`.
- Startup schema validation now adds missing `users.cf_worker_*` and `users.is_telegram_enabled` columns so Railway PostgreSQL does not rely on a manually executed one-off script for `cf_worker_mode`.
- `direct` and `auto` mode saves do not require a Worker URL. `worker` mode without URL returns a clear 422 detail.


## [2026-06-03] Update: Found Items and Hidden Sellers APIs implemented.
- GET /api/v1/items
- GET /api/v1/items/{item_id}
- GET /api/v1/hidden-sellers
- POST /api/v1/hidden-sellers
- DELETE /api/v1/hidden-sellers/{seller_id}


## [2026-06-03] Update: System and Admin APIs implemented.
- GET /api/v1/system/status
- GET /api/v1/admin/invites
- POST /api/v1/admin/invites
- DELETE /api/v1/admin/invites/{id}
- GET /api/v1/admin/logs


## [2026-06-03] Update: API-first legacy cleanup and frontend route guards

- Legacy backend Jinja route modules were removed after source verification:
  - `backend/app/web/router.py`
  - `backend/app/web/auth_router.py`
  - `backend/app/web/admin_router.py`
  - `backend/app/web/app_web_router.py`
- `backend/app/app_main.py` no longer registers legacy HTML routers. Backend `/` returns safe backend service JSON, or redirects to `FRONTEND_URL` in production when configured.
- Active public endpoints remain `/`, `/health`, `/api/health`, and `GET /api/v1/auth/csrf`.
- Active authenticated endpoints include `/api/v1/auth/me`, `/api/v1/auth/logout`, dashboard stats, monitors, items, hidden sellers, settings, Telegram controls, and system status.
- Active admin endpoints are under `/api/v1/admin/*`.
- CSRF-protected mutations include login/register/logout, settings updates, Telegram start/stop/test, monitor mutations/control, hidden seller mutations, and admin invite mutations.
- Next.js protected routes now guard `/dashboard`, `/settings`, and `/admin` through `GET /api/v1/auth/me`.
- Unauthenticated users redirect to `/login?next=/dashboard`, `/login?next=/settings`, or `/login?next=/admin`.
- Login and registration preserve a sanitized same-origin `next` path and default to `/dashboard`.
