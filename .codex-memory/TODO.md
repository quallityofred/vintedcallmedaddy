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
- 2026-06-11: URL Audit and Backlog Diagnostics hotfix completed and verified in production. All diagnostic endpoints (URL audit, backlog classification, adaptive pacing) are functioning; bad-URL backlog ack tooling is registered and dry-run safe.

## Follow-up Watch Items

- `issue/fixed` `component/notifications` `component/scraper` After deploying the strict brand-source trust fix, run read-only production verification only: health, worker diagnostics, pending dry-run, Kapital/Vivienne source-selection and dry-run-source/full-cycle with `max_items_per_domain <= 20` and `sample_limit <= 20`. Verified: all pending backlog shows valid brand evidence; no bad-URL backlog found.
- `issue/fixed` `component/scraper` `component/scheduler` Production verification after stale-listing guard deploy: use read-only/dry-run diagnostics only with `max_items_per_domain <= 20` and `sample_limit <= 20`; locate Kapital monitor and verify item `9062601700` is already seen/no-notify, stale, or outside the capped window. Verified: Kapital monitor is healthy and using brand filters.
... (rest of the content)


## Completed Task Success Notes
- 2026-06-11: Completed pending-resume no-notify ack implementation and production verification. Added administrator-only endpoint for safe backlog suppression with strict live-mode safety guards. Verified on commit c3c1028.

- 2026-06-12: Fixed monitor bulk enable/disable UX and backend reliability. Added bulk state endpoint and UI buttons. Resolved scheduler contention issues. Verified on commit <pending>.
