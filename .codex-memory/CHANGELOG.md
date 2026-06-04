---
type: changelog
project: vintedbot
tags:
  - vintedbot
  - core/changelog
---

# Changelog

- 2026-06-02: Initialized `Codex Memory/vintedbot` and verified read access to the repository and compatibility wrapper files.
- 2026-06-02: Verified that `Projects/vintedbot` is a junction to `C:\Users\egory\vintedbot`; both paths resolve to the same git working tree.
- 2026-06-02: Built a graph-friendly memory structure with component notes, audit notes, issue records, and linked decision notes after auditing `Projects/vintedbot`.
- 2026-06-02: Fixed all 10 audit issues: settings context/persistence, admin invite routes, user-scoped seller hiding, log isolation, duplicate router/scheduler modules, atomic invite use, CSRF/secure cookies, notification worker failure containment, and `.env.example` production security docs. Verified with `poetry run pytest -q` -> 26 passed.
- 2026-06-02: Pushed audit fixes to GitHub at commit `cd3b7f2c93f9f7fa65b0b33e915754620ef1ca82`.
- 2026-06-02: Normalized issue graph metadata tags so fixed issues use `issue/fixed`, component tags use consistent lowercase graph groups, and `PROJECT_GRAPH.md` includes recommended Obsidian graph groups.
- 2026-06-02: Added [[Issues/ISS-RWY-001 Railway PostgreSQL startup failure|ISS-RWY-001]] documenting that the Railway startup error is environment-related: PostgreSQL service down/unavailable, not caused by recent source-code fixes.

- 2026-06-02: Applied graph styling protocol metadata across core, component, issue, fix, decision, audit, runbook, changelog, and todo memory notes.
- 2026-06-02: Fixed [[Issues/ISS-RWY-002 AsyncSessionLocal None after startup|ISS-RWY-002]] by resolving the async database session factory dynamically at runtime instead of using stale imported `None` values from compatibility wrappers.
- 2026-06-02: Created [[Frontend Migration Plan]], [[Components/Frontend]], and [[Decisions/DEC-004 Next.js Frontend Migration|DEC-004]] after verifying current FastAPI/Jinja routes, templates, auth/CSRF behavior, APIs, tests, and deployment files. Source code was not modified.
- 2026-06-02: Implemented Phase 1 frontend scaffold in `Projects/vintedbot/frontend`: Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui foundation, Motion, Spline-ready placeholder, Playwright smoke test, landing/login/dashboard/settings placeholder pages, and same-origin `/api/*` rewrite config. Verified with frontend lint, build, Playwright smoke test, and `git diff --check`.
- 2026-06-02: Added [[Issues/ISS-FE-001 Next.js PostCSS audit advisory|ISS-FE-001]] for the moderate npm audit advisory reported through current Next.js/PostCSS where npm only suggests a breaking forced remediation.
- 2026-06-02: Extended the Next.js frontend design from scratch because no Figma selection was available. Added product-specific landing/dashboard sections, reusable `MonitorPreview` and `SectionHeading` components, clearer demo-placeholder labeling, dashboard API-readiness guidance, settings safety notes, and expanded Playwright smoke coverage to `/dashboard` and `/settings`.
- 2026-06-03: Split the repo into Railway-ready `backend/`, `frontend/`, and `docs/` structure; added backend/frontend Railway configs and `docs/DEPLOYMENT_ENV.md`; moved FastAPI/Jinja/backend tests under `backend/`; kept Next.js frontend under `frontend/`.
- 2026-06-03: Implemented safe settings ownership: Telegram bot token/chat ID remain per-user and write-only/masked in the Jinja settings UI; Cloudflare Worker and scraper defaults are admin/global DB settings; env vars are deployment/bootstrap defaults only.
- 2026-06-03: Validated split/settings work with `backend` Poetry install, backend pytest/import smoke, frontend npm install/lint/build/Playwright E2E, and `git diff --check`.
- 2026-06-03: Pushed Railway split/settings commit `51875c5e9ad5a61ba673282692f727db71338753` to GitHub `main`.
- 2026-06-03: Performed investigation-only audit of the split frontend/backend state. Opened [[Issues/ISS-FE-005 Frontend backend integration incomplete|ISS-FE-005]] documenting that Next pages remain placeholders and versioned FastAPI JSON APIs are missing. Source code was not modified.
- 2026-06-03: Fixed [[Issues/ISS-FE-006 Backend public root is confusing after split|ISS-FE-006]] by moving the legacy dashboard to `/dashboard`, making production backend `/` redirect to `FRONTEND_URL` or return minimal JSON, adding a Next.js backend health card via `/api/health`, and shell-wrapping the Railway backend start command for `${PORT:-8080}`.
- 2026-06-03: Fixed [[Issues/ISS-AUTH-001 Next frontend login API pending|ISS-AUTH-001]] by adding versioned JSON auth endpoints for CSRF, current user, login, and logout; replaced the Next.js login placeholder with a real `/api/v1/auth/*` client form.
- 2026-06-03: Created [[AGENT_WORKFLOW]] as the permanent Codexdian task workflow and updated [[PROJECT_GRAPH]]. Also corrected [[RUNBOOK]] Railway commands to match current source configs.
- 2026-06-03: Created [[API Contract]] and opened [[Issues/ISS-API-001 Full Next frontend API contract missing|ISS-API-001]] after inventorying current backend routes and frontend API usage. Source code was not modified.
- 2026-06-03: Completed auth/register/CSRF API phase by adding `POST /api/v1/auth/register` with API CSRF, atomic invite consumption, existing password hashing, existing HttpOnly session cookie, and tests. Opened/fixed [[Issues/ISS-AUTH-002 Next frontend registration API missing|ISS-AUTH-002]].
- 2026-06-03: Updated [[AGENT_WORKFLOW]] with token-efficient targeted memory usage rules so future tasks start from compact index notes instead of scanning the full memory folder.
- 2026-06-03: Completed settings Telegram/CF Worker/scraper API phase by adding versioned settings and Telegram endpoints with masked credentials, CSRF-protected mutations, admin-only global settings updates, runtime application, and focused tests. Opened/fixed [[Issues/ISS-API-002 Settings Telegram CF Worker scraper API missing|ISS-API-002]].
- 2026-06-03: Completed dashboard stats API phase by adding GET /api/v1/dashboard/stats with user-scoped counts for monitors, items, last discovery, and Telegram status; integrated into Next.js dashboard and verified with tests.

- 2026-06-03: Implemented read-only monitors API (list and detail) in ackend/app/web/monitors_api_router.py; integrated real monitor data into the Next.js dashboard MonitorPreview component; added backend tests and verified frontend build.

- 2026-06-03: Implemented monitor mutation APIs (create, update, delete, bulk-delete, pause, resume, check-now) and integrated them into the Next.js dashboard with a New/Edit Monitor dialog and bulk action support.

- 2026-06-03: Implemented items and hidden-sellers API (list/detail/hide) and integrated items list into the dashboard with seller-hide action support.

- 2026-06-03: Implemented system status API and admin-only invite management JSON APIs.

- 2026-06-03: Integrated System Status card in dashboard and created Admin Invite management page.

- 2026-06-03: Performed end-to-end verification and frontend UI polish pass, including fixes for test data collisions and frontend type/lint errors.

- 2026-06-03: Finalized legacy cleanup by removing Jinja2 templates, disabling legacy routes, and updating audit tests.

- 2026-06-03: Finished API-first migration cleanup by removing obsolete legacy backend route modules, moving invite-code consumption into a shared API-safe helper, keeping backend `/` as safe service JSON/production frontend redirect, and updating route-table/audit tests for the active `/api/v1/*` architecture.

- 2026-06-03: Added Next.js auth guards for `/dashboard`, `/settings`, and `/admin`; unauthenticated users redirect to `/login?next=...`, login/register preserve sanitized `next` redirects, non-admin users cannot see admin content, and Playwright coverage was expanded.

- 2026-06-03: Polished the Next.js frontend UI for dashboard/settings/admin workflows: standardized async loading and disabled states, improved monitor/item/invite table layouts, added accessible action labels, removed unfinished user-facing migration/legacy copy, and verified frontend lint/build/Playwright.
- 2026-06-04: Moved full monitor management from `/dashboard` to protected `/monitors`, added an authenticated `Monitors` nav item, replaced the dashboard monitor table with a compact summary/CTA card, removed monitor management from the public landing page, and expanded Playwright coverage for `/monitors`, monitor dialog/domain selection, and mobile overflow.
- 2026-06-04: Fixed `GET /api/v1/monitors/domains` by replacing the broken flag lookup with a curated unique Vinted marketplace registry, representative-only domain validation, alias URL normalization, URL cleaning tests, scheduler-side cross-domain item-ID dedup, a manual domain probe script, and frontend domain selector error/retry handling.
- 2026-06-04: Improved Telegram settings/test behavior and frontend polish: `/api/v1/telegram/test` now returns safe classified errors, `/settings` shows masked status and actionable messages, shared checkbox styling was polished, domain selection uses marketplace cards, and monitor selection uses the shared checkbox component.
- 2026-06-04: Reworked `/monitors` from a raw table into responsive monitor cards with a selection toolbar, visible square checkboxes, metadata tiles, labeled action buttons, polished empty state, and stronger domain marketplace card labels.
- 2026-06-04: Refined `/monitors` spacing below the monitor card list and simplified the create/edit domain selector into compact checkbox rows with code badges and minimal labels.
- 2026-06-04: Fixed `/monitors` edit/create state handling and selected-domain display: monitor API responses now include persisted `domains`, edit dialogs use isolated controlled draft state, closing without submit discards unsaved changes, and monitor cards show concise selected domains with truncation/title support.
- 2026-06-04: Verified and tightened monitor runtime behavior: cold-start checks now create `SeenItem` baseline only, repeat/cross-domain stable item IDs do not create duplicate user-visible findings or notifications, Telegram notification messages use safe HTML with monitor/item details, and failed sends keep items pending.
