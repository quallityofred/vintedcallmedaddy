---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/scraper
---

# Scraper

## Purpose

- Talks to Vinted endpoints, parses URLs, applies rate limits, and normalizes item payloads.

## Key Files

- `backend/app/scraper/client.py`
- `backend/app/scraper/parser.py`
- `backend/app/scraper/domains.py`
- `backend/app/scraper/app_scraper_url_parser.py`
- `backend/app/scraper/rate_limiter.py`
- `backend/app/runtime_settings.py`

## Runtime Flow

- `VintedClient` keeps per-domain sessions and warms them up.
- `TokenBucketLimiter` throttles requests and backs off after errors.
- `CloudflareFallback` can switch blocked domains to a worker URL.
- `parse_response()` filters promoted items and builds `VintedItem`.
- Admin/global scraper defaults are stored in `AppSettings` and applied to live runtime settings.
- Cloudflare Worker URL, block threshold, and recovery minutes are admin-configurable and not required deployment env variables.
- Unique Vinted marketplace selection is backed by `backend/app/scraper/domains.py`. User-selectable domains are curated representatives; aliases are kept for URL normalization and probe metadata only.

## Audit Notes

- The scraper remains async-first and conservative.
- Multi-domain dedup in `search_all_domains()` is based on Vinted item ID.
- The settings UI currently suggests runtime-adjustable scraper settings that are not actually wired through persistence or reloads.

## Related Issues

- [[Issues/ISS-006 Scraper settings form does not persist or apply values|ISS-006]]

- 2026-06-02: Dashboard scraper settings are persisted in `AppSettings` and applied to live rate/proxy/concurrency state; active sessions are refreshed after proxy changes.
- 2026-06-03: Admin settings now also cover Cloudflare Worker fallback and adaptive scheduling defaults. Startup loads DB-backed settings before creating the scraper client.
- 2026-06-03: Added versioned JSON APIs for scraper defaults and CF Worker settings. Scraper defaults are admin/global; CF Worker URL/block/recovery/mode are currently per-user. API updates validate values and mask proxy values in responses.
- 2026-06-04: Added representative-domain helpers, alias resolution, and a manual `backend/scripts/probe_vinted_unique_domains.py` script for grouping candidate domains by overlapping item IDs. URL parsing now preserves stable catalog/brand/order params and drops unstable pagination/session/tracking params.
- 2026-06-04: Runtime verification confirmed selected domains are passed to `VintedClient.search_all_domains()`, which dedupes duplicate item IDs inside a single multi-domain scrape. Scheduler now also suppresses stable item IDs previously seen by the same user on another selected domain.
- 2026-06-05: `VintedItem` now carries parsed `brand_id` from direct `brand_id` or nested `brand.id` payload fields. `backend/app/scraper/monitor_filters.py` centralizes monitor filter extraction from runtime params, including compatible array aliases such as `brand_ids[]`/`brand_ids`, catalog, size, status, and color IDs.
- 2026-06-05: Price parsing remains in `_extract_price()` and still stores original `VintedItem.price`/`currency`; approximate USD display is handled only at Telegram formatting time and does not change scraper ingestion or DB storage.
- 2026-06-05: Vinted URL parsing now accepts comma-separated array values such as `brand_ids=1,2` and extracts stable path filters from `/catalog/<id>` and `/brand(s)/<id>` URLs. `parse_response()` also recognizes nested `brand_dto.id` and `brand_details.id` shapes for post-fetch brand filtering.
