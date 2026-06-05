
# Copied implementation from app/scheduler/app_scheduler_tasks.py
import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session_factory
from app.models import FoundItem, HiddenSeller, Monitor, MonitorTelegramTopic, SeenItem, User
from app.scraper.client import VintedClient
from app.scraper.monitor_filters import extract_monitor_filters, has_restrictive_filters, item_matches_monitor_filters
from app.scraper.parser import VintedItem
from app.scraper.url_parser import parse_vinted_url
from app.telegram.notifications import send_item_notification
from app.telegram.topic_service import ensure_monitor_topic, record_topic_send_failure

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_INTERVAL_SECONDS = 900
EMPTY_THRESHOLD_FAST = 5
EMPTY_THRESHOLD_SLOW = 15
INTERVAL_STEP_UP = 1.3
INTERVAL_STEP_DOWN_FAST = 0.7

_telegram_bot: Bot | None = None
_notification_lock = asyncio.Lock()
_running_checks: set[int] = set()
_running_checks_lock = asyncio.Lock()
_global_check_semaphore = asyncio.Semaphore(settings.monitor_check_global_concurrency)
_user_check_semaphores: dict[int, asyncio.Semaphore] = {}
_backpressure_stats = {
    "already_running_skips": 0,
    "capacity_timeouts": 0,
}
AsyncSessionLocal = None


def _new_session() -> AsyncSession:
	session_factory = AsyncSessionLocal or get_session_factory()
	return session_factory()


@dataclass
class TelegramDeliveryTarget:
	ok: bool
	code: str
	message: str
	bot: Bot | None = None
	chat_id: int | None = None
	message_thread_id: int | None = None
	topic_id: int | None = None
	used_fallback: bool = False


@dataclass
class MonitorCheckContext:
	monitor_id: int
	user_id: int
	monitor_name: str
	params: dict
	domains: list[str]
	monitor_filters: object
	hidden_seller_ids: set[int]
	is_cold_start: bool
	original_interval: int
	cf_worker_url: str
	cf_worker_mode: str
	cf_worker_block_threshold: int
	cf_worker_recovery_minutes: int


@dataclass
class CheckCapacityLease:
	user_id: int
	global_acquired: bool = False
	user_acquired: bool = False

	def release(self) -> None:
		if self.user_acquired:
			_user_check_semaphore(self.user_id).release()
			self.user_acquired = False
		if self.global_acquired:
			_global_check_semaphore.release()
			self.global_acquired = False


def _user_check_semaphore(user_id: int) -> asyncio.Semaphore:
	limit = max(1, settings.monitor_check_per_user_concurrency)
	semaphore = _user_check_semaphores.get(user_id)
	if semaphore is None:
		semaphore = asyncio.Semaphore(limit)
		_user_check_semaphores[user_id] = semaphore
	return semaphore


def reset_backpressure_state_for_tests() -> None:
	_running_checks.clear()
	_user_check_semaphores.clear()
	_backpressure_stats["already_running_skips"] = 0
	_backpressure_stats["capacity_timeouts"] = 0
	global _global_check_semaphore
	_global_check_semaphore = asyncio.Semaphore(max(1, settings.monitor_check_global_concurrency))


def is_monitor_check_running(monitor_id: int) -> bool:
	return monitor_id in _running_checks


def is_monitor_check_capacity_saturated(user_id: int) -> bool:
	global_available = getattr(_global_check_semaphore, "_value", 1) > 0
	user_semaphore = _user_check_semaphores.get(user_id)
	user_available = user_semaphore is None or getattr(user_semaphore, "_value", 1) > 0
	return not (global_available and user_available)


def get_backpressure_state() -> dict[str, int | float]:
	user_active = 0
	for semaphore in _user_check_semaphores.values():
		user_active += max(0, settings.monitor_check_per_user_concurrency - getattr(semaphore, "_value", 0))
	return {
		"monitor_check_global_concurrency": settings.monitor_check_global_concurrency,
		"monitor_check_per_user_concurrency": settings.monitor_check_per_user_concurrency,
		"monitor_check_acquire_timeout_seconds": settings.monitor_check_acquire_timeout_seconds,
		"running_monitor_checks": len(_running_checks),
		"monitor_check_global_active": max(
			0,
			settings.monitor_check_global_concurrency - getattr(_global_check_semaphore, "_value", 0),
		),
		"monitor_check_user_active": user_active,
		"monitor_check_already_running_skips": _backpressure_stats["already_running_skips"],
		"monitor_check_capacity_timeouts": _backpressure_stats["capacity_timeouts"],
	}


async def resolve_telegram_delivery_target(
	db: AsyncSession,
	*,
	user: User,
	monitor: Monitor,
) -> TelegramDeliveryTarget:
	if not user.is_telegram_enabled:
		return TelegramDeliveryTarget(
			ok=False,
			code="telegram_disabled",
			message="Telegram notifications are disabled for this user.",
		)
	if not user.telegram_bot_token:
		return TelegramDeliveryTarget(
			ok=False,
			code="telegram_token_missing",
			message="Telegram bot token is not configured.",
		)

	from app.telegram.bot import get_or_create_bot

	bot_to_use, _ = get_or_create_bot(user.telegram_bot_token)

	if not user.telegram_topics_enabled:
		if not user.telegram_chat_id:
			return TelegramDeliveryTarget(
				ok=False,
				code="telegram_chat_missing",
				message="Telegram chat ID is not configured.",
			)
		return TelegramDeliveryTarget(
			ok=True,
			code="main_chat",
			message="Using main Telegram chat.",
			bot=bot_to_use,
			chat_id=int(user.telegram_chat_id),
		)

	if not user.telegram_topics_chat_id:
		logger.warning(
			"Telegram topic notification skipped: code=telegram_topics_chat_missing monitor_id=%s",
			monitor.id,
		)
		return TelegramDeliveryTarget(
			ok=False,
			code="telegram_topics_chat_missing",
			message="Telegram topic group chat ID is not configured.",
		)

	topic_result = await ensure_monitor_topic(db, bot=bot_to_use, user=user, monitor=monitor)
	if topic_result.ok and topic_result.topic and topic_result.topic.message_thread_id:
		return TelegramDeliveryTarget(
			ok=True,
			code="topic",
			message="Using Telegram monitor topic.",
			bot=bot_to_use,
			chat_id=int(topic_result.topic.chat_id),
			message_thread_id=topic_result.topic.message_thread_id,
			topic_id=topic_result.topic.id,
		)

	if user.telegram_topics_fallback_to_main_chat and user.telegram_chat_id:
		logger.warning(
			"Telegram topic notification fallback used: code=%s monitor_id=%s",
			topic_result.code,
			monitor.id,
		)
		return TelegramDeliveryTarget(
			ok=True,
			code="main_chat_fallback",
			message="Using main Telegram chat after topic routing failed.",
			bot=bot_to_use,
			chat_id=int(user.telegram_chat_id),
			used_fallback=True,
		)

	logger.warning(
		"Telegram topic notification skipped: code=%s status=%s monitor_id=%s",
		topic_result.code,
		topic_result.status,
		monitor.id,
	)
	return TelegramDeliveryTarget(
		ok=False,
		code=topic_result.code,
		message=topic_result.message,
		topic_id=topic_result.topic.id if topic_result.topic else None,
	)


def set_telegram_bot(bot: Bot) -> None:
	"""Set the global fallback Telegram bot for notifications."""
	global _telegram_bot
	_telegram_bot = bot


def _is_peak_time() -> bool:
	"""Return True if current UTC hour is within configured peak hours."""
	hour = datetime.now(timezone.utc).hour
	return settings.peak_start_hour <= hour < settings.peak_end_hour


def _get_effective_interval(base_interval: int) -> int:
	"""Calculate adaptive check interval based on time of day."""
	if _is_peak_time():
		return base_interval
	hour = datetime.now(timezone.utc).hour
	if 0 <= hour < settings.peak_start_hour:
		return int(base_interval * settings.night_interval_multiplier)
	return int(base_interval * settings.offpeak_interval_multiplier)


def _resolve_original_interval(monitor: Monitor) -> int:
	"""Retrieve the original interval stored in monitor params."""
	try:
		params: dict = json.loads(monitor.params_json)
		return params.get("_original_interval", monitor.interval_sec)
	except (json.JSONDecodeError, TypeError):
		return monitor.interval_sec


async def _update_monitor_interval(
	db,
	monitor: Monitor,
	found_new: bool,
	count: int = 0,
	original_interval: int | None = None,
) -> None:
	"""Adaptively adjust the monitor's polling interval."""
	if original_interval is None:
		original_interval = _resolve_original_interval(monitor)

	monitor.interval_sec = max(monitor.interval_sec, original_interval)

	if found_new:
		monitor.items_found_count += count
		monitor.consecutive_empty = 0
		new_interval = max(int(monitor.interval_sec * 0.7), original_interval)
		monitor.interval_sec = new_interval
	else:
		monitor.consecutive_empty += 1
		threshold = EMPTY_THRESHOLD_FAST if _is_peak_time() else EMPTY_THRESHOLD_SLOW
		if monitor.consecutive_empty >= threshold:
			new_interval = int(monitor.interval_sec * 1.3)
			monitor.interval_sec = min(new_interval, MAX_INTERVAL_SECONDS)


async def _has_seen_item(db, user_id: int, item_id: int) -> bool:
	result = await db.execute(
		select(SeenItem.id)
		.where(SeenItem.user_id == user_id, SeenItem.vinted_item_id == item_id)
		.limit(1)
	)
	return result.scalar_one_or_none() is not None


async def _try_start_monitor_check(monitor_id: int) -> bool:
	async with _running_checks_lock:
		if monitor_id in _running_checks:
			_backpressure_stats["already_running_skips"] += 1
			logger.info("check_skipped_already_running monitor_id=%s", monitor_id)
			return False
		_running_checks.add(monitor_id)
		return True


async def _finish_monitor_check(monitor_id: int) -> None:
	async with _running_checks_lock:
		_running_checks.discard(monitor_id)


async def _acquire_check_capacity(monitor_id: int, user_id: int) -> CheckCapacityLease | None:
	timeout = settings.monitor_check_acquire_timeout_seconds
	lease = CheckCapacityLease(user_id=user_id)
	user_semaphore = _user_check_semaphore(user_id)
	try:
		logger.debug("check_waiting_for_capacity monitor_id=%s user_id=%s", monitor_id, user_id)
		await asyncio.wait_for(user_semaphore.acquire(), timeout=timeout)
		lease.user_acquired = True
		await asyncio.wait_for(_global_check_semaphore.acquire(), timeout=timeout)
		lease.global_acquired = True
		return lease
	except asyncio.TimeoutError:
		lease.release()
		_backpressure_stats["capacity_timeouts"] += 1
		logger.info("check_skipped_capacity_timeout monitor_id=%s user_id=%s", monitor_id, user_id)
		return None


async def _load_monitor_check_context(monitor_id: int) -> MonitorCheckContext | None:
	async with _new_session() as db:
		result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
		monitor = result.scalar_one_or_none()
		if monitor is None or not monitor.is_active:
			return None
		if monitor.user_id is None:
			logger.warning("Skipping monitor with missing user_id", extra={"monitor_id": monitor.id})
			return None

		user = await db.get(User, monitor.user_id)
		if user is None:
			logger.warning("Skipping monitor with missing user", extra={"monitor_id": monitor.id})
			return None

		params = json.loads(monitor.params_json)
		monitor_filters = extract_monitor_filters(params)
		if not has_restrictive_filters(monitor_filters):
			url_params = parse_vinted_url(monitor.original_url)
			url_filters = extract_monitor_filters(url_params)
			if has_restrictive_filters(url_filters):
				url_params["_original_interval"] = params.get("_original_interval", monitor.interval_sec)
				params = url_params
				monitor_filters = url_filters
				logger.warning(
					"Using monitor URL-derived filters because stored params are not restrictive: monitor_id=%s",
					monitor.id,
				)
			elif "vinted." in monitor.original_url.lower():
				monitor.last_check_status = "failed"
				monitor.last_error = "Monitor URL has no searchable filters; refusing unfiltered marketplace check."
				monitor.last_check_completed_at = datetime.now(timezone.utc)
				await db.commit()
				logger.warning("Skipping unfiltered Vinted monitor: monitor_id=%s", monitor.id)
				return None
		domains = json.loads(monitor.domains_json)
		hidden_result = await db.execute(
			select(HiddenSeller.seller_id).where(HiddenSeller.user_id == monitor.user_id)
		)
		hidden_seller_ids = {row[0] for row in hidden_result.fetchall()}

		return MonitorCheckContext(
			monitor_id=monitor.id,
			user_id=monitor.user_id,
			monitor_name=monitor.name,
			params=params,
			domains=domains,
			monitor_filters=monitor_filters,
			hidden_seller_ids=hidden_seller_ids,
			is_cold_start=monitor.last_check_at is None,
			original_interval=params.get("_original_interval", monitor.interval_sec),
			cf_worker_url=user.cf_worker_url,
			cf_worker_mode=user.cf_worker_mode,
			cf_worker_block_threshold=user.cf_worker_block_threshold,
			cf_worker_recovery_minutes=user.cf_worker_recovery_minutes,
		)


async def _mark_monitor_check_running(monitor_id: int) -> None:
	async with _new_session() as db:
		result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
		monitor = result.scalar_one_or_none()
		if monitor is None or not monitor.is_active:
			return
		monitor.last_check_started_at = datetime.now(timezone.utc)
		monitor.last_check_status = "running"
		monitor.last_error = None
		await db.commit()


async def check_monitor(monitor_id: int, scraper_client: VintedClient | None = None) -> None:
    """Main task: check a single monitor for new Vinted listings."""
    started = time.monotonic()
    if not await _try_start_monitor_check(monitor_id):
        return

    lease: CheckCapacityLease | None = None
    try:
        context = await _load_monitor_check_context(monitor_id)
        if context is None:
            return

        lease = await _acquire_check_capacity(monitor_id, context.user_id)
        if lease is None:
            return

        await _mark_monitor_check_running(monitor_id)
        logger.info("check_started monitor_id=%s user_id=%s", monitor_id, context.user_id)
        try:
            owns_client = scraper_client is None
            client = scraper_client

            if client is None:
                from app.scraper.client import VintedClient, CloudflareFallback
                from app.scraper.rate_limiter import TokenBucketLimiter

                cf_fallback = None
                if context.cf_worker_url:
                    cf_fallback = CloudflareFallback(
                        worker_url=context.cf_worker_url,
                        mode=context.cf_worker_mode,
                        block_threshold=context.cf_worker_block_threshold,
                        recovery_minutes=context.cf_worker_recovery_minutes,
                    )

                rate_limiter = TokenBucketLimiter(
                    rate=float(settings.rate_limit_per_minute),
                    per=60.0,
                )
                client = VintedClient(rate_limiter=rate_limiter, cf_fallback=cf_fallback)

            try:
                items = await client.search_all_domains(
                    context.params,
                    context.domains,
                    mode=context.cf_worker_mode,
                )
            finally:
                if owns_client:
                    await client.close()

            items = items or []
            raw_result_count = len(items)

            async with _new_session() as db:
                result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
                monitor = result.scalar_one_or_none()
                if monitor is None or not monitor.is_active:
                    return

                if not items:
                    await _update_monitor_interval(db, monitor, False, original_interval=context.original_interval)
                    monitor.last_check_status = "success_zero_items"
                else:
                    # Items are available here, now process them.
                    # Keep the first copy of a Vinted item ID across selected domains.
                    filtered_items: list[VintedItem] = []
                    seen_item_ids: set[int] = set()
                    skipped_by_filter_count = 0
                    missing_brand_id_count = 0
                    for item in items:
                        if item.seller_id in context.hidden_seller_ids or item.id in seen_item_ids:
                            continue
                        matches_filters, skip_reason = item_matches_monitor_filters(item, context.monitor_filters)
                        if not matches_filters:
                            skipped_by_filter_count += 1
                            if skip_reason == "missing_brand_id":
                                missing_brand_id_count += 1
                            continue
                        seen_item_ids.add(item.id)
                        filtered_items.append(item)

                    logger.info(
                        "Monitor check filtered results: monitor_id=%s monitor_name=%s filter_keys=%s "
                        "raw_result_count=%s accepted_count=%s skipped_by_filter_count=%s "
                        "missing_brand_id_count=%s cold_start=%s",
                        monitor.id,
                        monitor.name,
                        context.monitor_filters.filter_keys,
                        raw_result_count,
                        len(filtered_items),
                        skipped_by_filter_count,
                        missing_brand_id_count,
                        context.is_cold_start,
                    )

                    seen_items_to_insert = []
                    found_items_to_insert = []
                    new_items_to_notify: list[VintedItem] = []

                    now = datetime.now(timezone.utc)
                    for item in filtered_items:
                        already_seen = await _has_seen_item(db, context.user_id, item.id)
                        if already_seen:
                            continue

                        seen_items_to_insert.append({
                            "user_id": context.user_id,
                            "vinted_item_id": item.id,
                            "domain": item.domain,
                            "seen_at": now,
                        })

                        if context.is_cold_start:
                            continue

                        found_items_to_insert.append({
                            "monitor_id": monitor_id,
                            "vinted_item_id": item.id,
                            "domain": item.domain,
                            "title": item.title,
                            "price": item.price,
                            "currency": item.currency,
                            "brand": item.brand,
                            "size": item.size,
                            "condition": item.condition,
                            "photo_url": item.photo_url,
                            "item_url": item.item_url,
                            "seller_id": item.seller_id,
                            "found_at": now,
                            "notified": False,
                        })
                        new_items_to_notify.append(item)

                    if seen_items_to_insert:
                        stmt = pg_insert(SeenItem).values(seen_items_to_insert).on_conflict_do_nothing(index_elements=["user_id", "vinted_item_id", "domain"])
                        await db.execute(stmt)

                    if found_items_to_insert:
                        found_stmt = pg_insert(FoundItem).values(found_items_to_insert).on_conflict_do_nothing(index_elements=["monitor_id", "vinted_item_id", "domain"])
                        await db.execute(found_stmt)

                    await _update_monitor_interval(
                        db,
                        monitor,
                        len(new_items_to_notify) > 0 or not context.is_cold_start,
                        count=len(new_items_to_notify),
                        original_interval=context.original_interval,
                    )

                    if new_items_to_notify:
                        asyncio.create_task(process_pending_notifications())

                    monitor.last_check_status = "baseline_created" if context.is_cold_start else "success_new_items" if new_items_to_notify else "success_no_new_items"

                    monitor.last_check_at = datetime.now(timezone.utc)
                monitor.last_check_completed_at = datetime.now(timezone.utc)
                await db.commit()
        except Exception as e:
            logger.error(f"Error in check_monitor {monitor_id}: {e}")
            async with _new_session() as db:
                result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
                monitor = result.scalar_one_or_none()
                if monitor:
                    monitor.last_check_status = "failed"
                    monitor.last_error = str(e)[:255]
                    monitor.last_check_completed_at = datetime.now(timezone.utc)
                    await db.commit()
            raise
    finally:
        if lease is not None:
            lease.release()
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info("check_finished monitor_id=%s duration_ms=%s", monitor_id, duration_ms)
        await _finish_monitor_check(monitor_id)



async def process_pending_notifications() -> None:
	"""Send pending Telegram notifications for newly found items."""
	async with _notification_lock:
		async with _new_session() as db:
			query = (
				select(FoundItem)
				.where(FoundItem.notified == False)  # noqa: E712
				.order_by(FoundItem.found_at.asc())
				.limit(50)
			)

			if not settings.is_sqlite():
				query = query.with_for_update(skip_locked=True)

			result = await db.execute(query)
			pending_items = result.scalars().all()

			if not pending_items:
				return

			notified_ids = []
			for fi in pending_items:
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
					seller_id=fi.seller_id,
				)

				delivery_target: TelegramDeliveryTarget | None = None
				try:
					async with _new_session() as db2:
						monitor_name = None
						monitor = await db2.get(Monitor, fi.monitor_id)
						if monitor and monitor.user_id:
							monitor_name = monitor.name
							user = await db2.get(User, monitor.user_id)
							if user:
								delivery_target = await resolve_telegram_delivery_target(
									db2,
									user=user,
									monitor=monitor,
								)
								if not delivery_target.ok:
									continue
							else:
								# Skip if disabled or not configured
								continue

					if delivery_target and delivery_target.bot and delivery_target.chat_id is not None:
						await send_item_notification(
							delivery_target.bot,
							delivery_target.chat_id,
							item,
							monitor_name=monitor_name,
							message_thread_id=delivery_target.message_thread_id,
						)
						fi.notified = True
						notified_ids.append(fi.id)
				except Exception as exc:
					if delivery_target and delivery_target.topic_id is not None:
						try:
							async with _new_session() as db3:
								topic = await db3.get(MonitorTelegramTopic, delivery_target.topic_id)
								if topic is not None:
									info = await record_topic_send_failure(db3, topic=topic, exc=exc)
									logger.warning(
										"Telegram topic notification failed: code=%s monitor_id=%s item_id=%s",
										info.code,
										fi.monitor_id,
										fi.vinted_item_id,
									)
						except Exception:
							logger.exception(
								"Failed to record Telegram topic notification error for item %s",
								fi.vinted_item_id,
							)
					logger.exception("Notification failed for item %s", fi.vinted_item_id)
			
			if notified_ids:
				await db.commit()


class MonitorScheduler:
	"""APScheduler wrapper that manages per-monitor polling jobs."""

	def __init__(self) -> None:
		self.scheduler = AsyncIOScheduler()
		self.job_ids: dict[int, str] = {}

	async def start(self) -> None:
		"""Load active monitors from DB and start all their jobs."""
		async with _new_session() as db:
			result = await db.execute(select(Monitor).where(Monitor.is_active == True))  # noqa: E712
			monitors = result.scalars().all()

		for monitor in monitors:
			effective = _get_effective_interval(monitor.interval_sec)
			stagger = random.uniform(5.0, 30.0)
			job = self.scheduler.add_job(
				check_monitor,
				trigger=IntervalTrigger(seconds=effective),
				args=[monitor.id],
				id=f"monitor_{monitor.id}",
				next_run_time=datetime.now(timezone.utc) + timedelta(seconds=stagger),
			)
			if job:
				self.job_ids[monitor.id] = job.id

		self.scheduler.start()
		logger.info("Scheduler started with %d monitors", len(monitors))

	async def stop(self) -> None:
		"""Shutdown the scheduler gracefully."""
		self.scheduler.shutdown(wait=True)

	def add_monitor(self, monitor_id: int, interval_sec: int) -> None:
		"""Add a new job for a monitor."""
		effective = _get_effective_interval(interval_sec)
		job = self.scheduler.add_job(
			check_monitor,
			trigger=IntervalTrigger(seconds=effective),
			args=[monitor_id],
			id=f"monitor_{monitor_id}",
		)
		if job:
			self.job_ids[monitor_id] = job.id

	def remove_monitor(self, monitor_id: int) -> None:
		"""Remove an existing monitor job."""
		job_id = self.job_ids.pop(monitor_id, None)
		if job_id:
			try:
				self.scheduler.remove_job(job_id)
			except Exception:
				pass

	def update_monitor(self, monitor_id: int, interval_sec: int) -> None:
		"""Reschedule a monitor with a new interval."""
		self.remove_monitor(monitor_id)
		self.add_monitor(monitor_id, interval_sec)

	def trigger_now(self, monitor_id: int) -> bool:
		"""Manually trigger a monitor check immediately."""
		job_id = self.job_ids.get(monitor_id)
		if not job_id:
			return False
		try:
			job = self.scheduler.get_job(job_id)
			if job:
				job.modify(next_run_time=datetime.now(timezone.utc))
				return True
		except Exception:
			pass
		return False
