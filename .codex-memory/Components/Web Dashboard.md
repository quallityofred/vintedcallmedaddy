---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/web
---

# Web Dashboard

## Purpose

- User-facing dashboard for stats, monitors, settings, and live logs.

## Key Files

- `frontend/src/app/dashboard/page.tsx`
- `frontend/src/app/settings/page.tsx`
- `frontend/src/app/admin/page.tsx`
- `frontend/src/components/auth-guard.tsx`
- `frontend/src/lib/auth.ts`
- `backend/app/web/*_api_router.py`

## Runtime Flow

- Next.js renders the current dashboard/settings/admin pages.
- Backend `/` is reserved for safe API-service behavior or production frontend redirect.
- Frontend protected pages call `/api/v1/auth/me` through the Next rewrite before rendering protected content.
- Backend JSON APIs under `/api/v1/*` own all protected data and mutations.

## Audit Notes

- The settings page receives a persisted `settings` mapping from route context.
- Shared system logs are admin-only; regular users receive user-scoped logs.
- Scraper controls are saved and applied through persisted app settings.
- Telegram token/chat ID settings are per-user and write-only/masked in rendered HTML.
- Global scraper settings are admin-only. Cloudflare Worker URL/block/recovery/mode are currently per-user settings.

## Related Issues

- [[Issues/ISS-001 Settings page misses required context|ISS-001]]
- [[Issues/ISS-004 Dashboard exposes shared system logs to every user|ISS-004]]
- [[Issues/ISS-006 Scraper settings form does not persist or apply values|ISS-006]]
- [[Issues/ISS-RWY-002 AsyncSessionLocal None after startup|ISS-RWY-002]]
- [[Issues/ISS-011 Settings page exposes saved Telegram credentials|ISS-011]]

- 2026-06-02: Settings page now receives and persists scraper settings; authenticated state-changing forms/fetch calls include CSRF tokens; shared system logs are admin-only.
- 2026-06-02: Dashboard route `GET /` no longer depends on a stale imported database session factory after startup.
- 2026-06-03: Settings page no longer renders saved Telegram credentials in full and now exposes global scraper/Cloudflare settings only to admins. See [[Fixes/FIX-011 Settings credential masking and admin globals|FIX-011]].
- 2026-06-03: Legacy Jinja dashboard route moved from `/` to `/dashboard` for the split deployment. Auth redirects and sidebar navigation now target `/dashboard`.
- 2026-06-03: Legacy Jinja route modules and templates were removed during API-first cleanup. The active dashboard surface is the Next.js frontend plus FastAPI JSON APIs.

## Frontend Migration Notes

- 2026-06-02: Current dashboard is Jinja/HTMX/form-first. A standalone Next.js frontend should be migrated incrementally and should use new versioned JSON APIs rather than replacing backend runtime behavior.
- 2026-06-02: Verify `GET /logs` before migrating logs/found-items: the current route appears to supply log-manager entries, while `logs.html` expects found-item table context.
- 2026-06-02: Phase 1 Next.js frontend scaffold was added without removing or changing Jinja templates/routes. The new `/dashboard` and `/settings` frontend pages are placeholders only and do not yet call backend auth/session/CSRF APIs.
- 2026-06-02: The Next.js dashboard originally started as a placeholder with reusable monitor preview and API-readiness checklist.
- 2026-06-03: The Next.js dashboard now includes protected auth/session checks and real dashboard/monitor/item/system API integration.
- 2026-06-03: The Next.js login page now uses real JSON auth. Dashboard and settings pages remain partially placeholder/API-pending.
- 2026-06-03: [[API Contract]] confirms active APIs now cover auth, dashboard, monitors, items, hidden sellers, settings, system status, and admin invites.
- 2026-06-03: Next protected routes are guarded:
  - `/dashboard` and `/settings` require a logged-in user.
  - `/admin` requires an admin user.
  - unauthenticated users redirect to `/login?next=...`.
- 2026-06-03: UI polish pass improved dashboard rhythm, monitor table controls, recent item states, settings token messaging, and admin invite management states. Icon-only/destructive actions now have explicit labels.
- 2026-06-04: Dashboard no longer embeds the full monitor management table. It shows a compact monitor summary card with counts and a `Manage monitors` CTA. Full monitor CRUD/control UI is now on protected `/monitors`.
- 2026-06-04: `/monitors` edit/create dialog now keeps unsaved draft state isolated from persisted monitor data. Closing the dialog without `Update monitor` discards edits; reopening shows saved name, URL, interval, and selected domains. Monitor cards now label selected targets as `Domains` instead of `Marketplace`.
- 2026-06-04: Settings page now shows masked Telegram credential status cards, disabled-action help, safe classified test errors, and clearer save/test/start/stop loading states. Checkbox polish keeps domain selection card-like and monitor selection compact.
- 2026-06-04: Settings CF Worker routing-mode save now shows backend validation details instead of a generic Failed message. Direct/Auto saves persist through PATCH/GET in tests; Worker-only mode requires a configured Worker URL and keeps the selected value visible on validation failure.
- 2026-06-04: Monitor debug trigger no longer nests a button inside a dialog trigger, preventing Next dev overlay/runtime markup issues. Debug output still handles missing `cf_worker` and shows only masked Worker URL.
- 2026-06-05: `/monitors` no longer refreshes stable Telegram topic settings every monitor poll or mounts one topic-status GET per monitor card. It uses one read-only batch topic-status request, keeps individual POST actions for Ensure/Test, and polls the monitor list less aggressively while the tab is visible.
- 2026-06-05: Dashboard Recent Items uses `/api/v1/items`, which is scoped through `FoundItem -> Monitor -> current_user`. Regression coverage now asserts another user's findings cannot appear in a user's recent-items list.

## Related Plans

- [[Frontend Migration Plan]]
- [[Components/Frontend Next.js]]
