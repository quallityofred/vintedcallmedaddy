from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from app.models import Monitor
from app.scraper.client import VintedClient, DomainSearchResult
from app.scraper.parser import VintedItem
from app.scraper.source_selector import should_use_hydration_source
from app.scraper.hydration_parser import hydration_record_to_vinted_item, analyze_hydration_html, get_candidate_samples
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
    candidate_samples: List[Dict[str, Any]] = field(default_factory=list)
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
                
                from app.scraper.hydration_parser import extract_next_f_chunks, extract_hydration_items, analyze_hydration_html, get_candidate_samples
                chunks = extract_next_f_chunks(html)
                hydration_items = extract_hydration_items(html, domain=domain)
                analysis = analyze_hydration_html(html)
                candidate_samples = get_candidate_samples(html, max_samples=5)
                
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
                    parser_strategy_used="current_regex_or_structural",
                    candidate_samples=candidate_samples
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
                    source=source
                ))
            samples_by_domain[domain] = samples

        except Exception as e:
            logger.exception("Dry-run failed for domain=%s", domain)
            errors_by_domain[domain] = str(e)
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
                    safe_error=str(e)
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
