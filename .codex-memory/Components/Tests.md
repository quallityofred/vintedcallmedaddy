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
- `backend/tests/test_telegram_topic_idempotency.py`
- `frontend/tests/e2e/landing.spec.ts`

## 2026-06-08 Cleanup And V2 Skeleton Coverage

- `test_notification_diagnostic.py` uses the route's actual overridden test DB session and verifies admin/CSRF guards, required monitor scope, dry-run read-only behavior, bounded deterministic apply behavior, idempotency, redaction, and no Telegram/monitor/SeenItem side effects.
- `test_scraper_engine_v2.py` verifies the flag defaults off, legacy source selection remains unchanged, all selected domains are preserved, and the adapter performs one catalog fetch per domain with no item-detail calls.
- `test_notification_pipeline_v2.py` verifies the flag defaults off, the live processor remains unchanged, only successful attempts are acknowledged, failures remain retryable, and redaction omits sensitive delivery data.
- 2026-06-08 delta repair coverage verifies Found-without-Seen history is not requeued, missing Seen memory is repaired, same-domain and cross-domain boundaries remain distinct, all domains are preserved, baseline routes write real Seen rows, and Found-to-Seen repair is read-only by default, bounded, monitor-scoped, idempotent, admin/CSRF protected, and Telegram-free. Full backend result: 395 passed.
- 2026-06-08 filter-drift coverage verifies catalog/gender URL parsing, internal-parameter removal, restrictive stored parameters overriding a broad original query, identical effective filter URLs for every selected domain, and safe mismatch diagnostics. Full backend result: 400 passed.
- 2026-06-11 stale-listing coverage adds `tests/test_filter_fingerprint_baseline.py`: missing-brand timestampless source windows baseline no-notify, subsequent same-fingerprint checks notify only leading items before the seen boundary, old source `listed_at` is seen-only, fresh source `listed_at` can notify, and fingerprint baseline state is domain-aware. Also updated stale route-contract tests for body-based diagnostics requests.
- 2026-06-11 brand-source trust coverage adds `tests/test_brand_source_trust_and_backlog.py`: broad unknown-brand Kapital/Vivienne-style rows are rejected despite `brand_ids[]`, matching brand title and explicit brand ID still pass, suspect backlog dry-runs are read-only/redacted, live suspect ack marks only eligible pending rows no-notify without Telegram, and live route confirmations are enforced.

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
- Backend readiness and frontend login feedback hotfix snapshot on `2026-06-05`:
  - `cd backend && poetry run pytest -q tests/test_auth_api.py tests/test_database_session_factory.py tests/test_startup_readiness.py` -> 24 passed.
  - `cd backend && poetry run pytest -q tests/test_telegram_topics.py` -> 28 passed.
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q tests/test_settings_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q` -> 140 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run build` -> passed with known Node `DEP0205` warning.
  - `cd frontend && npm run test:e2e` -> 13 passed with known Node `DEP0205` warning.
- Railway backend deployment readiness mismatch hotfix snapshot on `2026-06-05`:
  - `cd backend && poetry run pytest -q tests/test_startup_readiness.py` -> 4 passed.
  - `cd backend && poetry run pytest -q tests/test_auth_api.py tests/test_database_session_factory.py tests/test_startup_readiness.py` -> 35 passed.
  - `cd backend && poetry run pytest -q tests/test_telegram_topics.py` -> 28 passed.
  - `cd backend && poetry run pytest -q tests/test_monitors_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q tests/test_settings_api.py` -> 18 passed.
  - `cd backend && poetry run pytest -q` -> 151 passed.
  - `cd backend && poetry run python -c "from app.main import app; print('backend import ok')"` -> passed.
  - `cd backend && poetry run python -m py_compile scripts/db_health_check.py` -> passed.
  - `cd backend && poetry run python scripts/db_health_check.py` -> passed against local test config with safe missing-table error labels.
  - `git diff --check` -> passed with line-ending warnings only.

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
- 2026-06-05: Added `backend/tests/test_startup_readiness.py` for background startup ready/degraded states and expanded frontend E2E login coverage for backend `503` outage feedback.
- 2026-06-05: Added monitor correctness coverage for brand URL params sync, multiple `brand_ids[]` preservation, `brand_id` parsing, post-fetch wrong/missing-brand filtering, first-run brand baseline seeding without `FoundItem`, and notification suppression for skipped items. Full tracked backend suite passed; the raw `pytest -q` run was blocked only by an untracked local reset-operation test artifact.
- 2026-06-05: Added `backend/tests/test_currency_conversion.py` for static USD conversion, comma decimals, unknown/missing currencies, malformed amounts, and zero/negative fallbacks. Telegram runtime tests now assert non-USD messages include approximate USD and USD messages do not duplicate conversion text.
- 2026-06-05: Added `backend/tests/test_scheduler_backpressure.py` for global/per-user monitor check limits, same-monitor overlap prevention, semaphore release on success/failure, and no DB session held during mocked scraper work. Added config env/default tests, `/api/health` backpressure field assertions, and manual Check Now busy-response coverage.
- 2026-06-05: Added regression coverage for recent-items monitor correctness: comma/path Vinted filter parsing, nested brand-id extraction, scheduler URL-derived filter fallback when stored params are stale, refusal of unfiltered Vinted monitors, and explicit `/api/v1/items` recent-items user scoping.
- 2026-06-05: Added `frontend/tests/e2e/async-actions.spec.ts` for exact-key async action behavior: monitor Pause remains pending while another monitor Check runs, topic settings Save/Verify have independent pending states, and Recent Items hide-seller loading is scoped per seller. Frontend lint/build/e2e passed with the known Node `DEP0205` warning and existing mocked-test backend proxy noise.
- 2026-06-05: Added `backend/tests/test_delta_scraping.py` for delta monitor checks: stop at first accepted seen item, wrong/missing-brand items not acting as boundaries, cold-start multi-domain baseline without `FoundItem`, all selected domains checked, per-domain boundaries, `newest_first` runtime params, first-page default, and domain-aware seen lookup. Updated older cross-domain tests to match the selected-domain-independent contract.
- 2026-06-06: Added `backend/tests/test_candidate_detail_guard.py` for candidate-only detail behavior: detail fetch only for unseen candidates before a boundary, stale timestamps create `SeenItem` only, fresh timestamps create `FoundItem`, missing timestamps are safe seen-only, category mismatches skip before `FoundItem`, category matches allow findings, detail caps block unchecked candidates, and cold-start remains silent.
- 2026-06-06: Updated scraper/filter regression tests so missing `brand_id` is skipped for brand monitors. Added detail-fetch HTTP budget coverage in `backend/tests/test_scraper_http_budget.py` and config default/env tests for the detail guard settings.
- 2026-06-06: Verification snapshot for candidate detail guard: focused requested backend tests passed. `poetry run pytest -q --ignore=tests/test_full_reset_create_admin.py --ignore=test_api_keys.py --ignore=test_api_keys_v2.py --ignore=tests/test_telegram_topics.py` -> 192 passed. Raw full run still fails on two untracked local API-key artifacts and two out-of-scope Telegram topic send-failure status assertions.
- 2026-06-07: Added synthetic path-ID hydration fallback coverage for mismatched generic IDs, duplicate paths/URLs, missing required fields, unknown titles, malformed prices, multiple-record ordering, structured JSON compatibility, and normalizer canonicalization. Dry-run tests now assert field-sequence counters, read-only side effects, lazy optional diagnostics, and backend import safety; the endpoint client mock was corrected so tests no longer make an unintended public Vinted request.
- 2026-06-07: Added full-cycle dry-run tests for auth, unselected domains, domain-aware seen boundaries, existing found rows, cold-start seen-only simulation, no monitor mutation, explicit side-effect flags, and a Telegram send tripwire. The known `test_seen_lookup_is_domain_aware` in-memory SQLite fixture can still fail before test logic with `no such table: users`.
- 2026-06-07: Added diagnostics startup-chain and fail-closed coverage: router/full-cycle/backend imports, absence of the private failed-result import, redacted top-level JSON failures, per-domain continuation, JSON serialization for Decimal/datetime/set values, DB mutation tripwires, and Telegram tripwires. Clean `origin/main` independently reproduces the unrelated domain-aware delta expectation failure.
- 2026-06-07: Replaced mock-only baseline evidence with route-level temporary SQLite tests. They prove `dry_run=false` increases SeenItem count from 0 to 2, the second run creates zero, subsequent full-cycle simulation reports already-seen items and zero would-create FoundItems/notifications, while dry-run/default mode, FoundItem count, monitor timestamp, and Telegram remain unchanged.
- 2026-06-07: Added missing-photo FoundItem coverage using the real scheduler write path and local DB fixture. A fresh item with `photo_url=None` persists with `photo_url=""`, remains pending for notification, schedules notification processing, and the Telegram sender uses text-only mode; parser photo-shape and full-cycle readiness diagnostics are also covered.
- 2026-06-07: Added monitor Check Now CSRF tests for missing/valid tokens, ownership scoping, and unauthenticated requests. Added hydration diagnostics tests for missing/supported photos, timestamp presence, raw-payload redaction, and dry-run propagation; Playwright now asserts the CSRF header and actionable 403 feedback.
- 2026-06-07: Added synthetic hydration media discovery coverage for image/time token counts, canonical item-anchor distance buckets, sample caps, no-media cases, and raw URL/chunk redaction. Added pure detail-HTML tests for OG image, JSON-LD image, and published timestamp detection.
- 2026-06-08: Added route and worker coverage for async hydration+SSR merge jobs: full flattened completed status, structured unknown-job/auth responses, eight selected domains, concurrent execution, one fetch per domain, shared HTML identity across parsers, item-ID-only merge, hydration ordering/field authority, SSR-only exclusion, per-domain error isolation, no writes, and photo URL redaction.
- 2026-06-08: Added shared-service and scheduler flag coverage for hydration+SSR photo enrichment: default-off path isolation, same-HTML parser identity, one fetch per selected domain, concurrent all-domain execution, item-ID-only merge, hydration field/order preservation, SSR-only exclusion, hydration fallback after SSR parser failure, no implicit item cap/detail fetch, persisted FoundItem photo, and Telegram photo/text behavior.
- 2026-06-08: Added pending-notification diagnostics and limiter coverage: real SQLite monitor scoping/counts, bounded dry-run with no writes/sends, explicit batch success/failure/fallback behavior, retryable failed rows, redaction, admin/CSRF/limit guards, default-off worker guard, private/group/global rate limits, rate-limited photo/text fallback, and Telegram `retry_after` handling.
- 2026-06-10: Added `backend/tests/test_monitor_cold_start_reset.py` verifying dry-run safety, live reset mutation (SeenItem deletion + last_check_at reset), domain filtering, active-monitor guards, and endpoint confirmation requirements.
- 2026-06-10: Added `backend/tests/test_history_retention_cleanup.py` covering real deletion logic, dry-run safety, TTL/cap application, and preservation of pending items.
- 2026-06-10: Added domain-scoped retention tests verifying the `domains` filter contract and its effect on DB mutation.
- 2026-06-08: Added notification scoping regressions for two monitors, dry-run/live candidate parity, unscoped live rejection, truthful running-job metadata, and monitor-scoped check-triggered processing. Added scheduler-level hydration+SSR coverage for all selected domains, one fetch and shared HTML per domain, effective catalog/brand/gender params, hydration field authority, item-ID photo merge, and SSR-only exclusion. Verification: full backend suite `406 passed`.

## Related Frontend Notes

- [[Components/Frontend Next.js]]

- \	ests/test_history_retention_dry_run.py\: Verifies FoundItem and SeenItem retention planning (TTL, caps, preservation of pending items) and strict dry-run behavior.


- 2026-06-11: Added 	ests/test_ack_pending_before_resume.py covering the safe suppression of valid pending items. Verifies dry-run safety, live mode cutoff/confirmation requirements, valid brand evidence exclusion by default, and correct monitor/user scoping.
