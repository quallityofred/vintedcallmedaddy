from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from app.models import Monitor
from app.scraper.client import VintedClient, DomainSearchResult
from app.scraper.parser import VintedItem
from app.scraper.source_selector import should_use_hydration_source
from app.scraper.hydration_parser import hydration_record_to_vinted_item
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

    filters = extract_monitor_filters(params)

    for domain in dry_run_domains:
        try:
            items: List[VintedItem] = []
            raw_count = 0
            if source == "hydration":
                domain_url = monitor.original_url.replace("vinted.pl", domain)
                raw_records = await client.fetch_catalog_hydration_items(domain_url, domain=domain)
                raw_count = len(raw_records)
                items = [hydration_record_to_vinted_item(r, domain) for r in raw_records]
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
        pipeline_counts_by_domain=pipeline_counts_by_domain
    )
