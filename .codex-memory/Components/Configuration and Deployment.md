---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/configuration
---

# Configuration and Deployment

## Purpose

- Documents environment configuration, container setup, and deployment-sensitive runtime rules.

## Key Files

- `backend/app/app_config.py`
- `backend/.env.example`
- `backend/Dockerfile`
- `backend/docker-compose.yml`
- `backend/railway.json`
- `frontend/railway.json`
- `docs/DEPLOYMENT_ENV.md`

## Audit Notes

- Production validation requires `SECRET_KEY` in some hosted environments.
- `.env.example` does not currently reflect that requirement.
- The settings page exposes some runtime knobs that are not persisted into app settings storage.

## Related Issues

- [[Issues/ISS-006 Scraper settings form does not persist or apply values|ISS-006]]
- [[Issues/ISS-010 .env.example misses production security settings|ISS-010]]
- [[Issues/ISS-RWY-001 Railway PostgreSQL startup failure|ISS-RWY-001]]
- [[Issues/ISS-RWY-002 AsyncSessionLocal None after startup|ISS-RWY-002]]

- 2026-06-02: `.env.example` documents `SECRET_KEY` and `SESSION_COOKIE_SECURE`; session cookies become secure in production envs.
- 2026-06-02: Railway startup error was confirmed as an environment issue: the PostgreSQL service was down/unavailable, not a regression from recent code fixes. See [[Issues/ISS-RWY-001 Railway PostgreSQL startup failure|ISS-RWY-001]].
- 2026-06-02: Later Railway logs showed startup completion but `GET /` failed because of stale database session factory imports; this was tracked separately as source issue [[Issues/ISS-RWY-002 AsyncSessionLocal None after startup|ISS-RWY-002]].

## Frontend Migration Notes

- 2026-06-02: Recommended Railway migration shape is two services: existing FastAPI backend service plus a new `frontend/` Next.js service. The frontend should proxy `/api/*` to the backend through `BACKEND_URL` so browser calls remain same-origin to the frontend.
- 2026-06-02: Avoid a combined Python+Node runtime until operationally necessary; FastAPI continues to own scheduler, scraper, Telegram bot restoration, and database initialization.
- 2026-06-02: `frontend/.env.example` now documents safe frontend placeholders: `BACKEND_URL`, `NEXT_PUBLIC_APP_NAME`, and `NEXT_PUBLIC_SPLINE_SCENE_URL`. No secrets are stored there.
- 2026-06-02: `frontend/next.config.ts` defaults `BACKEND_URL` to `http://localhost:8080` and rewrites `/api/:path*` to the FastAPI backend.

## Railway Split

- 2026-06-03: Repo split into `backend/`, `frontend/`, and `docs/`.
- Backend Railway root: `backend`; build `poetry install --only main --no-root`; start `sh -c 'poetry run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}'`.
- Backend Railway healthcheck path: `/health`.
- Railway provides `PORT`; do not manually set `PORT=8080` for normal Railway deploys.
- Frontend Railway root: `frontend`; build `npm run build`; start `npm run start -- --hostname 0.0.0.0 --port $PORT`.
- Required backend deployment env is limited to deployment-level config such as `DATABASE_URL`, `SECRET_KEY`, `ENVIRONMENT`, `FRONTEND_URL`, `ALLOWED_ORIGINS`, and secure cookie/runtime hints.
- Telegram bot token/chat ID are per-user settings configured in the UI, not required backend deployment env.
- Cloudflare Worker and scraper defaults are admin/global DB settings configured in the UI, with env vars only as optional bootstrap defaults.
- Telegram long polling should run in only one Railway backend replica/process for a given bot token. Multiple replicas or a stale old deployment can make Stop/status appear inconsistent; use webhook architecture or a distributed runtime lock before scaling polling horizontally.
- See [[Decisions/DEC-005 Railway Split Frontend Backend Deployment|DEC-005]] and `Projects/vintedbot/docs/DEPLOYMENT_ENV.md`.

## Split Deployment Audit

- 2026-06-03: Frontend `/api/*` rewrite is configured to `BACKEND_URL` and is used for health, auth, dashboard, settings, monitor, item, hidden-seller, system, and admin calls.
- 2026-06-03: Backend CORS allows `ALLOWED_ORIGINS` and `FRONTEND_URL`; this helps direct cross-origin calls, though the preferred frontend path is same-origin `/api/*` through Next rewrites.
- 2026-06-03: CSRF/session flow needs JSON endpoints before the standalone frontend can safely authenticate and mutate backend state.
- 2026-06-03: Backend `/` now redirects to `FRONTEND_URL` in production when configured, otherwise returns minimal JSON service info. Legacy Jinja route modules were removed in the API-first cleanup.
- Related: [[Issues/ISS-FE-005 Frontend backend integration incomplete|ISS-FE-005]]
- Related: [[Issues/ISS-FE-006 Backend public root is confusing after split|ISS-FE-006]]

## API-first Deployment Notes

- 2026-06-03: Backend legacy route modules were removed. The backend public domain should show only safe backend service behavior on `/`, public health probes, and JSON APIs.
- 2026-06-03: Frontend protected pages rely on same-origin `/api/v1/auth/me` through the Next rewrite. Railway frontend must keep `BACKEND_URL` pointed at the backend service URL.
- 2026-06-03: After Railway redeploy, verify protected frontend redirects and backend health/root behavior from public domains.

## API Contract Notes

- 2026-06-03: [[API Contract]] confirms the frontend should continue using relative `/api/...` paths through the Next rewrite. No backend secrets should be exposed through `NEXT_PUBLIC_` env vars.
- 2026-06-03: Versioned settings APIs expose per-user CF Worker settings and admin/global scraper defaults through `/api/v1/settings/*`. Telegram credentials remain per-user, write-only/masked, and are still not required deployment env variables.
- 2026-06-03: Frontend lint needed generated Playwright output ignored in `frontend/eslint.config.mjs` so missing/ignored `test-results/` does not break validation.
- 2026-06-05: Backend Postgres async engine options are configurable through `db_pool_size`, `db_max_overflow`, `db_pool_timeout`, and `db_pool_recycle_seconds`. Defaults keep pre-ping enabled, recycle pooled connections after 300 seconds, and keep asyncpg statement cache disabled for pooler compatibility.
- 2026-06-05: Auth session lookup catches SQLAlchemy/asyncpg disconnects matching closed-connection failures, rolls back, retries once, and returns a safe `503` if the retry fails. This is intended to reduce frontend proxy socket resets caused by uncaught backend DB disconnects during authenticated API requests.
- 2026-06-05: The same narrow DB disconnect retry helper now covers login, register username lookup, logout session lookup, and both auth dependency implementations. FastAPI returns a controlled `503` only after a known disconnect fails its retry; invalid credentials and non-disconnect DB errors keep their existing behavior.
- 2026-06-05: Backend startup logs now include safe duration timings for database init, runtime settings load, scheduler start, Telegram bot restore, and total application startup. Use these timings in Railway logs to identify the slow startup phase before changing startup sequencing.
- 2026-06-05: Auth DB resilience was tightened again after production login still returned 500. Known disconnect detection now walks SQLAlchemy `orig`, `__cause__`, and `__context__` chains for asyncpg `ConnectionDoesNotExistError` shapes even when `connection_invalidated` is false. Auth login/register/logout and current-user lookups retry the full operation with a fresh session, including login session insert/commit. `DB_USE_NULL_POOL=true` is available as an explicit Railway/Supabase pooler mitigation if queue pooling continues to hand out unstable connections.
- 2026-06-05: Railway readiness was hardened after frontend proxy `ECONNRESET` coincided with backend `/health` service-unavailable healthchecks. FastAPI now releases HTTP liveness quickly and runs DB schema repair/runtime settings/scheduler/Telegram bot restore in a bounded background startup task. `/health` remains a fast liveness endpoint; `/api/health` exposes safe readiness fields (`startup_status`, `database_status`, `scheduler_ready`, `startup_error`). Startup logs include DB pool mode (`queue` or `null`) without printing the DB URL, so `DB_USE_NULL_POOL=true` can be confirmed from logs after deploy.
- 2026-06-05: Follow-up deployment mismatch investigation found the new readiness build could still fail before liveness because `lifespan()` had a function-local `import asyncio` in shutdown cleanup, shadowing the module import used to schedule the background startup task. That startup crash explains a Railway healthcheck failure retaining the old active image. Backend `/` and `/api/health` now include safe deploy markers (`health_schema_version`, `code_version`, optional short commit) so production/service mismatches are obvious without exposing secrets.
- 2026-06-05: DB request resilience now includes `db_operation_timeout_seconds` (default `10`) around the shared retry helper. A timed-out DB operation is rolled back, retried once with a fresh session, and then returned through the existing controlled `503` path if it still cannot complete. This protects login/auth requests from hanging until Railway/Next reports `ECONNRESET`.
- 2026-06-05: Postgres/asyncpg engine config now also sets `db_connect_timeout_seconds` (default `10`), asyncpg `command_timeout`, and PostgreSQL `statement_timeout` via safe server settings. `/api/health` includes `database_pool_mode` (`queue`, `null`, or `static`) so production can confirm whether `DB_USE_NULL_POOL=true` was applied without printing the database URL.
- 2026-06-05: Auth API operations have a separate `auth_db_operation_timeout_seconds` deadline (default `12`) around the whole retry flow. This is the final request boundary for login/register/logout if the DB driver stalls without raising a retryable SQLAlchemy/asyncpg error.

## Related Plans

- [[Frontend Migration Plan]]
- [[Components/Frontend Next.js]]

