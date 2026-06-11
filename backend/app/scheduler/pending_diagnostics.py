from __future__ import annotations
import logging
import json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FoundItem, Monitor, MonitorTelegramTopic, utc_now
from app.scraper.monitor_filters import (
    brand_text_matches_allowed,
    extract_monitor_filters,
    has_restrictive_filters,
    has_positive_brand_text,
)
from app.scraper.url_parser import get_effective_monitor_request_params

logger = logging.getLogger(__name__)

@dataclass
class PendingStats:
    total: int = 0
    lt_1h: int = 0
    h_1_to_6: int = 0
    h_6_to_24: int = 0
    d_1_to_3: int = 0
    d_3_to_7: int = 0
    gt_7d: int = 0
    oldest: Optional[datetime] = None
    newest: Optional[datetime] = None

def get_age_bucket(created_at: datetime) -> str:
    now = utc_now()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    
    age_minutes = (now - created_at).total_seconds() / 60
    
    if age_minutes < 60:
        return "lt_1h"
    elif age_minutes < 360:
        return "h_1_to_6"
    elif age_minutes < 1440:
        return "h_6_to_24"
    elif age_minutes < 4320:
        return "d_1_to_3"
    elif age_minutes < 10080:
        return "d_3_to_7"
    else:
        return "gt_7d"

async def run_pending_notifications_dry_run(
    db: AsyncSession,
    monitor_ids: Optional[List[int]] = None,
    domains: Optional[List[str]] = None,
    older_than_minutes: Optional[int] = None,
    include_inactive: bool = True,
    sample_limit: int = 10
) -> Dict[str, Any]:
    
    # 1. Base Query
    stmt = select(
        FoundItem, Monitor.name, Monitor.is_active, MonitorTelegramTopic.id.isnot(None).label("has_topic")
    ).join(Monitor, FoundItem.monitor_id == Monitor.id).outerjoin(
        MonitorTelegramTopic, FoundItem.monitor_id == MonitorTelegramTopic.monitor_id
    ).where(FoundItem.notified == False)
    
    if monitor_ids:
        stmt = stmt.where(FoundItem.monitor_id.in_(monitor_ids))
    if domains:
        stmt = stmt.where(FoundItem.domain.in_(domains))
    if not include_inactive:
        stmt = stmt.where(Monitor.is_active == True)
        
    result = await db.execute(stmt)
    rows = result.all()
    
    # Process rows
    total_pending = 0
    by_monitor = {}
    by_monitor_domain = {}
    samples = []
    
    now = utc_now()
    
    for item, mon_name, is_active, has_topic in rows:
        created_at = item.found_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
            
        if older_than_minutes and (now - created_at).total_seconds() / 60 < older_than_minutes:
            continue
            
        total_pending += 1
        bucket = get_age_bucket(created_at)
        
        # Monitor stats
        if item.monitor_id not in by_monitor:
            by_monitor[item.monitor_id] = {
                "stats": {"lt_1h": 0, "h_1_to_6": 0, "h_6_to_24": 0, "d_1_to_3": 0, "d_3_to_7": 0, "gt_7d": 0},
                "name": mon_name, "is_active": is_active, "has_topic": has_topic, "domains": set()
            }
        
        mon_stats = by_monitor[item.monitor_id]["stats"]
        _update_stats(mon_stats, bucket)
        by_monitor[item.monitor_id]["domains"].add(item.domain)
        
        # Domain stats
        key = (item.monitor_id, item.domain)
        if key not in by_monitor_domain:
            by_monitor_domain[key] = {
                "stats": {"lt_1h": 0, "h_1_to_6": 0, "h_6_to_24": 0, "d_1_to_3": 0, "d_3_to_7": 0, "gt_7d": 0},
                "name": mon_name, "is_active": is_active, "has_topic": has_topic
            }
        
        dom_stats = by_monitor_domain[key]["stats"]
        _update_stats(dom_stats, bucket)
        
        # Samples
        if len(samples) < sample_limit:
            samples.append({
                "monitor_id": item.monitor_id,
                "monitor_name": mon_name,
                "domain": item.domain,
                "vinted_item_id": item.vinted_item_id,
                "created_at": created_at.isoformat(),
                "age_minutes": int((now - created_at).total_seconds() / 60),
                "is_active": is_active,
                "has_topic": has_topic
            })
            
    # Finalize structure
    return {
        "dry_run": True,
        "pending_total": total_pending,
        "by_monitor": [{**{"monitor_id": k, "domains_count": len(v["domains"])}, **v} for k, v in by_monitor.items()],
        "by_monitor_domain": [{"monitor_id": k[0], "domain": k[1], **v} for k, v in by_monitor_domain.items()],
        "samples": samples,
        "side_effects": {
            "marks_notified": False,
            "deletes_found_items": False,
            "deletes_seen_items": False,
            "sends_telegram": False,
            "calls_vinted": False,
            "runs_baseline": False,
            "runs_check": False
        }
    }

def _update_stats(stats: Dict[str, int], bucket: str):
    stats[bucket] += 1

async def run_pending_notifications_ack_no_notify(
    db: AsyncSession,
    dry_run: bool = True,
    monitor_ids: Optional[List[int]] = None,
    domains: Optional[List[str]] = None,
    older_than_minutes: int = 1440,
    include_inactive: bool = True,
    include_active: bool = False,
    sample_limit: int = 10
) -> Dict[str, Any]:
    
    # 1. Base Query
    # Note: Using FoundItem alias to allow easier updates later
    stmt = select(FoundItem).join(Monitor, FoundItem.monitor_id == Monitor.id)
    
    stmt = stmt.where(FoundItem.notified == False)
    
    if monitor_ids:
        stmt = stmt.where(FoundItem.monitor_id.in_(monitor_ids))
    if domains:
        stmt = stmt.where(FoundItem.domain.in_(domains))
        
    # Active/Inactive filters
    if not include_inactive and not include_active:
        # Should not happen, but safe default: exclude all
        stmt = stmt.where(False)
    elif not include_inactive:
        stmt = stmt.where(Monitor.is_active == True)
    elif not include_active:
        stmt = stmt.where(Monitor.is_active == False)
        
    # Age filter
    now = utc_now()
    if older_than_minutes:
        cutoff = now - timedelta(minutes=older_than_minutes)
        stmt = stmt.where(FoundItem.found_at < cutoff)
        
    result = await db.execute(stmt)
    eligible_items = result.scalars().all()
    
    total_eligible = len(eligible_items)
    acked_count = 0
    
    if not dry_run:
        for item in eligible_items:
            item.notified = True
            acked_count += 1
        await db.commit()
        
    return {
        "dry_run": dry_run,
        "eligible_to_ack": total_eligible,
        "acked_count": acked_count if not dry_run else 0,
        "side_effects": {
            "marks_notified": not dry_run and acked_count > 0,
            "deletes_found_items": False,
            "deletes_seen_items": False,
            "sends_telegram": False,
            "calls_vinted": False,
            "runs_baseline": False,
            "runs_check": False
        }
    }


def _title_preview(value: str | None, limit: int = 80) -> str:
    text = (value or "").strip()
    return text[:limit]


def _item_has_verified_brand_evidence(item: FoundItem, filters) -> bool:
    if not filters.brand_ids:
        return False
    if item.brand_id is not None and str(item.brand_id) in filters.brand_ids:
        return True
    if not has_positive_brand_text(item.brand):
        return False
    return brand_text_matches_allowed(item.brand, filters.allowed_brand_names)


def _monitor_filters_for_pending_row(monitor: Monitor):
    try:
        params = get_effective_monitor_request_params(monitor.params_json, monitor.original_url)
    except Exception:
        try:
            params = json.loads(monitor.params_json)
        except Exception:
            params = {}
    return extract_monitor_filters(params, monitor_name=monitor.name)


def _safe_monitor_params(monitor: Monitor) -> dict[str, Any]:
    try:
        return get_effective_monitor_request_params(monitor.params_json, monitor.original_url)
    except Exception:
        try:
            return json.loads(monitor.params_json)
        except Exception:
            return {}


def _classify_pending_row(item: FoundItem, monitor: Monitor) -> dict[str, Any]:
    params = _safe_monitor_params(monitor)
    filters = extract_monitor_filters(params, monitor_name=monitor.name)
    has_real_filter = has_restrictive_filters(filters)
    has_verified_brand = _item_has_verified_brand_evidence(item, filters)

    if not has_real_filter:
        likely_cause = "broad_order_only_monitor"
    elif filters.brand_ids and not has_verified_brand:
        likely_cause = "unknown_brand_from_unverified_source"
    elif filters.brand_ids and has_verified_brand:
        likely_cause = "valid_positive_brand_evidence"
    else:
        likely_cause = "unknown"

    return {
        "likely_cause": likely_cause,
        "has_any_real_filter": has_real_filter,
        "is_order_only": not has_real_filter and bool(filters.order),
        "is_broad_feed_risk": not has_real_filter,
        "brand_ids": sorted(filters.brand_ids),
        "catalog_ids": sorted(filters.catalog_ids),
        "filter_keys": filters.filter_keys,
        "has_verified_brand_evidence": has_verified_brand,
        "brand_title_present": has_positive_brand_text(item.brand),
    }


def _pending_sample(item: FoundItem, monitor: Monitor, classification: dict[str, Any]) -> dict[str, Any]:
    found_at = item.found_at
    if found_at is not None and found_at.tzinfo is None:
        found_at = found_at.replace(tzinfo=timezone.utc)
    now = utc_now()
    age_minutes = None
    if found_at is not None:
        age_minutes = int((now - found_at).total_seconds() / 60)
    return {
        "found_item_id": item.id,
        "monitor_id": item.monitor_id,
        "monitor_name": monitor.name,
        "vinted_item_id": item.vinted_item_id,
        "domain": item.domain,
        "title_preview": _title_preview(item.title),
        "brand_title": item.brand if has_positive_brand_text(item.brand) else "unknown",
        "brand_id": item.brand_id,
        "found_at": found_at.isoformat() if found_at else None,
        "age_minutes": age_minutes,
        "likely_cause": classification["likely_cause"],
        "has_any_real_filter": classification["has_any_real_filter"],
        "is_order_only": classification["is_order_only"],
        "is_broad_feed_risk": classification["is_broad_feed_risk"],
        "has_verified_brand_evidence": classification["has_verified_brand_evidence"],
    }


async def run_pending_backlog_classification(
    db: AsyncSession,
    *,
    monitor_ids: Optional[List[int]] = None,
    domains: Optional[List[str]] = None,
    sample_limit: int = 10,
) -> Dict[str, Any]:
    sample_limit = max(0, min(sample_limit, 20))
    stmt = select(FoundItem, Monitor).join(Monitor, FoundItem.monitor_id == Monitor.id)
    stmt = stmt.where(FoundItem.notified == False)
    if monitor_ids:
        stmt = stmt.where(FoundItem.monitor_id.in_(monitor_ids))
    if domains:
        stmt = stmt.where(FoundItem.domain.in_(domains))

    rows = (await db.execute(stmt.order_by(FoundItem.found_at.asc(), FoundItem.id.asc()))).all()

    by_cause: dict[str, dict[str, Any]] = {}
    by_monitor: dict[int, dict[str, Any]] = {}
    samples: list[dict[str, Any]] = []

    for item, monitor in rows:
        classification = _classify_pending_row(item, monitor)
        cause = classification["likely_cause"]
        cause_bucket = by_cause.setdefault(cause, {"likely_cause": cause, "pending_count": 0})
        cause_bucket["pending_count"] += 1

        monitor_bucket = by_monitor.setdefault(
            item.monitor_id,
            {
                "monitor_id": item.monitor_id,
                "monitor_name": monitor.name,
                "pending_count": 0,
                "causes": {},
                "domains": set(),
                "has_any_real_filter": classification["has_any_real_filter"],
                "is_order_only": classification["is_order_only"],
                "is_broad_feed_risk": classification["is_broad_feed_risk"],
                "brand_ids": classification["brand_ids"],
                "catalog_ids": classification["catalog_ids"],
                "filter_keys": classification["filter_keys"],
            },
        )
        monitor_bucket["pending_count"] += 1
        monitor_bucket["causes"][cause] = monitor_bucket["causes"].get(cause, 0) + 1
        monitor_bucket["domains"].add(item.domain)

        if len(samples) < sample_limit:
            samples.append(_pending_sample(item, monitor, classification))

    by_monitor_list = []
    for bucket in by_monitor.values():
        by_monitor_list.append(
            {
                **bucket,
                "domains": sorted(bucket["domains"]),
            }
        )

    return {
        "dry_run": True,
        "pending_total": len(rows),
        "by_cause": sorted(by_cause.values(), key=lambda row: row["likely_cause"]),
        "by_monitor": sorted(by_monitor_list, key=lambda row: row["monitor_id"]),
        "samples": samples,
        "side_effects": {
            "reads_database": True,
            "writes_database": False,
            "writes_found_items": False,
            "marks_notified": False,
            "deletes_found_items": False,
            "deletes_seen_items": False,
            "sends_telegram": False,
            "calls_vinted": False,
            "runs_baseline": False,
            "runs_check": False,
        },
    }


async def run_bad_url_backlog_ack(
    db: AsyncSession,
    *,
    dry_run: bool = True,
    monitor_ids: Optional[List[int]] = None,
    domains: Optional[List[str]] = None,
    sample_limit: int = 10,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    sample_limit = max(0, min(sample_limit, 20))
    stmt = select(FoundItem, Monitor).join(Monitor, FoundItem.monitor_id == Monitor.id)
    stmt = stmt.where(FoundItem.notified == False)
    if monitor_ids:
        stmt = stmt.where(FoundItem.monitor_id.in_(monitor_ids))
    if domains:
        stmt = stmt.where(FoundItem.domain.in_(domains))

    rows = (await db.execute(stmt.order_by(FoundItem.found_at.asc(), FoundItem.id.asc()))).all()
    eligible_causes = {
        "broad_order_only_monitor",
        "unknown_brand_from_unverified_source",
    }
    eligible: list[FoundItem] = []
    samples: list[dict[str, Any]] = []
    excluded_positive_brand_evidence_count = 0
    excluded_other_count = 0

    for item, monitor in rows:
        classification = _classify_pending_row(item, monitor)
        if classification["has_verified_brand_evidence"]:
            excluded_positive_brand_evidence_count += 1
            continue
        if classification["likely_cause"] not in eligible_causes:
            excluded_other_count += 1
            continue
        eligible.append(item)
        if len(samples) < sample_limit:
            samples.append(_pending_sample(item, monitor, classification))

    acked_count = 0
    if not dry_run:
        for item in eligible:
            item.notified = True
            acked_count += 1
        await db.commit()

    return {
        "dry_run": dry_run,
        "reason": reason,
        "monitor_ids": monitor_ids,
        "domains": domains,
        "scanned_pending_count": len(rows),
        "eligible_count": len(eligible),
        "acked_count": acked_count,
        "excluded_positive_brand_evidence_count": excluded_positive_brand_evidence_count,
        "excluded_other_count": excluded_other_count,
        "eligible_causes": sorted(eligible_causes),
        "samples": samples,
        "side_effects": {
            "reads_database": True,
            "writes_database": not dry_run and acked_count > 0,
            "writes_found_items": not dry_run and acked_count > 0,
            "marks_notified": not dry_run and acked_count > 0,
            "deletes_found_items": False,
            "deletes_seen_items": False,
            "sends_telegram": False,
            "calls_vinted": False,
            "runs_baseline": False,
            "runs_check": False,
        },
    }


async def run_suspect_brand_filter_backlog_ack(
    db: AsyncSession,
    *,
    dry_run: bool = True,
    monitor_ids: Optional[List[int]] = None,
    domains: Optional[List[str]] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    sample_limit: int = 10,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    stmt = select(FoundItem, Monitor).join(Monitor, FoundItem.monitor_id == Monitor.id)
    stmt = stmt.where(FoundItem.notified == False)
    if monitor_ids:
        stmt = stmt.where(FoundItem.monitor_id.in_(monitor_ids))
    if domains:
        stmt = stmt.where(FoundItem.domain.in_(domains))
    if created_after is not None:
        stmt = stmt.where(FoundItem.found_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(FoundItem.found_at <= created_before)

    result = await db.execute(stmt.order_by(FoundItem.found_at.asc(), FoundItem.id.asc()))
    rows = result.all()

    scanned_pending_count = 0
    eligible_items: list[FoundItem] = []
    samples: list[dict[str, Any]] = []
    excluded_matching_brand_count = 0
    excluded_no_brand_filter_count = 0

    for item, monitor in rows:
        scanned_pending_count += 1
        filters = _monitor_filters_for_pending_row(monitor)
        if not filters.brand_ids:
            excluded_no_brand_filter_count += 1
            continue
        if _item_has_verified_brand_evidence(item, filters):
            excluded_matching_brand_count += 1
            continue
        eligible_items.append(item)
        if len(samples) < max(0, min(sample_limit, 20)):
            samples.append(
                {
                    "found_item_id": item.id,
                    "monitor_id": item.monitor_id,
                    "monitor_name": monitor.name,
                    "vinted_item_id": item.vinted_item_id,
                    "domain": item.domain,
                    "title_preview": _title_preview(item.title),
                    "brand_title": item.brand if has_positive_brand_text(item.brand) else "unknown",
                    "brand_id": item.brand_id,
                    "found_at": item.found_at.isoformat() if item.found_at else None,
                    "reason": "missing_verified_brand_evidence",
                }
            )

    acked_count = 0
    if not dry_run:
        for item in eligible_items:
            item.notified = True
            acked_count += 1
        await db.commit()

    return {
        "dry_run": dry_run,
        "reason": reason,
        "monitor_ids": monitor_ids,
        "domains": domains,
        "created_after": created_after.isoformat() if created_after else None,
        "created_before": created_before.isoformat() if created_before else None,
        "scanned_pending_count": scanned_pending_count,
        "eligible_count": len(eligible_items),
        "acked_count": acked_count,
        "excluded_matching_brand_count": excluded_matching_brand_count,
        "excluded_no_brand_filter_count": excluded_no_brand_filter_count,
        "samples": samples,
        "side_effects": {
            "reads_database": True,
            "writes_found_items": not dry_run and acked_count > 0,
            "marks_notified": not dry_run and acked_count > 0,
            "deletes_found_items": False,
            "deletes_seen_items": False,
            "sends_telegram": False,
            "calls_vinted": False,
            "runs_baseline": False,
            "runs_check": False,
        },
    }


async def run_ack_pending_before_resume(
    db: AsyncSession,
    *,
    dry_run: bool = True,
    cutoff_found_before: Optional[datetime] = None,
    cutoff_created_before: Optional[datetime] = None,
    monitor_ids: Optional[List[int]] = None,
    user_ids: Optional[List[int]] = None,
    include_valid_positive_brand_evidence: bool = False,
    include_unknown_cause: bool = False,
    sample_limit: int = 20,
    reason: str,
) -> Dict[str, Any]:
    now = utc_now()
    stmt = select(FoundItem, Monitor).join(Monitor, FoundItem.monitor_id == Monitor.id)
    stmt = stmt.where(FoundItem.notified == False)

    if monitor_ids:
        stmt = stmt.where(FoundItem.monitor_id.in_(monitor_ids))
    if user_ids:
        stmt = stmt.where(Monitor.user_id.in_(user_ids))

    # Apply cutoff filters
    if cutoff_found_before:
        if cutoff_found_before.tzinfo is None:
            cutoff_found_before = cutoff_found_before.replace(tzinfo=timezone.utc)
        stmt = stmt.where(FoundItem.found_at < cutoff_found_before)
    
    # We use found_at for created_before as well if specific created_at field is missing
    if cutoff_created_before:
        if cutoff_created_before.tzinfo is None:
            cutoff_created_before = cutoff_created_before.replace(tzinfo=timezone.utc)
        stmt = stmt.where(FoundItem.found_at < cutoff_created_before)

    rows = (await db.execute(stmt.order_by(FoundItem.found_at.asc(), FoundItem.id.asc()))).all()

    eligible: list[FoundItem] = []
    samples: list[dict[str, Any]] = []
    
    counts = {
        "matched_pending_count": len(rows),
        "excluded_valid_positive_brand_evidence_count": 0,
        "excluded_unknown_cause_count": 0,
        "excluded_after_cutoff_count": 0, # Placeholder if we decide to fetch more and filter in python
    }
    
    by_monitor = {}
    by_cause = {}
    by_domain = {}

    for item, monitor in rows:
        classification = _classify_pending_row(item, monitor)
        cause = classification["likely_cause"]
        
        # Eligibility checks
        is_eligible = True
        
        if cause == "valid_positive_brand_evidence" and not include_valid_positive_brand_evidence:
            counts["excluded_valid_positive_brand_evidence_count"] += 1
            is_eligible = False
        elif cause == "unknown" and not include_unknown_cause:
            counts["excluded_unknown_cause_count"] += 1
            is_eligible = False
            
        if is_eligible:
            eligible.append(item)
            if len(samples) < sample_limit:
                samples.append(_pending_sample(item, monitor, classification))
        
        # Always track stats
        by_monitor[item.monitor_id] = by_monitor.get(item.monitor_id, 0) + 1
        by_cause[cause] = by_cause.get(cause, 0) + 1
        by_domain[item.domain] = by_domain.get(item.domain, 0) + 1

    acked_count = 0
    if not dry_run and eligible:
        for item in eligible:
            item.notified = True
            acked_count += 1
        await db.commit()

    return {
        "dry_run": dry_run,
        "reason": reason,
        "recommended_cutoff_found_before": now.isoformat(),
        "recommended_cutoff_created_before": now.isoformat(),
        "server_now": now.isoformat(),
        "matched_pending_count": counts["matched_pending_count"],
        "eligible_count": len(eligible),
        "acked_count": acked_count,
        "excluded_valid_positive_brand_evidence_count": counts["excluded_valid_positive_brand_evidence_count"],
        "excluded_unknown_cause_count": counts["excluded_unknown_cause_count"],
        "counts_by_monitor": by_monitor,
        "counts_by_cause": by_cause,
        "counts_by_domain": by_domain,
        "samples": samples,
        "side_effects": {
            "reads_database": True,
            "writes_database": not dry_run and acked_count > 0,
            "marks_notified": not dry_run and acked_count > 0,
            "sends_telegram": False,
            "calls_vinted": False,
        },
        "warning": "This endpoint intentionally suppresses currently pending notifications. It should be used only before resuming Telegram after downtime/debugging."
    }
