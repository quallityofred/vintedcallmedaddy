from __future__ import annotations
import logging
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Monitor, SeenItem, FoundItem
from app.scheduler.tasks import is_monitor_check_running

logger = logging.getLogger(__name__)

async def run_monitor_cold_start_reset(
    db: AsyncSession,
    monitor_id: int,
    dry_run: bool = True,
    domains: Optional[List[str]] = None,
    clear_seen_items: bool = True,
    clear_found_items: bool = False,
    reset_last_checked: bool = True,
    require_monitor_inactive: bool = True,
    sample_limit: int = 10
) -> Dict[str, Any]:
    """
    Safely reset a monitor to a cold-start state.
    """
    # 1. Load monitor
    monitor = await db.get(Monitor, monitor_id)
    if not monitor:
        raise ValueError(f"Monitor {monitor_id} not found.")

    monitor_active = monitor.is_active
    is_running = is_monitor_check_running(monitor_id)

    result: Dict[str, Any] = {
        "dry_run": dry_run,
        "monitor_id": monitor_id,
        "monitor_name": monitor.name,
        "monitor_active": monitor_active,
        "is_running": is_running,
        "selected_domains": [],
        "would_delete_seen_items": 0,
        "deleted_seen_items": 0,
        "would_delete_found_items": 0,
        "deleted_found_items": 0,
        "pending_found_items_count": 0,
        "would_reset_last_checked": False,
        "reset_last_checked": False,
        "cold_start_mode_after_reset": False,
        "warnings": [],
        "samples": [],
        "side_effects": {
            "deletes_seen_items": False,
            "deletes_found_items": False,
            "sends_telegram": False,
            "calls_vinted": False,
            "runs_baseline": False,
            "runs_check": False,
            "creates_found_items": False,
            "creates_notifications": False
        }
    }

    # 2. Resolve domains
    try:
        monitor_domains = json.loads(monitor.domains_json)
    except (TypeError, json.JSONDecodeError):
        monitor_domains = []

    if domains:
        # Validate requested domains
        invalid_domains = [d for d in domains if d not in monitor_domains]
        if invalid_domains:
            result["warnings"].append(f"Some requested domains are not configured for this monitor: {invalid_domains}")
        target_domains = [d for d in domains if d in monitor_domains]
    else:
        target_domains = monitor_domains

    result["selected_domains"] = target_domains

    # 3. Count candidates
    if clear_seen_items:
        stmt = select(func.count(SeenItem.id)).where(SeenItem.monitor_id == monitor_id)
        if target_domains:
            stmt = stmt.where(SeenItem.domain.in_(target_domains))
        result["would_delete_seen_items"] = await db.scalar(stmt) or 0

        # Sample some seen items
        sample_stmt = select(SeenItem).where(SeenItem.monitor_id == monitor_id)
        if target_domains:
            sample_stmt = sample_stmt.where(SeenItem.domain.in_(target_domains))
        sample_stmt = sample_stmt.limit(sample_limit)
        samples_res = await db.execute(sample_stmt)
        for s in samples_res.scalars().all():
            result["samples"].append({
                "type": "seen_item",
                "vinted_item_id": str(s.vinted_item_id),
                "domain": s.domain,
                "seen_at": s.seen_at.isoformat() if s.seen_at else None
            })

    if clear_found_items:
        stmt = select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor_id)
        if target_domains:
            stmt = stmt.where(FoundItem.domain.in_(target_domains))
        result["would_delete_found_items"] = await db.scalar(stmt) or 0

        # Count pending items (notified=False)
        pending_stmt = select(func.count(FoundItem.id)).where(
            FoundItem.monitor_id == monitor_id,
            FoundItem.notified == False
        )
        if target_domains:
            pending_stmt = pending_stmt.where(FoundItem.domain.in_(target_domains))
        result["pending_found_items_count"] = await db.scalar(pending_stmt) or 0

    if reset_last_checked and monitor.last_check_at is not None:
        result["would_reset_last_checked"] = True

    # 4. Perform live reset if requested
    if not dry_run:
        if require_monitor_inactive and is_running:
            raise ValueError(f"Monitor {monitor_id} is currently running a check. Reset aborted.")

        if clear_seen_items:
            del_stmt = delete(SeenItem).where(SeenItem.monitor_id == monitor_id)
            if target_domains:
                del_stmt = del_stmt.where(SeenItem.domain.in_(target_domains))
            
            del_res = await db.execute(del_stmt)
            result["deleted_seen_items"] = del_res.rowcount
            result["side_effects"]["deletes_seen_items"] = del_res.rowcount > 0

        if clear_found_items:
            # We already expect confirmations to be handled in the router
            del_stmt = delete(FoundItem).where(FoundItem.monitor_id == monitor_id)
            if target_domains:
                del_stmt = del_stmt.where(FoundItem.domain.in_(target_domains))
            del_res = await db.execute(del_stmt)
            result["deleted_found_items"] = del_res.rowcount
            result["side_effects"]["deletes_found_items"] = del_res.rowcount > 0
            
            # If we cleared all found items (for all domains or filtered), we might want to update monitor count
            # but if it was filtered it's harder. For now, if all domains are reset, we set it to 0.
            if not domains or set(domains) == set(monitor_domains):
                monitor.items_found_count = 0

        if reset_last_checked:
            monitor.last_check_at = None
            monitor.last_check_status = "reset"
            result["reset_last_checked"] = True

        await db.commit()
        result["cold_start_mode_after_reset"] = monitor.last_check_at is None
    else:
        # In dry run, we report what WOULD happen
        result["cold_start_mode_after_reset"] = reset_last_checked or monitor.last_check_at is None

    return result
