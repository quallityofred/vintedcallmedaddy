from __future__ import annotations
import logging
import dataclasses
import json
import fastapi
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Optional

from app.web.api_dependencies import require_api_user
from app.web.csrf import require_api_csrf
from app.web.dependencies import get_db
from app.models import User, Monitor, FoundItem, SeenItem
from app.scheduler.diagnostics import registry
from app.scheduler.dry_run import (
    perform_monitor_baseline_seen,
    perform_monitor_full_cycle_dry_run,
)
from app.scraper.source_selector import (
    should_use_hydration_source,
    should_use_hydration_ssr_photo_merge,
)
from app.scraper.monitor_filters import extract_monitor_filters
from app.scraper.url_parser import normalize_catalog_search_params, parse_vinted_url
from app.config import get_settings
from app.scraper.client import VintedClient, TokenBucketLimiter
from app.schemas.notification_diagnostics import NotificationProcessRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])

def _create_failed_full_cycle_response(monitor_id: int, exc: Exception) -> dict:
    return {
        "monitor_id": monitor_id,
        "selected_source": None,
        "reason": "full_cycle_dry_run_failed",
        "selected_domains": [],
        "dry_run_domains": [],
        "summary": {},
        "counts_by_domain": {},
        "pipeline_counts_by_domain": {},
        "seen_found_simulation_by_domain": {},
        "samples_by_domain": {},
        "errors_by_domain": {"__global__": exc.__class__.__name__},
        "safe_error": "full_cycle_dry_run_failed",
        "side_effects": {
            "runs_scheduler_check": False,
            "writes_seen_items": False,
            "writes_found_items": False,
            "updates_monitor": False,
            "enqueues_notifications": False,
            "sends_telegram": False,
            "calls_vinted": False,
            "reads_database": True,
        },
    }


def _create_baseline_guard_response(monitor_id: int, selected_domains: list[str]) -> dict:
    return {
        "monitor_id": monitor_id,
        "dry_run": True,
        "selected_source": None,
        "reason": "baseline_seen_no_notify",
        "selected_domains": selected_domains,
        "baseline_domains": [],
        "summary": {
            "domains_checked": 0,
            "raw_fetched_total": 0,
            "after_filters_total": 0,
            "already_seen_total": 0,
            "would_create_seen_items_total": 0,
            "created_seen_items_total": 0,
            "would_create_found_items_total": 0,
            "would_enqueue_notifications_total": 0,
            "would_send_telegram_total": 0,
        },
        "counts_by_domain": {},
        "samples_by_domain": {},
        "errors_by_domain": {},
        "safe_error": "baseline_seen_request_too_large",
        "side_effects": {
            "runs_scheduler_check": False,
            "writes_seen_items": False,
            "writes_found_items": False,
            "updates_monitor": False,
            "enqueues_notifications": False,
            "sends_telegram": False,
            "calls_vinted": False,
            "reads_database": True,
        },
    }

from app.web.dependencies import get_db, get_scheduler
from app.scheduler.vinted_rate_limiter import get_vinted_rate_limiter

@router.get("/scheduler/adaptive-vinted-pacing")
async def get_adaptive_vinted_pacing_diagnostics(
    user: User = Depends(require_api_user),
    scheduler = Depends(get_scheduler),
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    pacing = await scheduler.get_pacing_diagnostics() if scheduler else None
    limiter = await get_vinted_rate_limiter()
    limiter_diag = limiter.get_diagnostics()

    return {
        "adaptive_pacing": dataclasses.asdict(pacing) if pacing else None,
        "rate_limiter": limiter_diag,
    }

@router.get("/monitors/{monitor_id}/source-selection")
async def get_monitor_source_selection(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Get diagnostic info for hydration source selection."""
    settings = get_settings()
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    import json
    try:
        params = json.loads(monitor.params_json)
    except Exception:
        params = {}

    # Check selector logic
    used = should_use_hydration_source(params)
    merge_used = should_use_hydration_ssr_photo_merge(params)
    original_url = monitor.original_url if isinstance(monitor.original_url, str) else ""
    original_url_params = normalize_catalog_search_params(parse_vinted_url(original_url))
    effective_request_params = normalize_catalog_search_params(params)
    monitor_name = monitor.name if isinstance(monitor.name, str) else None
    filters = extract_monitor_filters(params, monitor_name=monitor_name)

    # Determine reason
    reason = "api"
    if not settings.monitor_hydration_source_enabled:
        reason = "flag_disabled"
    elif not any(key in params for key in ["catalog[]", "catalog_ids[]", "catalog_ids", "catalog_id", "catalog"]):
        reason = "brand_only_api_path"
    else:
        reason = "catalog_filter_detected"

    # Get last check data if available
    diag = await registry.get_check(monitor_id)

    return {
        "monitor_id": monitor_id,
        "hydration_enabled_effective": settings.monitor_hydration_source_enabled,
        "hydration_ssr_photo_merge_enabled": settings.monitor_ssr_photo_merge_enabled,
        "hydration_ssr_photo_merge_eligible": merge_used,
        "selected_source": (
            "hydration_ssr_photo_merge"
            if merge_used
            else "hydration"
            if used
            else "api"
        ),
        "reason": reason,
        "has_catalog_filter": any(key in params for key in ["catalog[]", "catalog_ids[]", "catalog_ids", "catalog_id", "catalog"]),
        "has_brand_filter": "brand_ids[]" in params or "brand_ids" in params,
        "filter_diagnostics": {
            "stored_param_keys": sorted(key for key in params if not str(key).startswith("_")),
            "original_url_param_keys": sorted(original_url_params),
            "effective_request_param_keys": sorted(effective_request_params),
            "filter_keys": filters.filter_keys,
            "brand_ids": sorted(filters.brand_ids),
            "catalog_ids": sorted(filters.catalog_ids),
            "gender_ids": sorted(filters.gender_ids),
            "request_params_match_original_url": effective_request_params == original_url_params,
        },
        "detail_guards": {
            "enabled": settings.monitor_detail_guard_enabled,
            "category_guard_enabled": settings.monitor_detail_category_guard_enabled,
            "freshness_guard_enabled": settings.monitor_detail_freshness_guard_enabled,
        },
        "last_check": {
            "at": diag.last_check_at if diag else None,
            "source": diag.last_check_source if diag else None,
            "items_found_count_by_domain": diag.items_found_count_by_domain if diag else {},
            "source_details_by_domain": diag.source_details_by_domain if diag else {},
        },
        "side_effects": {
            "runs_monitor_check": False,
            "writes_seen_items": False,
            "writes_found_items": False,
            "updates_monitor": False,
            "enqueues_notifications": False,
            "sends_telegram": False,
            "calls_vinted": True
        }
    }

@router.post("/monitors/{monitor_id}/dry-run-source")
async def post_monitor_dry_run_source(
    monitor_id: int,
    max_domains: int = 1,
    max_items_per_domain: int = 10,
    domain: str | None = None,
    source: str = "hydration",
    sample_limit: int = Query(default=10, ge=0, le=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Perform a read-only dry-run of a monitor check."""
    settings = get_settings()
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    from app.scraper.client import VintedClient, TokenBucketLimiter
    from app.scheduler.dry_run import perform_monitor_dry_run

    # Manual client creation for dry-run
    rate_limiter = TokenBucketLimiter(rate=float(settings.rate_limit_per_minute), per=60.0)
    client = VintedClient(rate_limiter=rate_limiter)

    try:
        # Note: ssr_html_photo diagnostic was removed to prevent timeout.
        # Use /jobs/hydration-ssr-photo-merge for asynchronous all-domain validation.
        if source == "ssr_html_photo":
             raise HTTPException(status_code=400, detail="Use /jobs/hydration-ssr-photo-merge instead")

        res = await perform_monitor_dry_run(
            monitor,
            client,
            max_domains=min(max_domains, 3),
            max_items_per_domain=min(max_items_per_domain, 20),
            target_domain=domain
        )
        return JSONResponse(status_code=200, content=jsonable_encoder(dataclasses.asdict(res)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Dry-run failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()


@router.post("/monitors/{monitor_id}/dry-run-full-cycle", response_model=None)
async def post_monitor_full_cycle_dry_run(
    monitor_id: int,
    domain: str | None = None,
    max_domains: int = Query(default=8, ge=1, le=8),
    max_items_per_domain: int = Query(default=96, ge=1, le=120),
    include_samples: bool = True,
    sample_limit: int = Query(default=10, ge=0, le=20),
    include_media_diagnostics: bool = False,
    media_diag_max_items: int = Query(default=10, ge=1, le=20),
    media_diag_max_chunks: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Simulate a complete monitor cycle without scheduler or database side effects."""
    settings = get_settings()
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    # Guard: Reject oversized requests
    if domain is None and max_domains > 2:
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder({
                "monitor_id": monitor_id,
                "selected_source": "hydration",
                "reason": "full_cycle_dry_run_request_too_large",
                "selected_domains": json.loads(monitor.domains_json),
                "dry_run_domains": [],
                "summary": {
                    "domains_checked": 0, "raw_fetched_total": 0, "after_filters_total": 0,
                    "already_seen_total": 0, "already_found_total": 0,
                    "would_create_seen_items_total": 0, "would_create_found_items_total": 0,
                    "would_enqueue_notifications_total": 0, "would_send_telegram_total": 0
                },
                "counts_by_domain": {},
                "pipeline_counts_by_domain": {},
                "seen_found_simulation_by_domain": {},
                "samples_by_domain": {},
                "errors_by_domain": {},
                "safe_error": "full_cycle_dry_run_request_too_large",
                "limits": {
                    "max_domains_allowed": 2,
                    "requested_max_domains": max_domains,
                    "recommended_mode": "domain_or_small_batch"
                },
                "side_effects": {
                    "runs_scheduler_check": False,
                    "writes_seen_items": False,
                    "writes_found_items": False,
                    "updates_monitor": False,
                    "enqueues_notifications": False,
                    "sends_telegram": False,
                    "calls_vinted": False,
                    "reads_database": True
                }
            }),
        )

    client = None
    try:
        rate_limiter = TokenBucketLimiter(rate=float(settings.rate_limit_per_minute), per=60.0)
        client = VintedClient(rate_limiter=rate_limiter)
        dry_run = await perform_monitor_full_cycle_dry_run(
            monitor,
            client,
            db,
            max_domains=max_domains,
            max_items_per_domain=max_items_per_domain,
            target_domain=domain,
            include_samples=include_samples,
            sample_limit=sample_limit,
            include_media_diagnostics=include_media_diagnostics,
            media_diag_max_items=media_diag_max_items,
            media_diag_max_chunks=media_diag_max_chunks,
            telegram_enabled=bool(user.is_telegram_enabled),
        )
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder(dataclasses.asdict(dry_run)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning(
            "full_cycle_dry_run_failed monitor_id=%s exception_type=%s",
            monitor_id,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder(_create_failed_full_cycle_response(monitor_id, exc)),
        )
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as exc:
                logger.warning(
                    "full_cycle_dry_run_client_close_failed monitor_id=%s exception_type=%s",
                    monitor_id,
                    type(exc).__name__,
                )

@router.post("/monitors/{monitor_id}/baseline-seen-no-notify", response_model=None)
async def post_monitor_seen_baseline_no_notify(
    monitor_id: int,
    domain: str | None = None,
    max_domains: int = Query(default=1, ge=1, le=8),
    max_items_per_domain: int = Query(default=96, ge=1, le=120),
    dry_run: bool = True,
    sample_limit: int = Query(default=10, ge=0, le=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Create SeenItem entries for monitor results without creating FoundItems or notifications."""
    settings = get_settings()
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    try:
        selected_domains = json.loads(monitor.domains_json)
    except Exception:
        selected_domains = []
    if domain is None and max_domains > 2:
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder(_create_baseline_guard_response(monitor_id, selected_domains)),
        )

    client = None
    try:
        rate_limiter = TokenBucketLimiter(rate=float(settings.rate_limit_per_minute), per=60.0)
        client = VintedClient(rate_limiter=rate_limiter)

        dry_run_res = await perform_monitor_baseline_seen(
            monitor,
            client,
            db,
            max_domains=max_domains,
            max_items_per_domain=max_items_per_domain,
            target_domain=domain,
            dry_run=dry_run,
            sample_limit=sample_limit,
        )
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder(dry_run_res),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning(
            "baseline_seen_no_notify_failed monitor_id=%s exception_type=%s",
            monitor_id,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder(_create_failed_full_cycle_response(monitor_id, exc)),
        )
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as exc:
                logger.warning(
                    "baseline_seen_client_close_failed monitor_id=%s exception_type=%s",
                    monitor_id,
                    type(exc).__name__,
                )


@router.post("/monitors/{monitor_id}/jobs/hydration-ssr-photo-merge")
async def post_monitor_hydration_ssr_merge_job(
    monitor_id: int,
    background_tasks: fastapi.BackgroundTasks,
    domain: str | None = None,
    max_domains: int = Query(default=8, ge=1, le=8),
    max_items_per_domain: int = Query(default=96, ge=1, le=120),
    sample_limit: int = Query(default=3, ge=0, le=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Start an asynchronous background job for hydration+SSR photo merge."""
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    try:
        raw_domains = json.loads(monitor.domains_json)
        selected_domains = (
            list(dict.fromkeys(domain for domain in raw_domains if isinstance(domain, str)))
            if isinstance(raw_domains, list)
            else []
        )
    except Exception:
        selected_domains = []
    if domain is not None and domain not in selected_domains:
        raise HTTPException(status_code=400, detail="Domain is not selected by this monitor")

    job_id = f"merge_{monitor_id}_{uuid.uuid4().hex[:12]}"
    job = await registry.start_job(
        job_id,
        monitor_id,
        "hydration_with_ssr_photos",
    )

    # Offload to background
    from app.scheduler.tasks import run_hydration_ssr_merge_job
    background_tasks.add_task(
        run_hydration_ssr_merge_job,
        monitor_id,
        job_id,
        target_domain=domain,
        max_domains=max_domains,
        max_items_per_domain=max_items_per_domain,
        sample_limit=sample_limit,
    )

    return {
        "job_id": job_id,
        "status": job.status,
        "source": job.source,
        "started_at": job.started_at.isoformat(),
    }


@router.get("/monitors/{monitor_id}/jobs/{job_id}")
async def get_monitor_job_status(
    monitor_id: int,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    monitor_result = await db.execute(
        select(Monitor.id).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    if monitor_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    job = await registry.get_job(job_id, monitor_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={
                "job_id": job_id,
                "status": "not_found",
                "safe_error": "diagnostic_job_not_found",
            },
        )
    if job.status == "completed" and job.result is not None:
        return JSONResponse(status_code=200, content=jsonable_encoder(job.result))
    if job.status == "failed":
        return JSONResponse(
            status_code=200,
            content={
                "job_id": job.job_id,
                "status": "failed",
                "source": job.source,
                "started_at": job.started_at.isoformat(),
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "safe_error": job.safe_error or "hydration_ssr_merge_job_failed",
                "summary": {},
                "counts_by_domain": {},
                "samples_by_domain": {},
                "errors_by_domain": {"__global__": job.safe_error or "JobFailed"},
                "side_effects": {
                    "reads_database": True,
                    "calls_vinted": False,
                    "writes_seen_items": False,
                    "writes_found_items": False,
                    "enqueues_notifications": False,
                    "sends_telegram": False,
                    "runs_scheduler_check": False,
                },
            },
        )
    return {
        "job_id": job.job_id,
        "status": "running",
        "source": job.source,
        "started_at": job.started_at.isoformat(),
    }


@router.post("/monitors/{monitor_id}/start-with-baseline", response_model=None)
async def post_monitor_start_with_baseline(
    monitor_id: int,
    domain: str | None = None,
    max_domains: int = Query(default=2, ge=1, le=8),
    max_items_per_domain: int = Query(default=96, ge=1, le=120),
    dry_run: bool = True,
    activate_after: bool = False,
    sample_limit: int = Query(default=10, ge=0, le=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Run a baseline-only check and optionally activate the monitor."""
    settings = get_settings()
    result = await db.execute(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    if domain is None and max_domains > 2:
        return JSONResponse(
            status_code=400,
            content={"detail": "For batch baseline, please specify explicit domains or reduce max_domains to <= 2"},
        )

    last_check_at_before = monitor.last_check_at
    monitor_activated = False

    try:
        selected_domains = json.loads(monitor.domains_json)
    except Exception:
        selected_domains = []

    if activate_after:
        # Determine if this specific run covers all selected domains
        # If domain is specified, it only covers one domain (or none if not matched)
        # If max_domains is used, it only covers a subset
        # Safest condition: only allow if ALL domains are covered.
        covers_all = False
        if domain is not None:
             # If specific domain, is it the only one?
             covers_all = (len(selected_domains) == 1 and domain in selected_domains)
        else:
             # If no specific domain, does max_domains cover all?
             covers_all = (max_domains >= len(selected_domains))

        if not covers_all:
             return JSONResponse(
                status_code=400,
                content={
                    "reason": "partial_baseline_activation_not_allowed",
                    "selected_domains": selected_domains,
                    "baseline_domains": [domain] if domain else [],
                    "selected_domain_count": len(selected_domains),
                    "baseline_domain_count": 1 if domain else max_domains,
                    "safe_error": "partial_baseline_activation_not_allowed",
                    "side_effects": {
                        "runs_scheduler_check": False,
                        "writes_seen_items": False,
                        "writes_found_items": False,
                        "updates_monitor": False,
                        "enqueues_notifications": False,
                        "sends_telegram": False,
                        "calls_vinted": False,
                        "reads_database": True
                    },
                    "monitor_activated": False
                }
            )

    client = None
    try:
        rate_limiter = TokenBucketLimiter(rate=float(settings.rate_limit_per_minute), per=60.0)
        client = VintedClient(rate_limiter=rate_limiter)

        dry_run_res = await perform_monitor_baseline_seen(
            monitor,
            client,
            db,
            max_domains=max_domains,
            max_items_per_domain=max_items_per_domain,
            target_domain=domain,
            dry_run=dry_run,
            sample_limit=sample_limit,
        )

        if not dry_run and activate_after:
            monitor.is_active = True
            if monitor.last_check_at is None:
                monitor.last_check_at = datetime.now(timezone.utc)
            monitor_activated = True
            await db.commit()
            await db.refresh(monitor)

        res = {
            "reason": "start_with_baseline",
            "dry_run": dry_run,
            "activate_after": activate_after,
            "monitor_activated": monitor_activated,
            "monitor_last_check_at_before": last_check_at_before,
            "monitor_last_check_at_after": monitor.last_check_at,
            **dry_run_res,
        }
        return JSONResponse(status_code=200, content=jsonable_encoder(res))

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning(
            "start_with_baseline_failed monitor_id=%s exception_type=%s",
            monitor_id,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=jsonable_encoder(_create_failed_full_cycle_response(monitor_id, exc)),
        )
    finally:
        if client is not None:
            await client.close()


@router.post("/notifications/process-pending", dependencies=[Depends(require_api_csrf)])
async def process_notifications_diagnostic(
    req: NotificationProcessRequest,
    user: User = Depends(require_api_user),
):
    """Audit or process a bounded pending Telegram notification batch."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    if not req.dry_run:
        raise HTTPException(
            status_code=400,
            detail="async_notification_job_required: Use /api/v1/diagnostics/notifications/process-pending-jobs for live execution."
        )

    from app.scheduler.tasks import process_pending_notifications
    return await process_pending_notifications(
        limit=req.limit,
        monitor_id=req.monitor_id,
        dry_run=req.dry_run,
        sample_limit=req.sample_limit,
    )

@router.post("/notifications/process-pending-jobs", dependencies=[Depends(require_api_csrf)])
async def post_process_notifications_job(
    background_tasks: BackgroundTasks,
    req: NotificationProcessRequest,
    user: User = Depends(require_api_user),
):
    """Start an asynchronous background job for notification processing."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    if not req.dry_run and req.monitor_id is None:
        raise HTTPException(
            status_code=400,
            detail="monitor_id_required_for_live_notification_processing",
        )

    job_id = f"notify_{uuid.uuid4().hex[:12]}"
    # Always use monitor_id=0 for notification jobs in the registry
    await registry.start_job(
        job_id,
        0,
        "pending_notifications",
        request_metadata={
            "requested_monitor_id": req.monitor_id,
            "requested_limit": req.limit,
            "requested_sample_limit": req.sample_limit,
            "requested_dry_run": req.dry_run,
            "all_monitors": False,
        },
    )

    from app.scheduler.tasks import run_pending_notifications_job
    background_tasks.add_task(
        run_pending_notifications_job,
        job_id,
        monitor_id=req.monitor_id,
        limit=req.limit,
        sample_limit=req.sample_limit,
        dry_run=req.dry_run,
    )

    return {
        "job_id": job_id,
        "status": "running",
        "requested_monitor_id": req.monitor_id,
        "requested_limit": req.limit,
        "requested_sample_limit": req.sample_limit,
        "requested_dry_run": req.dry_run,
    }

@router.get("/notifications/process-pending-jobs/{job_id}")
async def get_notification_job_status(job_id: str, user: User = Depends(require_api_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Retrieve status from registry (using a monitor_id of 0 as a global placeholder)
    job = await registry.get_job(job_id, 0)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"job_id": job_id, "status": "not_found", "safe_error": "job_not_found"},
        )

    request = job.request_metadata
    requested_dry_run = bool(request.get("requested_dry_run", True))
    res = {
        "job_id": job.job_id,
        "status": job.status,
        "requested_monitor_id": request.get("requested_monitor_id"),
        "requested_limit": request.get("requested_limit"),
        "requested_sample_limit": request.get("requested_sample_limit"),
        "requested_dry_run": requested_dry_run,
        "all_monitors": bool(request.get("all_monitors", False)),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "duration_ms_total": 0,
        "summary": {
            "monitor_id": request.get("requested_monitor_id"),
            "limit": request.get("requested_limit"),
            "pending_before": None,
            "pending_total": None,
            "selected_for_processing": None,
            "selected_monitor_ids": [],
            "sent_photo_count": None,
            "sent_text_count": None,
            "fallback_text_count": None,
            "failed_count": None,
            "rate_limited_count": None,
            "marked_notified_count": None,
            "pending_after": None,
        },
        "errors_sample": [],
        "side_effects": {
            "reads_database": True,
            "calls_vinted": False,
            "writes_found_items": not requested_dry_run,
            "enqueues_notifications": False,
            "sends_telegram": not requested_dry_run,
            "runs_scheduler_check": False,
        },
    }

    if job.result is not None:
        # job.result is the dict from process_pending_notifications
        result = job.result
        res["duration_ms_total"] = result.get("duration_ms", 0)
        res["summary"] = {
            "monitor_id": result.get("monitor_id"),
            "limit": result.get("limit"),
            "pending_before": result.get("pending_before", 0),
            "pending_total": result.get("pending_total", 0),
            "selected_for_processing": result.get("selected_for_processing", 0),
            "selected_monitor_ids": result.get("selected_monitor_ids", []),
            "sent_photo_count": result.get("sent_photo_count", 0),
            "sent_text_count": result.get("sent_text_count", 0),
            "fallback_text_count": result.get("fallback_text_count", 0),
            "failed_count": result.get("failed_count", 0),
            "rate_limited_count": result.get("rate_limited_count", 0),
            "marked_notified_count": result.get("marked_notified_count", 0),
            "pending_after": result.get("pending_after", 0),
        }
        res["samples"] = result.get("samples", [])
        res["errors_sample"] = result.get("errors_sample", [])
        res["side_effects"] = result.get("side_effects", result.get("side_effects", res["side_effects"]))

    if job.status == "failed":
        res["safe_error"] = job.safe_error or "notification_job_failed"

    return JSONResponse(status_code=200, content=jsonable_encoder(res))


@router.get("/notifications/worker")
async def get_notification_worker_diagnostics(user: User = Depends(require_api_user)):
    """Get diagnostic info for the background pending notification worker."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    from app.scheduler.tasks import get_pending_notifications_worker_stats, _worker_lock
    stats = get_pending_notifications_worker_stats()
    
    return {
        **stats,
        "running": _worker_lock.locked(),
        "side_effects": {
            "reads_database": True,
            "writes_found_items": False,
            "sends_telegram": False,
        }
    }


@router.post("/monitors/{monitor_id}/backfill-seen-from-found-items", dependencies=[Depends(require_api_csrf)])
async def backfill_seen_from_found_items(
    monitor_id: int,
    dry_run: bool = True,
    limit: int = Query(default=1000, ge=1, le=5000),
    sample_limit: int = Query(default=10, ge=0, le=50),
    reason: str = Query(default="manual_seen_backfill_from_found_items", min_length=1, max_length=80),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Backfill missing SeenItem rows from existing FoundItem history without Telegram."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    monitor = await db.get(Monitor, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    missing_seen = ~select(SeenItem.id).where(
        SeenItem.monitor_id == FoundItem.monitor_id,
        SeenItem.vinted_item_id == FoundItem.vinted_item_id,
        SeenItem.domain == FoundItem.domain,
    ).exists()
    found_items_total = int(
        await db.scalar(
            select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor_id)
        )
        or 0
    )
    missing_total = int(
        await db.scalar(
            select(func.count(FoundItem.id)).where(
                FoundItem.monitor_id == monitor_id,
                missing_seen,
            )
        )
        or 0
    )
    missing_items = (
        await db.execute(
            select(FoundItem)
            .where(FoundItem.monitor_id == monitor_id, missing_seen)
            .order_by(FoundItem.found_at.asc(), FoundItem.id.asc())
            .limit(limit)
        )
    ).scalars().all()
    inserted_seen = 0

    if not dry_run and missing_items:
        rows = [
            {
                "monitor_id": monitor_id,
                "user_id": monitor.user_id,
                "vinted_item_id": int(item.vinted_item_id),
                "domain": item.domain,
                "seen_at": item.found_at,
            }
            for item in missing_items
        ]
        dialect_name = db.get_bind().dialect.name
        if dialect_name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        elif dialect_name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            raise RuntimeError("Unsupported database dialect for conflict-safe seen backfill")

        await db.execute(
            insert(SeenItem).values(rows).on_conflict_do_nothing(
                index_elements=["monitor_id", "vinted_item_id", "domain"]
            )
        )
        await db.commit()

        remaining_missing = int(
            await db.scalar(
                select(func.count(FoundItem.id)).where(
                    FoundItem.monitor_id == monitor_id,
                    missing_seen,
                )
            )
            or 0
        )
        inserted_seen = missing_total - remaining_missing

    missing_after_if_applied = max(
        0,
        missing_total - (inserted_seen if not dry_run else len(missing_items)),
    )
    return JSONResponse(
        status_code=200,
        content=jsonable_encoder(
            {
                "monitor_id": monitor_id,
                "dry_run": dry_run,
                "reason": reason,
                "found_items_scanned": found_items_total,
                "already_seen": found_items_total - missing_total,
                "missing_total": missing_total,
                "would_insert_seen": len(missing_items),
                "inserted_seen": inserted_seen,
                "missing_after_if_applied": missing_after_if_applied,
                "samples": [
                    {
                        "found_item_id": item.id,
                        "vinted_item_id": str(item.vinted_item_id),
                        "domain": item.domain,
                        "title_preview": item.title[:80],
                        "notified": bool(item.notified),
                    }
                    for item in missing_items[:sample_limit]
                ],
                "side_effects": {
                    "reads_database": True,
                    "writes_seen_items": bool(inserted_seen),
                    "writes_found_items": False,
                    "updates_monitor": False,
                    "enqueues_notifications": False,
                    "sends_telegram": False,
                    "runs_scheduler_check": False,
                },
            }
        ),
    )

@router.post("/notifications/ack-pending-no-notify", dependencies=[Depends(require_api_csrf)])
async def ack_pending_notifications_no_notify(
    monitor_id: int = Query(..., ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
    sample_limit: int = Query(default=10, ge=0, le=50),
    dry_run: bool = True,
    reason: str = Query(
        default="manual_backlog_cleanup_no_notify",
        min_length=1,
        max_length=80,
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Mark pending notification items as notified without sending Telegram."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    from app.models import FoundItem

    conditions = [
        FoundItem.notified == False,  # noqa: E712
        FoundItem.monitor_id == monitor_id,
    ]
    pending_before = int(
        await db.scalar(select(func.count(FoundItem.id)).where(*conditions)) or 0
    )
    items = (
        await db.execute(
            select(FoundItem)
            .where(*conditions)
            .order_by(FoundItem.found_at.asc(), FoundItem.id.asc())
            .limit(limit)
        )
    ).scalars().all()

    selected_for_ack = len(items)
    projected_pending_after = max(0, pending_before - selected_for_ack)
    res = {
        "dry_run": dry_run,
        "monitor_id": monitor_id,
        "pending_before": pending_before,
        "selected_for_ack": selected_for_ack,
        "would_mark_notified_count": selected_for_ack,
        "marked_notified_count": 0,
        "pending_after_if_applied": projected_pending_after,
        "pending_after": pending_before if dry_run else None,
        "samples": [
            {
                "found_item_id": item.id,
                "vinted_item_id": str(item.vinted_item_id),
                "domain": item.domain,
                "title_preview": item.title[:80],
                "has_photo_url": bool(item.photo_url),
            }
            for item in items[:sample_limit]
        ],
        "reason": reason,
        "side_effects": {
            "sends_telegram": False,
            "writes_found_items": not dry_run,
            "marks_notified": not dry_run,
        },
    }

    if not dry_run:
        for item in items:
            item.notified = True
        await db.commit()
        res["marked_notified_count"] = selected_for_ack
        res["pending_after"] = int(
            await db.scalar(select(func.count(FoundItem.id)).where(*conditions)) or 0
        )

    return JSONResponse(status_code=200, content=jsonable_encoder(res))


@router.post("/monitors/{monitor_id}/repair-stale-status", dependencies=[Depends(require_api_csrf)])
async def repair_monitor_stale_status(
    monitor_id: int,
    dry_run: bool = True,
    reason: str = Query(default="manual_stale_status_repair", min_length=1, max_length=80),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Safely repair stale 'running' status or inconsistent timestamps for a monitor."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")

    from app.scheduler.tasks import is_monitor_check_running
    is_running_in_registry = is_monitor_check_running(monitor_id)
    
    from app.scheduler.monitor_status import reconcile_monitor_check_status
    recon = reconcile_monitor_check_status(monitor, is_running_in_registry)


    # Protection: never repair if it's actually running in memory
    if is_running_in_registry:
        raise HTTPException(
            status_code=409,
            detail="Cannot repair status while a check is actively running in memory."
        )

    would_repair = recon["is_stale_running"] or recon["is_inconsistent_check_state"]
    proposed_updates: dict[str, Any] = {}

    if recon["is_stale_running"]:
        proposed_updates["last_check_status"] = "failed"
        proposed_updates["last_error"] = f"Repair: cleared stale running status ({reason})"

    if recon["is_inconsistent_check_state"]:
        # started > completed. Sync completed to started to resolve inconsistency.
        proposed_updates["last_check_completed_at"] = monitor.last_check_started_at

    res = {
        "monitor_id": monitor_id,
        "dry_run": dry_run,
        "raw_db_status": monitor.last_check_status,
        "raw_db_started_at": monitor.last_check_started_at,
        "raw_db_completed_at": monitor.last_check_completed_at,
        "reconciled_status": recon["effective_status"],
        "is_stale_running": recon["is_stale_running"],
        "is_inconsistent_check_state": recon["is_inconsistent_check_state"],
        "would_repair": would_repair,
        "proposed_updates": proposed_updates,
        "reason": reason,
        "side_effects": {
            "updates_monitor": not dry_run and would_repair,
            "reads_database": True,
        }
    }

    if not dry_run and would_repair:
        if "last_check_status" in proposed_updates:
            monitor.last_check_status = proposed_updates["last_check_status"]
        if "last_error" in proposed_updates:
            monitor.last_error = proposed_updates["last_error"]
        if "last_check_completed_at" in proposed_updates:
            monitor.last_check_completed_at = proposed_updates["last_check_completed_at"]

        await db.commit()
        await db.refresh(monitor)
        
        # Add after-repair state
        res["after_repair"] = {
            "last_check_status": monitor.last_check_status,
            "last_check_completed_at": monitor.last_check_completed_at,
        }

    return JSONResponse(status_code=200, content=jsonable_encoder(res))
