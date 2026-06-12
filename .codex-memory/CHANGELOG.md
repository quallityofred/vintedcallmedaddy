---
type: changelog
project: vintedbot
tags:
  - vintedbot
  - core/changelog
---

# Changelog

- 2026-06-12: Fixed monitor newness gate with high-watermark. Resolved persistent issue where old items were sent as new after reset. Added 'max_vinted_item_id' watermark to 'MonitorFilterBaseline' to suppress items with IDs below the baseline watermark that lack trusted timestamps. Updated 'check_monitor' to strictly enforce this newness gate. Verified with new regression test 'tests/test_newness_gate_watermark.py'.

- 2026-06-12: Fixed cold-start baseline protection. Resolved issue where old items were sent as new after monitor reset. Updated 'run_monitor_cold_start_reset' to clear 'MonitorFilterBaseline' table; fixed 'check_monitor' to skip baseline updates for failed domains; strengthened fingerprint baseline guard to include all items without timestamps during fingerprint changes. Verified with new regression test 'tests/test_reset_baseline_protection.py'.

- 2026-06-12: Added POST /api/v1/monitors/bulk-state and UI buttons for 'Disable all enabled' / 'Enable all paused'. Refactored MonitorScheduler to support bulk sync, avoiding lock contention and timeouts (500/ECONNRESET) caused by chained individual requests. Verified with backend regression and new targeted tests.

- 2026-06-11: Added POST /api/v1/maintenance/pending-notifications/ack-pending-before-resume for intentional backlog suppression before Telegram resume; implemented strict cutoff safety and multi-string confirmations for live mode. Enforced require_api_admin globally across all maintenance endpoints to ensure administrator-only access for sensitive operations. Added tests/test_ack_pending_before_resume.py for full logic coverage.

- 2026-06-11: Fixed URL audit and backlog diagnostics hotfix. Implemented full URL normalization contract for Vinted 'newest_first' variants; added scheduler broad-risk safety to prevent mass notifications from unfiltered monitors; added GET /api/v1/diagnostics/monitors/url-normalization-audit and GET /api/v1/diagnostics/pending-notifications/backlog-classification for read-only backlog analysis; registered POST /api/v1/maintenance/pending-notifications/ack-bad-url-backlog for safe cleanup. Fixed router NameError and URL audit Internal Server Error regressions.
- 2026-06-11: Fixed `issue/fixed` brand-only source trust after `de2c833`. Production diagnostics showed Kapital/Vivienne monitors had effective `brand_ids[]`, but broad unknown-brand source rows still passed filters because request params alone were trusted. Brand-filtered items now require explicit matching `brand_id` or positive matching brand title/name evidence; `brand_title="unknown"` no longer passes as Kapital/Vivienne. Added strict regression coverage and a dry-run-first maintenance endpoint for suspect brand-filter pending backlog quarantine.
- 2026-06-11: Fixed `issue/fixed` stale-listing notification flood after brand-filter relaxation. Brand-filtered items with missing item-level `brand_id` and no source timestamp now seed a monitor/domain filter-fingerprint baseline as `SeenItem` without `FoundItem`; source `listed_at` older than the previous check minus grace is also marked seen-only. Added `monitor_filter_baselines` state and regression coverage for Kapital-style item `9062601700` showing Vinted UI age `1 Woche`; diagnostics remain capped at 20/20 for production dry-runs.
- 2026-06-02: Initialized `Codex Memory/vintedbot` and verified read access to the repository and compatibility wrapper files.
- 2026-06-02: Verified that `Projects/vintedbot` is a junction to `C:\Users\egory\vintedbot`; both paths resolve to the same git working tree.
- 2026-06-02: Built a graph-friendly memory structure with component notes, audit notes, issue records, and linked decision notes after auditing `Projects/vintedbot`.
- 2026-06-02: Fixed all 10 audit issues: settings context/persistence, admin invite routes, user-scoped seller hiding, log isolation, duplicate router/scheduler modules, atomic invite use, CSRF/secure cookies, notification worker failure containment, and `.env.example` production security docs. Verified with `poetry run pytest -q` -> 26 passed.
- 2026-06-02: Pushed audit fixes to GitHub at commit `cd3b7f2c93f9f7fa65b0b33e915754620ef1ca82`.
- 2026-06-02: Normalized issue graph metadata tags so fixed issues use `issue/fixed`, component tags use consistent lowercase graph groups, and `PROJECT_GRAPH.md` includes recommended Obsidian graph groups.
- 2026-06-02: Added [[Issues/ISS-RWY-001 Railway PostgreSQL startup failure|ISS-RWY-001]] documenting that the Railway startup error is environment-related: PostgreSQL service down/unavailable, not caused by recent source-code fixes.
