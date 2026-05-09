# app/scheduler/tasks.py
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import FoundItem, HiddenSeller, Monitor, User
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


from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

# ... (rest of imports)

async def check_monitor(monitor_id: int, client: VintedClient) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
        monitor = result.scalar_one_or_none()
        if monitor is None or not monitor.is_active:
            return

        params: dict = json.loads(monitor.params_json)
        domains: list[str] = json.loads(monitor.domains_json)

        hidden_result = await db.execute(select(HiddenSeller.seller_id))
        hidden_seller_ids: set[int] = {row[0] for row in hidden_result.fetchall()}

    try:
        items = await client.search_all_domains(params, domains)
    except Exception:
        logger.exception("search_all_domains failed for monitor_id=%d", monitor_id)
        items = []

    new_items: list[VintedItem] = []
    is_cold_start = monitor.last_check_at is None or monitor.items_found_count == 0

    try:
        async with AsyncSessionLocal() as db:
            from app.models import FoundItem, HiddenSeller, Monitor, User, SeenItem
            # ...
                        # Deduplication logic using SeenItem
                        filtered_items = [i for i in items if i.seller_id not in hidden_seller_ids]
                        if filtered_items:
                            all_item_ids = [i.id for i in filtered_items]
                            existing_result = await db.execute(
                                select(SeenItem.vinted_item_id).where(
                                    SeenItem.vinted_item_id.in_(all_item_ids)
                                )
                            )
                            existing_ids: set[int] = {row[0] for row in existing_result.fetchall()}
                        else:
                            existing_ids = set()

                        for item in filtered_items:
                            if item.id in existing_ids:
                                continue

                            # Add to SeenItem for persistent deduplication
                            db.add(SeenItem(vinted_item_id=item.id, domain=item.domain))

                            found_item = FoundItem(
                                # ... rest of FoundItem init ...
                            )
                            db.add(found_item)
                            new_items.append(item)

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
                    notified=False,
                )
                db.add(found_item)
                new_items.append(item)

            original_interval = _resolve_original_interval(monitor)
            monitor.interval_sec = _reset_interval_if_scaled_from_time_window(monitor)
            if new_items:
                monitor.items_found_count += len(new_items)
                monitor.consecutive_empty = 0
                new_interval = max(
                    int(monitor.interval_sec * INTERVAL_STEP_DOWN_FAST),
                    original_interval,
                )
                monitor.interval_sec = new_interval
            else:
                monitor.consecutive_empty += 1
                if _is_peak_time():
                    threshold = EMPTY_THRESHOLD_FAST
                else:
                    threshold = EMPTY_THRESHOLD_SLOW
                if monitor.consecutive_empty >= threshold:
                    new_interval = int(monitor.interval_sec * INTERVAL_STEP_UP)
                    monitor.interval_sec = min(new_interval, MAX_INTERVAL_SECONDS)

            monitor.last_check_at = datetime.now(timezone.utc)
            await db.commit()

        bot_to_use = _telegram_bot
        chat_id_to_use = settings.telegram_chat_id
        if monitor.user_id:
            async with AsyncSessionLocal() as db:
                user_result = await db.execute(
                    select(User).where(User.id == monitor.user_id)
                )
                owner = user_result.scalar_one_or_none()
                if owner and owner.telegram_bot_token and owner.telegram_chat_id:
                    from app.telegram.bot import get_or_create_bot as _get_bot
                    bot_to_use, _ = _get_bot(owner.telegram_bot_token)
                    chat_id_to_use = int(owner.telegram_chat_id)

        for item in new_items:
            if not is_cold_start and bot_to_use and chat_id_to_use:
                await send_item_notification(
                    bot_to_use,
                    chat_id_to_use,
                    item,
                )

        if new_items:
            new_item_ids = [item.id for item in new_items]
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(FoundItem).where(
                        FoundItem.vinted_item_id.in_(new_item_ids)
                    )
                )
                for fi in result.scalars().all():
                    fi.notified = not is_cold_start
                await db.commit()

            logger.info(
                "Monitor %s found %d new items (interval=%ds)",
                monitor.name,
                len(new_items),
                monitor.interval_sec,
            )
    except IntegrityError as e:
        logger.warning("IntegrityError for monitor_id=%d: %s. This item may have been processed concurrently.", monitor_id, e.orig)
    except Exception:
        logger.exception("Unexpected error in check_monitor for monitor_id=%d", monitor_id)


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
