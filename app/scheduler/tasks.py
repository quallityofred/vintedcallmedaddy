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
from app.models import FoundItem, HiddenSeller, Monitor
from app.scraper.client import VintedClient
from app.scraper.parser import VintedItem
from app.telegram.notifications import send_item_notification

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_INTERVAL_SECONDS = 600
NIGHT_MULTIPLIER = 3
NIGHT_START_HOUR = 2
NIGHT_END_HOUR = 6
EMPTY_THRESHOLD = 10
INTERVAL_MULTIPLIER = 1.5

_telegram_bot: Bot | None = None


def set_telegram_bot(bot: Bot) -> None:
    global _telegram_bot
    _telegram_bot = bot


def _is_night_time() -> bool:
    hour = datetime.now(timezone.utc).hour
    return NIGHT_START_HOUR <= hour < NIGHT_END_HOUR


def _get_effective_interval(base_interval: int) -> int:
    if _is_night_time():
        return base_interval * NIGHT_MULTIPLIER
    return base_interval


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
    is_cold_start = monitor.last_check_at is None

    async with AsyncSessionLocal() as db:
        monitor = await db.merge(monitor)
        for item in items:
            if item.seller_id in hidden_seller_ids:
                continue

            exists_result = await db.execute(
                select(FoundItem.id).where(
                    FoundItem.vinted_item_id == item.id,
                    FoundItem.domain == item.domain,
                )
            )
            if exists_result.scalar_one_or_none() is not None:
                continue

            found_item = FoundItem(
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
                notified=False,
            )
            db.add(found_item)
            new_items.append(item)

        if new_items:
            monitor.items_found_count += len(new_items)
            monitor.consecutive_empty = 0
            monitor.interval_sec = _resolve_original_interval(monitor)
        else:
            monitor.consecutive_empty += 1
            if monitor.consecutive_empty >= EMPTY_THRESHOLD:
                new_interval = int(monitor.interval_sec * INTERVAL_MULTIPLIER)
                monitor.interval_sec = min(new_interval, MAX_INTERVAL_SECONDS)

        monitor.last_check_at = datetime.now(timezone.utc)
        await db.commit()

    for item in new_items:
        if not is_cold_start and _telegram_bot:
            await send_item_notification(
                _telegram_bot,
                settings.telegram_chat_id,
                item,
            )

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(FoundItem).where(
                    FoundItem.vinted_item_id == item.id,
                    FoundItem.domain == item.domain,
                )
            )
            fi = result.scalar_one_or_none()
            if fi:
                fi.notified = not is_cold_start
                await db.commit()

    if new_items:
        logger.info(
            "Monitor %s found %d new items",
            monitor.name,
            len(new_items),
        )


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
            stagger = random.uniform(5.0, 30.0)
            job = self.scheduler.add_job(
                check_monitor,
                trigger=IntervalTrigger(seconds=monitor.interval_sec),
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
        stagger = random.uniform(5.0, 30.0)
        job = self.scheduler.add_job(
            check_monitor,
            trigger=IntervalTrigger(seconds=interval_sec),
            args=[monitor_id, self.client],
            id=job_id,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=stagger),
            misfire_grace_time=300,
        )
        if job:
            self.job_ids[monitor_id] = job.id
        logger.info("Added monitor_id=%d to scheduler", monitor_id)

    def remove_monitor(self, monitor_id: int) -> None:
        job_id = self.job_ids.pop(monitor_id, None)
        if job_id:
            self.scheduler.remove_job(job_id)
            logger.info("Removed monitor_id=%d from scheduler", monitor_id)

    def update_monitor(self, monitor_id: int, interval_sec: int) -> None:
        self.remove_monitor(monitor_id)
        self.add_monitor(monitor_id, interval_sec)
        logger.info("Updated monitor_id=%d interval=%d", monitor_id, interval_sec)
