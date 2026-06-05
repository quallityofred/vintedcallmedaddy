---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/tests
---

# Tests

## Purpose

- Provides regression coverage for selected auth, import/export, migration, scheduler, and startup scenarios.

## Key Files

- `backend/tests/conftest.py`
- `backend/tests/test_admin_invite.py`
- `backend/tests/test_audit_fixes.py`
- `backend/tests/test_bot_startup_fix.py`
- `backend/tests/test_fixes_v2.py`
- `backend/tests/test_import_export.py`
- `backend/tests/test_migration.py`
- `backend/tests/test_overhaul.py`
- `backend/tests/test_stress.py`
- `frontend/tests/e2e/landing.spec.ts`

## Current Snapshot

- `poetry run pytest -q` passed with `16` tests on `2026-06-02`.
- Frontend Phase 1 snapshot on `2026-06-02`:
  - `npm run lint` passed in `frontend/`.
  - `npm run build` passed in `frontend/`.
  - `npm run test:e2e` passed in `frontend/` with one Chromium landing-page smoke test.
- Frontend design pass snapshot on `2026-06-02`:
  - `npm run lint` passed in `frontend/`.
  - `npm run build` passed in `frontend/`.
  - `npm run test:e2e` passed in `frontend/` with two Chromium smoke tests covering landing, dashboard, and settings.
- Railway split/settings snapshot on `2026-06-03`:
  - `cd backend && poetry install` completed.
  - `cd backend && poetry run pytest -q` -> 30 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm install` completed with the known moderate frontend audit advisory still present.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed.
  - `cd frontend && npm run test:e2e` -> 2 passed.
  - `git diff --check` -> passed with line-ending warnings only.
- Backend root/health connectivity snapshot on `2026-06-03`:
  - `cd backend && poetry run pytest -q` -> 34 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed.
  - `cd frontend && npm run test:e2e` -> 2 passed.
  - `git diff --check` -> passed with line-ending warnings only.
- JSON auth/login snapshot on `2026-06-03`:
  - `cd backend && poetry run pytest -q` -> 36 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed.
  - `cd frontend && npm run test:e2e` -> 3 passed.
  - `git diff --check` -> passed with line-ending warnings only.
- Auth/register API snapshot on `2026-06-03`:
  - `cd backend && poetry run pytest tests/test_auth_api.py -q` -> 4 passed.
  - `cd backend && poetry run pytest -q` -> 38 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed.
  - `cd frontend && npm run test:e2e` -> 3 passed.
  - `git diff --check` -> passed with line-ending warnings only.
- Settings/Telegram API snapshot on `2026-06-03`:
  - `cd backend && poetry run pytest tests/test_settings_api.py -q` -> 5 passed.
  - `cd backend && poetry run pytest -q` -> 43 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run lint` initially failed because ESLint scanned missing generated `test-results/`; fixed by ignoring Playwright output.
  - `cd frontend && npm run lint` -> passed after ignore fix.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 3 passed with known Node `DEP0205` warning.
  - `git diff --check` -> passed with line-ending warnings only.
- API-first cleanup/auth guard snapshot on `2026-06-03`:
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd backend && poetry run pytest -q` -> 57 passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 6 passed with known Node `DEP0205` warning.
  - `git diff --check` -> passed with line-ending warnings only.
- Frontend UI/UX polish snapshot on `2026-06-03`:
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 6 passed with known Node `DEP0205` warning.
  - `git diff --check` -> passed with line-ending warnings only.
- Dedicated monitors page snapshot on `2026-06-04`:
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 7 passed with known Node `DEP0205` warning and expected isolated local backend proxy noise.
- Unique Vinted domain loading snapshot on `2026-06-04`:
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 14 passed.
  - `cd backend && poetry run pytest -q tests/test_fixes_v2.py` -> 4 passed.
  - `cd backend && poetry run pytest -q tests/test_audit_fixes.py` -> 2 passed.
  - `cd backend && poetry run pytest -q` -> 64 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 8 passed with known Node `DEP0205` warning and expected isolated local backend proxy noise.
- Telegram/settings/checkbox polish snapshot on `2026-06-04`:
  - `cd backend && poetry run pytest -q tests/test_settings_api.py` -> 14 passed.
  - `cd backend && poetry run pytest -q` -> 73 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 8 passed with known Node `DEP0205` warning and expected isolated local backend proxy noise.
  - `git diff --check` -> passed with line-ending warnings only.
- Monitor edit/domains UI snapshot on `2026-06-04`:
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 14 passed.
  - `cd backend && poetry run pytest -q` -> 73 passed when run alone. A parallel run with backend import smoke failed from shared SQLite test setup (`no such table: users`), then passed on isolated rerun.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 8 passed with known Node `DEP0205` warning.
  - Playwright MCP verified `/monitors` edit opens with persisted name/URL/interval/domains, Escape close does not send `PATCH`, reopening restores persisted values, selected domains are visible, and desktop/mobile scroll width matches viewport.
  - `git diff --check` -> passed with line-ending warnings only.
- Monitor runtime/Telegram snapshot on `2026-06-04`:
  - `cd backend && poetry run pytest -q tests/test_fixes_v2.py` -> 9 passed.
  - `cd backend && poetry run pytest -q tests/test_audit_fixes.py` -> 2 passed.
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 14 passed.
  - `cd backend && poetry run pytest -q tests/test_stress.py` -> 1 passed.
  - `cd backend && poetry run pytest -q` -> 78 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `git diff --check` -> passed with line-ending warnings only.
  - Frontend was not changed in this pass, so frontend lint/build/e2e were not run.
- Telegram bot stop/status snapshot on `2026-06-04`:
  - Added `backend/tests/test_telegram_runtime.py` for idempotent start, stop cleanup, stop timeout truthfulness, `/api/health` live task counting, and cleanup-script secret-safe output.
  - Expanded `backend/tests/test_settings_api.py` to assert stop timeout returns a safe failure instead of false success.
- CF Worker routing mode save snapshot on `2026-06-04`:
  - `cd backend && poetry run pytest -q tests/test_settings_api.py tests/test_monitors_api.py` -> 32 passed.
  - `cd backend && poetry run pytest -q` -> 88 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd backend && poetry run python -m py_compile scripts/migrate_user_cf_worker_mode.py` -> passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 9 passed with known Node `DEP0205` warning.
  - `git diff --check` -> passed with line-ending warnings only.
- Telegram forum topics backend foundation snapshot on `2026-06-04`:
  - `cd backend && poetry run pytest -q tests/test_telegram_topics.py` -> 12 passed.
  - `cd backend && poetry run pytest -q tests/test_telegram_runtime.py` -> 5 passed.
  - `cd backend && poetry run pytest -q tests/test_settings_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q` -> 107 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd backend && poetry run python -m py_compile scripts/migrate_telegram_topics.py` -> passed.
  - Frontend was not changed in this phase, so frontend lint/build/e2e were not run.
- Telegram topic routing snapshot on `2026-06-04`:
  - `cd backend && poetry run pytest -q tests/test_telegram_topics.py` -> 22 passed.
  - `cd backend && poetry run pytest -q tests/test_telegram_runtime.py` -> 5 passed.
  - `cd backend && poetry run pytest -q tests/test_settings_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q` -> 117 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd backend && poetry run python -m py_compile scripts/migrate_telegram_topics.py` -> passed.
  - Frontend was not changed in this phase, so frontend lint/build/e2e were not run.
- Telegram topic monitor-name-only title fix on `2026-06-05`:
  - `cd backend && poetry run pytest -q tests/test_telegram_topics.py` -> 27 passed.
  - `cd backend && poetry run pytest -q tests/test_telegram_runtime.py` -> 5 passed.
  - `cd backend && poetry run pytest -q` -> 122 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - Frontend was not changed in this fix, so frontend lint/build were not run.
- DB connection resilience snapshot on `2026-06-05`:
  - `cd backend && poetry run pytest -q tests/test_database_session_factory.py tests/test_auth_api.py` -> 13 passed.
  - `cd backend && poetry run pytest -q tests/test_telegram_topics.py` -> 27 passed.
  - `cd backend && poetry run pytest -q tests/test_settings_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q` -> 128 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
- Monitor load and DB route retry hotfix snapshot on `2026-06-05`:
  - `cd backend && poetry run pytest -q tests/test_auth_api.py tests/test_database_session_factory.py` -> 15 passed.
  - `cd backend && poetry run pytest -q tests/test_telegram_topics.py` -> 28 passed.
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q` -> 131 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 12 passed with known Node `DEP0205` warning.
- Login DB disconnect hotfix snapshot on `2026-06-05`:
  - `cd backend && poetry run pytest -q tests/test_auth_api.py tests/test_database_session_factory.py` -> 19 passed.
  - `cd backend && poetry run pytest -q tests/test_telegram_topics.py` -> 28 passed.
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q tests/test_settings_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q` -> 135 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.

## Coverage Gaps

- Route-table/audit tests now cover active API-first routes and absence of removed legacy UI routes.
- No template-render test for `/settings`.
- No end-to-end seller-hide persistence test.
- No test for shared-system-log isolation.
- No concurrency test for invite consumption.
- No tests yet for missing Next-ready dashboard/settings/monitor/item/hidden-seller APIs listed in [[API Contract]].
- No real Telegram API tests for forum topics; all topic coverage uses mocks and avoids network calls.

## Related Issues

- [[Issues/ISS-001 Settings page misses required context|ISS-001]]
- [[Issues/ISS-002 Admin invite management routes are missing|ISS-002]]
- [[Issues/ISS-003 Hide seller flow is broken and not user-scoped|ISS-003]]
- [[Issues/ISS-004 Dashboard exposes shared system logs to every user|ISS-004]]
- [[Issues/ISS-007 Invite code consumption is race-prone|ISS-007]]

- 2026-06-02: Added `tests/test_audit_resolutions.py`; full suite now has 26 passing tests covering audit fixes.
- 2026-06-02: Added frontend Playwright config and `frontend/tests/e2e/landing.spec.ts` for the Next.js landing page.
- 2026-06-02: Expanded `frontend/tests/e2e/landing.spec.ts` to verify the scratch-designed monitor preview plus `/dashboard` and `/settings` placeholders.
- 2026-06-03: Added backend route tests for production `/`, development `/`, `/dashboard`, `/health`, and `/api/health`; updated Playwright smoke coverage for the frontend backend health card.
- 2026-06-03: Added `backend/tests/test_auth_api.py` for CSRF, login success/failure, `/me`, and logout; expanded Playwright login coverage for API error states.
- 2026-06-03: Expanded `backend/tests/test_auth_api.py` to cover JSON registration success, CSRF enforcement, invite consumption, duplicate username, password mismatch, and invalid invite cases.
- 2026-06-03: Added `backend/tests/test_settings_api.py` for versioned settings/Telegram APIs, including auth requirements, CSRF, credential masking, admin-only global updates, validation, and faked Telegram controls.
- 2026-06-03: Rewrote legacy route-table/audit tests to assert the API-first route surface and removed legacy UI routes.
- 2026-06-03: Expanded Playwright coverage for protected-route redirects, admin-only guard behavior, and login/register `next` redirects.
- 2026-06-03: Updated Playwright landing smoke assertion after replacing setup-oriented landing copy with product-ready copy.
- 2026-06-04: Expanded Playwright coverage for unauthenticated `/monitors` redirect, authenticated `Monitors` navigation, dashboard monitor summary, `/monitors` monitor dialog/domain selection, and mobile page-level overflow checks.
- 2026-06-04: Added backend tests for `/api/v1/monitors/domains`, representative validation, alias URL normalization, URL cleaning, and scheduler cross-domain item-ID dedup. Added frontend E2E coverage for domain selector failure/retry state.
- 2026-06-04: Added `backend/tests/test_telegram_topics.py` for topic settings defaults/patch, forum verification success/failures, idempotent ensure, in-progress duplicate prevention, permission/missing-thread handling, user scoping/auth, topic test sends, thread-aware low-level sends, and topic send failure keeping `FoundItem.notified=False`.
- 2026-06-04: Expanded `backend/tests/test_telegram_topics.py` for automatic notification routing: topics-disabled main-chat behavior, lazy topic creation, active topic reuse, permission failure, deleted-topic recreation, creating-state retry, topic send/rate-limit failures, explicit main-chat fallback, disabled user guard, and missing topic chat guard.
- 2026-06-05: Expanded `backend/tests/test_telegram_topics.py` for monitor-name-only topic names, no domain/id suffixes, whitespace/control cleanup, generic fallback, safe truncation, create-topic name payload, active-topic rename sync, preserved thread IDs, and rename-failure notification continuity.
- 2026-06-05: Added backend tests for Postgres async engine resilience options and auth-session DB disconnect retry/safe-503 behavior.
- 2026-06-05: Added backend tests for login DB disconnect retry/safe `503` and read-only batch Telegram topic status scoping/masking. Added Playwright coverage that `/monitors` with 20 monitors uses one batch topic-status call and no per-monitor topic GET burst.
- 2026-06-05: Expanded auth DB disconnect tests to match the production SQLAlchemy DBAPIError -> asyncpg ConnectionDoesNotExistError shape with `connection_invalidated=False`, fresh-session retry, login commit disconnect retry, repeated-disconnect safe `503`, NullPool engine option, and non-disconnect programming-error passthrough.

## Related Frontend Notes

- [[Components/Frontend Next.js]]
