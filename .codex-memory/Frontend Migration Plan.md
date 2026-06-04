---
type: plan
project: vintedbot
status: in-progress
severity: low
components:
  - Frontend
  - Web Dashboard
  - FastAPI Routes
  - Configuration and Deployment
tags:
  - vintedbot
  - plan/proposed
  - component/frontend
  - component/web
  - component/api
  - component/configuration
  - severity/low
created: 2026-06-02
updated: 2026-06-04
---

# Frontend Migration Plan

## Goal

Move the user-facing dashboard from FastAPI/Jinja templates to a modern `frontend/` app while keeping the existing FastAPI backend as the source of truth for auth, database access, scheduler control, scraper settings, Telegram bot lifecycle, and all user isolation rules.

The target UI should be a production dashboard, not a rewrite of backend behavior: fast monitor management, clear Telegram/scraper settings, live logs, found-item history, admin invite management, and a polished landing/auth experience. Existing Jinja pages must remain available until each replacement page has equivalent functionality and tests.

## Current UI inventory

Verified against `Projects/vintedbot` on `2026-06-02`; backend root/dashboard updates verified on `2026-06-03`.

### App and routing

- `app/app_main.py`
  - Creates the FastAPI app.
  - Mounts `/static`.
  - Configures Jinja templates and a global `csrf_token(request)` helper.
  - Includes `auth_router`, canonical `web_router`, and `admin_router` under `/admin`.
  - Provides `/health` and `/api/health`.
- `app/web/router.py`
  - Canonical web dashboard router.
  - Mostly HTML/form endpoints with some JSON helper APIs.
- `app/web/auth_router.py`
  - HTML login/register/logout flow.
- `app/web/admin_router.py`
  - HTML/admin invite management.
- `app/web/app_web_router.py`, `app/web/dependencies.py`
  - Compatibility re-export wrappers.

### Jinja templates

- `app/templates/base.html`
  - Authenticated dashboard layout, sidebar, nav, logout form, mobile sidebar, Tailwind CDN, HTMX, Lucide, custom JS helpers.
- `app/templates/dashboard.html`
  - Protected dashboard stats and a live console polling `/api/logs`.
- `app/templates/monitors/list.html`
  - Monitor table, import/export modals, bulk selection/delete, manual trigger, HTMX table refresh.
- `app/templates/monitors/form.html`
  - Create/edit monitor form, domain checkboxes, active toggle on edit.
- `app/templates/settings.html`
  - Telegram token/chat settings, bot test/start/stop controls, proxy list, sessions per domain, rate limit.
- `app/templates/logs.html`
  - Found-item style table with monitor filter/pagination, but current `GET /logs` route appears to pass log-manager data instead of the `items` and `monitors_map` values this template expects. Treat this as a pre-migration verification item.
- `app/templates/admin/invites.html`
  - Admin invite list/create/toggle/delete.
- `app/templates/auth/login.html`
  - HTML login form.
- `app/templates/auth/register.html`
  - HTML registration form with invite code.
- `app/templates/admin/import_summary.html`
  - Present but not obviously routed in the inspected files.
- `app/templates/app_templates_monitors_list.html`
  - Legacy/extra monitor-list template file; keep untouched until confirmed unused.
- `app/static/css/custom.css`
  - Scrollbars, toast, HTMX loading, checkbox styling, modal transitions.

### Current routes and functions

- Auth:
  - `GET /login`
  - `POST /login`
  - `GET /register`
  - `POST /register`
  - `POST /logout`
- Dashboard:
  - `GET /dashboard`
  - `GET /` redirects to `/dashboard` in development.
  - `GET /` redirects to `FRONTEND_URL` in production when configured, otherwise returns minimal JSON backend service info.
  - `GET /api/stats`
- Monitors:
  - `GET /monitors`
  - `GET /monitors/new`
  - `POST /monitors`
  - `GET /monitors/{monitor_id}/edit`
  - `POST /monitors/{monitor_id}/edit`
  - `POST /monitors/{monitor_id}/delete`
  - `POST /monitors/bulk-delete`
  - `POST /monitors/import`
  - `GET /export/json`
  - `GET /export/txt`
  - `POST /api/monitors/{monitor_id}/trigger`
- Settings and bot controls:
  - `GET /settings`
  - `POST /settings`
  - `POST /settings/test-bot`
  - `POST /settings/start-bot`
  - `POST /settings/stop-bot`
  - `POST /api/bot/start`
  - `POST /api/bot/stop`
  - `POST /api/bot/test`
- Logs:
  - `GET /logs`
  - `GET /api/logs`
- Admin:
  - `GET /admin/invites`
  - `POST /admin/invites`
  - `POST /admin/invites/{invite_id}/toggle`
  - `DELETE /admin/invites/{invite_id}`
- Health:
  - `GET /health`
  - `GET /api/health`

### Auth, session, and CSRF

- Auth is DB-backed through `UserSession`.
- Session token is stored in an HttpOnly `session_token` cookie.
- Cookie uses `SameSite=Lax`; `secure` is enabled when `SESSION_COOKIE_SECURE=true` or hosted env variables imply production.
- Authenticated state-changing routes depend on `require_csrf`.
- CSRF tokens are HMAC-SHA256 values derived from the session token and `SECRET_KEY`.
- Jinja currently injects CSRF tokens directly into forms/JS through `csrf_token(request)`.
- A standalone Next frontend cannot read the HttpOnly session cookie, so it needs a backend endpoint that returns the CSRF token for the current session.

## Target stack

- Next.js
  - Use a `frontend/` app with the App Router and TypeScript.
  - Use server components for shells and data-light pages where appropriate.
  - Use client components for forms, polling, Spline, Motion, and interactive controls.
  - Use `next.config.ts` rewrites/proxying so browser calls stay same-origin as the Next app while the backend remains FastAPI.
- TypeScript
  - Define frontend DTOs matching backend JSON responses.
  - Prefer explicit API client functions over ad hoc `fetch` scattered through components.
- Tailwind CSS
  - Move the current dark green dashboard tokens into Tailwind/CSS variables.
  - Prefer real design tokens and component variants over CDN Tailwind and large inline style blocks.
- shadcn/ui
  - Use the CLI-owned component model: copied components live in `frontend/components/ui`.
  - Start with `button`, `card`, `input`, `textarea`, `select`, `dialog`, `table`, `badge`, `toast/sonner`, `tabs`, `dropdown-menu`, `alert`, `form`.
  - Keep component customizations in the repo, not as runtime CDN dependencies.
- Motion
  - Use Motion sparingly for page transitions, dialogs, list enter/exit, and small feedback animations.
  - Keep operational screens dense and readable; avoid animation that delays dashboard work.
- Spline
  - Integrate Spline first for landing/auth polish or a restrained hero scene.
  - Use `@splinetool/react-spline/next` when possible for Next.js placeholder behavior.
  - Avoid putting heavy 3D inside core dashboard workflows.
- React Three Fiber + Drei
  - Defer until Spline cannot satisfy a specific product requirement.
  - Use only for custom interactive 3D that needs code-level control.
- Playwright
  - Add frontend E2E tests after core pages exist.
  - Use TypeScript tests.
  - Configure `webServer` to run the frontend and, when needed, the FastAPI backend during E2E.

## Proposed architecture

### App split

Use separate apps:

- `Projects/vintedbot/backend/`: existing FastAPI backend and legacy Jinja dashboard.
- `Projects/vintedbot/frontend/`: new Next.js TypeScript frontend.

Do not move scheduler, scraper, Telegram, auth, or database ownership into Next.js. Next should be a UI and optional backend-for-frontend proxy only.

### API proxy/rewrite strategy

Local development:

- FastAPI: `http://localhost:8080`
- Next.js: `http://localhost:3000`
- Next rewrites:
  - `/api/:path*` -> `${BACKEND_URL}/api/:path*`
  - Keep all new standalone frontend APIs under `/api/v1/...` on FastAPI, proxied through Next.

Recommended environment variables:

- `frontend/.env.local`
  - `BACKEND_URL=http://localhost:8080`
  - `NEXT_PUBLIC_APP_NAME=Vinted Monitor`
- Backend `.env.example` later:
  - ensure `ALLOWED_ORIGINS` covers local frontend if direct cross-origin calls are ever used.

Prefer same-origin browser calls through Next rewrites to reduce CORS and cookie problems. Avoid exposing the backend URL to browser code unless there is a concrete reason.

### Auth/session/CSRF strategy

Keep FastAPI-owned session cookies.

Required frontend flow:

1. Next login form posts to a FastAPI JSON auth endpoint through a same-origin rewrite.
2. FastAPI sets `session_token` HttpOnly cookie.
3. Next calls `/api/v1/auth/me` to hydrate the current user.
4. Next calls `/api/v1/auth/csrf` after login or before state-changing requests.
5. Frontend writes `X-CSRF-Token` on POST/PATCH/DELETE.
6. FastAPI continues to validate ownership and CSRF server-side.

Do not move auth secrets, Telegram tokens, or session validation into frontend code. Do not put Telegram tokens in local storage.

### Railway deployment strategy

Incremental Railway target:

- Backend service runs the current FastAPI app from `backend/`.
- Frontend service runs the Next app from `frontend/`.
- Configure the frontend service with an internal/private `BACKEND_URL` pointing to the backend service when available.
- Route browser API calls through the Next service so cookies are set on the frontend domain.
- Keep the backend public URL available during migration for old Jinja pages, or put both services behind one custom domain/proxy when ready.
- Current backend root behavior: production `/` redirects to `FRONTEND_URL` when configured, otherwise returns minimal JSON; legacy Jinja stays available at `/dashboard`.

Avoid a combined Python+Node runtime until there is a strong operational reason. A combined image would complicate process supervision and Next SSR. Static export is not a good default because auth, rewrites, and dynamic dashboard data need a server.

Status on `2026-06-03`: initial Railway split implemented. Repo now has `backend/`, `frontend/`, and `docs/`; backend and frontend each have Railway config. Deployment variables and manual URL wiring are documented in `Projects/vintedbot/docs/DEPLOYMENT_ENV.md`.

Settings update on `2026-06-03`: Telegram credentials are per-user and write-only/masked in the legacy settings UI. Cloudflare Worker and scraper defaults are admin/global DB settings, with env vars retained only as optional bootstrap defaults.

## Required backend API changes

The current backend has useful JSON helpers but is not yet a complete standalone frontend API.

2026-06-03 update: the Next.js dashboard now has a limited public health integration through `/api/health`. It does not replace the missing auth/session/dashboard/settings API contracts.

### Auth/session

- `GET /api/v1/auth/me`
  - Returns current user profile: `id`, `username`, `is_admin`, Telegram configured flags only, not raw token by default.
- `POST /api/v1/auth/login`
  - Accepts JSON or form-compatible payload, sets session cookie, returns user.
- `POST /api/v1/auth/register`
  - Accepts JSON payload and invite code, sets session cookie, returns user.
- `POST /api/v1/auth/logout`
  - CSRF-protected, clears session cookie.
- `GET /api/v1/auth/csrf`
  - Returns `{ "csrf_token": "..." }` for the current session.

### Dashboard

- Current `GET /api/stats` can be kept, but prefer versioned:
  - `GET /api/v1/dashboard/stats`
  - Include `active_count`, `today_items`, `total_items`, `last_found`, and optional bot/scheduler status.

### Monitors

- `GET /api/v1/monitors`
  - List monitors for current user, parsed domains, computed status fields.
- `POST /api/v1/monitors`
  - JSON create, CSRF-protected.
- `GET /api/v1/monitors/{monitor_id}`
  - User-scoped detail for edit page.
- `PATCH /api/v1/monitors/{monitor_id}`
  - JSON update, CSRF-protected.
- `DELETE /api/v1/monitors/{monitor_id}`
  - User-scoped delete, CSRF-protected.
- `POST /api/v1/monitors/bulk-delete`
  - JSON IDs, user-scoped, CSRF-protected.
- `POST /api/v1/monitors/import`
  - JSON and/or multipart import, CSRF-protected.
- `GET /api/v1/monitors/export.json`
  - Versioned equivalent of `/export/json`.
- `GET /api/v1/monitors/export.txt`
  - Versioned equivalent of `/export/txt`.
- `GET /api/v1/vinted/domains`
  - Domain metadata currently rendered from `VINTED_DOMAINS`.
- `POST /api/v1/monitors/{monitor_id}/trigger`
  - Versioned equivalent of current trigger endpoint.

### Settings and Telegram

- `GET /api/v1/settings`
  - Returns safe user settings, scraper settings, bot running status, and booleans such as `telegram_token_configured`.
  - Do not return raw Telegram bot token by default.
- `PATCH /api/v1/settings`
  - Updates Telegram settings and scraper settings, CSRF-protected.
  - Consider write-only token field semantics: blank means keep existing token, explicit clear action if needed.
- `POST /api/v1/settings/test-bot`
  - CSRF-protected test using submitted or saved values.
- `POST /api/v1/bot/start`
  - CSRF-protected.
- `POST /api/v1/bot/stop`
  - CSRF-protected.

### Logs and found items

- `GET /api/v1/logs`
  - Versioned equivalent of `/api/logs`, still user-scoped and admin-only for system logs.
- `GET /api/v1/found-items`
  - Paged found-item history with optional `monitor_id` filter.
  - Needed because the current `logs.html` template appears to represent found items while current `GET /logs` route supplies log-manager entries.

### Admin

- `GET /api/v1/admin/invites`
- `POST /api/v1/admin/invites`
- `PATCH /api/v1/admin/invites/{invite_id}`
- `DELETE /api/v1/admin/invites/{invite_id}`

All admin endpoints must keep `require_admin`, CSRF for state changes, and avoid returning unnecessary invite metadata.

## Migration phases

### Phase 1: scaffold frontend and design system

- Create `frontend/` with Next.js, TypeScript, Tailwind, shadcn/ui, Motion, Spline package, and Playwright.
- Add `next.config.ts` rewrite to the FastAPI backend.
- Add shared frontend API client helpers with credentials included.
- Add lint/typecheck/build/test scripts.
- Do not modify old Jinja templates.

Status on `2026-06-02`: complete for the scaffold/design foundation. Created `Projects/vintedbot/frontend` with Next.js `16.2.7`, React `19.2.4`, Tailwind CSS `4`, shadcn/ui `base-nova` components, Motion, Spline React, Playwright config, landing/login/dashboard/settings placeholder pages, reusable shell/cards/animated section/Spline placeholder components, and frontend `.env.example`.

Validation:

- `npm install` completed through `create-next-app` and subsequent package installs.
- `npm run lint` passed.
- `npm run build` passed.
- `npx playwright install chromium` completed.
- `npm run test:e2e` passed: `1 passed`.
- `git diff --check` passed.

Open follow-up:

- [[Issues/ISS-FE-001 Next.js PostCSS audit advisory|ISS-FE-001]]: `npm audit --omit=dev` reports a moderate PostCSS advisory through current Next.js; npm only offers a forced breaking remediation.

### Phase 2: public/landing pages

- Build a Next landing page or product intro page outside the existing protected Jinja dashboard.
- Add Spline hero only here at first.
- Keep backend `GET /` dashboard untouched until cutover routing is decided.
- Add simple health/API connectivity display using `/api/health`.

Status on `2026-06-02`: partially started from scratch because no Figma file, node, or selection was available to inspect. Added a product-specific landing/design pass with reusable `SectionHeading` and `MonitorPreview` components, clearer demo placeholders, dashboard API-readiness guidance, and settings safety notes. No backend API calls were introduced.

Validation:

- `npm run lint` passed.
- `npm run build` passed.
- `npm run test:e2e` passed: `2 passed`.
- `git diff --check` passed.

Design note:

- The UI intentionally labels demo values as placeholders and keeps auth/session/CSRF untouched until the versioned FastAPI JSON API work begins.

### Phase 3: auth pages

- Add JSON auth endpoints in FastAPI.
- Build Next login/register pages.
- Verify session cookie, `/api/v1/auth/me`, logout, and CSRF bootstrap.
- Keep old `/login` and `/register` Jinja pages available.

### Phase 4: dashboard shell

- Build authenticated Next dashboard shell, sidebar, top bar, user menu, protected-route handling.
- Use `/api/v1/dashboard/stats` and `/api/v1/logs`.
- Add loading, empty, and unauthorized states.
- Keep current Jinja dashboard accessible on backend during this phase.

Status on `2026-06-03`: protected-route handling is implemented for `/dashboard`, `/settings`, and `/admin` using `GET /api/v1/auth/me` through the Next rewrite. Unauthenticated users are redirected to `/login?next=...`; authenticated non-admin users are redirected away from `/admin`.

Status on `2026-06-04`: full monitor management was moved off `/dashboard` into a dedicated protected `/monitors` page. `/dashboard` now shows a compact monitor summary card with active, paused, and total counts from `/api/v1/dashboard/stats` plus a `Manage monitors` CTA.

### Phase 5: monitors/settings/admin pages

- Migrate monitors list, create/edit, import/export, bulk delete, and manual trigger.
- Migrate settings with safe token handling and scraper settings.
- Migrate bot start/stop/test flows.
- Migrate found-items history/logs after clarifying the current `/logs` route/template mismatch.
- Migrate admin invites last because it is low-frequency and security-sensitive.

Status on `2026-06-03`: core `/api/v1/*` endpoints and current Next page integrations exist for dashboard stats, monitors, settings/Telegram, items/hidden sellers, system status, and admin invites. Remaining work is UI polish, API client consolidation, and deployment verification rather than preserving old Jinja route modules.

UI polish status on `2026-06-03`: dashboard, settings, monitor, found-item, and admin invite surfaces now use more consistent `glass-panel` containers, responsive spacing, loading/error/empty states, disabled action states, and accessible labels for icon-only and destructive actions. Remaining follow-up is API client extraction and live deployment visual verification.

Monitor layout status on `2026-06-04`: full monitor CRUD/control UI is now scoped to `/monitors`; dashboard is an overview surface and no longer embeds the wide monitor table. Playwright covers unauthenticated `/monitors` redirect, authenticated navigation, monitor dialog/domain selection, and page-level mobile overflow for `/dashboard` and `/monitors`.

Telegram/settings polish status on `2026-06-04`: `/settings` now uses safe classified Telegram test errors from `/api/v1/telegram/test`, masked credential status cards, disabled-action help, and clearer loading/success/error states. Domain checkboxes use selectable marketplace cards, while monitor table checkboxes remain compact via the shared checkbox primitive.

### Phase 6: 3D/Spline polish

- Keep Spline limited to landing/auth or non-critical dashboard accents.
- Measure bundle impact and initial load.
- Add reduced-motion and low-power fallbacks.
- Only add React Three Fiber + Drei if Spline cannot support required interactions or if code-driven 3D is explicitly needed.

### Phase 7: Playwright E2E and deployment hardening

- Add Playwright tests for:
  - login/logout
  - registration with invite code
  - CSRF rejection on missing token
  - dashboard stats render
  - monitor create/edit/delete
  - settings save without leaking secrets
  - admin invite access control
- Configure Playwright `webServer` for both frontend and backend.
- Add Railway build/deploy docs for two services.
- Add smoke test for frontend -> backend rewrite.

## Risks

- Security:
  - Raw Telegram tokens must not be returned to the frontend unless there is an explicit edit workflow reason.
  - CSRF endpoint must only return a token for an authenticated session.
  - Keep all ownership checks server-side.
- Auth and cookies:
  - Cross-origin deployment can break HttpOnly cookie behavior. Prefer same-origin Next rewrites.
  - `SameSite=Lax` should be preserved unless a deployment topology proves it insufficient.
- CSRF:
  - Current Jinja injection does not work for standalone Next.
  - Missing CSRF bootstrap would block state-changing APIs or tempt unsafe exceptions.
- API compatibility:
  - Existing routes are form/redirect-first. Do not break them while adding JSON routes.
  - Version new endpoints under `/api/v1`.
- Deployment:
  - Railway two-service setup needs clear environment wiring and health checks.
  - Backend startup currently owns scheduler and Telegram restoration; frontend must not duplicate that.
- SEO:
  - Landing pages can benefit from Next metadata, but authenticated dashboard SEO is irrelevant.
- Bundle size:
  - Spline and future Three.js dependencies can be heavy. Lazy-load and keep them off operational pages.
- 3D performance:
  - Test desktop and mobile. Respect reduced motion.
- Current UI ambiguity:
  - `logs.html` appears to expect found items, while `GET /logs` currently supplies log-manager entries. Resolve before migrating logs/found-items.

## Recommended first implementation task

Create only the `frontend/` scaffold and connectivity skeleton:

1. Scaffold Next.js TypeScript app in `frontend/`.
2. Add Tailwind and shadcn/ui initialization.
3. Add `next.config.ts` rewrite from `/api/:path*` to `BACKEND_URL`.
4. Add a minimal page that calls `/api/health` through the rewrite.
5. Add Playwright config with a smoke test placeholder, but do not require browser verification until the local Playwright browser install is fixed.
6. Do not change FastAPI source code in the first task.

This proves the repo/deployment shape without touching auth, scheduler, scraper, deduplication, or existing Jinja pages.

## Documentation checked

- Context7: `/vercel/next.js`
- Context7: `/tailwindlabs/tailwindcss.com`
- Context7: `/shadcn-ui/ui`
- Official Motion docs: https://motion.dev/docs/react-installation
- Official Spline React package/docs: https://github.com/splinetool/react-spline and https://docs.spline.design/doc/exporting-as-code/docDdDWmkQri
- Official Playwright docs: https://playwright.dev/docs/test-typescript and https://playwright.dev/docs/test-webserver
- React Three Fiber docs for later evaluation: https://r3f.docs.pmnd.rs/
