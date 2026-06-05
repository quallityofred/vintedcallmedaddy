---
type: core
project: vintedbot
tags:
  - vintedbot
  - core/project-graph
---

# Project Graph

## Core Memory

- [[PROJECT_OVERVIEW]]
- [[ARCHITECTURE]]
- [[RUNBOOK]]
- [[AGENT_WORKFLOW]]
- [[API Contract]]
- [[AUDIT]]
- [[DECISIONS]]
- [[TODO]]
- [[CHANGELOG]]

## Components

- [[Components/Backend FastAPI]]
- [[Components/Frontend]]
- [[Components/Frontend Next.js]]
- [[Components/Web Dashboard]]
- [[Components/FastAPI Routes]]
- [[Components/Scheduler]]
- [[Components/Scraper]]
- [[Components/Telegram Bot]]
- [[Components/Database]]
- [[Components/Templates and Static]]
- [[Components/Configuration and Deployment]]
- [[Components/Tests]]

## Plans

- [[Frontend Migration Plan]]

## Frontend Design Passes

- 2026-06-02: No Figma design context was available. The Next.js frontend design was extended from scratch using product memory and [[Components/Frontend Next.js]].
- 2026-06-03: Frontend UI/UX polish pass standardized async states, improved dashboard/admin/settings layout rhythm, added action aria-labels, and removed unfinished migration/legacy user-facing copy.
- 2026-06-04: Dashboard monitor management was split into a dedicated protected `/monitors` page; dashboard now stays an overview surface with a compact monitor summary and CTA.
- 2026-06-04: Follow-up polish improved Telegram settings feedback, shared checkbox styling, domain marketplace cards, and compact monitor selection controls.
- 2026-06-04: `/monitors` received a strict visual rework: raw table rows were replaced by responsive monitor cards with visible selection, metadata tiles, and labeled actions.
- 2026-06-04: `/monitors` spacing and domain selector were refined with a compact minimal selector and clearer separation before informational cards.
- 2026-06-04: `/monitors` edit/create flow was hardened: monitor API responses include selected `domains`, edit dialogs use isolated controlled drafts, close-without-submit does not persist changes, and monitor cards show selected domains.

## Fixed Audit Issues

- [[Issues/ISS-001 Settings page misses required context|ISS-001]] -> [[Fixes/FIX-001 Settings page context|FIX-001]]
- [[Issues/ISS-002 Admin invite management routes are missing|ISS-002]] -> [[Fixes/FIX-002 Admin invite routes|FIX-002]]
- [[Issues/ISS-003 Hide seller flow is broken and not user-scoped|ISS-003]] -> [[Fixes/FIX-003 User scoped hide seller|FIX-003]]
- [[Issues/ISS-004 Dashboard exposes shared system logs to every user|ISS-004]] -> [[Fixes/FIX-004 Log API isolation|FIX-004]]
- [[Issues/ISS-005 Duplicate implementation modules shadow runtime behavior|ISS-005]] -> [[Fixes/FIX-005 Canonical router and scheduler modules|FIX-005]]
- [[Issues/ISS-006 Scraper settings form does not persist or apply values|ISS-006]] -> [[Fixes/FIX-006 Scraper settings persistence|FIX-006]]
- [[Issues/ISS-007 Invite code consumption is race-prone|ISS-007]] -> [[Fixes/FIX-007 Atomic invite consumption|FIX-007]]
- [[Issues/ISS-008 Session and CSRF protections are incomplete|ISS-008]] -> [[Fixes/FIX-008 CSRF and secure cookies|FIX-008]]
- [[Issues/ISS-009 Notification worker can crash on invalid Telegram tokens|ISS-009]] -> [[Fixes/FIX-009 Notification worker failure containment|FIX-009]]
- [[Issues/ISS-010 .env.example misses production security settings|ISS-010]] -> [[Fixes/FIX-010 Production security env example|FIX-010]]

## Fixed Runtime Issues

- [[Issues/ISS-RWY-002 AsyncSessionLocal None after startup|ISS-RWY-002]] -> [[Fixes/FIX-RWY-002 Database session dependency initialization|FIX-RWY-002]]
- [[Issues/ISS-FE-006 Backend public root is confusing after split|ISS-FE-006]] -> [[Fixes/FIX-FE-006 Backend root and health connectivity|FIX-FE-006]]
- [[Issues/ISS-AUTH-001 Next frontend login API pending|ISS-AUTH-001]] -> [[Fixes/FIX-AUTH-001 JSON auth API and login form|FIX-AUTH-001]]
- [[Issues/ISS-AUTH-002 Next frontend registration API missing|ISS-AUTH-002]] -> [[Fixes/FIX-AUTH-002 JSON registration API|FIX-AUTH-002]]
- [[Issues/ISS-API-002 Settings Telegram CF Worker scraper API missing|ISS-API-002]] -> [[Fixes/FIX-API-002 Settings Telegram CF Worker scraper APIs|FIX-API-002]]
- [[Issues/ISS-FE-007 Protected frontend routes visible while unauthenticated|ISS-FE-007]] -> [[Fixes/FIX-FE-007 Frontend auth guard for protected routes|FIX-FE-007]]
- [[Issues/ISS-API-004 Legacy placeholder route modules remained after API-first migration|ISS-API-004]] -> [[Fixes/FIX-API-004 Remove legacy placeholder route modules|FIX-API-004]]
- [[Issues/ISS-FE-008 Frontend UI polish incomplete|ISS-FE-008]] -> [[Fixes/FIX-FE-008 Frontend UI UX polish pass|FIX-FE-008]]
- [[Issues/ISS-FE-009 Dashboard monitor table overflow|ISS-FE-009]] -> [[Fixes/FIX-FE-009 Dedicated monitors page|FIX-FE-009]]
- [[Issues/ISS-API-005 Monitor domains endpoint 500|ISS-API-005]] -> [[Fixes/FIX-API-005 Unique Vinted domain loading|FIX-API-005]]
- [[Issues/ISS-TG-001 Telegram test returns vague 502|ISS-TG-001]] -> [[Fixes/FIX-TG-001 Telegram test error classification|FIX-TG-001]]
- [[Issues/ISS-FE-010 Checkbox and settings polish follow-up|ISS-FE-010]] -> [[Fixes/FIX-FE-010 Checkbox and settings polish pass|FIX-FE-010]]

## Fixed Security Issues

- [[Issues/ISS-011 Settings page exposes saved Telegram credentials|ISS-011]] -> [[Fixes/FIX-011 Settings credential masking and admin globals|FIX-011]]

## Open Environment Issues

- [[Issues/ISS-RWY-001 Railway PostgreSQL startup failure|ISS-RWY-001]]: Railway PostgreSQL service down/unavailable; not source-code-related. Later logs show startup now completes, so keep this as a deployment stability watch item until Railway DB health is confirmed.

## Open Frontend Issues

- [[Issues/ISS-FE-001 Next.js PostCSS audit advisory|ISS-FE-001]]: moderate npm audit advisory through current Next.js/PostCSS dependency path; no safe non-breaking npm remediation available at implementation time.
- [[Issues/ISS-FE-005 Frontend backend integration incomplete|ISS-FE-005]]: Next.js frontend now has health, auth, protected route guards, dashboard, settings, monitors, items, hidden sellers, system status, and admin invite connectivity; remaining work is polish/API client consolidation rather than missing core API surface.
- [[Issues/ISS-API-001 Full Next frontend API contract missing|ISS-API-001]]: core versioned API contract is now implemented for auth/register/CSRF, settings/Telegram/CF Worker/scraper, monitors, dashboard, items, hidden sellers, system status, and admin invites; keep open until API contract docs are normalized and final frontend page integration is hardened.

## Decisions

- [[Decisions/DEC-001 Working Tree Path Alias|DEC-001 Working Tree Path Alias]]
- [[Decisions/DEC-002 Graph Memory Structure|DEC-002 Graph Memory Structure]]
- [[Decisions/DEC-003 Canonical Runtime Modules|DEC-003 Canonical Runtime Modules]]
- [[Decisions/DEC-004 Next.js Frontend Migration|DEC-004 Next.js Frontend Migration]]
- [[Decisions/DEC-005 Railway Split Frontend Backend Deployment|DEC-005 Railway Split Frontend Backend Deployment]]

## Deployment

- 2026-06-03: Railway split implemented with backend root `backend` and frontend root `frontend`; deployment variables documented in `Projects/vintedbot/docs/DEPLOYMENT_ENV.md`.
- 2026-06-03: Backend Railway start command shell-wraps `${PORT:-8080}` and healthcheck path is `/health`. Backend public `/` no longer exposes the legacy Jinja dashboard in production.

## Workflow

- [[AGENT_WORKFLOW]] is the permanent Codexdian workflow for future tasks: memory-first startup, source verification, graph metadata rules, secret handling, split Railway architecture, testing, memory updates, and git/push rules.
- 2026-06-03: [[AGENT_WORKFLOW]] now requires token-efficient targeted memory usage: start with workflow, graph, TODO, and relevant changelog entries; read API/frontend/runbook/architecture/component/issue notes only when task-relevant.

## API Contract

- [[API Contract]] inventories current backend/frontend API state and missing Next-ready endpoints for auth, registration, CSRF, settings, Telegram, CF Worker, scraper settings, monitors, dashboard, items, hidden sellers, and system status.
- 2026-06-03: API-first cleanup removed obsolete legacy route modules and added frontend auth guards for protected Next routes. `/api/v1/*` remains the active app API surface.
- 2026-06-04: Monitor domains API now exposes unique Vinted marketplace representatives and validates monitor create/update target domains against that registry.
- 2026-06-04: Monitor list/detail/create/update/control responses now include selected representative `domains` so frontend edit forms can initialize from persisted state.
- 2026-06-04: Telegram test API now returns safe classified setup/runtime error codes for the Next settings UI.
- 2026-06-04: Monitor runtime was verified and tightened: cold start writes `SeenItem` baseline only, user-level stable item IDs dedupe repeats across domains, and Telegram notifications use safe HTML through the monitor owner's saved credentials.
- 2026-06-04: Telegram bot stop/status was hardened: stop no longer reports success until polling ends, timeout/incomplete stops remain visible as running, `/api/health` prunes stale bot tasks, and a safe cleanup script can clear webhook/pending-update state without printing credentials.
- 2026-06-04: CF Worker routing mode persistence was hardened with startup user-column migrations, explicit `cf_worker_mode` PATCH/GET tests, frontend payload/error handling tests, and a fixed monitor debug trigger.
- 2026-06-05: Frontend action buttons now use a shared exact-key async action model. Monitor mutations update local state from returned API data where available, same-monitor conflicting actions are disabled, unrelated monitor/seller/settings actions keep independent loading state, and stale monitor poll responses are ignored after newer mutations.

## Recommended Obsidian Graph Groups

```text
tag:#issue/open
Color: red

tag:#issue/fixed
Color: green

tag:#issue/blocked
Color: gray

tag:#severity/critical
Color: bright red or purple

tag:#severity/high
Color: orange

tag:#severity/medium
Color: yellow

tag:#severity/low
Color: light gray

tag:#fix/completed
Color: green or blue-green

tag:#fix/partial
Color: teal

tag:#decision
Color: purple

tag:#core/project-graph OR tag:#core/project-overview OR tag:#core/architecture OR tag:#core/runbook OR tag:#core/audit OR tag:#core/todo OR tag:#core/changelog OR tag:#core/decisions
Color: white

tag:#component/frontend OR tag:#component/web OR tag:#component/api OR tag:#component/scheduler OR tag:#component/scraper OR tag:#component/telegram OR tag:#component/database OR tag:#component/templates OR tag:#component/configuration OR tag:#component/tests
Color: blue
```
