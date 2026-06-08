from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FoundItem, SeenItem, Monitor

logger = logging.getLogger(__name__)

@dataclass
class RetentionConfig:
    found_items_retention_days: int = 14
    found_items_max_per_monitor_domain: int = 288
    seen_items_max_per_monitor_domain: int = 288
    sample_limit: int = 10

@dataclass
class RetentionSample:
    monitor_id: int
    domain: str
    vinted_item_id: int
    created_at: str
    notified: Optional[bool] = None

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
    found_items_max_per_monitor_domain: int = 288,
    seen_items_max_per_monitor_domain: int = 288,
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

    # 2. Process FoundItems
    if include_found_items:
        await _analyze_found_items(db, actual_monitor_ids, config, plan, stats_map)

    # 3. Process SeenItems
    if include_seen_items:
        await _analyze_seen_items(db, actual_monitor_ids, config, plan, stats_map)

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

    return plan.__dict__

async def _analyze_found_items(
    db: AsyncSession,
    monitor_ids: List[int],
    config: RetentionConfig,
    plan: RetentionPlan,
    stats_map: Dict[tuple[int, str], MonitorDomainStats]
):
    # FoundItems: 
    # - notified=False: always keep
    # - notified=True: 
    #   - keep if found_at >= (now - retention_days) AND rank <= cap
    
    from app.models import utc_now
    now = utc_now()
    cutoff_date = now - timedelta(days=config.found_items_retention_days)
    
    # Query all FoundItems for target monitors
    stmt = select(
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
    
    # In-memory grouping and ranking (safer for dry-run without complex window functions in SQLite/PG compatibility)
    current_group = None
    rank = 0
    
    for monitor_id, domain, item_id, found_at, notified in rows:
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
        
        # Ranking notified items per monitor-domain
        if current_group != key:
            current_group = key
            rank = 1
        else:
            rank += 1
            
        # Retention criteria: 
        # Would delete if (older than TTL) OR (beyond cap)
        
        # Ensure found_at is timezone-aware if cutoff_date is
        if found_at.tzinfo is None and cutoff_date.tzinfo is not None:
            found_at = found_at.replace(tzinfo=timezone.utc)
        elif found_at.tzinfo is not None and cutoff_date.tzinfo is None:
            found_at = found_at.replace(tzinfo=None)

        is_too_old = found_at < cutoff_date
        is_beyond_cap = rank > config.found_items_max_per_monitor_domain
        
        if is_too_old or is_beyond_cap:
            stats.found_items_would_delete += 1
            plan.found_items_would_delete_total += 1
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

async def _analyze_seen_items(
    db: AsyncSession,
    monitor_ids: List[int],
    config: RetentionConfig,
    plan: RetentionPlan,
    stats_map: Dict[tuple[int, str], MonitorDomainStats]
):
    # SeenItems:
    # - Keep newest N per monitor-domain
    
    stmt = select(
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
    
    current_group = None
    rank = 0
    
    for monitor_id, domain, item_id, seen_at in rows:
        # Some SeenItems might not have monitor_id if they are global (though our schema implies monitor_id is likely)
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
            if len(plan.samples) < config.sample_limit * 2: # Allow more seen samples
                # Filter to avoid duplicates in samples list if already present from found_items (unlikely but good practice)
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
