# Copied implementation from app/scheduler/app_scheduler_tasks.py
import asyncio
import inspect
import json
import logging
import random
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session_factory
from app.models import FoundItem, HiddenSeller, Monitor, MonitorTelegramTopic, SeenItem, User
from app.scraper.client import DomainSearchResult, VintedClient, TokenBucketLimiter
from app.scraper.monitor_filters import extract_monitor_filters, has_restrictive_filters, item_matches_monitor_filters
from app.scraper.parser import VintedItem
from app.scheduler.found_item_values import build_found_item_values
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


class _ReusedSessionContext:
	def __init__(self, session: AsyncSession) -> None:
		self.session = session

	async def __aenter__(self) -> AsyncSession:
		return self.session

	async def __aexit__(self, exc_type, exc, tb) -> None:
		await self.session.close()


def _new_session():
	session_factory = AsyncSessionLocal or get_session_factory()
	session = session_factory()
	if isinstance(session, AsyncSession):
		return _ReusedSessionContext(session)
	return session


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


@dataclass(frozen=True)
class PendingNotificationCandidate:
	found_item_id: int
	monitor_id: int
	vinted_item_id: int
	domain: str
	title: str
	price: float
	currency: str
	brand: str
	size: str
	condition: str
	photo_url: str
	item_url: str
	seller_id: int
	found_at: datetime


@dataclass
class MonitorCheckContext:
	monitor_id: int
	user_id: int
	monitor_name: str
	params: dict
	original_url: str
	domains: list[str]
	monitor_filters: object
	hidden_seller_ids: set[int]
	is_cold_start: bool
	freshness_cutoff_at: datetime | None
	original_interval: int
	cf_worker_url: str
	cf_worker_mode: str
	cf_worker_block_threshold: int
	cf_worker_recovery_minutes: int


@dataclass
class DomainDeltaResult:
	domain: str
	raw_count: int
	accepted_count: int
	new_candidate_count: int
	seen_boundary_hit: bool
	stopped_at_seen_item_id: int | None
	skipped_by_filter_count: int
	missing_brand_id_count: int
	request_count: int
	duration_ms: int
	error: str | None
	new_items: list[VintedItem]
	baseline_items: list[VintedItem]
	seen_only_items: list[VintedItem]
	detail_requests_count: int = 0
	detail_success_count: int = 0
	detail_failed_count: int = 0
	detail_cap_exceeded_count: int = 0
	stale_skipped_count: int = 0
	wrong_category_skipped_count: int = 0
	detail_missing_timestamp_count: int = 0
	detail_missing_category_count: int = 0


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
		"monitor_check_max_pages_per_domain": settings.monitor_check_max_pages_per_domain,
		"running_monitor_checks": len(_running_checks),
		"monitor_check_global_active": max(
			0,
			settings.monitor_check_global_concurrency - getattr(_global_check_semaphore, "_value", 0),
		),
		"monitor_check_user_active": user_active,
		"monitor_check_already_running_skips": _backpressure_stats["already_running_skips"],
		"monitor_check_capacity_timeouts": _backpressure_stats["capacity_timeouts"],
		"monitor_candidate_detail_max_per_check": settings.monitor_candidate_detail_max_per_check,
		"monitor_detail_guard_enabled": int(settings.monitor_detail_guard_enabled),
		"monitor_detail_category_guard_enabled": int(settings.monitor_detail_category_guard_enabled),
		"monitor_detail_freshness_guard_enabled": int(settings.monitor_detail_freshness_guard_enabled),
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


def _runtime_search_params(params: dict) -> dict:
	search_params = dict(params)
	search_params["order"] = "newest_first"
	search_params.pop("page", None)
	search_params.pop("search_id", None)

	# Map catalog aliases to Vinted API expected key: catalog_ids[]
	catalog_aliases = ["catalog[]", "catalog", "catalog_ids"]
	found_catalogs = set()
	for alias in catalog_aliases:
		if alias in search_params:
			values = search_params.pop(alias)
			if isinstance(values, list):
				found_catalogs.update(values)
			else:
				found_catalogs.add(values)

	if found_catalogs:
		search_params["catalog_ids[]"] = sorted(list(found_catalogs))

	return search_params


async def _load_seen_item_ids(db, monitor_id: int, domain: str, item_ids: set[int]) -> set[int]:
	if not item_ids:
		return set()
	result = await db.execute(
		select(SeenItem.vinted_item_id)
		.where(
			SeenItem.monitor_id == monitor_id,
			SeenItem.domain == domain,
			SeenItem.vinted_item_id.in_(item_ids),
		)
	)
	return {int(row[0]) for row in result.fetchall()}


async def _fetch_domain_results(
	client: VintedClient,
	*,
	context: MonitorCheckContext,
	mode: str,
) -> list[DomainSearchResult]:
	from app.scraper.source_selector import (
		should_use_hydration_source,
		should_use_hydration_ssr_photo_merge,
	)
	from app.scraper.hydration_parser import hydration_record_to_vinted_item

	search_params = _runtime_search_params(context.params)
	max_pages = max(1, settings.monitor_check_max_pages_per_domain)
	if max_pages > 1:
		logger.warning(
			"monitor_check_max_pages_per_domain=%s configured, but delta checks currently fetch page 1 only",
			max_pages,
		)

	# Hydration Source Branch
	if should_use_hydration_source(context.params):
		logger.info("Using hydration source for monitor=%s", context.monitor_id)
		if should_use_hydration_ssr_photo_merge(context.params):
			from app.scraper.hydration_ssr_merge import fetch_and_parse_hydration_ssr_photos

			async def fetch_merged_domain(domain: str) -> DomainSearchResult:
				domain_url = _catalog_url_for_domain(context.original_url, domain)
				try:
					merge_result = await fetch_and_parse_hydration_ssr_photos(
						client,
						domain_url,
						domain=domain,
					)
					items = [
						hydration_record_to_vinted_item(record, domain)
						for record in merge_result.records
					]
					stats = merge_result.stats.to_safe_dict()
					if merge_result.stats.photo_merge_fallback_used:
						logger.warning(
							"hydration_ssr_photo_merge_fallback monitor_id=%s domain=%s exception_type=%s",
							context.monitor_id,
							domain,
							merge_result.stats.photo_merge_error,
						)
					return DomainSearchResult(
						domain=domain,
						items=items,
						request_count=merge_result.stats.html_fetch_count,
						duration_ms=merge_result.stats.duration_ms,
						source_diagnostics=stats,
					)
				except Exception as exc:
					logger.warning(
						"hydration_ssr_photo_merge_domain_failed monitor_id=%s domain=%s exception_type=%s",
						context.monitor_id,
						domain,
						type(exc).__name__,
					)
					return DomainSearchResult(
						domain=domain,
						items=[],
						request_count=1,
						error=type(exc).__name__,
						source_diagnostics={
							"source_used": "hydration_ssr_photo_merge",
							"safe_error": type(exc).__name__,
						},
					)

			return await asyncio.gather(
				*(fetch_merged_domain(domain) for domain in context.domains)
			)

		by_domain: dict[str, list[VintedItem]] = {domain: [] for domain in context.domains}
		for domain in context.domains:
			# Use client to fetch per domain
			domain_url = context.original_url.replace("vinted.pl", domain)
			hydration_items = await client.fetch_catalog_hydration_items(domain_url, domain=domain)
			items = [hydration_record_to_vinted_item(i, domain) for i in hydration_items]
			by_domain[domain].extend(items)

		# Return structured items per domain
		return [
			DomainSearchResult(domain=domain, items=by_domain.get(domain, []), request_count=len(context.domains))
			for domain in context.domains
		]

	# API Path Branch
	items = await client.search_all_domains(search_params, context.domains, mode=mode)
	by_domain: dict[str, list[VintedItem]] = {domain: [] for domain in context.domains}
	for item in items or []:
		by_domain.setdefault(item.domain, []).append(item)
	return [
		DomainSearchResult(domain=domain, items=by_domain.get(domain, []), request_count=1)
		for domain in context.domains
	]


async def _select_domain_delta_items(
	db,
	*,
	context: MonitorCheckContext,
	result: DomainSearchResult,
) -> DomainDeltaResult:
	raw_items = result.items or []
	accepted_items: list[VintedItem] = []
	accepted_ids: set[int] = set()
	skipped_by_filter_count = 0
	missing_brand_id_count = 0
	seen_in_result: set[int] = set()

	for item in raw_items:
		if item.seller_id in context.hidden_seller_ids:
			continue
		if item.id in seen_in_result:
			continue
		seen_in_result.add(item.id)
		matches_filters, skip_reason = item_matches_monitor_filters(item, context.monitor_filters)
		if not matches_filters:
			skipped_by_filter_count += 1
			if skip_reason == "missing_brand_id":
				missing_brand_id_count += 1
			continue
		accepted_items.append(item)
		accepted_ids.add(item.id)

	seen_ids = await _load_seen_item_ids(db, context.monitor_id, result.domain, accepted_ids)
	new_items: list[VintedItem] = []
	baseline_items: list[VintedItem] = []
	seen_boundary_hit = False
	stopped_at_seen_item_id: int | None = None
	defer_summary_seen_boundary = (
		settings.monitor_detail_guard_enabled
		and settings.monitor_detail_category_guard_enabled
		and bool(context.monitor_filters.catalog_ids)
	)

	for item in accepted_items:
		if context.is_cold_start:
			if item.id not in seen_ids:
				baseline_items.append(item)
			continue
		if item.id in seen_ids:
			if defer_summary_seen_boundary:
				continue
			seen_boundary_hit = True
			stopped_at_seen_item_id = item.id
			break
		new_items.append(item)

	return DomainDeltaResult(
		domain=result.domain,
		raw_count=len(raw_items),
		accepted_count=len(accepted_items),
		new_candidate_count=len(new_items),
		seen_boundary_hit=seen_boundary_hit,
		stopped_at_seen_item_id=stopped_at_seen_item_id,
		skipped_by_filter_count=skipped_by_filter_count,
		missing_brand_id_count=missing_brand_id_count,
		request_count=result.request_count,
		duration_ms=result.duration_ms,
		error=result.error,
		new_items=new_items,
		baseline_items=baseline_items,
		seen_only_items=[],
	)


def _candidate_detail_needed(context: MonitorCheckContext) -> bool:
	if not settings.monitor_detail_guard_enabled:
		return False
	if (
		settings.monitor_detail_category_guard_enabled
		and context.monitor_filters.catalog_ids
	):
		return True
	if (
		not context.is_cold_start
		and settings.monitor_detail_freshness_guard_enabled
	):
		return True
	return False


def _detail_category_matches(context: MonitorCheckContext, detail) -> tuple[bool | None, str | None]:
	if not (
		settings.monitor_detail_category_guard_enabled
		and context.monitor_filters.catalog_ids
	):
		return True, None

	detail_ids = set(detail.catalog_ids) | set(detail.category_ids)
	if not detail_ids:
		return None, "detail_missing_category"
	if detail_ids & set(context.monitor_filters.catalog_ids):
		return True, None
	return False, "wrong_category"


def _detail_is_fresh(context: MonitorCheckContext, detail) -> tuple[bool | None, str | None]:
	if context.is_cold_start or not settings.monitor_detail_freshness_guard_enabled:
		return True, None
	if context.freshness_cutoff_at is None:
		return True, None
	if detail.listed_at is None:
		return None, "detail_missing_timestamp"
	cutoff_source = context.freshness_cutoff_at
	if cutoff_source.tzinfo is None:
		cutoff_source = cutoff_source.replace(tzinfo=timezone.utc)
	cutoff = cutoff_source.astimezone(timezone.utc) - timedelta(seconds=settings.monitor_freshness_grace_seconds)
	listed_at = detail.listed_at
	if listed_at.tzinfo is None:
		listed_at = listed_at.replace(tzinfo=timezone.utc)
	listed_at = listed_at.astimezone(timezone.utc)
	if listed_at < cutoff:
		return False, "stale_item"
	return True, None


async def _apply_candidate_detail_guard(
	client: VintedClient,
	*,
	context: MonitorCheckContext,
	domain_deltas: list[DomainDeltaResult],
) -> None:
	if not _candidate_detail_needed(context):
		return

	fetch_detail = getattr(client, "fetch_item_detail", None)
	if fetch_detail is None or not inspect.iscoroutinefunction(fetch_detail):
		logger.warning(
			"Monitor detail guard skipped because scraper client has no async detail fetch: monitor_id=%s",
			context.monitor_id,
		)
		return
	detail_cap_remaining = max(0, settings.monitor_candidate_detail_max_per_check)

	for delta in domain_deltas:
		source_items = delta.baseline_items if context.is_cold_start else delta.new_items
		allowed_items: list[VintedItem] = []
		seen_only_items: list[VintedItem] = []

		for item in source_items:
			if detail_cap_remaining <= 0:
				delta.detail_cap_exceeded_count += 1
				continue

			detail_cap_remaining -= 1
			delta.detail_requests_count += 1
			detail = await fetch_detail(item.domain, item.id)

			if detail is None:
				delta.detail_failed_count += 1
				if context.monitor_filters.catalog_ids and settings.monitor_detail_category_guard_enabled:
					continue
				if not context.is_cold_start and settings.monitor_detail_freshness_guard_enabled:
					seen_only_items.append(item)
				continue

			delta.detail_success_count += 1
			category_match, category_reason = _detail_category_matches(context, detail)
			if category_match is None:
				delta.detail_missing_category_count += 1
				continue
			if category_match is False:
				delta.wrong_category_skipped_count += 1
				continue

			fresh, fresh_reason = _detail_is_fresh(context, detail)
			if fresh is None:
				delta.detail_missing_timestamp_count += 1
				seen_only_items.append(item)
				continue
			if fresh is False:
				delta.stale_skipped_count += 1
				seen_only_items.append(item)
				continue

			allowed_items.append(item)

		if context.is_cold_start:
			delta.baseline_items = allowed_items
		else:
			delta.new_items = allowed_items
			delta.new_candidate_count = len(allowed_items)
		delta.seen_only_items.extend(seen_only_items)


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
			original_url=monitor.original_url,
			domains=domains,
			monitor_filters=monitor_filters,
			hidden_seller_ids=hidden_seller_ids,
			is_cold_start=monitor.last_check_at is None,
			freshness_cutoff_at=monitor.last_check_at,
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
				domain_results = await _fetch_domain_results(
					client,
					context=context,
					mode=context.cf_worker_mode,
				)

				# Record diagnostics
				from app.scheduler.diagnostics import registry
				from app.scraper.source_selector import (
					should_use_hydration_source,
					should_use_hydration_ssr_photo_merge,
				)
				domain_counts = {r.domain: len(r.items or []) for r in domain_results}
				if should_use_hydration_ssr_photo_merge(context.params):
					source = "hydration_ssr_photo_merge"
				elif should_use_hydration_source(context.params):
					source = "hydration"
				else:
					source = "api"
				source_details = {
					result.domain: result.source_diagnostics
					for result in domain_results
					if result.source_diagnostics
				}
				await registry.record_check(
					context.monitor_id,
					source,
					domain_counts,
					source_details_by_domain=source_details,
				)
				raw_result_count = sum(len(result.items or []) for result in domain_results)
				domain_deltas: list[DomainDeltaResult] = []
				if domain_results and raw_result_count > 0:
					async with _new_session() as db:
						result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
						monitor = result.scalar_one_or_none()
						if monitor is None or not monitor.is_active:
							return
						domain_deltas = [
							await _select_domain_delta_items(
								db,
								context=context,
								result=result,
							)
							for result in domain_results
						]

					await _apply_candidate_detail_guard(
						client,
						context=context,
						domain_deltas=domain_deltas,
					)
			finally:
				if owns_client:
					await client.close()

			async with _new_session() as db:
				result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
				monitor = result.scalar_one_or_none()
				if monitor is None or not monitor.is_active:
					return

				if not domain_results or raw_result_count == 0:
					await _update_monitor_interval(db, monitor, False, original_interval=context.original_interval)
					monitor.last_check_status = "success_zero_items"
				else:
					accepted_count = sum(delta.accepted_count for delta in domain_deltas)
					skipped_by_filter_count = sum(delta.skipped_by_filter_count for delta in domain_deltas)
					missing_brand_id_count = sum(delta.missing_brand_id_count for delta in domain_deltas)
					seen_boundary_hits = sum(1 for delta in domain_deltas if delta.seen_boundary_hit)
					request_count = sum(delta.request_count for delta in domain_deltas)
					checked_domain_count = len(domain_deltas)
					detail_requests_count = sum(delta.detail_requests_count for delta in domain_deltas)
					detail_success_count = sum(delta.detail_success_count for delta in domain_deltas)
					detail_failed_count = sum(delta.detail_failed_count for delta in domain_deltas)
					detail_cap_exceeded_count = sum(delta.detail_cap_exceeded_count for delta in domain_deltas)
					stale_skipped_count = sum(delta.stale_skipped_count for delta in domain_deltas)
					wrong_category_skipped_count = sum(delta.wrong_category_skipped_count for delta in domain_deltas)
					detail_missing_timestamp_count = sum(delta.detail_missing_timestamp_count for delta in domain_deltas)
					detail_missing_category_count = sum(delta.detail_missing_category_count for delta in domain_deltas)

					logger.info(
						"Monitor delta check results: monitor_id=%s user_id=%s monitor_name=%s filter_keys=%s "
						"selected_domain_count=%s checked_domain_count=%s request_count=%s raw_count=%s "
						"accepted_count=%s new_count=%s seen_boundary_hits=%s skipped_by_filter_count=%s "
						"missing_brand_id_count=%s detail_requests_count=%s detail_success_count=%s "
						"detail_failed_count=%s detail_cap_exceeded_count=%s stale_skipped_count=%s "
						"wrong_category_skipped_count=%s detail_missing_timestamp_count=%s "
						"detail_missing_category_count=%s cold_start=%s",
						monitor.id,
						context.user_id,
						monitor.name,
						context.monitor_filters.filter_keys,
						len(context.domains),
						checked_domain_count,
						request_count,
						raw_result_count,
						accepted_count,
						sum(delta.new_candidate_count for delta in domain_deltas),
						seen_boundary_hits,
						skipped_by_filter_count,
						missing_brand_id_count,
						detail_requests_count,
						detail_success_count,
						detail_failed_count,
						detail_cap_exceeded_count,
						stale_skipped_count,
						wrong_category_skipped_count,
						detail_missing_timestamp_count,
						detail_missing_category_count,
						context.is_cold_start,
					)
					for delta in domain_deltas:
						logger.info(
							"Monitor domain delta: monitor_id=%s domain=%s raw_count=%s accepted_count=%s "
							"new_candidate_count=%s seen_boundary_hit=%s stopped_at_seen_item_id=%s "
							"skipped_by_filter_count=%s missing_brand_id_count=%s request_count=%s duration_ms=%s "
							"detail_requests_count=%s detail_success_count=%s detail_failed_count=%s "
							"detail_cap_exceeded_count=%s stale_skipped_count=%s wrong_category_skipped_count=%s "
							"detail_missing_timestamp_count=%s detail_missing_category_count=%s error=%s",
							monitor.id,
							delta.domain,
							delta.raw_count,
							delta.accepted_count,
							delta.new_candidate_count,
							delta.seen_boundary_hit,
							delta.stopped_at_seen_item_id,
							delta.skipped_by_filter_count,
							delta.missing_brand_id_count,
							delta.request_count,
							delta.duration_ms,
							delta.detail_requests_count,
							delta.detail_success_count,
							delta.detail_failed_count,
							delta.detail_cap_exceeded_count,
							delta.stale_skipped_count,
							delta.wrong_category_skipped_count,
							delta.detail_missing_timestamp_count,
							delta.detail_missing_category_count,
							delta.error,
						)

					seen_items_to_insert = []
					found_items_to_insert = []
					new_items_to_notify: list[VintedItem] = []

					# Process results and deduplicate items across domains within this check cycle.
					found_vinted_ids: set[int] = set()

					now = datetime.now(timezone.utc)
					for delta in domain_deltas:
						delta_items = delta.baseline_items if context.is_cold_start else delta.new_items
						seen_source_items = list(delta_items) + list(delta.seen_only_items)
						seen_source_ids: set[int] = set()
						for item in seen_source_items:
							if item.id in seen_source_ids:
								continue
							seen_source_ids.add(item.id)
							# For SeenItem, we track per domain to maintain correct delta boundaries.
							seen_items_to_insert.append({
								"monitor_id": monitor_id,
								"user_id": context.user_id,
								"vinted_item_id": item.id,
								"domain": item.domain,
								"seen_at": now,
							})

						if context.is_cold_start:
							continue

						for item in delta.new_items:
							# For FoundItem, deduplicate globally across all domains for this monitor.
							if item.id in found_vinted_ids:
								continue
							found_vinted_ids.add(item.id)

							found_items_to_insert.append(
								build_found_item_values(
									monitor_id=monitor_id,
									item=item,
									found_at=now,
								)
							)
							new_items_to_notify.append(item)

					if seen_items_to_insert:
						stmt = pg_insert(SeenItem).values(seen_items_to_insert).on_conflict_do_nothing(
							index_elements=["monitor_id", "vinted_item_id", "domain"]
						)
						await db.execute(stmt)

					if found_items_to_insert:
						found_stmt = pg_insert(FoundItem).values(found_items_to_insert).on_conflict_do_nothing(
							index_elements=["monitor_id", "vinted_item_id"]
						)
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



def _pending_conditions(monitor_id: int | None) -> list[object]:
	conditions: list[object] = [FoundItem.notified == False]  # noqa: E712
	if monitor_id is not None:
		conditions.append(FoundItem.monitor_id == monitor_id)
	return conditions


async def _count_pending_notifications(monitor_id: int | None) -> int:
	async with _new_session() as db:
		result = await db.execute(
			select(func.count(FoundItem.id)).where(*_pending_conditions(monitor_id))
		)
		return int(result.scalar_one())


async def collect_pending_notification_candidates(
	*,
	monitor_id: int | None = None,
	limit: int = 50,
) -> tuple[list[PendingNotificationCandidate], dict[str, object]]:
	"""Read a bounded pending notification batch without mutating database state."""
	conditions = _pending_conditions(monitor_id)
	async with _new_session() as db:
		pending_total = int(
			(await db.execute(select(func.count(FoundItem.id)).where(*conditions))).scalar_one()
		)
		rows = (
			await db.execute(
				select(FoundItem)
				.where(*conditions)
				.order_by(FoundItem.found_at.asc(), FoundItem.id.asc())
				.limit(limit)
			)
		).scalars().all()
		candidates = [
			PendingNotificationCandidate(
				found_item_id=row.id,
				monitor_id=row.monitor_id,
				vinted_item_id=row.vinted_item_id,
				domain=row.domain,
				title=row.title,
				price=row.price,
				currency=row.currency,
				brand=row.brand,
				size=row.size,
				condition=row.condition,
				photo_url=row.photo_url,
				item_url=row.item_url,
				seller_id=row.seller_id,
				found_at=row.found_at,
			)
			for row in rows
		]

		monitor_ids = {candidate.monitor_id for candidate in candidates}
		if monitor_id is not None:
			monitor_ids.add(monitor_id)
		users: list[User] = []
		if monitor_ids:
			monitors = (
				await db.execute(select(Monitor).where(Monitor.id.in_(monitor_ids)))
			).scalars().all()
			user_ids = {monitor.user_id for monitor in monitors if monitor.user_id is not None}
			if user_ids:
				users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()

	bot_configured = bool(users) and all(bool(user.telegram_bot_token) for user in users)
	chat_configured = bool(users) and all(
		bool(user.telegram_topics_chat_id if user.telegram_topics_enabled else user.telegram_chat_id)
		for user in users
	)
	uses_group_rate = False
	for user in users:
		configured_chat = user.telegram_topics_chat_id if user.telegram_topics_enabled else user.telegram_chat_id
		try:
			uses_group_rate = uses_group_rate or user.telegram_topics_enabled or int(configured_chat or 0) < 0
		except (TypeError, ValueError):
			# Unknown chat types use the safer private/unknown limiter.
			pass
	metadata: dict[str, object] = {
		"pending_total": pending_total,
		"telegram_bot_configured": bot_configured,
		"telegram_chat_configured": chat_configured,
		"uses_group_rate": uses_group_rate,
	}
	return candidates, metadata


def _pending_sample(candidate: PendingNotificationCandidate) -> dict[str, object]:
	return {
		"found_item_id": candidate.found_item_id,
		"vinted_item_id": str(candidate.vinted_item_id),
		"domain": candidate.domain,
		"title_preview": candidate.title[:80],
		"has_photo_url": bool(candidate.photo_url),
		"notified": False,
		"found_at": candidate.found_at.isoformat(),
	}


async def process_pending_notifications(
	limit: int = 50,
	*,
	monitor_id: int | None = None,
	dry_run: bool = False,
	sample_limit: int = 10,
) -> dict[str, object]:
	"""Audit or deliver a bounded pending batch; only successful sends are acknowledged."""
	started = time.monotonic()
	async with _notification_lock:
		candidates, metadata = await collect_pending_notification_candidates(
			monitor_id=monitor_id,
			limit=limit,
		)
		with_photo = sum(1 for candidate in candidates if candidate.photo_url)
		base_result: dict[str, object] = {
			"dry_run": dry_run,
			"monitor_id": monitor_id,
			"limit": limit,
			"pending_total": metadata["pending_total"],
			"pending_before": metadata["pending_total"],
			"selected_for_processing": len(candidates),
			"with_photo_url": with_photo,
			"without_photo_url": len(candidates) - with_photo,
			"estimated_seconds_private_chat": len(candidates),
			"estimated_seconds": len(candidates) * (3 if metadata["uses_group_rate"] else 1),
			"telegram_bot_configured": metadata["telegram_bot_configured"],
			"telegram_chat_configured": metadata["telegram_chat_configured"],
			"samples": [_pending_sample(candidate) for candidate in candidates[:sample_limit]],
			"errors_sample": [],
		}
		if dry_run:
			base_result.update(
				{
					"sent_photo_count": 0,
					"sent_text_count": 0,
					"fallback_text_count": 0,
					"failed_count": 0,
					"rate_limited_count": 0,
					"marked_notified_count": 0,
					"pending_after": metadata["pending_total"],
					"duration_ms": int((time.monotonic() - started) * 1000),
					"side_effects": {
						"reads_database": True,
						"writes_found_items": False,
						"sends_telegram": False,
					},
				}
			)
			return base_result

		sent_photo_count = 0
		sent_text_count = 0
		fallback_text_count = 0
		failed_count = 0
		rate_limited_count = 0
		marked_notified_count = 0
		send_attempt_count = 0
		errors_sample: list[dict[str, object]] = []

		for candidate in candidates:
			delivery_target: TelegramDeliveryTarget | None = None
			try:
				async with _new_session() as db:
					monitor = await db.get(Monitor, candidate.monitor_id)
					user = await db.get(User, monitor.user_id) if monitor and monitor.user_id else None
					if monitor is None or user is None:
						raise RuntimeError("notification_owner_missing")
					monitor_name = monitor.name
					delivery_target = await resolve_telegram_delivery_target(db, user=user, monitor=monitor)
				if not delivery_target.ok or delivery_target.bot is None or delivery_target.chat_id is None:
					failed_count += 1
					if len(errors_sample) < sample_limit:
						errors_sample.append(
							{"found_item_id": candidate.found_item_id, "code": delivery_target.code}
						)
					continue

				item = VintedItem(
					id=candidate.vinted_item_id,
					title=candidate.title,
					price=candidate.price,
					currency=candidate.currency,
					brand=candidate.brand,
					size=candidate.size,
					condition=candidate.condition,
					photo_url=candidate.photo_url,
					item_url=candidate.item_url,
					domain=candidate.domain,
					seller_id=candidate.seller_id,
				)
				send_attempt_count += 1
				delivery_mode = await send_item_notification(
					delivery_target.bot,
					delivery_target.chat_id,
					item,
					monitor_name=monitor_name,
					message_thread_id=delivery_target.message_thread_id,
				)
				async with _new_session() as db:
					found_item = await db.get(FoundItem, candidate.found_item_id)
					if found_item is not None and not found_item.notified:
						found_item.notified = True
						await db.commit()
						marked_notified_count += 1
				if delivery_mode == "photo":
					sent_photo_count += 1
				elif delivery_mode == "fallback_text":
					fallback_text_count += 1
				else:
					sent_text_count += 1
			except Exception as exc:
				failed_count += 1
				if type(exc).__name__ == "TelegramRetryAfter":
					rate_limited_count += 1
				if delivery_target and delivery_target.topic_id is not None:
					try:
						async with _new_session() as db:
							topic = await db.get(MonitorTelegramTopic, delivery_target.topic_id)
							if topic is not None:
								await record_topic_send_failure(db, topic=topic, exc=exc)
					except Exception as record_exc:
						logger.warning(
							"Telegram topic failure record failed item_id=%s exception_type=%s",
							candidate.vinted_item_id,
							type(record_exc).__name__,
						)
				if len(errors_sample) < sample_limit:
					errors_sample.append(
						{
							"found_item_id": candidate.found_item_id,
							"code": "telegram_rate_limited"
							if type(exc).__name__ == "TelegramRetryAfter"
							else "telegram_send_failed",
							"exception_type": type(exc).__name__,
						}
					)
				logger.warning(
					"Notification failed monitor_id=%s item_id=%s exception_type=%s",
					candidate.monitor_id,
					candidate.vinted_item_id,
					type(exc).__name__,
				)

		pending_after = await _count_pending_notifications(monitor_id)
		base_result.update(
			{
				"sent_photo_count": sent_photo_count,
				"sent_text_count": sent_text_count,
				"fallback_text_count": fallback_text_count,
				"failed_count": failed_count,
				"rate_limited_count": rate_limited_count,
				"marked_notified_count": marked_notified_count,
				"pending_after": pending_after,
				"duration_ms": int((time.monotonic() - started) * 1000),
				"errors_sample": errors_sample,
				"side_effects": {
					"reads_database": True,
					"writes_found_items": marked_notified_count > 0,
					"sends_telegram": send_attempt_count > 0,
				},
			}
		)
		return base_result


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

		if settings.pending_notifications_worker_enabled:
			self.scheduler.add_job(
				process_pending_notifications,
				trigger=IntervalTrigger(minutes=1),
				args=[500],
				id="pending_notifications_processor",
			)
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

def _catalog_url_for_domain(original_url: str, domain: str) -> str:
    parsed = urllib.parse.urlsplit(original_url)
    return urllib.parse.urlunsplit(
        (parsed.scheme or "https", f"www.{domain}", parsed.path, parsed.query, "")
    )


def _public_item_path(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parsed = urllib.parse.urlsplit(value)
    path = parsed.path if parsed.scheme or parsed.netloc else value.split("?", 1)[0]
    return path if path.startswith("/items/") else ""


async def run_hydration_ssr_merge_job(
    monitor_id: int,
    job_id: str,
    *,
    target_domain: str | None = None,
    max_domains: int = 8,
    max_items_per_domain: int = 96,
    sample_limit: int = 3,
) -> dict | None:
    """Run a read-only one-fetch-per-domain hydration/SSR merge diagnostic."""
    from app.scheduler.diagnostics import registry
    from app.scraper.hydration_ssr_merge import fetch_and_parse_hydration_ssr_photos

    started_at = datetime.now(timezone.utc)
    total_started = time.monotonic()
    client = None
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            query_result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
            monitor = query_result.scalar_one_or_none()

        if monitor is None:
            await registry.fail_job(job_id, "MonitorNotFound")
            return None

        try:
            raw_domains = json.loads(monitor.domains_json)
            selected_domains = (
                list(dict.fromkeys(domain for domain in raw_domains if isinstance(domain, str)))
                if isinstance(raw_domains, list)
                else []
            )
        except Exception:
            selected_domains = []
        if target_domain is not None:
            if target_domain not in selected_domains:
                await registry.fail_job(job_id, "DomainNotSelected")
                return None
            job_domains = [target_domain]
        else:
            job_domains = selected_domains[:max(1, min(max_domains, 8))]

        rate_limiter = TokenBucketLimiter(
            rate=float(settings.rate_limit_per_minute),
            per=60.0,
        )
        client = VintedClient(rate_limiter=rate_limiter)

        async def process_domain(domain: str):
            domain_url = _catalog_url_for_domain(monitor.original_url, domain)
            merge_result = await fetch_and_parse_hydration_ssr_photos(
                client,
                domain_url,
                domain=domain,
                max_items=max_items_per_domain,
            )
            samples = []
            for position, item in enumerate(merge_result.records[:sample_limit]):
                item_id = str(item.get("id"))
                photo_url = item.get("photo_url") or ""
                has_ssr_photo = item_id in merge_result.ssr_photo_item_ids
                samples.append(
                    {
                        "position": position,
                        "item_id": item_id,
                        "item_url_path": _public_item_path(
                            item.get("path") or item.get("url")
                        ),
                        "has_hydration_title": bool(item.get("title")),
                        "title_preview": str(item.get("title") or "")[:50],
                        "has_hydration_price": item.get("price") is not None,
                        "currency": str(item.get("currency") or ""),
                        "has_ssr_photo": has_ssr_photo,
                        "photo_host": urllib.parse.urlsplit(photo_url).hostname
                        if has_ssr_photo and photo_url
                        else None,
                    }
                )

            counts = merge_result.stats.to_safe_dict()
            return domain, counts, samples

        domain_results = await asyncio.gather(
            *(process_domain(domain) for domain in job_domains),
            return_exceptions=True,
        )
        counts_by_domain: dict[str, dict] = {}
        samples_by_domain: dict[str, list[dict]] = {}
        errors_by_domain: dict[str, str] = {}
        for domain, domain_result in zip(job_domains, domain_results):
            if isinstance(domain_result, BaseException):
                errors_by_domain[domain] = type(domain_result).__name__
                logger.warning(
                    "hydration_ssr_merge_domain_failed job_id=%s monitor_id=%s domain=%s exception_type=%s",
                    job_id,
                    monitor_id,
                    domain,
                    type(domain_result).__name__,
                )
                continue
            result_domain, counts, samples = domain_result
            counts_by_domain[result_domain] = counts
            samples_by_domain[result_domain] = samples

        summary = {
            "domains_requested_total": len(job_domains),
            "domains_processed_total": len(counts_by_domain) + len(errors_by_domain),
            "domains_succeeded_total": len(counts_by_domain),
            "domains_failed_total": len(errors_by_domain),
            "html_fetch_count_total": sum(v["html_fetch_count"] for v in counts_by_domain.values()),
            "hydration_items_total": sum(v["hydration_items"] for v in counts_by_domain.values()),
            "ssr_photo_map_total": sum(v["ssr_photo_map_items"] for v in counts_by_domain.values()),
            "overlap_total": sum(v["overlap_count"] for v in counts_by_domain.values()),
            "merged_with_photo_total": sum(v["merged_with_photo"] for v in counts_by_domain.values()),
            "missing_photo_after_merge_total": sum(v["missing_photo_after_merge"] for v in counts_by_domain.values()),
            "hydration_only_total": sum(v["hydration_only_count"] for v in counts_by_domain.values()),
            "ssr_photo_only_total": sum(v["ssr_photo_only_count"] for v in counts_by_domain.values()),
        }
        completed_at = datetime.now(timezone.utc)
        diagnostic_result = {
            "job_id": job_id,
            "status": "completed",
            "source": "hydration_with_ssr_photos",
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms_total": int((time.monotonic() - total_started) * 1000),
            "summary": summary,
            "counts_by_domain": counts_by_domain,
            "samples_by_domain": samples_by_domain,
            "errors_by_domain": errors_by_domain,
            "side_effects": {
                "reads_database": True,
                "calls_vinted": True,
                "writes_seen_items": False,
                "writes_found_items": False,
                "enqueues_notifications": False,
                "sends_telegram": False,
                "runs_scheduler_check": False,
            },
        }
        await registry.complete_job(job_id, diagnostic_result)
        return diagnostic_result
    except Exception as exc:
        logger.warning(
            "hydration_ssr_merge_job_failed job_id=%s monitor_id=%s exception_type=%s",
            job_id,
            monitor_id,
            type(exc).__name__,
        )
        await registry.fail_job(job_id, type(exc).__name__)
        return None
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as exc:
                logger.warning(
                    "hydration_ssr_merge_client_close_failed job_id=%s exception_type=%s",
                    job_id,
                    type(exc).__name__,
                )
