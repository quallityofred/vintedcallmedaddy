from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import FoundItem, Monitor
from app.scheduler.dry_run import perform_monitor_baseline_seen
from app.scheduler.tasks import check_monitor, process_pending_notifications
from app.scraper.client import VintedClient, TokenBucketLimiter
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

async def cleanup_pending_no_notify_for_monitor(
    monitor_id: int,
    limit: int = 1000,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Mark pending notifications for a monitor as notified without sending them."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        conditions = [
            FoundItem.notified == False,  # noqa: E712
            FoundItem.monitor_id == monitor_id,
        ]
        pending_before = int(
            await db.scalar(select(func.count(FoundItem.id)).where(*conditions)) or 0
        )
        
        if pending_before == 0:
            return {
                "pending_before": 0,
                "selected_for_ack": 0,
                "marked_notified_count": 0,
                "pending_after": 0,
            }

        stmt = (
            select(FoundItem.id)
            .where(*conditions)
            .order_by(FoundItem.found_at.asc(), FoundItem.id.asc())
            .limit(limit)
        )
        item_ids = (await db.execute(stmt)).scalars().all()
        selected_count = len(item_ids)

        if not dry_run and selected_count > 0:
            update_stmt = (
                update(FoundItem)
                .where(FoundItem.id.in_(item_ids))
                .values(notified=True)
            )
            await db.execute(update_stmt)
            await db.commit()
            
            pending_after = int(
                await db.scalar(select(func.count(FoundItem.id)).where(*conditions)) or 0
            )
        else:
            pending_after = pending_before - selected_count if not dry_run else pending_before

        return {
            "pending_before": pending_before,
            "selected_for_ack": selected_count,
            "marked_notified_count": selected_count if not dry_run else 0,
            "pending_after": pending_after,
        }

async def baseline_seen_no_notify_for_monitor(
    monitor_id: int,
    max_items_per_domain: int = 96,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Wrapper for baseline SeenItem creation."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        monitor = await db.get(Monitor, monitor_id)
        if not monitor:
            raise ValueError(f"Monitor {monitor_id} not found")
        
        rate_limiter = TokenBucketLimiter(rate=float(settings.rate_limit_per_minute), per=60.0)
        async with VintedClient(rate_limiter=rate_limiter) as client:
            res = await perform_monitor_baseline_seen(
                monitor,
                client,
                db,
                max_domains=8,
                max_items_per_domain=max_items_per_domain,
                dry_run=dry_run,
            )
            return res

async def send_all_pending_for_monitor(
    monitor_id: int,
    batch_limit: int = 20,
    max_batches: int = 5,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Send all pending notifications for a monitor in sequential batches."""
    total_sent_photo = 0
    total_sent_text = 0
    total_failed = 0
    total_marked_notified = 0
    batches_run = 0
    
    # Get initial pending count
    session_factory = get_session_factory()
    async with session_factory() as db:
        pending_before = int(
            await db.scalar(
                select(func.count(FoundItem.id)).where(
                    FoundItem.monitor_id == monitor_id,
                    FoundItem.notified == False,  # noqa: E712
                )
            ) or 0
        )

    if pending_before == 0:
        return {
            "pending_before": 0,
            "batches_run": 0,
            "total_sent_photo": 0,
            "total_sent_text": 0,
            "total_failed": 0,
            "total_marked_notified": 0,
            "pending_after": 0,
        }

    for _ in range(max_batches):
        res = await process_pending_notifications(
            limit=batch_limit,
            monitor_id=monitor_id,
            dry_run=dry_run,
        )
        
        batches_run += 1
        total_sent_photo += res.get("sent_photo_count", 0)
        total_sent_text += res.get("sent_text_count", 0) + res.get("fallback_text_count", 0)
        total_failed += res.get("failed_count", 0)
        total_marked_notified += res.get("marked_notified_count", 0)
        
        # If we didn't process a full batch or no more pending, stop
        if res.get("selected_for_processing", 0) < batch_limit:
            break
            
        # Optional: small delay between batches if not dry run
        if not dry_run:
            await asyncio.sleep(1)

    async with session_factory() as db:
        pending_after = int(
            await db.scalar(
                select(func.count(FoundItem.id)).where(
                    FoundItem.monitor_id == monitor_id,
                    FoundItem.notified == False,  # noqa: E712
                )
            ) or 0
        )

    return {
        "pending_before": pending_before,
        "batches_run": batches_run,
        "total_sent_photo": total_sent_photo,
        "total_sent_text": total_sent_text,
        "total_failed": total_failed,
        "total_marked_notified": total_marked_notified,
        "pending_after": pending_after,
    }

async def run_monitor_full_cycle_job(
    monitor_id: int,
    dry_run: bool = True,
    cleanup_existing_pending: bool = False,
    cold_baseline: bool = False,
    run_check: bool = True,
    send_pending: bool = False,
    pause_before: bool = True,
    pause_after: bool = True,
    max_items_per_domain: int = 96,
    notification_batch_limit: int = 20,
    max_notification_batches: int = 5,
) -> Dict[str, Any]:
    """Orchestrate a full monitor cycle."""
    started_at = datetime.now(timezone.utc)
    side_effects = []
    
    session_factory = get_session_factory()
    async with session_factory() as db:
        monitor = await db.get(Monitor, monitor_id)
        if not monitor:
            raise ValueError(f"Monitor {monitor_id} not found")
        
        monitor_name = monitor.name
        is_active_initial = monitor.is_active
        
        if pause_before and monitor.is_active and not dry_run:
            monitor.is_active = False
            await db.commit()
            side_effects.append("paused_before")

    results = {}

    if cleanup_existing_pending:
        res = await cleanup_pending_no_notify_for_monitor(
            monitor_id, limit=2000, dry_run=dry_run
        )
        results["cleanup"] = res
        side_effects.append("cleaned_pending")

    if cold_baseline:
        res = await baseline_seen_no_notify_for_monitor(
            monitor_id, max_items_per_domain=max_items_per_domain, dry_run=dry_run
        )
        results["baseline"] = res
        side_effects.append("created_baseline")

    if run_check:
        # check_monitor handles its own sessions and locking
        # Note: check_monitor will launch its own process_pending_notifications task
        # if it finds new items. We might want to wait or manage this.
        # For full-cycle, we'll run it and then potentially run our own send_pending loop.
        if not dry_run:
             await check_monitor(monitor_id)
             side_effects.append("ran_check")
        else:
             from app.scheduler.dry_run import perform_monitor_full_cycle_dry_run
             async with session_factory() as db:
                 monitor = await db.get(Monitor, monitor_id)
                 rate_limiter = TokenBucketLimiter(rate=float(settings.rate_limit_per_minute), per=60.0)
                 async with VintedClient(rate_limiter=rate_limiter) as client:
                     res = await perform_monitor_full_cycle_dry_run(
                         monitor, client, db, 
                         max_domains=8, 
                         max_items_per_domain=max_items_per_domain
                     )
                     import dataclasses
                     results["check_dry_run"] = dataclasses.asdict(res)
             side_effects.append("simulated_check")

    if send_pending:
        res = await send_all_pending_for_monitor(
            monitor_id,
            batch_limit=notification_batch_limit,
            max_batches=max_notification_batches,
            dry_run=dry_run,
        )
        results["notifications"] = res
        side_effects.append("sent_notifications")

    if not dry_run:
        async with session_factory() as db:
            monitor = await db.get(Monitor, monitor_id)
            if pause_after:
                monitor.is_active = False
                side_effects.append("paused_after")
            else:
                monitor.is_active = True
                side_effects.append("resumed_after")
            await db.commit()

    completed_at = datetime.now(timezone.utc)
    return {
        "monitor_id": monitor_id,
        "monitor_name": monitor_name,
        "dry_run": dry_run,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "side_effects": side_effects,
        "results": results,
    }
