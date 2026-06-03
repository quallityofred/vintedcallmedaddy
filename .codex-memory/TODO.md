---
type: todo
project: vintedbot
tags:
  - vintedbot
  - core/todo
---

# TODO

## Audit Fix Status

- 2026-06-02: All audit issues ISS-001 through ISS-010 were fixed and tested.

## Follow-up Watch Items

- Verify Railway remains stable after the database availability incident in [[Issues/ISS-RWY-001 Railway PostgreSQL startup failure|ISS-RWY-001]].
- Redeploy the database session initialization fix in [[Issues/ISS-RWY-002 AsyncSessionLocal None after startup|ISS-RWY-002]] and check `GET /` after `Application startup complete`.
- Monitor production scraper behavior after runtime settings changes, especially active session refresh and concurrency changes.
- Consider adding a migration framework if schema changes grow beyond lightweight startup migrations.
- Keep localized UI text encoding consistent in future template/test edits.
- Before migrating the logs/found-items page, verify the current `GET /logs` route and `app/templates/logs.html` contract. The route currently appears to pass log-manager entries while the template expects found-item data such as `items` and `monitors_map`.

## Frontend Migration

- 2026-06-02: Phase 1 scaffold completed in `Projects/vintedbot/frontend`.
- 2026-06-03: [[Issues/ISS-FE-005 Frontend backend integration incomplete|ISS-FE-005]] opened after split deployment audit. The Next frontend is still a placeholder shell and lacks real API integration.
- 2026-06-03: Auth JSON endpoints were added in [[Issues/ISS-AUTH-001 Next frontend login API pending|ISS-AUTH-001]].
- 2026-06-03: Auth/register/CSRF API phase completed in [[Issues/ISS-AUTH-002 Next frontend registration API missing|ISS-AUTH-002]].
- 2026-06-03: [[API Contract]] created and [[Issues/ISS-API-001 Full Next frontend API contract missing|ISS-API-001]] opened for remaining Next-ready APIs.
- 2026-06-03: Settings Telegram/CF Worker/scraper API phase completed in [[Issues/ISS-API-002 Settings Telegram CF Worker scraper API missing|ISS-API-002]].
- Next API phase: monitors CRUD/control. Start with user-scoped `GET /api/v1/monitors`, `POST /api/v1/monitors`, `GET/PATCH/DELETE /api/v1/monitors/{id}`, then scheduler-safe trigger/control endpoints.
- 2026-06-03: Backend `/` behavior decided and implemented in [[Issues/ISS-FE-006 Backend public root is confusing after split|ISS-FE-006]]: production redirects to `FRONTEND_URL` when configured, otherwise returns minimal JSON; legacy Jinja dashboard stays at `/dashboard`.
- Consider extracting a small frontend API client now that login uses relative `/api/v1/auth/*` requests.
- Replace dashboard/settings placeholders with API-backed flows after monitor/dashboard APIs are stable.
- Keep all existing Jinja routes until the replacement page has equivalent behavior and E2E coverage.
- 2026-06-03: Railway two-service split implemented and documented with backend root `backend` and frontend root `frontend`.
- After Railway service creation, paste backend URL into frontend `BACKEND_URL`, then paste frontend URL into backend `FRONTEND_URL` and `ALLOWED_ORIGINS`.
- Rotate any previously exposed database password, `DATABASE_URL`, `SECRET_KEY`, Telegram token, proxy credential, or other credential before deployment.
- Track [[Issues/ISS-FE-001 Next.js PostCSS audit advisory|ISS-FE-001]] and re-run `npm audit --omit=dev` after Next.js releases a non-breaking dependency update.
- 2026-06-02: Public/landing design polish started from scratch because no Figma context was available.

## Backend Settings

- 2026-06-03: Telegram credentials are per-user write-only/masked in the Jinja settings UI.
- 2026-06-03: Cloudflare Worker and scraper defaults are admin/global DB settings.
- Follow up after deployment: verify an admin can change CF Worker/scraper defaults in production without redeploying.

## Graph Metadata Validation

- 2026-06-02: No remaining issue graph metadata problems after normalization scan.








