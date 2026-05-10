import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import FoundItem, HiddenSeller, Monitor, SeenItem, User
from app.scraper.client import VintedClient
from app.scraper.parser import VintedItem
from app.telegram.notifications import send_item_notification

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_INTERVAL_SECONDS = 900
EMPTY_THRESHOLD_FAST = 5
EMPTY_THRESHOLD_SLOW = 15
INTERVAL_STEP_UP = 1.3
INTERVAL_STEP_DOWN_FAST = 0.7

_telegram_bot: Bot | None = None


def set_telegram_bot(bot: Bot) -> None:
    global _telegram_bot
    _telegram_bot = bot


def _is_peak_time() -> bool:
    hour = datetime.now(timezone.utc).hour
    return settings.peak_start_hour <= hour < settings.peak_end_hour


def _get_effective_interval(base_interval: int) -> int:
    if _is_peak_time():
        return base_interval
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < settings.peak_start_hour:
        return int(base_interval * settings.night_interval_multiplier)
    return int(base_interval * settings.offpeak_interval_multiplier)


def _get_time_window_multiplier() -> float:
    if _is_peak_time():
        return 1.0
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < settings.peak_start_hour:
        return settings.night_interval_multiplier
    return settings.offpeak_interval_multiplier


def _normalize_adaptive_interval(monitor: Monitor) -> int:
    original_interval = _resolve_original_interval(monitor)
    return max(min(monitor.interval_sec, MAX_INTERVAL_SECONDS), original_interval)


def _reset_interval_if_scaled_from_time_window(monitor: Monitor) -> int:
    original_interval = _resolve_original_interval(monitor)
    if monitor.interval_sec <= original_interval:
        return original_interval
    night_scaled = int(original_interval * settings.night_interval_multiplier)
    offpeak_scaled = int(original_interval * settings.offpeak_interval_multiplier)
    if monitor.interval_sec in {night_scaled, offpeak_scaled}:
        return original_interval
    return _normalize_adaptive_interval(monitor)


async def _update_monitor_interval(db: AsyncSessionLocal, monitor: Monitor, found_new: bool, count: int = 0) -> None:
    original_interval = _resolve_original_interval(monitor)
    monitor.interval_sec = _reset_interval_if_scaled_from_time_window(monitor)
    
    if found_new:
        monitor.items_found_count += count
        monitor.consecutive_empty = 0
        new_interval = max(
            int(monitor.interval_sec * INTERVAL_STEP_DOWN_FAST),
            original_interval,
        )
        monitor.interval_sec = new_interval
    else:
        monitor.consecutive_empty += 1
        threshold = EMPTY_THRESHOLD_FAST if _is_peak_time() else EMPTY_THRESHOLD_SLOW
        if monitor.consecutive_empty >= threshold:
            new_interval = int(monitor.interval_sec * INTERVAL_STEP_UP)
            monitor.interval_sec = min(new_interval, MAX_INTERVAL_SECONDS)


async def check_monitor(monitor_id: int, client: VintedClient) -> None:
    # 1. Fetch monitor and hidden sellers, then release connection
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
        monitor = result.scalar_one_or_none()
        if monitor is None or not monitor.is_active:
            return

        params: dict = json.loads(monitor.params_json)
        domains: list[str] = json.loads(monitor.domains_json)

        hidden_result = await db.execute(select(HiddenSeller.seller_id))
        hidden_seller_ids: set[int] = {row[0] for row in hidden_result.fetchall()}
        
        # Capture monitor state needed for scraping
        is_cold_start = monitor.last_check_at is None or monitor.items_found_count == 0

    # 2. Perform search (OUTSIDE DB session)
    try:
        items = await client.search_all_domains(params, domains)
    except Exception:
        logger.exception("search_all_domains failed for monitor_id=%d", monitor_id)
        items = []

    # 3. Save results in a new session
    new_items_to_notify: list[VintedItem] = []
    async with AsyncSessionLocal() as db:
        # Re-fetch or merge monitor to the new session
        result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
        monitor = result.scalar_one_or_none()
        if monitor is None or not monitor.is_active:
            return

        if not items:
            await _update_monitor_interval(db, monitor, False)
            await db.commit()
            return

        filtered_items = [i for i in items if i.seller_id not in hidden_seller_ids]
        
        for item in filtered_items:
            # Atomic upsert for SeenItem
            stmt = pg_insert(SeenItem).values(
                vinted_item_id=item.id, 
                domain=item.domain,
                seen_at=datetime.now(timezone.utc)
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=['vinted_item_id', 'domain'])
            res = await db.execute(stmt)
            
            if res.rowcount == 0:
                continue

            # If cold start, we mark as notified=True to SILENCE
            # If normal run, we mark as notified=False to QUEUE for sending
            notified_status = True if is_cold_start else False
            
            found_stmt = pg_insert(FoundItem).values(
                monitor_id=monitor_id,
                vinted_item_id=item.id,
                domain=item.domain,
                title=item.title,
                price=item.price,
                currency=item.currency,
                brand=item.brand,
                size=item.size,
                condition=item.condition,
                photo_url=item.photo_url,
                item_url=item.item_url,
                seller_id=item.seller_id,
                found_at=datetime.now(timezone.utc),
                notified=notified_status,
            )
            found_stmt = found_stmt.on_conflict_do_nothing(index_elements=['vinted_item_id', 'domain'])
            found_res = await db.execute(found_stmt)
            
            if found_res.rowcount > 0 and not notified_status:
                new_items_to_notify.append(item)

        await _update_monitor_interval(db, monitor, (len(new_items_to_notify) > 0 or not is_cold_start), count=len(new_items_to_notify))
        monitor.last_check_at = datetime.now(timezone.utc)
        await db.commit()

    # 4. Process Pending Notifications (including any backlog)
    await process_pending_notifications()


async def process_pending_notifications() -> None:
    """Finds all FoundItems with notified=False and attempts to send them."""
    async with AsyncSessionLocal() as db:
        # Get items that haven't been notified yet, oldest first
        result = await db.execute(
            select(FoundItem)
            .where(FoundItem.notified == False)
            .order_by(FoundItem.found_at.asc())
            .limit(50) # Process in batches to avoid new flood
        )
        pending_items = result.scalars().all()
        
        if not pending_items:
            return

        logger.info("Processing %d pending notifications", len(pending_items))
        
        # Group by monitor to reuse bot/chat_id
        for fi in pending_items:
            # We need VintedItem object for the notification function
            item = VintedItem(
                id=fi.vinted_item_id,
                title=fi.title,
                price=fi.price,
                currency=fi.currency,
                brand=fi.brand,
                size=fi.size,
                condition=fi.condition,
                photo_url=fi.photo_url,
                item_url=fi.item_url,
                domain=fi.domain,
                seller_id=fi.seller_id
            )
            
            success = await _send_single_notification(fi.monitor_id, item)
            if success:
                fi.notified = True
                await db.commit() # Commit each one to avoid re-sending on crash
            else:
                # If failed (e.g. Flood limit), stop processing the rest of the batch
                logger.warning("Stopping notification batch processing due to failure/limit")
                break


async def _send_single_notification(monitor_id: int, item: VintedItem) -> bool:
    """Sends a single notification and returns True if successful."""
    bot_to_use = _telegram_bot
    chat_id_to_use = settings.telegram_chat_id
    
    async with AsyncSessionLocal() as db:
        monitor = await db.get(Monitor, monitor_id)
        if not monitor: return True # Monitor deleted, skip
            
        if monitor.user_id:
            user = await db.get(User, monitor.user_id)
            if user and user.telegram_bot_token and user.telegram_chat_id:
                from app.telegram.bot import get_or_create_bot as _get_bot
                bot_to_use, _ = _get_bot(user.telegram_bot_token)
                chat_id_to_use = int(user.telegram_chat_id)

    if not bot_to_use or not chat_id_to_use:
        return True # Can't notify, mark as done to avoid stuck queue

    try:
        from app.telegram.notifications import send_item_notification
        await send_item_notification(bot_to_use, chat_id_to_use, item)
        return True
    except Exception:
        # If it's a TelegramRetryAfter, the send_item_notification already waited,
        # but if we are still hitting limits, we return False to pause the queue.
        return False


def _resolve_original_interval(monitor: Monitor) -> int:
    try:
        params: dict = json.loads(monitor.params_json)
        return params.get("_original_interval", monitor.interval_sec)
    except (json.JSONDecodeError, TypeError):
        return monitor.interval_sec


class MonitorScheduler:
    def __init__(self, client: VintedClient) -> None:
        self.client = client
        self.scheduler = AsyncIOScheduler()
        self.job_ids: dict[int, str] = {}

    async def start(self) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Monitor).where(Monitor.is_active == True)
            )
            monitors = result.scalars().all()

        for monitor in monitors:
            normalized = _normalize_adaptive_interval(monitor)
            effective = _get_effective_interval(normalized)
            stagger = random.uniform(5.0, 30.0)
            job = self.scheduler.add_job(
                check_monitor,
                trigger=IntervalTrigger(seconds=effective),
                args=[monitor.id, self.client],
                id=f"monitor_{monitor.id}",
                next_run_time=datetime.now(timezone.utc) + timedelta(seconds=stagger),
                misfire_grace_time=300,
            )
            if job:
                self.job_ids[monitor.id] = job.id

        self.scheduler.start()
        logger.info("Scheduler started with %d monitors", len(monitors))

    async def stop(self) -> None:
        self.scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")

    def add_monitor(self, monitor_id: int, interval_sec: int) -> None:
        job_id = f"monitor_{monitor_id}"
        if job_id in {j.id for j in self.scheduler.get_jobs()}:
            return
        effective = _get_effective_interval(interval_sec)
        stagger = random.uniform(5.0, 30.0)
        job = self.scheduler.add_job(
            check_monitor,
            trigger=IntervalTrigger(seconds=effective),
            args=[monitor_id, self.client],
            id=job_id,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=stagger),
            misfire_grace_time=300,
        )
        if job:
            self.job_ids[monitor_id] = job.id
        logger.info("Added monitor_id=%d interval=%d (effective=%d)", monitor_id, interval_sec, effective)

    def remove_monitor(self, monitor_id: int) -> None:
        job_id = self.job_ids.pop(monitor_id, None)
        if job_id:
            self.scheduler.remove_job(job_id)
            logger.info("Removed monitor_id=%d from scheduler", monitor_id)

    def update_monitor(self, monitor_id: int, interval_sec: int) -> None:
        self.remove_monitor(monitor_id)
        self.add_monitor(monitor_id, interval_sec)
        logger.info("Updated monitor_id=%d interval=%d", monitor_id, interval_sec)
