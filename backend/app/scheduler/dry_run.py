from __future__ import annotations
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FoundItem, Monitor, SeenItem
from app.scraper.client import VintedClient, DomainSearchResult
from app.scraper.parser import VintedItem
from app.scraper.source_selector import should_use_hydration_source
from app.scheduler.found_item_values import inspect_found_item_insert_readiness
from app.scraper.hydration_parser import (
    hydration_record_to_vinted_item,
    analyze_hydration_html,
    get_candidate_samples,
    collect_redacted_candidate_structures,
    extract_next_f_chunks,
    extract_hydration_items,
)

# ... (rest of imports) ...

def _safe_collect_literal_marker_diagnostics(html: str, max_samples: int = 3) -> dict:
    """Startup-safe wrapper for literal marker diagnostics."""
    try:
        from app.scraper.hydration_parser import collect_literal_marker_diagnostics
    except ImportError:
        return {
            "literal_marker_samples": {"items_path": [], "brand_title": [], "price": []},
            "literal_marker_chunk_summary": {"top_chunks_with_all_core_markers": []},
            "safe_error": "literal_marker_diagnostics_unavailable",
        }
    except Exception:
        return {
            "literal_marker_samples": {"items_path": [], "brand_title": [], "price": []},
            "literal_marker_chunk_summary": {"top_chunks_with_all_core_markers": []},
            "safe_error": "literal_marker_diagnostics_failed",
        }

    try:
        result = collect_literal_marker_diagnostics(html)
        if not isinstance(result, dict):
            return {
                "literal_marker_samples": {"items_path": [], "brand_title": [], "price": []},
                "literal_marker_chunk_summary": {"top_chunks_with_all_core_markers": []},
                "safe_error": "literal_marker_diagnostics_invalid_result",
            }
        return result
    except Exception:
        return {
            "literal_marker_samples": {"items_path": [], "brand_title": [], "price": []},
            "literal_marker_chunk_summary": {"top_chunks_with_all_core_markers": []},
            "safe_error": "literal_marker_diagnostics_failed",
        }
from app.scraper.monitor_filters import extract_monitor_filters, item_matches_monitor_filters

logger = logging.getLogger(__name__)

@dataclass
class DryRunItem:
    id: str
    title: str
    brand_title: str
    price: float
    currency: str
    url: str
    domain: str
    source: str
    has_photo: bool = False

@dataclass
class FetchDiagnostics:
    requested_domain: str
    requested_url_host: str
    requested_url_path: str
    requested_url_param_keys: List[str]
    html_fetched: bool
    html_bytes: int
    html_contains_next_f: bool
    next_f_chunks: int
    normalized_hydration_records: int
    safe_page_markers: Dict[str, bool]
    chunks_with_item_text_markers: int
    chunks_with_brand_title_marker: int
    chunks_with_price_marker: int
    chunks_with_items_path_marker: int
    candidate_item_objects_count: int
    parser_strategy_used: str
    field_sequence_path_markers: int = 0
    field_sequence_records_before_validation: int = 0
    field_sequence_records_after_validation: int = 0
    field_sequence_records_after_dedup: int = 0
    field_sequence_rejections: Dict[str, int] = field(default_factory=dict)
    candidate_samples: List[Dict[str, Any]] = field(default_factory=list)
    literal_marker_samples: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    literal_marker_chunk_summary: Dict[str, Any] = field(default_factory=dict)
    safe_error: Optional[str] = None

@dataclass
class MonitorDryRunResult:
    monitor_id: int
    selected_source: str
    reason: str
    selected_domains: List[str]
    dry_run_domains: List[str]
    counts_by_domain: Dict[str, int]
    samples_by_domain: Dict[str, List[DryRunItem]]
    errors_by_domain: Dict[str, str]
    pipeline_counts_by_domain: Dict[str, Dict[str, int]] = field(default_factory=dict)
    fetch_diagnostics_by_domain: Dict[str, FetchDiagnostics] = field(default_factory=dict)
    side_effects: Dict[str, bool] = field(default_factory=lambda: {
        "runs_scheduler_check": False,
        "writes_seen_items": False,
        "writes_found_items": False,
        "updates_monitor": False,
        "enqueues_notifications": False,
        "sends_telegram": False,
        "calls_vinted": True
    })


@dataclass
class FullCycleDomainCounts:
    raw_fetched: int
    converted: int
    after_filters: int
    already_seen: int = 0
    already_found: int = 0
    would_create_seen_items: int = 0
    would_create_found_items: int = 0
    would_enqueue_notifications: int = 0
    would_send_telegram: int = 0
    would_be_new_items: int = 0
    seen_boundary_hit: bool = False
    stopped_at_seen_item_id: Optional[str] = None
    found_item_insert_ready: int = 0
    found_item_insert_missing_photo_url: int = 0
    found_item_insert_missing_title: int = 0
    found_item_insert_missing_url: int = 0
    found_item_insert_missing_price: int = 0
    found_item_insert_missing_currency: int = 0
    would_fail_found_item_insert_before_fix: int = 0


@dataclass
class FullCycleSimulationSamples:
    sample_already_seen: List[DryRunItem] = field(default_factory=list)
    sample_already_found: List[DryRunItem] = field(default_factory=list)
    sample_would_be_new: List[DryRunItem] = field(default_factory=list)


@dataclass
class MonitorFullCycleDryRunResult:
    monitor_id: int
    selected_source: str
    reason: str
    selected_domains: List[str]
    dry_run_domains: List[str]
    summary: Dict[str, int]
    counts_by_domain: Dict[str, FullCycleDomainCounts]
    pipeline_counts_by_domain: Dict[str, Dict[str, Any]]
    seen_found_simulation_by_domain: Dict[str, FullCycleSimulationSamples]
    samples_by_domain: Dict[str, List[DryRunItem]]
    errors_by_domain: Dict[str, str]
    side_effects: Dict[str, bool] = field(default_factory=lambda: {
        "runs_scheduler_check": False,
        "writes_seen_items": False,
        "writes_found_items": False,
        "updates_monitor": False,
        "enqueues_notifications": False,
        "sends_telegram": False,
        "calls_vinted": True,
        "reads_database": True,
    })

async def perform_monitor_dry_run(
    monitor: Monitor,
    client: VintedClient,
    max_domains: int = 1,
    max_items_per_domain: int = 10,
    target_domain: Optional[str] = None
) -> MonitorDryRunResult:
    """
    Perform a safe dry-run of a monitor check.
    Fetches items from Vinted but does not mutate any local state.
    """
    import json
    try:
        params = json.loads(monitor.params_json)
        selected_domains = json.loads(monitor.domains_json)
    except Exception:
        params = {}
        selected_domains = ["vinted.pl"]

    source = "hydration" if should_use_hydration_source(params) else "api"
    
    # Determine which domains to test
    if target_domain:
        if target_domain not in selected_domains:
            raise ValueError(f"Domain {target_domain} is not selected by this monitor")
        dry_run_domains = [target_domain]
    else:
        dry_run_domains = selected_domains[:max_domains]

    counts_by_domain = {}
    samples_by_domain = {}
    errors_by_domain = {}
    pipeline_counts_by_domain = {}
    fetch_diagnostics_by_domain = {}

    filters = extract_monitor_filters(params, monitor_name=monitor.name)

    for domain in dry_run_domains:
        try:
            items: List[VintedItem] = []
            raw_count = 0
            
            # Setup for hydration diagnostics
            domain_url = monitor.original_url.replace("vinted.pl", domain)
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(domain_url)
            
            if source == "hydration":
                html = await client.fetch_catalog_html(domain_url, domain=domain)
                
                chunks = extract_next_f_chunks(html)
                parser_diagnostics: Dict[str, Any] = {}
                hydration_items = extract_hydration_items(
                    html,
                    domain=domain,
                    diagnostics=parser_diagnostics,
                )
                analysis = analyze_hydration_html(html)
                candidate_samples = get_candidate_samples(html, max_samples=5)
                if not candidate_samples:
                    candidate_samples = collect_redacted_candidate_structures(html, max_samples=5)
                
                literal_diag = _safe_collect_literal_marker_diagnostics(html, max_samples=3)

                raw_count = len(hydration_items)
                items = [hydration_record_to_vinted_item(r, domain) for r in hydration_items]
                
                # Fetch diagnostics
                fetch_diagnostics_by_domain[domain] = FetchDiagnostics(
                    requested_domain=domain,
                    requested_url_host=parsed_url.hostname or "",
                    requested_url_path=parsed_url.path,
                    requested_url_param_keys=list(parse_qs(parsed_url.query).keys()),
                    html_fetched=bool(html),
                    html_bytes=len(html),
                    html_contains_next_f=analysis["html_contains_next_f"],
                    next_f_chunks=analysis["next_f_chunks"],
                    normalized_hydration_records=raw_count,
                    safe_page_markers={
                        "has_catalog_marker": "catalog" in html.lower(),
                        "has_login_marker": "login" in html.lower() or "signin" in html.lower(),
                        "has_block_marker": "access denied" in html.lower() or "blocked" in html.lower(),
                        "has_consent_marker": "consent" in html.lower(),
                    },
                    chunks_with_item_text_markers=analysis["chunks_with_item_text_markers"],
                    chunks_with_brand_title_marker=analysis["chunks_with_brand_title_marker"],
                    chunks_with_price_marker=analysis["chunks_with_price_marker"],
                    chunks_with_items_path_marker=analysis["chunks_with_items_path_marker"],
                    candidate_item_objects_count=analysis["candidate_item_objects_count"],
                    parser_strategy_used=parser_diagnostics.get(
                        "parser_strategy_used",
                        "structured_json",
                    ),
                    field_sequence_path_markers=parser_diagnostics.get(
                        "field_sequence_path_markers",
                        0,
                    ),
                    field_sequence_records_before_validation=parser_diagnostics.get(
                        "field_sequence_records_before_validation",
                        0,
                    ),
                    field_sequence_records_after_validation=parser_diagnostics.get(
                        "field_sequence_records_after_validation",
                        0,
                    ),
                    field_sequence_records_after_dedup=parser_diagnostics.get(
                        "field_sequence_records_after_dedup",
                        0,
                    ),
                    field_sequence_rejections=parser_diagnostics.get(
                        "field_sequence_rejections",
                        {},
                    ),
                    candidate_samples=candidate_samples,
                    literal_marker_samples=literal_diag["literal_marker_samples"],
                    literal_marker_chunk_summary=literal_diag["literal_marker_chunk_summary"],
                    safe_error=literal_diag.get("safe_error"),
                )
            else:
                # Minimal API dry-run: use search_all_domains but for one domain
                # search_all_domains is already deduplicated and filtered by brand
                items = await client.search_all_domains(params, [domain])
                raw_count = len(items)

            # Apply filters
            accepted_items = []
            filter_rejections = {}
            for item in items:
                matches, skip_reason = item_matches_monitor_filters(item, filters)
                if matches:
                    accepted_items.append(item)
                else:
                    filter_rejections[skip_reason] = filter_rejections.get(skip_reason, 0) + 1
            
            counts_by_domain[domain] = len(accepted_items)
            pipeline_counts_by_domain[domain] = {
                "raw_fetched": raw_count,
                "converted": len(items),
                "after_filters": len(accepted_items),
                "rejections": filter_rejections
            }
            if source == "hydration":
                pipeline_counts_by_domain[domain].update({
                    "field_sequence_path_markers": parser_diagnostics.get(
                        "field_sequence_path_markers",
                        0,
                    ),
                    "field_sequence_records_before_validation": parser_diagnostics.get(
                        "field_sequence_records_before_validation",
                        0,
                    ),
                    "field_sequence_records_after_validation": parser_diagnostics.get(
                        "field_sequence_records_after_validation",
                        0,
                    ),
                    "field_sequence_records_after_dedup": parser_diagnostics.get(
                        "field_sequence_records_after_dedup",
                        0,
                    ),
                })
            
            samples = []
            for item in accepted_items[:max_items_per_domain]:
                samples.append(DryRunItem(
                    id=str(item.id),
                    title=item.title or "",
                    brand_title=item.brand or "unknown",
                    price=float(item.price or 0.0),
                    currency=item.currency or "",
                    url=item.item_url or "",
                    domain=domain,
                    source=source,
                    has_photo=bool(item.photo_url),
                ))
            samples_by_domain[domain] = samples

        except Exception as e:
            logger.exception("Dry-run failed for domain=%s", domain)
            safe_error = type(e).__name__
            errors_by_domain[domain] = safe_error
            if domain not in fetch_diagnostics_by_domain:
                 fetch_diagnostics_by_domain[domain] = FetchDiagnostics(
                    requested_domain=domain,
                    requested_url_host="",
                    requested_url_path="",
                    requested_url_param_keys=[],
                    html_fetched=False,
                    html_bytes=0,
                    html_contains_next_f=False,
                    next_f_chunks=0,
                    normalized_hydration_records=0,
                    safe_page_markers={},
                    chunks_with_item_text_markers=0,
                    chunks_with_brand_title_marker=0,
                    chunks_with_price_marker=0,
                    chunks_with_items_path_marker=0,
                    candidate_item_objects_count=0,
                    parser_strategy_used="none",
                    safe_error=safe_error
                )

    reason = "catalog_filter_detected" if source == "hydration" else "brand_only_api_path"
    if source == "api" and should_use_hydration_source(params) == False: # Double check logic
         if any(key in params for key in ["catalog[]", "catalog_ids[]", "catalog_id", "catalog"]) == False:
              reason = "no_catalog_filter"

    return MonitorDryRunResult(
        monitor_id=monitor.id,
        selected_source=source,
        reason=reason,
        selected_domains=selected_domains,
        dry_run_domains=dry_run_domains,
        counts_by_domain=counts_by_domain,
        samples_by_domain=samples_by_domain,
        errors_by_domain=errors_by_domain,
        pipeline_counts_by_domain=pipeline_counts_by_domain,
        fetch_diagnostics_by_domain=fetch_diagnostics_by_domain
    )


async def _load_existing_item_ids(
    db: AsyncSession,
    *,
    monitor_id: int,
    domain: str,
    item_ids: set[int],
) -> tuple[set[int], set[int]]:
    """Read existing delta state without attaching or mutating ORM objects."""
    if not item_ids:
        return set(), set()

    seen_result = await db.execute(
        select(SeenItem.vinted_item_id).where(
            SeenItem.monitor_id == monitor_id,
            SeenItem.domain == domain,
            SeenItem.vinted_item_id.in_(item_ids),
        )
    )
    found_result = await db.execute(
        select(FoundItem.vinted_item_id).where(
            FoundItem.monitor_id == monitor_id,
            FoundItem.vinted_item_id.in_(item_ids),
        )
    )
    return (
        {int(row[0]) for row in seen_result.fetchall()},
        {int(row[0]) for row in found_result.fetchall()},
    )


async def perform_monitor_full_cycle_dry_run(
    monitor: Monitor,
    client: VintedClient,
    db: AsyncSession,
    *,
    max_domains: int = 8,
    max_items_per_domain: int = 96,
    target_domain: Optional[str] = None,
    include_samples: bool = True,
    sample_limit: int = 10,
    telegram_enabled: bool = False,
) -> MonitorFullCycleDryRunResult:
    """Simulate scheduler delta decisions using fetches and read-only DB queries."""
    source_result = await perform_monitor_dry_run(
        monitor,
        client,
        max_domains=max_domains,
        max_items_per_domain=max_items_per_domain,
        target_domain=target_domain,
    )

    counts_by_domain: Dict[str, FullCycleDomainCounts] = {}
    simulations: Dict[str, FullCycleSimulationSamples] = {}
    samples_by_domain: Dict[str, List[DryRunItem]] = {}
    errors_by_domain = dict(source_result.errors_by_domain)
    found_ids_across_domains: set[int] = set()

    summary = {
        "domains_checked": len(source_result.dry_run_domains),
        "raw_fetched_total": 0,
        "after_filters_total": 0,
        "already_seen_total": 0,
        "already_found_total": 0,
        "would_create_seen_items_total": 0,
        "would_create_found_items_total": 0,
        "would_enqueue_notifications_total": 0,
        "would_send_telegram_total": 0,
        "found_item_insert_ready_total": 0,
        "found_item_insert_missing_photo_url_total": 0,
        "would_fail_found_item_insert_before_fix_total": 0,
    }

    for domain in source_result.dry_run_domains:
        pipeline = source_result.pipeline_counts_by_domain.get(domain, {})
        domain_items = source_result.samples_by_domain.get(domain, [])[:max_items_per_domain]
        counts = FullCycleDomainCounts(
            raw_fetched=int(pipeline.get("raw_fetched", 0)),
            converted=int(pipeline.get("converted", 0)),
            after_filters=int(pipeline.get("after_filters", 0)),
        )
        simulation = FullCycleSimulationSamples()
        if domain in errors_by_domain:
            counts_by_domain[domain] = counts
            simulations[domain] = simulation
            samples_by_domain[domain] = []
            summary["raw_fetched_total"] += counts.raw_fetched
            summary["after_filters_total"] += counts.after_filters
            continue

        item_ids = {int(item.id) for item in domain_items}
        try:
            seen_ids, found_ids = await _load_existing_item_ids(
                db,
                monitor_id=monitor.id,
                domain=domain,
                item_ids=item_ids,
            )
        except Exception as exc:
            errors_by_domain[domain] = type(exc).__name__
            counts_by_domain[domain] = counts
            simulations[domain] = simulation
            samples_by_domain[domain] = []
            summary["raw_fetched_total"] += counts.raw_fetched
            summary["after_filters_total"] += counts.after_filters
            logger.warning(
                "full_cycle_domain_simulation_failed monitor_id=%s domain=%s exception_type=%s",
                monitor.id,
                domain,
                type(exc).__name__,
            )
            continue

        found_ids_across_domains.update(found_ids)
        is_cold_start = monitor.last_check_at is None

        for item in domain_items:
            item_id = int(item.id)
            if item_id in seen_ids:
                counts.already_seen += 1
                if len(simulation.sample_already_seen) < sample_limit:
                    simulation.sample_already_seen.append(item)
                if not is_cold_start:
                    counts.seen_boundary_hit = True
                    counts.stopped_at_seen_item_id = item.id
                    break
                continue

            if item_id in found_ids_across_domains:
                counts.already_found += 1
                counts.would_create_seen_items += 1
                if len(simulation.sample_already_found) < sample_limit:
                    simulation.sample_already_found.append(item)
                continue

            counts.would_create_seen_items += 1
            if is_cold_start:
                continue

            found_ids_across_domains.add(item_id)
            counts.would_be_new_items += 1
            counts.would_create_found_items += 1
            counts.would_enqueue_notifications += 1
            readiness = inspect_found_item_insert_readiness(item)
            counts.found_item_insert_ready += int(readiness["ready"])
            counts.found_item_insert_missing_photo_url += int(
                readiness["missing_photo_url"]
            )
            counts.found_item_insert_missing_title += int(
                readiness["missing_title"]
            )
            counts.found_item_insert_missing_url += int(readiness["missing_url"])
            counts.found_item_insert_missing_price += int(
                readiness["missing_price"]
            )
            counts.found_item_insert_missing_currency += int(
                readiness["missing_currency"]
            )
            counts.would_fail_found_item_insert_before_fix += int(
                readiness["would_fail_before_fix"]
            )
            if telegram_enabled:
                counts.would_send_telegram += 1
            if len(simulation.sample_would_be_new) < sample_limit:
                simulation.sample_would_be_new.append(item)

        counts_by_domain[domain] = counts
        simulations[domain] = simulation
        samples_by_domain[domain] = domain_items[:sample_limit] if include_samples else []

        summary["raw_fetched_total"] += counts.raw_fetched
        summary["after_filters_total"] += counts.after_filters
        summary["already_seen_total"] += counts.already_seen
        summary["already_found_total"] += counts.already_found
        summary["would_create_seen_items_total"] += counts.would_create_seen_items
        summary["would_create_found_items_total"] += counts.would_create_found_items
        summary["would_enqueue_notifications_total"] += counts.would_enqueue_notifications
        summary["would_send_telegram_total"] += counts.would_send_telegram
        summary["found_item_insert_ready_total"] += counts.found_item_insert_ready
        summary["found_item_insert_missing_photo_url_total"] += (
            counts.found_item_insert_missing_photo_url
        )
        summary["would_fail_found_item_insert_before_fix_total"] += (
            counts.would_fail_found_item_insert_before_fix
        )

    return MonitorFullCycleDryRunResult(
        monitor_id=monitor.id,
        selected_source=source_result.selected_source,
        reason=source_result.reason,
        selected_domains=source_result.selected_domains,
        dry_run_domains=source_result.dry_run_domains,
        summary=summary,
        counts_by_domain=counts_by_domain,
        pipeline_counts_by_domain=source_result.pipeline_counts_by_domain,
        seen_found_simulation_by_domain=simulations,
        samples_by_domain=samples_by_domain,
        errors_by_domain=errors_by_domain,
    )

async def perform_monitor_baseline_seen(
    monitor: Monitor,
    client: VintedClient,
    db: AsyncSession,
    *,
    max_domains: int = 1,
    max_items_per_domain: int = 96,
    target_domain: Optional[str] = None,
    dry_run: bool = True,
    sample_limit: int = 10,
) -> dict:
    """Fetch/filter monitor items and optionally persist only missing SeenItem rows."""
    source_result = await perform_monitor_dry_run(
        monitor,
        client,
        max_domains=max_domains,
        max_items_per_domain=max_items_per_domain,
        target_domain=target_domain,
    )
    summary = {
        "domains_checked": len(source_result.dry_run_domains),
        "raw_fetched_total": 0,
        "after_filters_total": 0,
        "already_seen_total": 0,
        "would_create_seen_items_total": 0,
        "created_seen_items_total": 0,
        "would_create_found_items_total": 0,
        "would_enqueue_notifications_total": 0,
        "would_send_telegram_total": 0,
    }
    counts_by_domain: dict[str, dict[str, int]] = {}
    samples_by_domain: dict[str, list[dict[str, Any]]] = {}
    missing_by_domain: dict[str, list[DryRunItem]] = {}
    existing_by_domain: dict[str, set[int]] = {}

    for domain in source_result.dry_run_domains:
        pipeline = source_result.pipeline_counts_by_domain.get(domain, {})
        items = source_result.samples_by_domain.get(domain, [])[:max_items_per_domain]
        item_ids = {int(item.id) for item in items}
        seen_result = await db.execute(
            select(SeenItem.vinted_item_id).where(
                SeenItem.monitor_id == monitor.id,
                SeenItem.domain == domain,
                SeenItem.vinted_item_id.in_(item_ids),
            )
        ) if item_ids else None
        existing_ids = {int(row[0]) for row in seen_result.fetchall()} if seen_result else set()
        existing_by_domain[domain] = existing_ids
        missing_items = [item for item in items if int(item.id) not in existing_ids]
        missing_by_domain[domain] = missing_items

        counts = {
            "raw_fetched": int(pipeline.get("raw_fetched", 0)),
            "converted": int(pipeline.get("converted", 0)),
            "after_filters": int(pipeline.get("after_filters", 0)),
            "already_seen": len(items) - len(missing_items),
            "would_create_seen_items": len(missing_items),
            "created_seen_items": 0,
        }
        counts_by_domain[domain] = counts
        samples_by_domain[domain] = [
            {
                "id": item.id,
                "title": item.title,
                "brand_title": item.brand_title,
                "price": item.price,
                "currency": item.currency,
                "url": item.url,
                "domain": item.domain,
                "source": item.source,
            }
            for item in missing_items[:sample_limit]
        ]
        summary["raw_fetched_total"] += counts["raw_fetched"]
        summary["after_filters_total"] += counts["after_filters"]
        summary["already_seen_total"] += counts["already_seen"]
        summary["would_create_seen_items_total"] += counts["would_create_seen_items"]

    if not dry_run:
        rows = [
            {
                "monitor_id": monitor.id,
                "user_id": monitor.user_id,
                "vinted_item_id": int(item.id),
                "domain": domain,
                "seen_at": datetime.now(timezone.utc),
            }
            for domain, items in missing_by_domain.items()
            for item in items
        ]
        if rows:
            dialect_name = db.get_bind().dialect.name
            if dialect_name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            elif dialect_name == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            else:
                raise RuntimeError("Unsupported database dialect for conflict-safe baseline insert")
            statement = insert(SeenItem).values(rows).on_conflict_do_nothing(
                index_elements=["monitor_id", "vinted_item_id", "domain"]
            )
            await db.execute(statement)
        await db.commit()

        for domain, missing_items in missing_by_domain.items():
            missing_ids = {int(item.id) for item in missing_items}
            if not missing_ids:
                continue
            final_result = await db.execute(
                select(SeenItem.vinted_item_id).where(
                    SeenItem.monitor_id == monitor.id,
                    SeenItem.domain == domain,
                    SeenItem.vinted_item_id.in_(missing_ids),
                )
            )
            final_ids = {int(row[0]) for row in final_result.fetchall()}
            created = len(final_ids - existing_by_domain[domain])
            counts_by_domain[domain]["created_seen_items"] = created
            summary["created_seen_items_total"] += created

    return {
        "monitor_id": monitor.id,
        "dry_run": dry_run,
        "selected_source": source_result.selected_source,
        "reason": "baseline_seen_no_notify",
        "selected_domains": source_result.selected_domains,
        "baseline_domains": source_result.dry_run_domains,
        "summary": summary,
        "counts_by_domain": counts_by_domain,
        "samples_by_domain": samples_by_domain,
        "errors_by_domain": source_result.errors_by_domain,
        "safe_error": None,
        "side_effects": {
            "runs_scheduler_check": False,
            "writes_seen_items": summary["created_seen_items_total"] > 0,
            "writes_found_items": False,
            "updates_monitor": False,
            "enqueues_notifications": False,
            "sends_telegram": False,
            "calls_vinted": True,
            "reads_database": True,
        },
    }
