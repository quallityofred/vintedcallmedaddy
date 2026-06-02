
# Copied implementation from app/scheduler/app_scheduler_tasks.py
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
_notification_lock = asyncio.Lock()


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


async def check_monitor(monitor_id: int, client: VintedClient) -> None:
	"""Main task: check a single monitor for new Vinted listings."""
	try:
		async with AsyncSessionLocal() as db:
			result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
			monitor = result.scalar_one_or_none()
			if monitor is None or not monitor.is_active:
				return

			params = json.loads(monitor.params_json)
			domains = json.loads(monitor.domains_json)
			user_id = monitor.user_id
			is_cold_start = monitor.last_check_at is None
			original_interval = params.get("_original_interval", monitor.interval_sec)

			hidden_result = await db.execute(
				select(HiddenSeller.seller_id).where(HiddenSeller.user_id == user_id)
			)
			hidden_seller_ids = {row[0] for row in hidden_result.fetchall()}

		items = await client.search_all_domains(params, domains)

		if not items:
			async with AsyncSessionLocal() as db:
				result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
				monitor = result.scalar_one_or_none()
				if monitor and monitor.is_active:
					await _update_monitor_interval(db, monitor, False, original_interval=original_interval)
					await db.commit()
			return

		async with AsyncSessionLocal() as db:
			result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
			monitor = result.scalar_one_or_none()
			if monitor is None or not monitor.is_active:
				return

			filtered_items = [i for i in items if i.seller_id not in hidden_seller_ids]
			new_items_to_notify: list[VintedItem] = []
			is_pg = not settings.is_sqlite()

			for item in filtered_items:
				if is_pg:
					stmt = pg_insert(SeenItem).values(
						user_id=user_id,
						vinted_item_id=item.id,
						domain=item.domain,
						seen_at=datetime.now(timezone.utc),
					).on_conflict_do_nothing(index_elements=["user_id", "vinted_item_id", "domain"])
					res = await db.execute(stmt)
					is_new_for_user = res.rowcount > 0
				else:
					stmt = insert(SeenItem).values(
						user_id=user_id,
						vinted_item_id=item.id,
						domain=item.domain,
						seen_at=datetime.now(timezone.utc),
					).prefix_with("OR IGNORE")
					res = await db.execute(stmt)
					is_new_for_user = res.rowcount > 0

				notified_status = is_cold_start or not is_new_for_user

				if is_pg:
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
					).on_conflict_do_nothing(index_elements=["monitor_id", "vinted_item_id", "domain"])
					found_res = await db.execute(found_stmt)
					if found_res.rowcount > 0 and not notified_status:
						new_items_to_notify.append(item)
				else:
					found_stmt = insert(FoundItem).values(
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
					).prefix_with("OR IGNORE")
					found_res = await db.execute(found_stmt)
					if found_res.rowcount > 0 and not notified_status:
						new_items_to_notify.append(item)

			await _update_monitor_interval(
				db,
				monitor,
				len(new_items_to_notify) > 0 or not is_cold_start,
				count=len(new_items_to_notify),
				original_interval=original_interval,
			)
			monitor.last_check_at = datetime.now(timezone.utc)
			await db.commit()

		if new_items_to_notify:
			asyncio.create_task(process_pending_notifications())
	except Exception as e:
		logger.error(f"Error in check_monitor {monitor_id}: {e}")
		raise


async def process_pending_notifications() -> None:
	"""Send pending Telegram notifications for newly found items."""
	async with _notification_lock:
		async with AsyncSessionLocal() as db:
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

				try:
					bot_to_use = _telegram_bot
					chat_id_to_use = settings.telegram_chat_id

					async with AsyncSessionLocal() as db2:
						monitor = await db2.get(Monitor, fi.monitor_id)
						if monitor and monitor.user_id:
							user = await db2.get(User, monitor.user_id)
							if user and user.telegram_bot_token and user.telegram_chat_id:
								from app.telegram.bot import get_or_create_bot
								bot_to_use, _ = get_or_create_bot(user.telegram_bot_token)
								chat_id_to_use = int(user.telegram_chat_id)

					if bot_to_use and chat_id_to_use is not None:
						await send_item_notification(bot_to_use, chat_id_to_use, item)
						fi.notified = True
						await db.commit()
				except Exception:
					logger.exception("Notification failed for item %s", fi.vinted_item_id)
					break


class MonitorScheduler:
	"""APScheduler wrapper that manages per-monitor polling jobs."""

	def __init__(self, client: VintedClient) -> None:
		self.client = client
		self.scheduler = AsyncIOScheduler()
		self.job_ids: dict[int, str] = {}

	async def start(self) -> None:
		"""Load active monitors from DB and start all their jobs."""
		async with AsyncSessionLocal() as db:
			result = await db.execute(select(Monitor).where(Monitor.is_active == True))  # noqa: E712
			monitors = result.scalars().all()

		for monitor in monitors:
			effective = _get_effective_interval(monitor.interval_sec)
			stagger = random.uniform(5.0, 30.0)
			job = self.scheduler.add_job(
				check_monitor,
				trigger=IntervalTrigger(seconds=effective),
				args=[monitor.id, self.client],
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
			args=[monitor_id, self.client],
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
