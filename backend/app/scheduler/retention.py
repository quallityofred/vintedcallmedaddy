from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select, func, and_, or_, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FoundItem, SeenItem, Monitor

logger = logging.getLogger(__name__)

@dataclass
class RetentionConfig:
    found_items_retention_days: int = 14
    found_items_max_per_monitor_domain: int = 128
    seen_items_max_per_monitor_domain: int = 192
    sample_limit: int = 10

@dataclass
class MonitorDomainStats:
    monitor_id: int
    domain: str

    found_items_total: int = 0
    found_items_notified: int = 0
    found_items_pending: int = 0
    found_items_would_delete: int = 0
    found_items_would_keep: int = 0

    seen_items_total: int = 0
    seen_items_would_delete: int = 0
    seen_items_would_keep: int = 0

@dataclass
class RetentionPlan:
    dry_run: bool = True
    include_found_items: bool = True
    include_seen_items: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    monitors_considered: List[int] = field(default_factory=list)

    found_items_total: int = 0
    found_items_notified_total: int = 0
    found_items_pending_total: int = 0
    found_items_would_delete_total: int = 0
    found_items_would_keep_total: int = 0

    seen_items_total: int = 0
    seen_items_would_delete_total: int = 0
    seen_items_would_keep_total: int = 0

    by_monitor_domain: List[Dict[str, Any]] = field(default_factory=list)
    samples: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    side_effects: Dict[str, bool] = field(default_factory=lambda: {
        "deletes_found_items": False,
        "deletes_seen_items": False,
        "sends_telegram": False,
        "calls_vinted": False,
        "runs_baseline": False,
        "runs_check": False
    })

async def run_history_retention_dry_run(
    db: AsyncSession,
    monitor_ids: Optional[List[int]] = None,
    include_found_items: bool = True,
    include_seen_items: bool = True,
    found_items_retention_days: int = 14,
    found_items_max_per_monitor_domain: int = 128,
    seen_items_max_per_monitor_domain: int = 192,
    sample_limit: int = 10
) -> Dict[str, Any]:
    """
    Perform a dry-run history retention analysis.
    Reports what WOULD be pruned without modifying the database.
    """
    config = RetentionConfig(
        found_items_retention_days=found_items_retention_days,
        found_items_max_per_monitor_domain=found_items_max_per_monitor_domain,
        seen_items_max_per_monitor_domain=seen_items_max_per_monitor_domain,
        sample_limit=sample_limit
    )

    plan = RetentionPlan(
        include_found_items=include_found_items,
        include_seen_items=include_seen_items,
        config={
            "found_items_retention_days": config.found_items_retention_days,
            "found_items_max_per_monitor_domain": config.found_items_max_per_monitor_domain,
            "seen_items_max_per_monitor_domain": config.seen_items_max_per_monitor_domain,
            "sample_limit": config.sample_limit
        }
    )

    # 1. Get monitors
    stmt = select(Monitor.id)
    if monitor_ids:
        stmt = stmt.where(Monitor.id.in_(monitor_ids))

    monitors_result = await db.execute(stmt)
    actual_monitor_ids = [m[0] for m in monitors_result.all()]
    plan.monitors_considered = actual_monitor_ids

    if not actual_monitor_ids:
        plan.warnings.append("No monitors found or selected.")
        return plan.__dict__

    stats_map: Dict[tuple[int, str], MonitorDomainStats] = {}
    found_items_to_delete: List[int] = []
    seen_items_to_delete: List[int] = []

    # 2. Process FoundItems
    if include_found_items:
        found_items_to_delete = await _analyze_found_items(db, actual_monitor_ids, config, plan, stats_map)

    # 3. Process SeenItems
    if include_seen_items:
        seen_items_to_delete = await _analyze_seen_items(db, actual_monitor_ids, config, plan, stats_map)

    # Convert stats_map to list
    for stats in stats_map.values():
        plan.by_monitor_domain.append({
            "monitor_id": stats.monitor_id,
            "domain": stats.domain,
            "found_items": {
                "total": stats.found_items_total,
                "notified": stats.found_items_notified,
                "pending": stats.found_items_pending,
                "would_delete": stats.found_items_would_delete,
                "would_keep": stats.found_items_would_keep
            },
            "seen_items": {
                "total": stats.seen_items_total,
                "would_delete": stats.seen_items_would_delete,
                "would_keep": stats.seen_items_would_keep
            }
        })

    result_dict = plan.__dict__
    result_dict["_found_items_to_delete"] = found_items_to_delete
    result_dict["_seen_items_to_delete"] = seen_items_to_delete
    return result_dict

async def _analyze_found_items(
    db: AsyncSession,
    monitor_ids: List[int],
    config: RetentionConfig,
    plan: RetentionPlan,
    stats_map: Dict[tuple[int, str], MonitorDomainStats]
) -> List[int]:
    from app.models import utc_now
    now = utc_now()
    cutoff_date = now - timedelta(days=config.found_items_retention_days)

    stmt = select(
        FoundItem.id,
        FoundItem.monitor_id,
        FoundItem.domain,
        FoundItem.vinted_item_id,
        FoundItem.found_at,
        FoundItem.notified
    ).where(FoundItem.monitor_id.in_(monitor_ids)).order_by(
        FoundItem.monitor_id,
        FoundItem.domain,
        desc(FoundItem.found_at)
    )

    result = await db.execute(stmt)
    rows = result.all()

    ids_to_delete = []
    current_group = None
    rank = 0

    for row_id, monitor_id, domain, item_id, found_at, notified in rows:
        key = (monitor_id, domain)
        if key not in stats_map:
            stats_map[key] = MonitorDomainStats(monitor_id=monitor_id, domain=domain)
        stats = stats_map[key]

        stats.found_items_total += 1
        plan.found_items_total += 1

        if not notified:
            stats.found_items_pending += 1
            plan.found_items_pending_total += 1
            stats.found_items_would_keep += 1
            plan.found_items_would_keep_total += 1
            continue

        stats.found_items_notified += 1
        plan.found_items_notified_total += 1

        if current_group != key:
            current_group = key
            rank = 1
        else:
            rank += 1

        if found_at.tzinfo is None and cutoff_date.tzinfo is not None:
            found_at = found_at.replace(tzinfo=timezone.utc)
        elif found_at.tzinfo is not None and cutoff_date.tzinfo is None:
            found_at = found_at.replace(tzinfo=None)

        is_too_old = found_at < cutoff_date
        is_beyond_cap = rank > config.found_items_max_per_monitor_domain

        if is_too_old or is_beyond_cap:
            stats.found_items_would_delete += 1
            plan.found_items_would_delete_total += 1
            ids_to_delete.append(row_id)
            if len(plan.samples) < config.sample_limit:
                plan.samples.append({
                    "type": "found_item",
                    "monitor_id": monitor_id,
                    "domain": domain,
                    "vinted_item_id": item_id,
                    "created_at": found_at.isoformat(),
                    "notified": notified,
                    "reason": "too_old" if is_too_old else "beyond_cap"
                })
        else:
            stats.found_items_would_keep += 1
            plan.found_items_would_keep_total += 1
    
    return ids_to_delete

async def _analyze_seen_items(
    db: AsyncSession,
    monitor_ids: List[int],
    config: RetentionConfig,
    plan: RetentionPlan,
    stats_map: Dict[tuple[int, str], MonitorDomainStats]
) -> List[int]:
    stmt = select(
        SeenItem.id,
        SeenItem.monitor_id,
        SeenItem.domain,
        SeenItem.vinted_item_id,
        SeenItem.seen_at
    ).where(SeenItem.monitor_id.in_(monitor_ids)).order_by(
        SeenItem.monitor_id,
        SeenItem.domain,
        desc(SeenItem.seen_at)
    )

    result = await db.execute(stmt)
    rows = result.all()

    ids_to_delete = []
    current_group = None
    rank = 0

    for row_id, monitor_id, domain, item_id, seen_at in rows:
        if monitor_id is None:
            plan.warnings.append(f"SeenItem {item_id} has no monitor_id, skipping.")
            continue

        key = (monitor_id, domain)
        if key not in stats_map:
            stats_map[key] = MonitorDomainStats(monitor_id=monitor_id, domain=domain)
        stats = stats_map[key]

        stats.seen_items_total += 1
        plan.seen_items_total += 1

        if current_group != key:
            current_group = key
            rank = 1
        else:
            rank += 1

        is_beyond_cap = rank > config.seen_items_max_per_monitor_domain

        if is_beyond_cap:
            stats.seen_items_would_delete += 1
            plan.seen_items_would_delete_total += 1
            ids_to_delete.append(row_id)
            if len(plan.samples) < config.sample_limit * 2:
                plan.samples.append({
                    "type": "seen_item",
                    "monitor_id": monitor_id,
                    "domain": domain,
                    "vinted_item_id": item_id,
                    "created_at": seen_at.isoformat(),
                    "reason": "beyond_cap"
                })
        else:
            stats.seen_items_would_keep += 1
            plan.seen_items_would_keep_total += 1
            
    return ids_to_delete

async def run_history_retention_cleanup(
    db: AsyncSession,
    dry_run: bool = True,
    monitor_ids: Optional[List[int]] = None,
    include_found_items: bool = True,
    include_seen_items: bool = True,
    found_items_retention_days: int = 14,
    found_items_max_per_monitor_domain: int = 128,
    seen_items_max_per_monitor_domain: int = 192,
    sample_limit: int = 10,
    reason: Optional[str] = None,
    confirm: Optional[str] = None
) -> Dict[str, Any]:
    # Run the analysis
    plan_dict = await run_history_retention_dry_run(
        db=db,
        monitor_ids=monitor_ids,
        include_found_items=include_found_items,
        include_seen_items=include_seen_items,
        found_items_retention_days=found_items_retention_days,
        found_items_max_per_monitor_domain=found_items_max_per_monitor_domain,
        seen_items_max_per_monitor_domain=seen_items_max_per_monitor_domain,
        sample_limit=sample_limit
    )

    found_ids = plan_dict.pop("_found_items_to_delete", [])
    seen_ids = plan_dict.pop("_seen_items_to_delete", [])

    if dry_run:
        plan_dict['dry_run'] = True
        return plan_dict

    # Perform deletion
    deleted_found = 0
    deleted_seen = 0

    if include_found_items and found_ids:
        stmt = delete(FoundItem).where(FoundItem.id.in_(found_ids))
        res = await db.execute(stmt)
        deleted_found = res.rowcount
        plan_dict['side_effects']['deletes_found_items'] = deleted_found > 0

    if include_seen_items and seen_ids:
        stmt = delete(SeenItem).where(SeenItem.id.in_(seen_ids))
        res = await db.execute(stmt)
        deleted_seen = res.rowcount
        plan_dict['side_effects']['deletes_seen_items'] = deleted_seen > 0

    await db.commit()

    plan_dict['found_items_deleted_count'] = deleted_found
    plan_dict['seen_items_deleted_count'] = deleted_seen
    plan_dict['dry_run'] = False
    
    # Update totals after deletion
    plan_dict['found_items_total_after'] = plan_dict['found_items_total'] - deleted_found
    plan_dict['seen_items_total_after'] = plan_dict['seen_items_total'] - deleted_seen

    return plan_dict
