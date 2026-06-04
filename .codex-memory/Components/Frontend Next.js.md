---
type: component
project: vintedbot
status: in-progress
severity: low
tags:
  - vintedbot
  - component/frontend
  - status/in-progress
  - severity/low
created: 2026-06-02
updated: 2026-06-04
---

# Frontend Next.js

## Purpose

- Concrete Phase 1 frontend app in `Projects/vintedbot/frontend`.
- Provides the design foundation and placeholder routes for incremental Jinja-to-Next migration.

## Key Files

- `frontend/package.json`
- `frontend/next.config.ts`
- `frontend/components.json`
- `frontend/src/app/page.tsx`
- `frontend/src/app/login/page.tsx`
- `frontend/src/app/register/page.tsx`
- `frontend/src/app/dashboard/page.tsx`
- `frontend/src/app/monitors/page.tsx`
- `frontend/src/app/settings/page.tsx`
- `frontend/src/app/admin/page.tsx`
- `frontend/src/app/globals.css`
- `frontend/src/lib/auth.ts`
- `frontend/src/components/auth-guard.tsx`
- `frontend/src/components/page-shell.tsx`
- `frontend/src/components/login-form.tsx`
- `frontend/src/components/register-form.tsx`
- `frontend/src/components/dashboard-card.tsx`
- `frontend/src/components/backend-health-card.tsx`
- `frontend/src/components/animated-section.tsx`
- `frontend/src/components/monitor-preview.tsx`
- `frontend/src/components/monitors-summary-card.tsx`
- `frontend/src/components/section-heading.tsx`
- `frontend/src/components/spline-hero.tsx`
- `frontend/src/components/ui/*`
- `frontend/playwright.config.ts`
- `frontend/tests/e2e/landing.spec.ts`

## Architecture

- Next.js App Router with TypeScript.
- Tailwind CSS v4 theme tokens in `globals.css`.
- shadcn/ui `base-nova` preset components under `src/components/ui`.
- Motion is used only in client-side `AnimatedSection`.
- Spline is isolated to `SplineHero`; it renders a placeholder unless `NEXT_PUBLIC_SPLINE_SCENE_URL` is set.
- `next.config.ts` rewrites `/api/:path*` to `BACKEND_URL`, defaulting to `http://localhost:8080`.
- `BackendHealthCard` calls public `/api/health` through that rewrite and does not call protected endpoints.
- Frontend Railway root directory is `frontend`.
- Frontend Railway build command: `npm run build`.
- Frontend Railway start command: `npm run start -- --hostname 0.0.0.0 --port $PORT`.

## Validation

- `npm run lint` passed.
- `npm run build` passed.
- `npx playwright install chromium` completed.
- `npm run test:e2e` passed with one Chromium smoke test.
- `git diff --check` passed.
- 2026-06-03 health/root fix validation: lint passed, build passed, Playwright E2E passed with two Chromium smoke tests.

## Design Updates

- 2026-06-02: No Figma design selection was available, so the frontend was extended from scratch based on product memory.
- Added reusable `MonitorPreview` to show clearly marked demo monitor rows and safety events.
- Added reusable `SectionHeading` for consistent landing sections.
- Updated `/` with product-specific command-center content and placeholder monitor preview.
- Updated `/dashboard` with monitor preview and an API-readiness checklist.
- Updated `/settings` with safety notes for future token, proxy, and CSRF-sensitive controls.
- Expanded Playwright smoke tests to cover `/dashboard` and `/settings`.

## Health Connectivity

- 2026-06-03: Dashboard now includes backend health connectivity through `/api/health`.
- The card displays reachable/unreachable state, backend status, scheduler job count, running bot count, and last checked timestamp.
- This is intentionally limited to the public health endpoint until auth/session/CSRF JSON APIs exist.

## Known Issues

- [[Issues/ISS-FE-001 Next.js PostCSS audit advisory|ISS-FE-001]]
- [[Issues/ISS-FE-005 Frontend backend integration incomplete|ISS-FE-005]]
- [[Issues/ISS-FE-006 Backend public root is confusing after split|ISS-FE-006]] fixed by [[Fixes/FIX-FE-006 Backend root and health connectivity|FIX-FE-006]]

## Integration Audit

- 2026-06-03: Login page now posts to `/api/v1/auth/login` after fetching `/api/v1/auth/csrf`.
- 2026-06-03: Backend now also exposes `/api/v1/auth/register`, but the Next frontend does not have a registration page yet.
- 2026-06-03: Backend now exposes settings/Telegram APIs for the settings page, but the Next settings page still needs integration in the final frontend API client/page phase.
- 2026-06-03: Frontend now calls public `/api/health` plus `/api/v1/*` auth, dashboard, settings, monitor, item, hidden-seller, system, and admin endpoints.
- 2026-06-03: Real API work should continue with monitor CRUD/control APIs before dashboard and final page integration phases.
- 2026-06-03: `frontend/eslint.config.mjs` ignores generated Playwright output so validation does not fail when `test-results/` is absent or ignored.
- 2026-06-03: [[API Contract]] documents current frontend API usage and missing page APIs.

## Auth Integration

- 2026-06-03: Replaced disabled login placeholder with `LoginForm`.
- The form uses relative `/api/v1/auth/*` calls through the Next rewrite and redirects to `/dashboard` after success.
- Error states are generic and do not expose stack traces or password/hash details.
- Optional legacy login fallback is hidden in production unless `NEXT_PUBLIC_LEGACY_LOGIN_URL` is configured.
- 2026-06-03: Added `AuthGuard` and `fetchCurrentUser` for protected pages.
- `/dashboard` and `/settings` require an authenticated user.
- `/admin` requires an authenticated admin user.
- Unauthenticated protected-route visits redirect to `/login?next=<same-origin-path>`.
- Login and registration preserve sanitized `next` paths and otherwise default to `/dashboard`.
- Dashboard `401` stats responses redirect to login instead of rendering generic error cards.

## Latest Validation

- 2026-06-03 API-first cleanup/auth guard pass:
  - `npm run lint` -> passed.
  - `npm run build` -> passed with known Node `DEP0205` warning.
  - `npm run test:e2e` -> 6 passed with known Node `DEP0205` warning.
- 2026-06-03 UI/UX polish pass:
  - `npm run lint` -> passed.
  - `npm run build` -> passed with known Node `DEP0205` warning.
  - `npm run test:e2e` -> 6 passed with known Node `DEP0205` warning.
  - `git diff --check` -> passed with line-ending warnings only.
- 2026-06-04 dedicated monitors page pass:
  - `npm run lint` -> passed.
  - `npm run build` -> passed with known Node `DEP0205` warning.
  - `npm run test:e2e` -> 7 passed with known Node `DEP0205` warning and expected local backend proxy noise in isolated tests.
- 2026-06-04 unique domain loading fix:
  - `npm run lint` -> passed.
  - `npm run build` -> passed with known Node `DEP0205` warning.
  - `npm run test:e2e` -> 8 passed with known Node `DEP0205` warning and expected local backend proxy noise in isolated tests.
- 2026-06-04 Telegram/settings/checkbox polish:
  - `npm run lint` -> passed.
  - `npm run build` -> passed with known Node `DEP0205` warning.
  - `npm run test:e2e` -> 8 passed with known Node `DEP0205` warning and expected local backend proxy noise in isolated tests.
- 2026-06-04 CF Worker routing mode settings fix:
  - `npm run lint` -> passed.
  - `npm run build` -> passed with known Node `DEP0205` warning.
  - `npm run test:e2e` -> 9 passed with known Node `DEP0205` warning.

## UI Polish

- 2026-06-03: Standardized async loading/disabled states across monitor, item, settings, and admin invite controls.
- Added accessible labels to icon-only monitor actions, item links/hide-seller action, admin revoke buttons, and monitor selection checkboxes.
- Improved dashboard spacing by keeping health/status cards stacked until wide desktop.
- Removed user-facing migration/legacy/preview copy from public and login surfaces.
- Kept API calls relative to `/api/...` and did not introduce frontend secrets.
- 2026-06-04: Moved full monitor management to `/monitors`; dashboard now renders `MonitorsSummaryCard` instead of `MonitorPreview`.
- Added authenticated `Monitors` navigation in `PageShell`; logged-out users do not see it, and Admin remains admin-only.
- Removed monitor management from the public landing page so CRUD controls live only behind authentication.
- 2026-06-04: `DomainSelection` now loads unique marketplace representatives from `/api/v1/monitors/domains`, preserves selected representative payloads, shows a clean retry state on endpoint failure, and no longer silently presents `0 / 0` on backend errors.
- 2026-06-04: Follow-up polish updated the shared checkbox primitive, rendered domain marketplaces as selectable cards, switched monitor row/bulk selection to the shared checkbox, and improved `/settings` Telegram masked status plus safe action feedback.
- 2026-06-04: `/monitors` was visually reworked from a table into responsive monitor cards/list rows. Each card shows a clear square selection checkbox, monitor name, source URL link, active/paused status, marketplace, interval, found count, last check, and labeled Edit/Check/Pause/Resume/Delete buttons. The list toolbar owns select-all and bulk delete.
- 2026-06-04: `/monitors` follow-up refinement added intentional spacing before informational cards and simplified `DomainSelection` to compact rows: checkbox, country code badge, and marketplace name. Hosts/aliases stay out of the main visual and are available only as option title metadata.
- 2026-06-04: `/monitors` edit/create forms now use isolated controlled draft state. Edit initializes from persisted monitor name, URL, interval, and selected `domains`; closing via Escape/outside/close discards drafts without submitting. Monitor cards display selected domains under `Domains` with truncate/title behavior.

## Settings Feedback

- 2026-06-04: `/settings` displays masked Telegram token/chat status, bot runtime status, credential safety copy, disabled-action help, and inline safe success/error notices.
- `Send test` is disabled until both token and chat ID are configured. `Start bot` is disabled until a token is configured.
- Telegram test failures display backend-provided safe `detail` messages and do not expose token/chat values.
- 2026-06-04: CF Worker routing mode save now sends flat `cf_worker_mode`, uses a typed `auto`/`direct`/`worker` union, validates optional numeric fields before PATCH, updates local state from PATCH response, and displays backend `detail` on failure while keeping the selected value visible.
- Routing mode labels render as `Auto`, `Direct only`, and `CF Worker only` instead of raw API values.

## Related

- [[Frontend Migration Plan]]
- [[Components/Frontend]]
- [[Decisions/DEC-004 Next.js Frontend Migration]]
- [[Decisions/DEC-005 Railway Split Frontend Backend Deployment]]
- [[Fixes/FIX-AUTH-001 JSON auth API and login form]]
- [[Fixes/FIX-AUTH-002 JSON registration API]]
- [[Fixes/FIX-API-002 Settings Telegram CF Worker scraper APIs]]
- [[Fixes/FIX-FE-007 Frontend auth guard for protected routes]]
- [[API Contract]]
