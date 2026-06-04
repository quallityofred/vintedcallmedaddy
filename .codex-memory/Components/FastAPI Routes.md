---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/api
---

# FastAPI Routes

## Purpose

- Defines the web surface for auth, dashboard pages, monitor CRUD, settings, logs, and API helpers.

## Key Files

- `backend/app/app_main.py`
- `backend/app/web/auth_api_router.py`
- `backend/app/web/dashboard_api_router.py`
- `backend/app/web/monitors_api_router.py`
- `backend/app/web/items_api_router.py`
- `backend/app/web/settings_api_router.py`
- `backend/app/web/system_api_router.py`
- `backend/app/web/admin_api_router.py`
- `backend/app/web/api_dependencies.py`
- `backend/app/web/invite_codes.py`
- `backend/app/web/auth.py`
- `backend/app/web/app_web_dependencies.py`

## Runtime Flow

- `app.app_main:create_app()` registers public health/root routes and versioned `/api/v1/*` JSON routers.
- Legacy Jinja route modules were removed in the API-first cleanup.
- `app.web.app_web_dependencies:get_db()` resolves the current async session factory at request time.

## Audit Notes

- Runtime duplicate route registrations from legacy modules were fixed.
- Admin invite routes are registered.
- Auth uses DB-backed sessions with random tokens and cookie-based persistence.

## Related Issues

- [[Issues/ISS-002 Admin invite management routes are missing|ISS-002]]
- [[Issues/ISS-005 Duplicate implementation modules shadow runtime behavior|ISS-005]]
- [[Issues/ISS-007 Invite code consumption is race-prone|ISS-007]]
- [[Issues/ISS-008 Session and CSRF protections are incomplete|ISS-008]]
- [[Issues/ISS-RWY-002 AsyncSessionLocal None after startup|ISS-RWY-002]]

- 2026-06-02: `app.web.router` is canonical; `app.web.app_web_router` is a compatibility re-export. Added admin invite routes and CSRF checks for authenticated state changes.
- 2026-06-02: Web request DB dependencies now resolve the initialized database session factory dynamically, fixing Railway `GET /` failures after successful startup.

## Frontend Migration Notes

- 2026-06-02: Existing routes are mostly HTML/form/redirect endpoints. The Next.js frontend needs a versioned JSON API layer for auth/session bootstrap, CSRF, monitors, settings, found items/logs, and admin invites.
- 2026-06-02: Preserve existing Jinja routes during migration; add new `/api/v1/...` endpoints instead of changing current route response contracts.
- 2026-06-03: Early route audit found missing `/api/v1/...` endpoints. Later API migration phases added the core versioned auth, dashboard, monitor, item, hidden-seller, settings, Telegram, system, and admin invite APIs.
- 2026-06-03: Backend `/` was changed for the split deployment:
  - production with `FRONTEND_URL` redirects to the frontend;
  - production without `FRONTEND_URL` returns minimal JSON service info;
  - development redirects to `/dashboard`;
  - legacy Jinja dashboard remains at `/dashboard`.
- 2026-06-03: `/health` and `/api/health` remain public unauthenticated health probes.
- 2026-06-03: Added first versioned JSON auth API:
  - `GET /api/v1/auth/csrf`
  - `GET /api/v1/auth/me`
  - `POST /api/v1/auth/login`
  - `POST /api/v1/auth/register`
  - `POST /api/v1/auth/logout`
- 2026-06-03: JSON auth reuses existing `User`, `UserSession`, PBKDF2 password checks, invite-code consumption, and HttpOnly `session_token`; login/register/logout POSTs require API CSRF through `X-CSRF-Token`.
- 2026-06-03: Added versioned settings and Telegram API phase:
  - `GET /api/v1/settings`
  - `PATCH /api/v1/settings/telegram`
  - `PATCH /api/v1/settings/cloudflare-worker`
  - `PATCH /api/v1/settings/scraper`
  - `GET /api/v1/telegram/status`
  - `POST /api/v1/telegram/start`
  - `POST /api/v1/telegram/stop`
  - `POST /api/v1/telegram/test`
- 2026-06-03: Settings API returns masked Telegram/proxy state only, requires API CSRF for mutations, and restricts global scraper/CF Worker updates to admins.
- 2026-06-04: `/api/v1/telegram/test` returns safe structured error `code`/`detail` payloads for missing credentials, invalid token/chat, chat access issues, bot conflicts, rate limits, upstream timeouts, and unknown failures.
- 2026-06-03: [[API Contract]] inventories all current route surfaces. Current versioned API covers auth/register/CSRF, dashboard stats, monitors, items, hidden sellers, settings/Telegram, system status, and admin invites.
- 2026-06-04: `GET /api/v1/monitors/domains` now returns unique Vinted marketplace representatives and cannot fail from the old missing `get_flag` import. Monitor create/update validates representatives and rejects empty/unknown selected domains with `400`.
- 2026-06-04: Monitor response payloads for list/detail/create/update/pause/resume now include selected representative `domains`, allowing the Next `/monitors` edit form to initialize from persisted state instead of stale frontend draft state.
- 2026-06-03: Removed obsolete legacy placeholder route modules: `router.py`, `auth_router.py`, `admin_router.py`, and `app_web_router.py`.
- 2026-06-03: Added API dependency helpers so admin/system APIs return JSON `401`/`403` behavior instead of legacy redirects.

## Related Open Issues

- [[Issues/ISS-FE-005 Frontend backend integration incomplete|ISS-FE-005]]
- [[Issues/ISS-API-001 Full Next frontend API contract missing|ISS-API-001]]

## Related Fixed Issues

- [[Issues/ISS-AUTH-001 Next frontend login API pending|ISS-AUTH-001]]
- [[Issues/ISS-AUTH-002 Next frontend registration API missing|ISS-AUTH-002]]
- [[Issues/ISS-API-002 Settings Telegram CF Worker scraper API missing|ISS-API-002]]
- [[Issues/ISS-FE-006 Backend public root is confusing after split|ISS-FE-006]]
- [[Issues/ISS-API-004 Legacy placeholder route modules remained after API-first migration|ISS-API-004]]
- [[Issues/ISS-API-005 Monitor domains endpoint 500|ISS-API-005]]

## Related Plans

- [[Frontend Migration Plan]]
- [[API Contract]]
