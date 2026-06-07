from __future__ import annotations
import logging
import dataclasses
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Optional

from app.web.api_dependencies import require_api_user
from app.web.dependencies import get_db
from app.models import User, Monitor
from app.scheduler.diagnostics import registry
from app.scraper.source_selector import should_use_hydration_source
from app.config import get_settings
from app.scheduler.dry_run import (
    perform_monitor_dry_run,
    perform_monitor_full_cycle_dry_run,
    perform_monitor_baseline_seen,
)
from app.scraper.client import VintedClient, TokenBucketLimiter

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

    # Determine reason
    reason = "api"
    if not settings.monitor_hydration_source_enabled:
        reason = "flag_disabled"
    elif not any(key in params for key in ["catalog[]", "catalog_ids[]", "catalog_id", "catalog"]):
        reason = "brand_only_api_path"
    else:
        reason = "catalog_filter_detected"

    # Get last check data if available
    diag = await registry.get_check(monitor_id)

    return {
        "monitor_id": monitor_id,
        "hydration_enabled_effective": settings.monitor_hydration_source_enabled,
        "selected_source": "hydration" if used else "api",
        "reason": reason,
        "has_catalog_filter": any(key in params for key in ["catalog[]", "catalog_ids[]", "catalog_id", "catalog"]),
        "has_brand_filter": "brand_ids[]" in params or "brand_ids" in params,
        "detail_guards": {
            "enabled": settings.monitor_detail_guard_enabled,
            "category_guard_enabled": settings.monitor_detail_category_guard_enabled,
            "freshness_guard_enabled": settings.monitor_detail_freshness_guard_enabled,
        },
        "last_check": {
            "at": diag.last_check_at if diag else None,
            "source": diag.last_check_source if diag else None,
            "items_found_count_by_domain": diag.items_found_count_by_domain if diag else {},
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

    # If source is ssr_html_photo, we'd need to use the new parser.
    # For now, just implement the endpoint skeleton.

    try:
        if source == "ssr_html_photo":
            from app.scraper.catalog_ssr_parser import parse_catalog_ssr_html

            # Use the existing monitor URL
            domain_url = monitor.original_url
            if domain:
                domain_url = monitor.original_url.replace("vinted.pl", domain)

            # Fetch HTML
            html = await client.fetch_catalog_html(domain_url, domain=domain or "vinted.pl")

            # Parse
            items = parse_catalog_ssr_html(html)

            # Return samples
            res = {
                "source": "ssr_html_photo",
                "raw_cards_total": len(items),
                "normalized_items_total": len(items),
                "with_photo_total": len([i for i in items if i['photo_url']]),
                "missing_photo_total": len([i for i in items if not i['photo_url']]),
                "samples": items[:max_items_per_domain]
            }
            return JSONResponse(status_code=200, content=res)

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
