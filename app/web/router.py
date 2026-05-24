
# Actual implementation moved from app/web/app_web_router.py
# Keep this module as the canonical `app.web.router` so tests and imports
# that patch or reference `app.web.router.*` affect the running code.
"""Main web routes for the Vinted Monitor dashboard.

Endpoints:
  GET  /                         → dashboard with stats
  GET  /monitors                 → list monitors (+ HTMX partial)
  GET  /monitors/new             → create form
  POST /monitors                 → create monitor
  GET  /monitors/{id}/edit       → edit form
  POST /monitors/{id}/edit       → update monitor
  POST /monitors/{id}/delete     → delete monitor
  POST /monitors/bulk-delete     → bulk delete
  POST /monitors/import          → import JSON / TXT
  GET  /export/json              → export all monitors as JSON
  GET  /export/txt               → export URLs as plain text
  GET  /settings                 → settings page
  POST /settings                 → save settings
  GET  /logs                     → logs page (paginated)
  GET  /api/logs                 → JSON logs API
  GET  /api/stats                → JSON dashboard stats
  POST /api/bot/start            → start Telegram bot
  POST /api/bot/stop             → stop Telegram bot
  POST /api/bot/test             → send test message
  POST /api/monitors/{id}/trigger → manual check trigger
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import log_manager
from app.models import AppSettings, FoundItem, Monitor, User
from app.scraper.domains import VINTED_DOMAINS
from app.scraper.url_parser import extract_domains_from_url, parse_vinted_url
from app.config import get_settings
import app.web.dependencies as web_deps
from app.web.dependencies import (
	RequireLoginException,
	get_db,
	get_scheduler,
	get_scraper_client,
	require_admin,
	require_user,
	start_bot,
	stop_bot,
)

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

# If the full implementation lives in `app.web.app_web_router`, include
# its APIRouter so routes defined there (e.g. /settings/start-bot) are
# available on the canonical `app.web.router` used by the app factory.
try:
	from app.web.app_web_router import router as _impl_router
	router.include_router(_impl_router)
except Exception:
	pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _templates(request: Request):
	return request.app.state.templates


def _fmt_interval(seconds: int) -> str:
	if seconds < 60:
		return f"{seconds}s"
	return f"{seconds // 60}m{seconds % 60:02d}s"


# ---------------------------------------------------------------------------
# Re-export / alias helpers
# ---------------------------------------------------------------------------
try:
	from app.web.app_web_router import import_monitors as _impl_import_monitors
except Exception:
	_impl_import_monitors = None


if _impl_import_monitors:
	async def import_monitors(request, raw_text: str = "", db: AsyncSession = None, user: User = None, import_file=None):
		"""Wrapper that delegates to `app.web.app_web_router.import_monitors`.

		When tests patch `app.web.router.get_scheduler`, they patch the name
		in this module. The implementation in `app_web_router` resolves the
		`get_scheduler` name from its own globals, so we temporarily inject
		this module's `get_scheduler` into the implementation's globals so
		test patches take effect.
		"""
		orig = _impl_import_monitors.__globals__.get("get_scheduler")
		_impl_import_monitors.__globals__["get_scheduler"] = get_scheduler
		try:
			return await _impl_import_monitors(request, raw_text, db, user, import_file)
		finally:
			if orig is None:
				# restore to original (delete key) to avoid side-effects
				_impl_import_monitors.__globals__.pop("get_scheduler", None)
			else:
				_impl_import_monitors.__globals__["get_scheduler"] = orig


async def _get_db_setting(db: AsyncSession, key: str, default: str = "") -> str:
	result = await db.execute(select(AppSettings).where(AppSettings.key == key))
	row = result.scalar_one_or_none()
	return row.value if row else default


async def _set_db_setting(db: AsyncSession, key: str, value: str) -> None:
	result = await db.execute(select(AppSettings).where(AppSettings.key == key))
	row = result.scalar_one_or_none()
	if row:
		row.value = value
	else:
		db.add(AppSettings(key=key, value=value))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def dashboard(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	"""Main dashboard with statistics and live console."""
	today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

	active_count_q = await db.execute(
		select(func.count()).select_from(Monitor)
		.where(Monitor.user_id == user.id, Monitor.is_active == True)  # noqa: E712
	)
	active_count = active_count_q.scalar() or 0

	today_items_q = await db.execute(
		select(func.count()).select_from(FoundItem)
		.join(Monitor, FoundItem.monitor_id == Monitor.id)
		.where(Monitor.user_id == user.id, FoundItem.found_at >= today_start)
	)
	today_items = today_items_q.scalar() or 0

	total_items_q = await db.execute(
		select(func.count()).select_from(FoundItem)
		.join(Monitor, FoundItem.monitor_id == Monitor.id)
		.where(Monitor.user_id == user.id)
	)
	total_items = total_items_q.scalar() or 0

	last_found_q = await db.execute(
		select(func.max(FoundItem.found_at))
		.join(Monitor, FoundItem.monitor_id == Monitor.id)
		.where(Monitor.user_id == user.id)
	)
	last_found = last_found_q.scalar()

	return _templates(request).TemplateResponse(
		request,
		"dashboard.html",
		{
			"request": request,
			"user": user,
			"active_count": active_count,
			"today_items": today_items,
			"total_items": total_items,
			"last_found": last_found,
		},
	)


@router.get("/api/stats")
async def api_stats(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	"""JSON stats for the dashboard cards / HTMX polling."""
	today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

	active_count = (await db.execute(
		select(func.count()).select_from(Monitor)
		.where(Monitor.user_id == user.id, Monitor.is_active == True)  # noqa: E712
	)).scalar() or 0

	today_items = (await db.execute(
		select(func.count()).select_from(FoundItem)
		.join(Monitor, FoundItem.monitor_id == Monitor.id)
		.where(Monitor.user_id == user.id, FoundItem.found_at >= today_start)
	)).scalar() or 0

	total_items = (await db.execute(
		select(func.count()).select_from(FoundItem)
		.join(Monitor, FoundItem.monitor_id == Monitor.id)
		.where(Monitor.user_id == user.id)
	)).scalar() or 0

	return JSONResponse({
		"active_count": active_count,
		"today_items": today_items,
		"total_items": total_items,
	})


# ---------------------------------------------------------------------------
# Monitors – list
# ---------------------------------------------------------------------------

@router.get("/monitors", response_class=HTMLResponse)
async def monitors_list(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	result = await db.execute(
		select(Monitor)
		.where(Monitor.user_id == user.id)
		.order_by(Monitor.created_at.desc())
	)
	monitors = result.scalars().all()

	return _templates(request).TemplateResponse(
		request,
		"monitors/list.html",
		{"request": request, "user": user, "monitors": monitors},
	)


# ---------------------------------------------------------------------------
# Monitors – create
# ---------------------------------------------------------------------------

@router.get("/monitors/new", response_class=HTMLResponse)
async def monitor_new_form(
	request: Request,
	user: User = Depends(require_user),
):
	return _templates(request).TemplateResponse(
		request,
		"monitors/form.html",
		{
			"request": request,
			"user": user,
			"monitor": None,
			"domains": VINTED_DOMAINS,
			"selected_domains": list(VINTED_DOMAINS.keys()),
			"error": None,
		},
	)


@router.post("/monitors", response_class=HTMLResponse)
async def monitor_create(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
	name: str = Form(...),
	url: str = Form(...),
	interval_sec: int = Form(120),
):
	form_data = await request.form()
	domains: list[str] = form_data.getlist("domains")

	if not domains:
		suggested = extract_domains_from_url(url)
		domains = suggested if suggested else list(VINTED_DOMAINS.keys())

	# Validate domains
	domains = [d for d in domains if d in VINTED_DOMAINS]
	if not domains:
		return _templates(request).TemplateResponse(
			request,
			"monitors/form.html",
			{
				"request": request,
				"user": user,
				"monitor": None,
				"domains": VINTED_DOMAINS,
				"selected_domains": [],
				"error": "Выберите хотя бы один домен",
			},
			status_code=422,
		)

	try:
		params = parse_vinted_url(url)
	except Exception as exc:
		logger.warning("URL parse error: %s", exc)
		params = {}

	params["_original_interval"] = interval_sec

	monitor = Monitor(
		user_id=user.id,
		name=name.strip(),
		original_url=url,
		params_json=json.dumps(params),
		domains_json=json.dumps(domains),
		interval_sec=interval_sec,
		is_active=True,
	)
	db.add(monitor)
	await db.commit()
	await db.refresh(monitor)

	# Register with scheduler
	scheduler = get_scheduler(request)
	if scheduler:
		scheduler.add_monitor(monitor.id, interval_sec)
		logger.info("Scheduled new monitor id=%d", monitor.id)

	return RedirectResponse(url="/monitors", status_code=303)


# ---------------------------------------------------------------------------
# Monitors – edit
# ---------------------------------------------------------------------------

@router.get("/monitors/{monitor_id}/edit", response_class=HTMLResponse)
async def monitor_edit_form(
	monitor_id: int,
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	result = await db.execute(
		select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
	)
	monitor = result.scalar_one_or_none()
	if monitor is None:
		raise HTTPException(status_code=404, detail="Monitor not found")

	selected_domains = json.loads(monitor.domains_json)
	return _templates(request).TemplateResponse(
		request,
		"monitors/form.html",
		{
			"request": request,
			"user": user,
			"monitor": monitor,
			"domains": VINTED_DOMAINS,
			"selected_domains": selected_domains,
			"error": None,
		},
	)


@router.post("/monitors/{monitor_id}/edit", response_class=HTMLResponse)
async def monitor_update(
	monitor_id: int,
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
	name: str = Form(...),
	url: str = Form(...),
	interval_sec: int = Form(120),
):
	result = await db.execute(
		select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
	)
	monitor = result.scalar_one_or_none()
	if monitor is None:
		raise HTTPException(status_code=404, detail="Monitor not found")

	form_data = await request.form()
	domains: list[str] = form_data.getlist("domains")
	domains = [d for d in domains if d in VINTED_DOMAINS]
	if not domains:
		domains = json.loads(monitor.domains_json)

	is_active_val = form_data.get("is_active")
	is_active = is_active_val in ("true", "on", "1", True)

	try:
		params = parse_vinted_url(url)
	except Exception:
		params = json.loads(monitor.params_json)

	params["_original_interval"] = interval_sec

	monitor.name = name.strip()
	monitor.original_url = url
	monitor.params_json = json.dumps(params)
	monitor.domains_json = json.dumps(domains)
	monitor.interval_sec = interval_sec
	monitor.is_active = is_active
	await db.commit()

	scheduler = get_scheduler(request)
	if scheduler:
		if is_active:
			scheduler.update_monitor(monitor.id, interval_sec)
		else:
			scheduler.remove_monitor(monitor.id)

	return RedirectResponse(url="/monitors", status_code=303)


# ---------------------------------------------------------------------------
# Monitors – delete
# ---------------------------------------------------------------------------

@router.post("/monitors/{monitor_id}/delete")
async def monitor_delete(
	monitor_id: int,
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	result = await db.execute(
		select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
	)
	monitor = result.scalar_one_or_none()
	if monitor is None:
		raise HTTPException(status_code=404, detail="Monitor not found")

	scheduler = get_scheduler(request)
	if scheduler:
		scheduler.remove_monitor(monitor_id)

	await db.delete(monitor)
	await db.commit()
	return RedirectResponse(url="/monitors", status_code=303)


@router.post("/monitors/bulk-delete")
async def monitor_bulk_delete(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	form_data = await request.form()
	raw_ids = form_data.getlist("monitor_ids")
	monitor_ids = []
	for raw in raw_ids:
		try:
			monitor_ids.append(int(raw))
		except (ValueError, TypeError):
			pass

	if not monitor_ids:
		return RedirectResponse(url="/monitors", status_code=303)

	result = await db.execute(
		select(Monitor).where(
			Monitor.id.in_(monitor_ids),
			Monitor.user_id == user.id,
		)
	)
	monitors = result.scalars().all()

	scheduler = get_scheduler(request)
	for monitor in monitors:
		if scheduler:
			scheduler.remove_monitor(monitor.id)
		await db.delete(monitor)

	await db.commit()
	return RedirectResponse(url="/monitors", status_code=303)


# ---------------------------------------------------------------------------
# Import / Export
# ---------------------------------------------------------------------------

@router.get("/export/json")
async def export_json(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	result = await db.execute(
		select(Monitor).where(Monitor.user_id == user.id).order_by(Monitor.created_at)
	)
	monitors = result.scalars().all()
	data = [
		{
			"name": m.name,
			"url": m.original_url,
			"domains": json.loads(m.domains_json),
			"interval_sec": m.interval_sec,
			"is_active": m.is_active,
		}
		for m in monitors
	]
	return JSONResponse(content=data)


@router.get("/export/txt", response_class=PlainTextResponse)
async def export_txt(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	result = await db.execute(
		select(Monitor).where(Monitor.user_id == user.id).order_by(Monitor.created_at)
	)
	monitors = result.scalars().all()
	lines = [m.original_url for m in monitors]
	return PlainTextResponse("\n".join(lines))


@router.post("/monitors/import", response_class=HTMLResponse)
async def monitor_import(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
	import_data: str = Form(default=""),
	import_file: UploadFile | None = File(default=None),
):
	"""Import monitors from JSON blob or TXT URL list."""
	content = import_data.strip()

	if import_file and import_file.filename:
		raw = await import_file.read()
		content = raw.decode("utf-8", errors="replace").strip()

	if not content:
		return RedirectResponse(url="/monitors", status_code=303)

	created = 0
	scheduler = get_scheduler(request)

	# Try JSON first
	if content.startswith("[") or content.startswith("{"):
		try:
			payload = json.loads(content)
			if isinstance(payload, dict):
				payload = [payload]
			for item in payload:
				if not isinstance(item, dict):
					continue
				url = item.get("url", "")
				if not url:
					continue
				name = item.get("name") or url[:60]
				domains = item.get("domains") or list(VINTED_DOMAINS.keys())
				domains = [d for d in domains if d in VINTED_DOMAINS]
				interval_sec = int(item.get("interval_sec", 120))
				params = parse_vinted_url(url)
				params["_original_interval"] = interval_sec
				monitor = Monitor(
					user_id=user.id,
					name=name,
					original_url=url,
					params_json=json.dumps(params),
					domains_json=json.dumps(domains),
					interval_sec=interval_sec,
					is_active=item.get("is_active", True),
				)
				db.add(monitor)
				await db.flush()
				if scheduler and monitor.is_active:
					scheduler.add_monitor(monitor.id, interval_sec)
				created += 1
			await db.commit()
		except Exception as exc:
			logger.warning("JSON import error: %s", exc)
	else:
		# Plain-text URL list
		for line in content.splitlines():
			url = line.strip()
			if not url or not url.startswith("http"):
				continue
			params = parse_vinted_url(url)
			interval_sec = 120
			params["_original_interval"] = interval_sec
			domains = list(VINTED_DOMAINS.keys())
			monitor = Monitor(
				user_id=user.id,
				name=url[:60],
				original_url=url,
				params_json=json.dumps(params),
				domains_json=json.dumps(domains),
				interval_sec=interval_sec,
				is_active=True,
			)
			db.add(monitor)
			await db.flush()
			if scheduler and monitor.is_active:
				logger.debug("import_monitors: adding monitor to scheduler id=%s interval=%s scheduler=%s", monitor.id, interval_sec, bool(scheduler))
				scheduler.add_monitor(monitor.id, interval_sec)
			created += 1
		await db.commit()

	logger.info("Imported %d monitors for user %s", created, user.username)
	return RedirectResponse(url="/monitors", status_code=303)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	bot_running = web_deps.is_bot_running(user.telegram_bot_token) if user.telegram_bot_token else False
	return _templates(request).TemplateResponse(
		request,
		"settings.html",
		{
			"request": request,
			"user": user,
			"bot_running": bot_running,
			"saved": False,
		},
	)

@router.post("/settings", response_class=HTMLResponse)
async def settings_save(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
	telegram_token: str = Form(default=""),
	telegram_chat_id: str = Form(default=""),
	proxies: str = Form(default=""),
	sessions_per_domain: int = Form(default=3),
	rate_limit_per_minute: int = Form(default=8),
):
	old_token = user.telegram_bot_token

	if telegram_token:
		user.telegram_bot_token = telegram_token.strip()
	if telegram_chat_id:
		user.telegram_chat_id = telegram_chat_id.strip()

	await db.commit()

	# Restart bot if token changed
	if old_token and old_token != user.telegram_bot_token:
		await stop_bot(old_token)

	bot_running = web_deps.is_bot_running(user.telegram_bot_token) if user.telegram_bot_token else False
	return _templates(request).TemplateResponse(
		request,
		"settings.html",
		{
			"request": request,
			"user": user,
			"bot_running": bot_running,
			"saved": True,
		},
	)

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

