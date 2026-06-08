from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FoundItem, Monitor, MonitorTelegramTopic, utc_now

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
