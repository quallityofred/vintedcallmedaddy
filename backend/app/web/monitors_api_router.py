from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Monitor, MonitorTelegramTopic, User, FoundItem
from app.scraper.domains import (
    get_unique_vinted_marketplaces,
    validate_selected_domains,
)
from app.scraper.url_parser import extract_domains_from_url, parse_vinted_url, normalize_vinted_monitor_url
from app.web.auth import get_current_user
from app.web.csrf import require_csrf
from app.web.dependencies import get_db, get_scheduler
from app.runtime_settings import mask_secret
from app.telegram.topic_service import ensure_monitor_topic, send_topic_test, topic_payload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/monitors", tags=["monitors"])


class MonitorResponse(BaseModel):
    id: int
    name: str
    original_url: str
    interval_sec: int
    is_active: bool
    last_check_at: Optional[datetime] = None
    last_check_status: Optional[str] = None
    is_stale_running: bool = False
    is_inconsistent_check_state: bool = False
    created_at: datetime
    updated_at: datetime
    items_found_count: int
    domains: List[str]

    model_config = ConfigDict(from_attributes=True)


class MonitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., pattern=r"^https?://")
    interval_sec: int = Field(120, ge=60, le=3600)
    domains: Optional[List[str]] = None


class MonitorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    url: Optional[str] = Field(None, pattern=r"^https?://")
    interval_sec: Optional[int] = Field(None, ge=60, le=3600)
    is_active: Optional[bool] = None
    domains: Optional[List[str]] = None


class BulkDeleteRequest(BaseModel):
    monitor_ids: List[int] = Field(..., min_length=1, max_length=100)


class BulkDeleteResponse(BaseModel):
    deleted_count: int
    not_found_or_forbidden_ids: List[int]


async def require_api_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _monitor_domains(monitor: Monitor) -> List[str]:
    try:
        domains = json.loads(monitor.domains_json or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(domains, list):
        return []

    return [domain for domain in domains if isinstance(domain, str)]


def _monitor_response(monitor: Monitor, items_found_count: int | None = None, is_running_in_registry: bool = False) -> dict[str, object]:
    from app.scheduler.monitor_status import reconcile_monitor_check_status
    recon = reconcile_monitor_check_status(monitor, is_running_in_registry)

    return {
        "id": monitor.id,
        "name": monitor.name,
        "original_url": monitor.original_url,
        "interval_sec": monitor.interval_sec,
        "is_active": monitor.is_active,
        "last_check_at": monitor.last_check_at,
        "last_check_status": recon["effective_status"],
        "is_stale_running": recon["is_stale_running"],
        "is_inconsistent_check_state": recon["is_inconsistent_check_state"],
        "created_at": monitor.created_at,
        "updated_at": monitor.updated_at,
        "items_found_count": items_found_count if items_found_count is not None else monitor.items_found_count,
        "domains": _monitor_domains(monitor),
    }


def _build_monitor_params(url: str, interval_sec: int) -> dict[str, object]:
    try:
        params = parse_vinted_url(url)
    except Exception as exc:
        logger.warning("URL parse error: %s", exc)
        raise HTTPException(status_code=400, detail="Could not parse monitor URL") from exc

    params["_original_interval"] = interval_sec
    return params


async def _get_owned_monitor(db: AsyncSession, user: User, monitor_id: int) -> Monitor:
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return monitor


async def _get_monitor_topic(db: AsyncSession, user: User, monitor_id: int) -> MonitorTelegramTopic | None:
    result = await db.execute(
        select(MonitorTelegramTopic)
        .where(MonitorTelegramTopic.monitor_id == monitor_id, MonitorTelegramTopic.user_id == user.id)
        .order_by(MonitorTelegramTopic.updated_at.desc())
    )
    return result.scalar_one_or_none()


def _monitor_topic_response(
    *,
    monitor_id: int,
    user: User,
    topic: MonitorTelegramTopic | None,
) -> dict[str, object]:
    return {
        "monitor_id": monitor_id,
        "enabled": user.telegram_topics_enabled,
        "topic": topic_payload(topic),
    }


@router.get("", response_model=List[MonitorResponse])
async def list_monitors(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """List all monitors for the current user with live found item counts."""
    result = await db.execute(
        select(Monitor)
        .where(Monitor.user_id == user.id)
        .order_by(Monitor.created_at.desc())
    )
    monitors = result.scalars().all()

    if not monitors:
        return []

    monitor_ids = [m.id for m in monitors]
    from app.scheduler.tasks import is_monitor_check_running
    counts_result = await db.execute(
        select(FoundItem.monitor_id, func.count(FoundItem.id))
        .where(FoundItem.monitor_id.in_(monitor_ids))
        .group_by(FoundItem.monitor_id)
    )
    counts = dict(counts_result.all())

    return [
        _monitor_response(
            monitor,
            items_found_count=counts.get(monitor.id, 0),
            is_running_in_registry=is_monitor_check_running(monitor.id)
        )
        for monitor in monitors
    ]


@router.get("/domains")
async def list_supported_domains():
    """List user-selectable unique Vinted marketplace representatives."""
    return get_unique_vinted_marketplaces()


@router.get("/telegram-topics")
async def list_monitor_telegram_topics(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Return stored topic mappings for all current-user monitors without Telegram side effects."""
    monitor_ids_result = await db.execute(select(Monitor.id).where(Monitor.user_id == user.id))
    monitor_ids = [row[0] for row in monitor_ids_result.all()]
    if not monitor_ids:
        return {"topics_enabled": user.telegram_topics_enabled, "topics": {}}

    topics_result = await db.execute(
        select(MonitorTelegramTopic)
        .where(
            MonitorTelegramTopic.user_id == user.id,
            MonitorTelegramTopic.monitor_id.in_(monitor_ids),
        )
        .order_by(MonitorTelegramTopic.updated_at.desc())
    )
    topics: dict[str, dict[str, object]] = {}
    for topic in topics_result.scalars().all():
        key = str(topic.monitor_id)
        if key in topics:
            continue
        payload = topic_payload(topic) or {}
        payload["monitor_id"] = topic.monitor_id
        payload["updated_at"] = topic.updated_at.isoformat() if topic.updated_at else None
        topics[key] = payload

    return {
        "topics_enabled": user.telegram_topics_enabled,
        "topics": topics,
    }


@router.get("/{monitor_id}", response_model=MonitorResponse)
async def get_monitor(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Get details of a specific monitor with live found item count."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    from app.scheduler.tasks import is_monitor_check_running
    is_running_in_registry = is_monitor_check_running(monitor_id)

    count = await db.scalar(
        select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id)
    )
    return _monitor_response(monitor, items_found_count=count or 0, is_running_in_registry=is_running_in_registry)


@router.post("", response_model=MonitorResponse, dependencies=[Depends(require_csrf)])
async def create_monitor(
    request: Request,
    data: MonitorCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Create a new monitor."""
    normalized_url = normalize_vinted_monitor_url(data.url)
    try:
        if data.domains is None:
            domains = validate_selected_domains(extract_domains_from_url(normalized_url))
        else:
            domains = validate_selected_domains(data.domains)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    params = _build_monitor_params(normalized_url, data.interval_sec)

    monitor = Monitor(
        user_id=user.id,
        name=data.name.strip(),
        original_url=normalized_url,
        params_json=json.dumps(params),
        domains_json=json.dumps(domains),
        interval_sec=data.interval_sec,
        is_active=True,
    )
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)

    scheduler = get_scheduler(request)
    if scheduler:
        await scheduler.add_monitor(monitor.id, monitor.interval_sec)

    return _monitor_response(monitor, items_found_count=0)


@router.patch("/{monitor_id}", response_model=MonitorResponse, dependencies=[Depends(require_csrf)])
async def update_monitor(
    request: Request,
    monitor_id: int,
    data: MonitorUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Update an existing monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    if data.name is not None:
        monitor.name = data.name.strip()

    if data.url is not None:
        normalized_url = normalize_vinted_monitor_url(data.url)
        monitor.original_url = normalized_url
        params = _build_monitor_params(normalized_url, data.interval_sec or monitor.interval_sec)
        monitor.params_json = json.dumps(params)

    if data.interval_sec is not None:
        monitor.interval_sec = data.interval_sec
        try:
            params = json.loads(monitor.params_json)
            params["_original_interval"] = data.interval_sec
            monitor.params_json = json.dumps(params)
        except Exception:
            pass

    if data.is_active is not None:
        monitor.is_active = data.is_active

    if data.domains is not None:
        try:
            monitor.domains_json = json.dumps(validate_selected_domains(data.domains))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(monitor)

    scheduler = get_scheduler(request)
    if scheduler:
        if monitor.is_active:
            await scheduler.update_monitor(monitor.id, monitor.interval_sec)
        else:
            await scheduler.remove_monitor(monitor.id)

    count = await db.scalar(
        select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id)
    )
    return _monitor_response(monitor, items_found_count=count or 0)


@router.get("/{monitor_id}/telegram-topic")
async def get_monitor_telegram_topic(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    await _get_owned_monitor(db, user, monitor_id)
    topic = await _get_monitor_topic(db, user, monitor_id)
    return _monitor_topic_response(monitor_id=monitor_id, user=user, topic=topic)


@router.post("/{monitor_id}/telegram-topic/ensure", dependencies=[Depends(require_csrf)])
async def ensure_monitor_telegram_topic(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    monitor = await _get_owned_monitor(db, user, monitor_id)
    if not user.telegram_topics_enabled:
        return _monitor_topic_response(monitor_id=monitor.id, user=user, topic=None)
    if not user.telegram_bot_token:
        raise HTTPException(status_code=400, detail="Telegram bot token is not configured")

    from app.telegram.bot import get_or_create_bot

    bot, _ = get_or_create_bot(user.telegram_bot_token)
    result = await ensure_monitor_topic(db, bot=bot, user=user, monitor=monitor)
    status_code = 200 if result.ok else 400
    return JSONResponse(result.to_response(), status_code=status_code)


@router.post("/{monitor_id}/telegram-topic/test", dependencies=[Depends(require_csrf)])
async def test_monitor_telegram_topic(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    monitor = await _get_owned_monitor(db, user, monitor_id)
    if not user.telegram_topics_enabled:
        raise HTTPException(status_code=400, detail="Telegram topic routing is disabled")
    if not user.telegram_bot_token:
        raise HTTPException(status_code=400, detail="Telegram bot token is not configured")

    from app.telegram.bot import get_or_create_bot

    bot, _ = get_or_create_bot(user.telegram_bot_token)
    result = await send_topic_test(db, bot=bot, user=user, monitor=monitor)
    status_code = 200 if result.ok else 400
    return JSONResponse(result.to_response(), status_code=status_code)


@router.delete("/{monitor_id}", status_code=204, dependencies=[Depends(require_csrf)])
async def delete_monitor(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Delete a monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    scheduler = get_scheduler(request)
    if scheduler:
        await scheduler.remove_monitor(monitor_id)

    await db.delete(monitor)
    await db.commit()
    return None


@router.post("/bulk-delete", response_model=BulkDeleteResponse, dependencies=[Depends(require_csrf)])
async def bulk_delete_monitors(
    request: Request,
    data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Delete multiple monitors at once."""
    result = await db.execute(
        select(Monitor).where(
            Monitor.id.in_(data.monitor_ids),
            Monitor.user_id == user.id
        )
    )
    monitors = result.scalars().all()

    found_ids = {m.id for m in monitors}
    not_found_or_forbidden_ids = [id for id in data.monitor_ids if id not in found_ids]

    scheduler = get_scheduler(request)
    for monitor in monitors:
        if scheduler:
            await scheduler.remove_monitor(monitor.id)
        await db.delete(monitor)

    await db.commit()

    return {
        "deleted_count": len(monitors),
        "not_found_or_forbidden_ids": not_found_or_forbidden_ids
    }


@router.post("/{monitor_id}/pause", response_model=MonitorResponse, dependencies=[Depends(require_csrf)])
async def pause_monitor(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Deactivate a monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    monitor.is_active = False
    await db.commit()
    await db.refresh(monitor)

    scheduler = get_scheduler(request)
    if scheduler:
        await scheduler.remove_monitor(monitor_id)

    count = await db.scalar(
        select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id)
    )
    return _monitor_response(monitor, items_found_count=count or 0)


@router.post("/{monitor_id}/resume", response_model=MonitorResponse, dependencies=[Depends(require_csrf)])
async def resume_monitor(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Activate a monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    monitor.is_active = True
    await db.commit()
    await db.refresh(monitor)

    scheduler = get_scheduler(request)
    if scheduler:
        await scheduler.add_monitor(monitor.id, monitor.interval_sec)

    count = await db.scalar(
        select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id)
    )
    return _monitor_response(monitor, items_found_count=count or 0)



@router.post("/{monitor_id}/check-now", dependencies=[Depends(require_csrf)])
async def check_monitor_now(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Manually trigger an immediate check."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    if not monitor.is_active:
        return JSONResponse(
            {"ok": False, "code": "paused", "message": "Resume this monitor before checking."},
            status_code=400,
        )

    from app.scheduler.tasks import is_monitor_check_capacity_saturated, is_monitor_check_running

    # Check for in-flight check
    # Reconcile DB status with registry: if DB says running but registry says not,
    # it's a stale status. If registry says running, it is truly busy.
    is_running_in_registry = is_monitor_check_running(monitor_id)
    if is_running_in_registry:
        return JSONResponse(
            {
                "ok": False,
                "code": "already_running",
                "message": "Check is already running for this monitor. Please wait for it to complete.",
                "retry_after": 10,
            },
            status_code=409,
        )
    # If DB says running but registry says NOT running, it is stale.
    # The check-now proceed logic doesn't depend on DB status == "running" anymore.
    # The debug_monitor endpoint will mark it as failed/stale in the UI.

    if is_monitor_check_capacity_saturated(user.id):
        return JSONResponse(
            {
                "ok": False,
                "code": "check_capacity_busy",
                "message": "System check capacity is currently full. Please try again in a few seconds.",
                "retry_after": 5,
            },
            status_code=429,
        )

    # Cooldown: 30 seconds
    now = datetime.now(timezone.utc)
    if monitor.last_check_started_at:
        started_at = monitor.last_check_started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed = (now - started_at).total_seconds()
        if elapsed < 30:
            return JSONResponse(
                {
                    "ok": False,
                    "code": "cooldown",
                    "message": f"Please wait {int(30 - elapsed)}s before checking again.",
                    "retry_after": int(30 - elapsed),
                },
                status_code=429,
            )

    scheduler = get_scheduler(request)
    if scheduler and scheduler.trigger_now(monitor_id):
        return {
            "ok": True,
            "code": "triggered",
            "message": "Check started.",
            "retry_after": 30
        }

    raise HTTPException(status_code=503, detail="Scheduler unavailable or monitor not scheduled")


@router.get("/{monitor_id}/debug")
async def debug_monitor(
    request: Request,
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Get diagnostic info for a specific monitor."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    await db.refresh(user)

    scheduler = get_scheduler(request)
    job_info = {"job_exists": False}
    if scheduler:
        job_ids = getattr(scheduler, "job_ids", {})
        job_id = job_ids.get(monitor.id)
        if job_id:
            job = scheduler.scheduler.get_job(job_id)
            if job:
                job_info = {
                    "job_exists": True,
                    "job_id": job.id,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
                }

    from app.scheduler.tasks import is_monitor_check_running
    is_running_in_registry = is_monitor_check_running(monitor_id)

    from app.scheduler.monitor_status import reconcile_monitor_check_status
    recon = reconcile_monitor_check_status(monitor, is_running_in_registry)

    live_found_count = await db.scalar(
        select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id)
    )

    return {
        "monitor_id": monitor.id,
        "name": monitor.name,
        "is_active": monitor.is_active,
        "interval_sec": monitor.interval_sec,
        "domains": _monitor_domains(monitor),
        "last_check_at": monitor.last_check_at,
        "last_check_started_at": monitor.last_check_started_at,
        "last_check_completed_at": monitor.last_check_completed_at,
        "last_check_status": recon["effective_status"],
        "last_error": monitor.last_error,
        "items_found_count": live_found_count or 0,
        "scheduler": job_info,
        "explanation": recon["explanation"],
        "is_stale_running": recon["is_stale_running"],
        "is_inconsistent_check_state": recon["is_inconsistent_check_state"],
        "cf_worker": {
            "mode": user.cf_worker_mode if user.cf_worker_mode in ["auto", "manual", "off"] else "auto",
            "configured": bool(user.cf_worker_url),
            "url_masked": mask_secret(user.cf_worker_url, visible=8) if user.cf_worker_url else None,
        },
    }
