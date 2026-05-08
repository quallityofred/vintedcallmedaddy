# app/web/router.py
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, FoundItem, Monitor
from app.scraper.domains import VINTED_DOMAINS
from app.scraper.url_parser import parse_vinted_url
from app.web.dependencies import get_db, get_scheduler

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    active_count_result = await db.execute(
        select(func.count(Monitor.id)).where(Monitor.is_active == True)
    )
    active_count = active_count_result.scalar() or 0

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_items_result = await db.execute(
        select(func.count(FoundItem.id)).where(FoundItem.found_at >= today_start)
    )
    today_items = today_items_result.scalar() or 0

    total_result = await db.execute(select(func.count(FoundItem.id)))
    total_items = total_result.scalar() or 0

    last_item_result = await db.execute(
        select(FoundItem.found_at).order_by(desc(FoundItem.found_at)).limit(1)
    )
    last_found = last_item_result.scalar_one_or_none()

    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "active_count": active_count,
            "today_items": today_items,
            "total_items": total_items,
            "last_found": last_found,
        },
    )


@router.get("/monitors", response_class=HTMLResponse)
async def monitors_list(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Monitor).order_by(desc(Monitor.created_at)))
    monitors = result.scalars().all()
    return request.app.state.templates.TemplateResponse(
        request,
        "monitors/list.html",
        {"request": request, "monitors": monitors},
    )


@router.get("/monitors/new", response_class=HTMLResponse)
async def monitor_new(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "monitors/form.html",
        {
            "request": request,
            "monitor": None,
            "domains": VINTED_DOMAINS,
            "selected_domains": [],
        },
    )


@router.post("/monitors", response_class=HTMLResponse)
async def monitor_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    url: str = Form(...),
    interval_sec: int = Form(120),
    domains: list[str] = Form(default=[]),
):
    parsed = parse_vinted_url(url)
    api_params = parsed["params"]
    api_params["_original_interval"] = interval_sec

    monitor = Monitor(
        name=name,
        original_url=url,
        params_json=json.dumps(api_params),
        domains_json=json.dumps(domains),
        interval_sec=interval_sec,
        is_active=True,
    )
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)

    try:
        scheduler = get_scheduler()
        scheduler.add_monitor(monitor.id, interval_sec)
    except RuntimeError:
        logger.warning("Scheduler not available, monitor job not added")

    return RedirectResponse(url="/monitors", status_code=303)


@router.get("/monitors/{monitor_id}/edit", response_class=HTMLResponse)
async def monitor_edit(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    selected_domains = json.loads(monitor.domains_json)
    return request.app.state.templates.TemplateResponse(
        request,
        "monitors/form.html",
        {
            "request": request,
            "monitor": monitor,
            "domains": VINTED_DOMAINS,
            "selected_domains": selected_domains,
        },
    )


@router.post("/monitors/{monitor_id}/edit", response_class=HTMLResponse)
async def monitor_update(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    url: str = Form(...),
    interval_sec: int = Form(120),
    is_active: bool = Form(True),
    domains: list[str] = Form(default=[]),
):
    result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    parsed = parse_vinted_url(url)
    api_params = parsed["params"]
    api_params["_original_interval"] = interval_sec

    monitor.name = name
    monitor.original_url = url
    monitor.params_json = json.dumps(api_params)
    monitor.domains_json = json.dumps(domains)
    monitor.interval_sec = interval_sec
    monitor.is_active = is_active
    await db.commit()

    try:
        scheduler = get_scheduler()
        scheduler.update_monitor(monitor_id, interval_sec)
    except RuntimeError:
        logger.warning("Scheduler not available, monitor job not updated")

    return RedirectResponse(url="/monitors", status_code=303)


@router.delete("/monitors/{monitor_id}")
async def monitor_delete(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    await db.delete(monitor)
    await db.commit()

    try:
        scheduler = get_scheduler()
        scheduler.remove_monitor(monitor_id)
    except RuntimeError:
        logger.warning("Scheduler not available, monitor job not removed")

    return Response(status_code=200)


@router.post("/monitors/{monitor_id}/toggle", response_class=HTMLResponse)
async def monitor_toggle(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    monitor.is_active = not monitor.is_active
    await db.commit()

    return request.app.state.templates.TemplateResponse(
        request,
        "monitors/partials/monitor_row.html",
        {"request": request, "monitor": monitor},
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AppSettings))
    settings_map: dict[str, str] = {row.key: row.value for row in result.scalars().all()}

    return request.app.state.templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "settings": settings_map,
        },
    )


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    db: AsyncSession = Depends(get_db),
    telegram_token: str = Form(""),
    telegram_chat_id: str = Form(""),
    proxies: str = Form(""),
    sessions_per_domain: int = Form(3),
    rate_limit_per_minute: int = Form(8),
):
    settings_data = {
        "telegram_bot_token": telegram_token,
        "telegram_chat_id": telegram_chat_id,
        "proxies": proxies,
        "sessions_per_domain": str(sessions_per_domain),
        "rate_limit_per_minute": str(rate_limit_per_minute),
    }

    for key, value in settings_data.items():
        existing = await db.get(AppSettings, key)
        if existing is None:
            db.add(AppSettings(key=key, value=value))
        else:
            existing.value = value
    await db.commit()

    return RedirectResponse(url="/settings", status_code=303)


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    monitor_id: int | None = Query(None),
):
    per_page = 50
    query = select(FoundItem).order_by(desc(FoundItem.found_at))
    count_query = select(func.count(FoundItem.id))

    if monitor_id is not None:
        query = query.where(FoundItem.monitor_id == monitor_id)
        count_query = count_query.where(FoundItem.monitor_id == monitor_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    offset = (page - 1) * per_page
    items_result = await db.execute(query.offset(offset).limit(per_page))
    items = items_result.scalars().all()

    monitors_result = await db.execute(select(Monitor.id, Monitor.name))
    monitors_map: dict[int, str] = {row[0]: row[1] for row in monitors_result.fetchall()}

    return request.app.state.templates.TemplateResponse(
        request,
        "logs.html",
        {
            "request": request,
            "items": items,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "monitor_id": monitor_id,
            "monitors_map": monitors_map,
        },
    )
