---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/scheduler
---

# Scheduler

## Purpose

- Periodically checks monitors, writes deduplicated items, and triggers Telegram notifications.

## Key Files

- `app/scheduler/tasks.py`
- `app/scheduler/app_scheduler_tasks.py`
- `app/models.py`

## Runtime Flow

- `app.app_main` creates `MonitorScheduler`.
- Scheduler loads active monitors and registers APScheduler interval jobs.
- `check_monitor()` performs scraping, deduplication, hidden-seller filtering, and notification enqueueing.
- `process_pending_notifications()` sends unsent items.
- Cold-start checks write only `SeenItem` baseline rows; they do not create user-visible `FoundItem` rows or Telegram notifications.
- Post-baseline checks treat stable Vinted item ID as the per-user seen identity across selected domains. Repeated item IDs do not create duplicate found items or notifications.
- `FoundItem(notified=False)` represents a genuinely new post-baseline finding ready for Telegram delivery.

## Audit Notes

- DB-level deduplication is preserved for both `SeenItem` and `FoundItem`.
- Existing schema uniqueness still includes domain, but runtime checks `SeenItem(user_id, vinted_item_id)` before inserting so cross-domain repeats are suppressed.
- Hidden-seller filtering is only as correct as the callback that writes `HiddenSeller`.
- There is a duplicate scheduler implementation file that can drift from the canonical one.

## Related Issues

- [[Issues/ISS-003 Hide seller flow is broken and not user-scoped|ISS-003]]
- [[Issues/ISS-005 Duplicate implementation modules shadow runtime behavior|ISS-005]]
- [[Issues/ISS-009 Notification worker can crash on invalid Telegram tokens|ISS-009]]

- 2026-06-02: Notification worker now guards bot acquisition and chat-id parsing; `app.scheduler.tasks` is canonical and `app_scheduler_tasks.py` re-exports it.
- 2026-06-04: Runtime verification tightened cold-start and cross-domain dedup behavior. Telegram send failures no longer mark items notified; pending items remain retryable.
- 2026-06-05: Scheduler checks now apply a post-fetch monitor-filter guard before writing `SeenItem` or `FoundItem`. For brand-filtered monitors, items with non-matching `brand_id` or missing `brand_id` are skipped to prevent unrelated-brand notifications. Check logs include safe raw/accepted/skipped counts and cold-start state.
- 2026-06-05: Monitor checks now use process-local backpressure: same-monitor overlap prevention, global concurrency default `2` (`MONITOR_CHECK_GLOBAL_CONCURRENCY`), per-user concurrency default `1` (`MONITOR_CHECK_PER_USER_CONCURRENCY`), and acquire timeout default `2s` (`MONITOR_CHECK_ACQUIRE_TIMEOUT_SECONDS`). The check flow loads a primitive context from DB, closes the session, runs scraper network work, then opens a new short DB session for writes.
- 2026-06-05: Check context loading now refuses Vinted monitors with no restrictive runtime filters before scraper execution. If stored `params_json` is non-restrictive but `original_url` still contains restrictive filters, the scheduler uses URL-derived params for that check and logs a safe warning instead of querying the full marketplace.
- 2026-06-05: Monitor checks now use delta scraping per selected domain. The scheduler forces runtime params to `order=newest_first`, removes stale `page`, fetches page 1 by default (`MONITOR_CHECK_MAX_PAGES_PER_DOMAIN=1`), applies monitor filters before seen-boundary checks, stops each domain at the first accepted seen item, and keeps cold-start baseline silent by writing `SeenItem` only. Wrong-brand and missing-brand items are skipped and do not act as a boundary.
- 2026-06-06: Non-cold monitor checks now run a candidate detail guard after summary/delta selection and before DB writes. Detail is fetched only for candidate items that would otherwise become `FoundItem`, capped by `MONITOR_CANDIDATE_DETAIL_MAX_PER_CHECK` (default `10`) and using the scraper HTTP budget. Freshness guard compares detail `listed_at` against previous `last_check_at` minus `MONITOR_FRESHNESS_GRACE_SECONDS` (default `600`); stale/missing timestamp candidates are marked seen-only so they do not repeat. Category guard uses detail catalog/category IDs for monitors with catalog filters; mismatches/missing detail category are skipped without notification.
- 2026-06-06: Category-filtered monitors no longer trust summary-only seen boundaries because live catalog search can ignore catalog params. They avoid false stop-at-seen behavior from wrong-category summary rows and rely on bounded detail/freshness checks for candidate creation. Brand monitors now skip missing `brand_id` summary items instead of allowing them through.
- 2026-06-07: Hydration dry-run diagnostics now report field-sequence path markers, records before/after validation and deduplication, safe rejection counters, and the actual parser strategy. The dry-run remains read-only and its optional literal diagnostics stay behind a startup-safe lazy wrapper.
- 2026-06-07: Full-cycle diagnostics simulate scheduler delta decisions without invoking `check_monitor`: source fetching/filtering is followed by bulk read-only domain-aware seen and monitor-scoped found queries. Cold-start would seed seen rows only; normal checks stop at the first seen boundary and report would-create/would-enqueue counts without writes or Telegram calls.
- 2026-06-07: Full-cycle diagnostics fail closed without private scheduler imports. Global failures return router-local redacted JSON, per-domain read failures are recorded by exception class while other domains continue, and session mutation plus notification paths remain outside the helper.
- 2026-06-07: `perform_monitor_baseline_seen` is the single owner of the diagnostics baseline write. It reuses the read-only source/filter path, looks up SeenItem by `(monitor_id, vinted_item_id, domain)`, and only when `dry_run=false` performs a conflict-safe bulk insert plus commit; it never invokes the real scheduler, FoundItem, monitor update, notification, or Telegram paths.
- 2026-06-07: FoundItem creation now uses `build_found_item_values` before bulk insert. All non-null model values are normalized, `photo_url=None` becomes `""`, and notification processing consequently uses the existing text-only send path when no image is available; valid new items are not suppressed or capped.
- 2026-06-07: Hydration source/full-cycle dry-run now carries safe item-field diagnostics: aggregate supported photo/timestamp key presence, normalized present/missing counts, and optional ISO timestamp/source sample metadata. These fields are diagnostic only and do not invent freshness or change scheduler decisions.
- 2026-06-07: Hydration dry-run now also carries raw React Flight media-marker diagnostics: per-marker counts, chunks containing item/media/time markers, and bounded item-anchor distance buckets. The scanner never returns marker values and does not alter scheduler photo or freshness decisions.
- 2026-06-08: The hydration+SSR photo merge diagnostic uses a dedicated in-memory job registry keyed by job ID. Its background worker resolves selected domains, runs bounded concurrent one-fetch-per-domain tasks, passes the same HTML to both parsers, keeps hydration fields authoritative, and contributes only SSR photo host/presence diagnostics with no scheduler or database writes.
- 2026-06-08: Scheduler photo enrichment is prepared behind default-off `MONITOR_SSR_PHOTO_MERGE_ENABLED`. Only monitors already eligible for the hydration catalog source can enter the branch. Each selected domain is fetched once, the same HTML feeds hydration and SSR parsers, merge is by item ID, hydration remains authoritative, SSR-only items are excluded, and SSR parser failure degrades to hydration-only without changing dedupe, FoundItem, or Telegram semantics.
- 2026-06-08: Pending notification processing now has a shared structured audit/delivery contract. Selection is monitor-scoped and bounded, dry-run performs reads only, live processing uses short sessions and marks each row notified only after successful delivery. A process-local lock prevents overlapping processors. `PENDING_NOTIFICATIONS_WORKER_ENABLED` remains false by default; the manual admin endpoint remains available with API CSRF while the periodic job is disabled.
