# app/web/router.py
import json
import logging
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, FoundItem, InviteCode, Monitor, User
from app.scraper.domains import VINTED_DOMAINS
from app.scraper.url_parser import parse_vinted_url
from app.web.auth import require_admin, require_user
from app.web.dependencies import get_db, get_scheduler, is_bot_running, settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    active_count_result = await db.execute(
        select(func.count(Monitor.id)).where(
            Monitor.is_active == True, Monitor.user_id == user.id
        )
    )
    active_count = active_count_result.scalar() or 0

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    user_monitor_ids = select(Monitor.id).where(Monitor.user_id == user.id)
    today_items_result = await db.execute(
        select(func.count(FoundItem.id)).where(
            FoundItem.found_at >= today_start,
            FoundItem.monitor_id.in_(user_monitor_ids),
        )
    )
    today_items = today_items_result.scalar() or 0

    total_result = await db.execute(
        select(func.count(FoundItem.id)).where(
            FoundItem.monitor_id.in_(user_monitor_ids)
        )
    )
    total_items = total_result.scalar() or 0

    last_item_result = await db.execute(
        select(FoundItem.found_at)
        .where(FoundItem.monitor_id.in_(user_monitor_ids))
        .order_by(desc(FoundItem.found_at))
        .limit(1)
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
            "user": user,
        },
    )


@router.get("/monitors", response_class=HTMLResponse)
async def monitors_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    result = await db.execute(
        select(Monitor)
        .where(Monitor.user_id == user.id)
        .order_by(desc(Monitor.created_at))
    )
    monitors = result.scalars().all()
    return request.app.state.templates.TemplateResponse(
        request,
        "monitors/list.html",
        {"request": request, "monitors": monitors, "user": user},
    )


@router.get("/monitors/new", response_class=HTMLResponse)
async def monitor_new(request: Request, user: User = Depends(require_user)):
    return request.app.state.templates.TemplateResponse(
        request,
        "monitors/form.html",
        {
            "request": request,
            "monitor": None,
            "domains": VINTED_DOMAINS,
            "selected_domains": [],
            "user": user,
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
    domains: list[str] = Form(default=[]),
):
    parsed = parse_vinted_url(url)
    api_params = parsed["params"]
    api_params["_original_interval"] = interval_sec

    monitor = Monitor(
        user_id=user.id,
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
    user: User = Depends(require_user),
):
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
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
            "user": user,
        },
    )


@router.post("/monitors/{monitor_id}/edit", response_class=HTMLResponse)
async def monitor_update(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
    name: str = Form(...),
    url: str = Form(...),
    interval_sec: int = Form(120),
    is_active: bool = Form(True),
    domains: list[str] = Form(default=[]),
):
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    parsed = parse_vinted_url(url)
    api_params = parsed["params"]
    api_params["_original_interval"] = interval_sec

    # Reset baseline if search parameters changed
    new_params_json = json.dumps(api_params)
    new_domains_json = json.dumps(domains)
    if monitor.params_json != new_params_json or monitor.domains_json != new_domains_json:
        # Purge pending notifications for this monitor because criteria changed
        from sqlalchemy import delete
        await db.execute(
            delete(FoundItem).where(
                FoundItem.monitor_id == monitor_id,
                FoundItem.notified == False
            )
        )
        monitor.last_check_at = None
        monitor.items_found_count = 0

    monitor.name = name
    monitor.original_url = url
    monitor.params_json = new_params_json
    monitor.domains_json = new_domains_json
    monitor.interval_sec = interval_sec
    monitor.is_active = is_active
    await db.commit()

    try:
        scheduler = get_scheduler()
        scheduler.update_monitor(monitor_id, interval_sec)
    except RuntimeError:
        logger.warning("Scheduler not available, monitor job not updated")

    return RedirectResponse(url="/monitors", status_code=303)


@router.post("/monitors/{monitor_id}/delete", response_class=Response)
async def monitor_delete(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    from sqlalchemy import delete
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    await db.execute(delete(FoundItem).where(FoundItem.monitor_id == monitor_id))
    await db.delete(monitor)
    await db.commit()

    try:
        scheduler = get_scheduler()
        scheduler.remove_monitor(monitor_id)
    except RuntimeError:
        logger.warning("Scheduler not available, monitor job not removed")

    return Response(status_code=204)



@router.post("/monitors/{monitor_id}/toggle", response_class=HTMLResponse)
async def monitor_toggle(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
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
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    result = await db.execute(select(AppSettings))
    settings_map: dict[str, str] = {row.key: row.value for row in result.scalars().all()}

    return request.app.state.templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "settings": settings_map,
            "user": user,
            "bot_running": is_bot_running(user.telegram_bot_token),
        },
    )


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
    telegram_token: str = Form(""),
    telegram_chat_id: str = Form(""),
    proxies: str = Form(""),
    sessions_per_domain: int = Form(3),
    rate_limit_per_minute: int = Form(8),
):
    telegram_token = telegram_token.strip()
    telegram_chat_id = telegram_chat_id.strip()
    
    # Update user-specific Telegram config
    user.telegram_bot_token = telegram_token
    user.telegram_chat_id = telegram_chat_id

    # Store global config in AppSettings
    global_settings = {
        "proxies": proxies,
        "sessions_per_domain": str(sessions_per_domain),
        "rate_limit_per_minute": str(rate_limit_per_minute),
    }

    for key, value in global_settings.items():
        existing = await db.get(AppSettings, key)
        if existing is None:
            db.add(AppSettings(key=key, value=value))
        else:
            existing.value = value
    
    await db.commit()
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/test-bot")
async def settings_test_bot(
    telegram_token: str = Form(...),
    telegram_chat_id: str = Form(...),
):
    from app.web.dependencies import send_test_message
    return await send_test_message(telegram_token, telegram_chat_id)


@router.post("/settings/start-bot")
async def settings_start_bot(
    user: User = Depends(require_user),
    telegram_token: str = Form(...),
    telegram_chat_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.web.dependencies import start_bot
    # Save first to ensure it's in DB
    user.telegram_bot_token = telegram_token
    user.telegram_chat_id = telegram_chat_id
    await db.commit()
    
    return await start_bot(telegram_token, owner_user_id=user.id)


@router.post("/settings/stop-bot")
async def settings_stop_bot(
    user: User = Depends(require_user),
):
    from app.web.dependencies import stop_bot
    return await stop_bot(user.telegram_bot_token)

@router.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
    page: int = Query(1, ge=1),
    monitor_id: int | None = Query(None),
):
    per_page = 50
    # FIX: Scoping logs query to user's monitors
    user_monitor_ids = select(Monitor.id).where(Monitor.user_id == user.id).scalar_subquery()

    query = (
        select(FoundItem)
        .where(FoundItem.monitor_id.in_(user_monitor_ids))
        .order_by(desc(FoundItem.found_at))
    )
    count_query = select(func.count(FoundItem.id)).where(
        FoundItem.monitor_id.in_(user_monitor_ids)
    )

    if monitor_id is not None:
        query = query.where(FoundItem.monitor_id == monitor_id)
        count_query = count_query.where(FoundItem.monitor_id == monitor_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    offset = (page - 1) * per_page
    items_result = await db.execute(query.offset(offset).limit(per_page))
    items = items_result.scalars().all()

    monitors_result = await db.execute(
        select(Monitor.id, Monitor.name).where(Monitor.user_id == user.id)
    )
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
            "user": user,
        },
    )


@router.get("/export", response_class=Response)
async def export_monitors(
    format: str = Query("json"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    result = await db.execute(
        select(Monitor).where(Monitor.user_id == user.id)
    )
    monitors = result.scalars().all()
    
    if format == "json":
        data = [
            {
                "name": m.name,
                "url": m.original_url,
                "interval": m.interval_sec,
                "domains": json.loads(m.domains_json)
            }
            for m in monitors
        ]
        content = json.dumps(data, indent=2, ensure_ascii=False)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="monitors.json"'}
        )
    else:
        lines = [m.original_url for m in monitors]
        content = "\n".join(lines)
        return Response(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": 'attachment; filename="monitors.txt"'}
        )


@router.post("/import")
async def import_monitors(
    request: Request,
    raw_text: str = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    import_data = []
    
    # Check if a file was uploaded
    try:
        form = await request.form()
    except TypeError:
        # Fallback for sync-mocked requests in tests
        form = await request.form() if asyncio.iscoroutinefunction(request.form) else request.form()
    file = form.get("file")
    
    if file and hasattr(file, "filename") and file.filename:
        content = await file.read()
        text_content = content.decode("utf-8")
        if file.filename.endswith(".json"):
            try:
                import_data = json.loads(text_content)
            except json.JSONDecodeError:
                return RedirectResponse(url="/monitors?error=Invalid+JSON", status_code=303)
        else:
            import_data = [{"url": line.strip()} for line in text_content.splitlines() if line.strip()]
    elif raw_text:
        import_data = [{"url": line.strip()} for line in raw_text.splitlines() if line.strip()]

    if not import_data:
        return RedirectResponse(url="/monitors?error=No+data+to+import", status_code=303)

    from app.scraper.url_parser import parse_vinted_url
    
    scheduler = get_scheduler()
    results = {"added": [], "duplicates": [], "errors": []}
    
    for entry in import_data:
        if isinstance(entry, str):
            url = entry.strip()
            name = None
            interval = settings.check_interval_seconds
        else:
            url = entry.get("url")
            name = entry.get("name")
            interval = int(entry.get("interval") or settings.check_interval_seconds)

        if not url: continue
        
        try:
            parsed = parse_vinted_url(url)
            final_name = name or f"Imported {datetime.now().strftime('%H:%M:%S')}"
            
            # Prevent duplicates for the same user
            exists = await db.execute(
                select(Monitor).where(Monitor.user_id == user.id, Monitor.original_url == url)
            )
            if exists.scalar_one_or_none():
                results["duplicates"].append(url)
                continue

            new_monitor = Monitor(
                user_id=user.id,
                name=final_name,
                original_url=url,
                params_json=json.dumps(parsed["params"]),
                domains_json=json.dumps([parsed["domain"]]),
                interval_sec=interval,
                is_active=True,
            )
            db.add(new_monitor)
            await db.flush() # Get ID
            
            try:
                scheduler.add_monitor(new_monitor.id, new_monitor.interval_sec)
            except Exception:
                logger.warning("Failed to add imported monitor to scheduler")
                
            results["added"].append({"name": final_name, "url": url})
        except Exception:
            logger.exception("Failed to import URL: %s", url)
            results["errors"].append(url)
            continue
            
    await db.commit()
    return request.app.state.templates.TemplateResponse(
        request,
        "admin/import_summary.html",
        {"request": request, "results": results, "user": user}
    )


# --- Admin: Invite Code Management ---

@router.get("/admin/invites", response_class=HTMLResponse)
async def admin_invites_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    result = await db.execute(
        select(InviteCode).order_by(desc(InviteCode.created_at))
    )
    invites = result.scalars().all()
    return request.app.state.templates.TemplateResponse(
        request,
        "admin/invites.html",
        {"request": request, "invites": invites, "user": user},
    )


@router.post("/admin/invites")
async def admin_invite_create(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    code: str = Form(None),
    max_uses: int = Form(1),
):
    import secrets
    if not code:
        code = f"INV-{secrets.token_hex(4).upper()}"
    
    new_invite = InviteCode(
        code=code.strip(),
        max_uses=max_uses,
        created_by_id=user.id
    )
    db.add(new_invite)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Код уже существует")
        
    return RedirectResponse(url="/admin/invites", status_code=303)


@router.post("/admin/invites/{invite_id}/toggle")
async def admin_invite_toggle(
    invite_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    invite = await db.get(InviteCode, invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    
    invite.is_active = not invite.is_active
    await db.commit()
    return RedirectResponse(url="/admin/invites", status_code=303)


@router.delete("/admin/invites/{invite_id}")
async def admin_invite_delete(
    invite_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    invite = await db.get(InviteCode, invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    
    await db.delete(invite)
    await db.commit()
    return Response(status_code=204)
