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
- Redeploy the database session initialization fix in [[Issues/ISS-RWY-002 AsyncSessionLocal None after startup|ISS-RWY-002]] and check GET / after Application startup complete.
- Monitor production scraper behavior after runtime settings changes, especially active session refresh and concurrency changes.
- After Railway redeploy, create a low-risk test monitor and verify first check establishes baseline without Telegram spam, then confirm subsequent genuinely new findings send one notification through the saved user Telegram credentials.
- After Railway redeploy, verify Telegram Start/Stop from /settings: Start should make the bot respond, Stop should make /api/health reduce ots_running and the bot should stop responding. Keep backend long polling to one Railway replica/process per bot token.
- Consider adding a migration framework if schema changes grow beyond lightweight startup migrations.
- Keep localized UI text encoding consistent in future template/test edits.
- Before migrating the logs/found-items page, verify the current GET /logs route and pp/templates/logs.html contract. The route currently appears to pass log-manager entries while the template expects found-item data such as items and monitors_map.
- **Infrastructure Observation:** Intermittent ECONNRESET proxy errors were observed between the Railway frontend and backend (/api/v1/monitors and /api/v1/settings/telegram/topics). If it repeats:
    1. Check backend logs at the exact timestamp.
    2. Confirm whether backend restarted/crashed.
    3. Confirm frontend BACKEND_URL.
    4. If backend health is stable but proxy resets continue, prefer Railway private/internal backend URL for frontend BACKEND_URL.
    5. Verify API endpoints through frontend while logged in.
- **Scraper Verification:** After deploying the candidate detail guard, keep Telegram disabled and verify one controlled category+brand monitor. First check should baseline silently; later checks should skip stale items and wrong-category items without `FoundItem` spam. If Vinted detail remains blocked with 403 in production, confirm the fallback counters show detail failures and no unchecked notifications.
- **Telegram Topics Follow-up**: Idempotent creation is fixed with in-memory locks and atomic DB updates. Existing duplicate Telegram UI topics created before this fix may require one-time manual cleanup.

## Frontend Migration

- 2026-06-02: Phase 1 scaffold completed in Projects/vintedbot/frontend.
- 2026-06-03: [[Issues/ISS-FE-005 Frontend backend integration incomplete|ISS-FE-005]] opened after split deployment audit. The Next frontend is still a placeholder shell and lacks real API integration.
- 2026-06-03: Auth JSON endpoints were added in [[Issues/ISS-AUTH-001 Next frontend login API pending|ISS-AUTH-001]].
- 2026-06-03: Auth/register/CSRF API phase completed in [[Issues/ISS-AUTH-002 Next frontend registration API missing|ISS-AUTH-002]].
- 2026-06-03: [[API Contract]] created and [[Issues/ISS-API-001 Full Next frontend API contract missing|ISS-API-001]] opened for remaining Next-ready APIs.
- 2026-06-03: Settings Telegram/CF Worker/scraper API phase completed in [[Issues/ISS-API-002 Settings Telegram CF Worker scraper API missing|ISS-API-002]].
- Next API phase status: monitors CRUD/control, dashboard stats, items/hidden sellers, system status, and admin invite APIs are implemented. Current follow-up is frontend page polish and API client extraction around the implemented contracts.
- 2026-06-03: Backend / behavior decided and implemented in [[Issues/ISS-FE-006 Backend public root is confusing after split|ISS-FE-006]]: production redirects to FRONTEND_URL when configured, otherwise returns minimal JSON; legacy Jinja dashboard stays at /dashboard.
- Consider extracting a small frontend API client now that login/register, dashboard, settings, monitors, items, hidden sellers, system status, and admin invite pages use relative /api/v1/* requests.
- Keep backend legacy Jinja route modules removed. If a missing legacy behavior is discovered, restore it only behind an explicit API-first compatibility decision and tests.
- 2026-06-03: Railway two-service split implemented and documented with backend root ackend and frontend root rontend.
- After Railway service creation, paste backend URL into frontend BACKEND_URL, then paste frontend URL into backend FRONTEND_URL and ALLOWED_ORIGINS.
- Rotate any previously exposed database password, DATABASE_URL, SECRET_KEY, Telegram token, proxy credential, or other credential before deployment.
- Track [[Issues/ISS-FE-001 Next.js PostCSS audit advisory|ISS-FE-001]] and re-run
pm audit --omit=dev after Next.js releases a non-breaking dependency update.
- 2026-06-02: Public/landing design polish started from scratch because no Figma context was available.

## Backend Settings

- **Operational Consistency:** Monitor cards now show live FOUND counts from the database. If a monitor's cached items_found_count becomes stale (e.g. after manual cleanup), the UI will still reflect the truth from the found_items table.

- 2026-06-03: Telegram credentials are per-user write-only/masked in the Jinja settings UI.
- 2026-06-03: Cloudflare Worker and scraper defaults are admin/global DB settings.
- Follow up after deployment: verify an admin can change CF Worker/scraper defaults in production without redeploying.
- After Railway redeploy, verify authenticated /settings CF Worker routing mode saves in production: Direct and Auto should PATCH 200 and persist through GET/refresh; Worker mode should either persist when URL is configured or show the clear Worker URL validation message.
- Next Telegram topics phase: add frontend settings/monitor UI for forum topic configuration and manual verification.
- Automatic topic routing is now backend-enabled behind 	elegram_topics_enabled; frontend UI still needs to make the opt-in and fallback behavior explicit.
- After deploy, verify an existing verbose Telegram topic can be synced/renamed to the monitor-only title without creating a duplicate topic.
- Add a manual repair action for mappings in missing, closed, permission_error, or chat_unreachable status.
- Consider periodic topic verification before notification routing is broadly enabled.

## API-first Cleanup

- 2026-06-03: [[Issues/ISS-FE-007 Protected frontend routes visible while unauthenticated|ISS-FE-007]] fixed with client-side auth guards for /dashboard, /settings, and /admin.
- 2026-06-03: [[Issues/ISS-API-004 Legacy placeholder route modules remained after API-first migration|ISS-API-004]] fixed by removing obsolete legacy router modules and updating route-table/audit tests.
- 2026-06-03: [[Issues/ISS-FE-008 Frontend UI polish incomplete|ISS-FE-008]] fixed with standardized async states, accessible actions, improved dashboard/settings/admin layouts, and product-ready copy.
- 2026-06-04: [[Issues/ISS-FE-009 Dashboard monitor table overflow|ISS-FE-009]] fixed by moving full monitor management to protected /monitors and replacing the dashboard table with a compact monitor summary CTA.
- 2026-06-04: [[Issues/ISS-API-005 Monitor domains endpoint 500|ISS-API-005]] fixed with unique Vinted marketplace representatives, alias URL normalization, representative-only monitor validation, and cross-domain item-ID dedup tests.
- 2026-06-04: [[Issues/ISS-TG-001 Telegram test returns vague 502|ISS-TG-001]] fixed with safe Telegram test error codes/details, and [[Issues/ISS-FE-010 Checkbox and settings polish follow-up|ISS-FE-010]] fixed with shared checkbox/domain/settings UI polish.
- Follow up: after Railway redeploy, verify backend /, /health, /api/health, frontend login/register redirects, and unauthenticated protected-route redirects from the public frontend domain.

## Frontend Polish Follow-up

- After Railway redeploy, verify /dashboard, /settings, and /admin at mobile width and desktop width.
- After Railway redeploy, verify /dashboard no longer shows the full monitor table and /monitors supports create/edit/pause/resume/check-now/delete/bulk-delete with real user data.
- After Railway redeploy, open /monitors, create a monitor, and confirm GET /api/v1/monitors/domains returns unique representatives with no 500 and no Target Domains (0 / 0) failure state.
- After Railway redeploy, verify the new /monitors responsive card/list UI with real monitor data on desktop and mobile.
- After Railway redeploy, verify /monitors info-card spacing and the compact domain selector in the create/edit dialog.
- After Railway redeploy, verify /monitors edit close behavior with real monitors: change draft fields, close without submit, reopen, and confirm persisted name/URL/interval/domains remain unchanged.
- After Railway redeploy, verify monitor cards show selected target domains and long domain lists truncate without horizontal overflow.
- After Railway redeploy, verify /settings shows classified Telegram test errors for missing/invalid credentials without exposing token or chat values.
- Continue migrating remaining settings/topic/dashboard mutations to the typed CSRF-aware frontend API client; monitor mutations now use it.
- After explicit deployment approval, inspect monitor 22 full-cycle `item_field_diagnostics` to determine whether catalog hydration actually contains supported photo or timestamp fields. Do not infer listing freshness when timestamp counters remain zero.
- After explicit deployment approval, inspect monitor 22 `media_token_diagnostics` per domain. Only add catalog photo extraction when a marker/value can be structurally tied to the same `/items/<id>` record; otherwise evaluate optional detail-page enrichment behind a feature flag.
- After explicit deployment approval, rerun monitor 22 dry-run for `vinted.pl`. Success requires normalized hydration records near the unique item-path count, canonical IDs matching `/items/<id>`, no duplicate URLs with different IDs, `after_filters > 0`, and all side-effect flags false.
- After explicit deployment approval, call `POST /api/v1/diagnostics/monitors/22/dry-run-full-cycle` before enabling a real scheduler check; review per-domain seen/found/new counts and require all side-effect flags to remain false.
- Deployment gate for full-cycle diagnostics: verify `/api/health`, then run monitor 22 with `max_domains=8`, `max_items_per_domain=96`, and `sample_limit=10`; treat `safe_error=full_cycle_dry_run_failed` or any domain error as a blocker for a real monitor check.
- Deployment gate for SeenItem baseline: wait for explicit commit/push approval, verify `/api/health`, run `baseline-seen-no-notify` with `dry_run=true` for one selected domain, then run once with `dry_run=false` and confirm a second run creates zero while full-cycle reports the same items as already seen.
- Deployment gate for missing-photo FoundItem fix: wait for explicit approval, verify `/api/health`, inspect full-cycle `found_item_insert_*` counters for monitor 22, then run one controlled real check and confirm missing-photo items persist and notify through text-only Telegram without a scheduler IntegrityError.
- Deployment gate for the async hydration+SSR merge diagnostic: wait for explicit approval, verify `/api/health`, start the eight-domain job, poll by returned job ID, and require `domains_processed_total=8`, `html_fetch_count_total=8`, no domain errors, and complete top-level summary/count/sample fields before planning scheduler integration.
- Hydration+SSR scheduler release: deploy the integration code with `MONITOR_SSR_PHOTO_MERGE_ENABLED=false`, validate health and the eight-domain async job, then enable the flag only in a separately approved release. Roll back by restoring the flag to `false`; do not add per-item detail fetching or notification caps.
- Pending notification controlled release: keep `PENDING_NOTIFICATIONS_WORKER_ENABLED=false`; after an approved deploy call `POST /api/v1/diagnostics/notifications/process-pending?monitor_id=22&limit=10&dry_run=true`, verify scoped counts/redaction, then only with separate send approval call the same endpoint with `dry_run=false`. Confirm Telegram delivery and `notified=true` before draining another bounded batch. The endpoint is admin and API-CSRF protected.
- Backlog acknowledgement release gate: verify `ack-pending-no-notify` with `dry_run=true` before applying a bounded monitor-scoped cleanup. Apply mode intentionally sends no Telegram and is idempotent; it must never be used without an explicit monitor ID.
- Scraper engine v2 remains `SCRAPER_ENGINE_V2_ENABLED=false`. Before any future switch, integrate through an explicit scheduler release with all selected domains preserved, one catalog fetch per domain, no per-item detail fetch, and hydration as the item-data authority.
- Notification pipeline v2 remains `NOTIFICATION_PIPELINE_V2_ENABLED=false`. Before any future switch, define durable DB-backed job state and restart recovery without weakening existing retry, topic routing, or rate-limiter behavior.
- Monitor 22 repair gate after deployment: first run `backfill-seen-from-found-items` with `dry_run=true`; review `missing_total` and bounded samples. Only after explicit approval apply bounded batches with `dry_run=false` until `missing_total=0`, then run baseline/full-cycle read-only diagnostics before any controlled check-now. This repair sends no Telegram and does not alter FoundItem notification state.
- Monitor 22 filter gate after deployment: inspect `GET /api/v1/diagnostics/monitors/22/source-selection` and require effective catalog/brand/gender keys to match the intended configuration. If `request_params_match_original_url=false`, the scheduler still uses effective stored filters, but the monitor URL should be repaired separately for operator clarity. Run bounded full-cycle dry-run and require a seen boundary or explicitly baseline before another controlled check-now.
- Notification scoping release gate: after deployment verify `/api/health`, start a monitor-scoped dry-run notification job for monitor 22, and confirm `requested_monitor_id=22`, `selected_monitor_ids=[22]`, and no Telegram side effects. A later explicitly approved live job must remain monitor-scoped; unscoped live jobs are rejected. Keep `PENDING_NOTIFICATIONS_WORKER_ENABLED=false`.

## Graph Metadata Validation

- 2026-06-02: No remaining issue graph metadata problems after normalization scan.
- **Monitor Repair Release:** After deploy, use POST /api/v1/diagnostics/monitors/22/repair-stale-status?dry_run=true to verify monitor 22's stale state, then run with dry_run=false to clear it. Verify GET /api/v1/monitors/22/debug reports effective status ailed (not unning) and is_stale_running=false. Confirm check-now is available and not blocked by the previous stale state.

## Telegram Output Enhancement

- **Beautiful Telegram Output TODO:** After the production core rollout is verified, enhance the Telegram notification formatting for better visual impact and usability:
    - Large item photo at top.
    - Clear label "?? New Vinted item found".
    - Monitor name.
    - Item title.
    - Price plus approximate USD (already exists, keep clean).
    - Brand.
    - Size.
    - Condition.
    - Seller name.
    - Source domain.
    - Inline buttons: "Open on Vinted" and "Hide seller".
    - Text fallback if no photo_url.
    - No raw long URLs if buttons are available.
    - Use Telegram HTML/Markdown safe formatting.


- [x] Implement live history retention cleanup with strict confirmation (Phase C)
- [ ] Monitor production history retention cleanup behavior and counts.
- [ ] Monitor production monitor cold-start reset behavior and next-run baseline success.

