
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
from app.models import FoundItem, Monitor, User
from app.runtime_settings import (
	apply_global_settings_to_runtime,
	load_global_settings,
	mask_secret,
	save_global_settings,
)
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
from app.web.csrf import require_csrf

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

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


@router.post("/monitors", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
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


@router.post("/monitors/{monitor_id}/edit", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
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

@router.post("/monitors/{monitor_id}/delete", dependencies=[Depends(require_csrf)])
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


@router.post("/monitors/bulk-delete", dependencies=[Depends(require_csrf)])
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


@router.post("/monitors/import", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
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
	global_settings = await load_global_settings(db)
	return _templates(request).TemplateResponse(
		request,
		"settings.html",
		{
			"request": request,
			"user": user,
			"bot_running": bot_running,
			"saved": False,
			"settings": global_settings,
			"telegram_token_masked": mask_secret(user.telegram_bot_token),
			"telegram_chat_id_masked": mask_secret(user.telegram_chat_id),
			"telegram_token_configured": bool(user.telegram_bot_token),
			"telegram_chat_id_configured": bool(user.telegram_chat_id),
			"can_edit_global_settings": user.is_admin,
			"settings_error": None,
		},
	)

@router.post("/settings", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
async def settings_save(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
	telegram_token: str = Form(default=""),
	telegram_chat_id: str = Form(default=""),
	proxies: str = Form(default=""),
	sessions_per_domain: int = Form(default=3),
	rate_limit_per_minute: int = Form(default=8),
	cf_worker_url: str = Form(default=""),
	cf_worker_block_threshold: int = Form(default=2),
	cf_worker_recovery_minutes: int = Form(default=10),
	check_interval_seconds: int = Form(default=120),
	offpeak_interval_multiplier: float = Form(default=2.5),
	night_interval_multiplier: float = Form(default=5.0),
	peak_start_hour: int = Form(default=8),
	peak_end_hour: int = Form(default=23),
):
	old_token = user.telegram_bot_token

	if telegram_token.strip():
		user.telegram_bot_token = telegram_token.strip()
	if telegram_chat_id.strip():
		user.telegram_chat_id = telegram_chat_id.strip()

	settings_error = None
	global_settings = await load_global_settings(db)
	if user.is_admin:
		try:
			global_settings = await save_global_settings(
				db,
				{
					"proxies": proxies,
					"sessions_per_domain": sessions_per_domain,
					"rate_limit_per_minute": rate_limit_per_minute,
					"cf_worker_url": cf_worker_url,
					"cf_worker_block_threshold": cf_worker_block_threshold,
					"cf_worker_recovery_minutes": cf_worker_recovery_minutes,
					"check_interval_seconds": check_interval_seconds,
					"offpeak_interval_multiplier": offpeak_interval_multiplier,
					"night_interval_multiplier": night_interval_multiplier,
					"peak_start_hour": peak_start_hour,
					"peak_end_hour": peak_end_hour,
				},
			)
		except ValueError as exc:
			settings_error = str(exc)

	await db.commit()
	if user.is_admin and settings_error is None:
		await apply_global_settings_to_runtime(global_settings, get_scraper_client(request))

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
			"saved": settings_error is None,
			"settings": global_settings,
			"telegram_token_masked": mask_secret(user.telegram_bot_token),
			"telegram_chat_id_masked": mask_secret(user.telegram_chat_id),
			"telegram_token_configured": bool(user.telegram_bot_token),
			"telegram_chat_id_configured": bool(user.telegram_chat_id),
			"can_edit_global_settings": user.is_admin,
			"settings_error": settings_error,
		},
		status_code=422 if settings_error else 200,
	)

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

@router.get("/logs", response_class=HTMLResponse)
async def logs_page(
	request: Request,
	page: int = 1,
	user: User = Depends(require_user),
):
	per_page = 100
	all_logs = log_manager.get_user_logs(user.id)
	total = len(all_logs)
	start = (page - 1) * per_page
	page_logs = list(reversed(all_logs))[start: start + per_page]
	total_pages = max(1, (total + per_page - 1) // per_page)

	return _templates(request).TemplateResponse(
		request,
		"logs.html",
		{
			"request": request,
			"user": user,
			"logs": page_logs,
			"page": page,
			"total_pages": total_pages,
			"total": total,
		},
	)


@router.get("/api/logs")
async def api_logs(
	request: Request,
	limit: int = 100,
	user: User = Depends(require_user),
):
	"""Return recent logs as JSON array (newest first)."""
	limit = max(1, min(limit, 500))
	logs = list(reversed(log_manager.get_user_logs(user.id)))[:limit]
	system = list(reversed(log_manager.get_system_logs()))[:20] if user.is_admin else []
	return JSONResponse({"logs": logs, "system": system})


# ---------------------------------------------------------------------------
# Bot management API
# ---------------------------------------------------------------------------

@router.post("/api/bot/start", dependencies=[Depends(require_csrf)])
async def api_bot_start(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	if not user.telegram_bot_token:
		return JSONResponse({"ok": False, "message": "РўРѕРєРµРЅ РЅРµ Р·Р°РґР°РЅ"}, status_code=400)
	msg = await start_bot(user.telegram_bot_token, owner_user_id=user.id)
	return JSONResponse({"ok": True, "message": msg})


@router.post("/api/bot/stop", dependencies=[Depends(require_csrf)])
async def api_bot_stop(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	if not user.telegram_bot_token:
		return JSONResponse({"ok": False, "message": "РўРѕРєРµРЅ РЅРµ Р·Р°РґР°РЅ"}, status_code=400)
	await stop_bot(user.telegram_bot_token)
	return JSONResponse({"ok": True, "message": "Р‘РѕС‚ РѕСЃС‚Р°РЅРѕРІР»РµРЅ"})


@router.post("/api/bot/test", dependencies=[Depends(require_csrf)])
async def api_bot_test(
	request: Request,
	user: User = Depends(require_user),
):
	"""Send a test Telegram message to the user's saved chat."""
	return await _send_test_message(user.telegram_bot_token, user.telegram_chat_id)


@router.post("/settings/test-bot", dependencies=[Depends(require_csrf)])
async def settings_test_bot(
	request: Request,
	user: User = Depends(require_user),
	telegram_token: str = Form(default=""),
	telegram_chat_id: str = Form(default=""),
):
	"""Send a test Telegram message with submitted settings without saving them."""
	token = telegram_token.strip() or user.telegram_bot_token
	chat_id = telegram_chat_id.strip() or user.telegram_chat_id
	return await _send_test_message(token, chat_id)


async def _send_test_message(token: str, chat_id: str):
	if not token or not chat_id:
		return JSONResponse({"ok": False, "message": "Р‘РѕС‚ РЅРµ РЅР°СЃС‚СЂРѕРµРЅ"}, status_code=400)

	try:
		from app.telegram.bot import get_or_create_bot
		bot, _ = get_or_create_bot(token)
		await bot.send_message(
			int(chat_id),
			"вњ… <b>РўРµСЃС‚ РїСЂРѕР№РґРµРЅ!</b>\nVinted Monitor СЂР°Р±РѕС‚Р°РµС‚ РєРѕСЂСЂРµРєС‚РЅРѕ.",
			parse_mode="HTML",
		)
		return JSONResponse({"ok": True, "message": "РўРµСЃС‚ РѕС‚РїСЂР°РІР»РµРЅ"})
	except Exception as exc:
		return JSONResponse({"ok": False, "message": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------

@router.post("/api/monitors/{monitor_id}/trigger", dependencies=[Depends(require_csrf)])
async def api_monitor_trigger(
	monitor_id: int,
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	"""Manually trigger an immediate check for a monitor."""
	result = await db.execute(
		select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
	)
	monitor = result.scalar_one_or_none()
	if monitor is None:
		raise HTTPException(status_code=404, detail="Monitor not found")

	scheduler = get_scheduler(request)
	if scheduler and scheduler.trigger_now(monitor_id):
		return JSONResponse({"ok": True, "message": "РџСЂРѕРІРµСЂРєР° Р·Р°РїСѓС‰РµРЅР°"})
	return JSONResponse({"ok": False, "message": "РџР»Р°РЅРёСЂРѕРІС‰РёРє РЅРµРґРѕСЃС‚СѓРїРµРЅ"}, status_code=503)


# ---------------------------------------------------------------------------
# Settings bot controls
# ---------------------------------------------------------------------------

@router.post("/settings/start-bot", dependencies=[Depends(require_csrf)])
async def settings_start_bot(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
	telegram_token: str = Form(default=""),
	telegram_chat_id: str = Form(default=""),
):
	"""Save bot settings and start polling. Used by JS and tests."""
	submitted_token = telegram_token.strip()
	submitted_chat_id = telegram_chat_id.strip()
	effective_token = submitted_token or user.telegram_bot_token
	if not effective_token:
		return JSONResponse({"ok": False, "message": "РўРѕРєРµРЅ РЅРµ СѓРєР°Р·Р°РЅ"}, status_code=400)

	old_token = user.telegram_bot_token
	if submitted_token:
		user.telegram_bot_token = submitted_token
	if submitted_chat_id:
		user.telegram_chat_id = submitted_chat_id
	await db.commit()

	if old_token and old_token != user.telegram_bot_token:
		await stop_bot(old_token)

	if web_deps.is_bot_running(user.telegram_bot_token):
		return JSONResponse({"ok": True, "message": "Р‘РѕС‚ СѓР¶Рµ Р·Р°РїСѓС‰РµРЅ"})

	msg = await start_bot(user.telegram_bot_token, owner_user_id=user.id)
	return JSONResponse({"ok": True, "message": msg})


@router.post("/settings/stop-bot", dependencies=[Depends(require_csrf)])
async def settings_stop_bot(
	request: Request,
	db: AsyncSession = Depends(get_db),
	user: User = Depends(require_user),
):
	"""Stop the bot for the current user."""
	if not user.telegram_bot_token:
		return JSONResponse({"ok": False, "message": "РўРѕРєРµРЅ РЅРµ Р·Р°РґР°РЅ"}, status_code=400)
	await stop_bot(user.telegram_bot_token)
	return JSONResponse({"ok": True, "message": "Р‘РѕС‚ РѕСЃС‚Р°РЅРѕРІР»РµРЅ"})


# ---------------------------------------------------------------------------
# import_monitors alias for direct unit tests
# ---------------------------------------------------------------------------

async def import_monitors(
	request,
	raw_text: str = "",
	db: AsyncSession = None,
	user: User = None,
	import_file=None,
) -> None:
	content = (raw_text or "").strip()
	if not content:
		return

	scheduler = get_scheduler(request) if request else None
	created = 0

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
			logger.warning("import_monitors JSON error: %s", exc)
	else:
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
				scheduler.add_monitor(monitor.id, interval_sec)
			created += 1
		await db.commit()

	logger.info("import_monitors: created %d monitors", created)

