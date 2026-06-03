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
updated: 2026-06-03
---

# API Contract

Source verified against `Projects/vintedbot` on 2026-06-03. This note inventories the current backend/frontend API state for the split FastAPI + Next.js app. It intentionally stores no secrets.

## API Principles

- Frontend browser code should call relative `/api/...` paths.
- `frontend/next.config.ts` rewrites `/api/:path*` to `${BACKEND_URL}/api/:path*`.
- FastAPI owns auth, sessions, CSRF, database access, scheduler state, scraper state, Telegram integration, and user isolation.
- New Next-ready endpoints should use versioned `/api/v1/...` paths.
- Existing Jinja/HTMX routes should remain stable until a Next replacement has equivalent behavior and tests.
- State-changing JSON endpoints must require `X-CSRF-Token`.
- Token-like values must be masked or write-only; never return Telegram tokens, password hashes/salts, proxy credentials, cookies, or session values.

## Current Frontend API Usage

- `frontend/src/components/login-form.tsx`
  - `GET /api/v1/auth/csrf`
  - `POST /api/v1/auth/login`
- `frontend/src/components/backend-health-card.tsx`
  - `GET /api/health`
- `frontend/src/app/dashboard/page.tsx`
  - still renders `API pending` dashboard cards.
  - references future `/api/v1/monitors`.
- `frontend/src/app/settings/page.tsx`
  - still renders disabled placeholder settings UI.
- `frontend/src/components/monitor-preview.tsx`
  - demo placeholder; no backend calls.

## Existing Endpoints

### System Status

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | JSON | public | Liveness response: `status`, `service`. |
| `GET` | `/api/health` | JSON | public | Extended health: `status`, `scheduler_jobs`, `bots_running`. Used by Next dashboard health card. |
| `GET` | `/` | redirect/JSON | public | Production redirects to `FRONTEND_URL` when configured; otherwise minimal JSON backend status. Development redirects to `/dashboard`. |

### Auth, CSRF, Me, Logout

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/auth/csrf` | JSON | public | Returns CSRF token. Uses session token when logged in; sets anonymous HttpOnly API CSRF seed cookie before login. |
| `GET` | `/api/v1/auth/me` | JSON | session | Returns `user.id`, `user.username`, `user.is_admin`. Returns `401` when unauthenticated. |
| `POST` | `/api/v1/auth/login` | JSON | CSRF | Accepts JSON username/password. Creates existing `session_token` HttpOnly cookie. Returns safe user payload and session CSRF token. |
| `POST` | `/api/v1/auth/register` | JSON | CSRF | Accepts JSON username/password confirmation/invite code. Consumes invite code atomically, creates user and session cookie, returns safe user payload and session CSRF token. |
| `POST` | `/api/v1/auth/logout` | JSON | session + CSRF | Deletes DB session and clears cookies. |
| `GET` | `/login` | HTML | public/session-aware | Legacy Jinja login. Redirects authenticated users to `/dashboard`. |
| `POST` | `/login` | HTML form | public | Legacy Jinja login. Does not expose password hashes. |
| `POST` | `/logout` | redirect | session + CSRF | Legacy logout. |

### Registration and Invites

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/register` | HTML | public/session-aware | Legacy Jinja registration form. |
| `POST` | `/register` | HTML form | public | Legacy registration with invite code. Uses atomic invite consumption helper. |
| `GET` | `/admin/invites` | HTML | admin | Legacy admin invite management. |
| `POST` | `/admin/invites` | redirect | admin + CSRF | Create invite. |
| `POST` | `/admin/invites/{invite_id}/toggle` | redirect | admin + CSRF | Toggle invite active state. |
| `DELETE` | `/admin/invites/{invite_id}` | empty | admin + CSRF | Delete invite. |

### Dashboard and Logs

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/dashboard` | HTML | session | Legacy dashboard. Computes active monitors, today items, total items, last found. |
| GET | /api/stats | JSON | session | Unversioned dashboard helper with ctive_count, 	oday_items, 	otal_items. |
| GET | /api/v1/dashboard/stats | JSON | session | User-scoped counts for monitors, items, last found, and Telegram status. |
| `GET` | `/logs` | HTML | session | Legacy logs page. Current route passes log-manager entries. |
| `GET` | `/api/logs?limit=100` | JSON | session | User-scoped logs; admins also receive limited system logs. |

### Monitors

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/monitors` | HTML | session | Legacy monitor list, user-scoped. Also used by HTMX polling. |
| `GET` | `/monitors/new` | HTML | session | Legacy create form. |
| `POST` | `/monitors` | HTML form/redirect | session + CSRF | Create monitor, parse URL, schedule job. |
| `GET` | `/monitors/{monitor_id}/edit` | HTML | session | User-scoped edit form. |
| `POST` | `/monitors/{monitor_id}/edit` | HTML form/redirect | session + CSRF | Update monitor and scheduler job. |
| `POST` | `/monitors/{monitor_id}/delete` | redirect | session + CSRF | User-scoped delete and scheduler removal. |
| `POST` | `/monitors/bulk-delete` | redirect | session + CSRF | User-scoped bulk delete. |
| `POST` | `/monitors/import` | HTML form/redirect | session + CSRF | Import JSON/TXT monitor definitions. |
| `GET` | `/export/json` | JSON | session | Export user monitors as JSON array. |
| `GET` | `/export/txt` | text | session | Export user monitor URLs. |
| `POST` | `/api/monitors/{monitor_id}/trigger` | JSON | session + CSRF | Unversioned manual trigger helper. User-scoped. |

### Settings, Telegram, CF Worker, Scraper Settings

| Method | Path | Type | Auth | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/settings` | HTML | session | Legacy settings. Masks Telegram token/chat ID. Shows admin-only global settings fields. |
| `POST` | `/settings` | HTML form | session + CSRF | Saves per-user Telegram values if submitted; admins can save global scraper/CF Worker settings. |
| `POST` | `/settings/test-bot` | JSON | session + CSRF | Tests submitted or saved Telegram credentials. |
| `POST` | `/settings/start-bot` | JSON | session + CSRF | Saves submitted Telegram values if present and starts current user's bot. |
| `POST` | `/settings/stop-bot` | JSON | session + CSRF | Stops current user's bot. |
| `POST` | `/api/bot/start` | JSON | session + CSRF | Unversioned start helper using saved per-user token. |
| `POST` | `/api/bot/stop` | JSON | session + CSRF | Unversioned stop helper using saved per-user token. |
| `POST` | `/api/bot/test` | JSON | session + CSRF | Unversioned test helper using saved per-user token/chat ID. |
| `GET` | `/api/v1/settings` | JSON | session | Returns safe user payload, masked Telegram state, and admin-only global settings. Proxy values are masked/configured-only. |
| `PATCH` | `/api/v1/settings/telegram` | JSON | session + CSRF | Write-only per-user Telegram token/chat ID update. Supports explicit clearing. Returns masked Telegram state only. |
| `PATCH` | `/api/v1/settings/cloudflare-worker` | JSON | admin + CSRF | Updates admin/global CF Worker URL, block threshold, and recovery minutes; applies runtime settings. |
| `PATCH` | `/api/v1/settings/scraper` | JSON | admin + CSRF | Updates admin/global scraper defaults such as sessions, rate limit, intervals, peak hours, and write-only/masked proxies; applies runtime settings. |
| `GET` | `/api/v1/telegram/status` | JSON | session | Returns masked/configured Telegram state and whether the current user's bot is running. |
| `POST` | `/api/v1/telegram/start` | JSON | session + CSRF | Starts the current user's saved Telegram bot token without returning the token. |
| `POST` | `/api/v1/telegram/stop` | JSON | session + CSRF | Stops the current user's Telegram bot without returning the token. |
| `POST` | `/api/v1/telegram/test` | JSON | session + CSRF | Sends a test message using saved per-user credentials; failures return a generic safe message. |

Current settings ownership:

- Telegram token/chat ID: per-user `User` columns; UI masks saved values.
- CF Worker URL, block threshold, recovery minutes: global admin `AppSettings`.
- Scraper defaults: global admin `AppSettings` for proxies, sessions per domain, rate limit, check interval, off-peak/night multipliers, peak hours.
- Runtime settings apply to scraper client and scheduler where implemented.

### Items and Hidden Sellers

| Capability | Current State |
| --- | --- |
| Found items | Stored in `FoundItem`, exposed indirectly via dashboard stats and scheduler notifications. No Next-ready item list/detail API exists. |
| Seen items | Stored in `SeenItem`, used by scheduler dedup/cold-start behavior. No web JSON API exists. |
| Hidden sellers | Stored in `HiddenSeller`, created through Telegram callback `hide_seller_handler`, filtered in scheduler. No web JSON API exists. |

## Missing Next-Ready Endpoints

### Auth and Registration

- `GET /api/v1/admin/invites`
- `POST /api/v1/admin/invites`
- `PATCH /api/v1/admin/invites/{invite_id}`
- `DELETE /api/v1/admin/invites/{invite_id}`

### Dashboard

- `GET /api/v1/dashboard/stats`
  - user-scoped counts: active monitors, paused monitors, items today, total items, last discovery, Telegram status.
- `GET /api/v1/dashboard/activity`
  - recent user-scoped log/activity rows.

### Monitors

- `GET /api/v1/monitors`
- `POST /api/v1/monitors`
- `GET /api/v1/monitors/{monitor_id}`
- `PATCH /api/v1/monitors/{monitor_id}`
- `DELETE /api/v1/monitors/{monitor_id}`
- `POST /api/v1/monitors/bulk-delete`
- `POST /api/v1/monitors/import`
- `GET /api/v1/monitors/export.json`
- `GET /api/v1/monitors/export.txt`
- `POST /api/v1/monitors/{monitor_id}/trigger`

### Items and Hidden Sellers

- `GET /api/v1/items`
- `GET /api/v1/items/{item_id}`
- `GET /api/v1/hidden-sellers`
- `POST /api/v1/hidden-sellers`
- `DELETE /api/v1/hidden-sellers/{seller_id}`

### System Status

- `GET /api/v1/system/status`
  - safe aggregate status for frontend diagnostics.
- `GET /api/v1/system/logs`
  - admin-only system logs if needed; regular users must never receive shared system logs.

## Frontend Pages Needing APIs

- `/login`
  - has JSON login; still needs optional session preflight redirect using `/api/v1/auth/me`.
- `/dashboard`
  - needs dashboard stats, recent activity/logs, real monitor summary, Telegram status.
- `/settings`
  - backend settings/Telegram APIs now exist; frontend page still needs integration and forms.
- Future monitor pages
  - need monitor CRUD, import/export, manual trigger.
- Future items/logs pages
  - need item history, found item detail, user log feed, admin-only system logs.
- Future admin pages
  - need invite management JSON endpoints.

## Safest Implementation Order

1. Auth/register/CSRF phase is complete for backend JSON endpoints: CSRF, me, login, register, logout.
2. Settings/Telegram/CF Worker/scraper phase is complete for backend JSON endpoints.
3. Add monitor list/detail CRUD APIs with strict `Monitor.user_id == current_user.id` checks and scheduler job updates.
4. Add manual trigger/import/export monitor APIs after CRUD tests are stable.
5. Add dashboard stats/activity, item history APIs, hidden seller APIs, and safe system status APIs.
6. Add frontend API client extraction and integrate final pages after backend contracts stabilize.
7. Add admin invite APIs only when the Next admin UI is ready.

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
