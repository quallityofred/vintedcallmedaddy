import asyncio
import logging
import json
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Any, List

from app.database import get_session_factory
from app.models import Monitor
from app.scraper.client import VintedClient, TokenBucketLimiter
from app.config import get_settings
from app.scraper.catalog_ssr_parser import parse_catalog_ssr_photo_map
from app.scraper.hydration_parser import extract_hydration_items
from sqlalchemy import select

logger = logging.getLogger(__name__)
settings = get_settings()

async def run_hydration_ssr_merge_job(monitor_id: int, job_id: str):
    """
    Background job to perform one-fetch hydration+SSR photo merge for all domains.
    """
    from app.scheduler.diagnostics import registry
    
    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
        monitor = result.scalar_one_or_none()
        if not monitor:
            await registry.record_check(monitor_id, f"job_{job_id}", {}, "Monitor not found")
            return

        try:
            selected_domains = json.loads(monitor.domains_json)
        except Exception:
            selected_domains = []

        rate_limiter = TokenBucketLimiter(rate=float(settings.rate_limit_per_minute), per=60.0)
        client = VintedClient(rate_limiter=rate_limiter)
        
        overall_summary = {
            "html_fetch_count_total": 0,
            "hydration_items_total": 0,
            "ssr_photo_map_total": 0,
            "overlap_total": 0,
            "merged_with_photo_total": 0,
            "missing_photo_after_merge_total": 0,
            "hydration_only_total": 0,
            "ssr_photo_only_total": 0,
            "duration_ms_total": 0
        }
        res_counts = {}
        res_samples = {}
        res_errors = {}
        
        start_total = time.time()
        try:
            # Concurrent domain processing
            async def process_domain(d):
                start_d = time.time()
                domain_url = monitor.original_url.replace("vinted.pl", d)
                
                # Fetch once
                html = await client.fetch_catalog_html(domain_url, domain=d)
                
                hydration_items = extract_hydration_items(html, domain=d)
                ssr_photo_map = parse_catalog_ssr_photo_map(html)
                
                merged_items = []
                merged_with_photo_count = 0
                for item in hydration_items:
                    item_id = str(item.get('id'))
                    if item_id in ssr_photo_map:
                        item['photo_url'] = ssr_photo_map[item_id]
                        merged_with_photo_count += 1
                    merged_items.append(item)
                
                ssr_only_ids = [i for i in ssr_photo_map.keys() if i not in [str(item.get('id')) for item in hydration_items]]
                
                # Redacted samples for diagnostic
                redacted_samples = []
                for item in merged_items[:10]: # Bounded samples
                    redacted_item = {
                        "position": item.get('position', 0),
                        "item_id": item.get('id'),
                        "item_url_path": item.get('path', ''),
                        "has_hydration_title": bool(item.get('title')),
                        "title_preview": str(item.get('title', ''))[:50],
                        "has_hydration_price": bool(item.get('price')),
                        "price": item.get('price', 0.0),
                        "currency": item.get('currency', 'PLN'),
                        "has_ssr_photo": bool(item.get('photo_url')),
                        "photo_host": urllib.parse.urlparse(item.get('photo_url', '')).hostname if item.get('photo_url') else None
                    }
                    redacted_samples.append(redacted_item)
                
                return d, {
                    "html_fetch_count": 1,
                    "duration_ms": int((time.time() - start_d) * 1000),
                    "hydration_items": len(hydration_items),
                    "ssr_photo_map_items": len(ssr_photo_map),
                    "overlap_count": merged_with_photo_count,
                    "merged_with_photo": merged_with_photo_count,
                    "missing_photo_after_merge": len([i for i in merged_items if not i.get('photo_url')]),
                    "hydration_only_count": len([i for i in hydration_items if str(i.get('id')) not in ssr_photo_map]),
                    "ssr_photo_only_count": len(ssr_only_ids),
                    "order_preserved": True,
                    "photo_hosts": list(set([urllib.parse.urlparse(p).hostname for p in ssr_photo_map.values() if p]))
                }, redacted_samples

            results = await asyncio.gather(*(process_domain(d) for d in selected_domains), return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Merge job failed: {result}")
                    continue
                d, counts, samples = result
                res_counts[d] = counts
                res_samples[d] = samples
                
                overall_summary["html_fetch_count_total"] += counts["html_fetch_count"]
                overall_summary["hydration_items_total"] += counts["hydration_items"]
                overall_summary["ssr_photo_map_total"] += counts["ssr_photo_map_items"]
                overall_summary["overlap_total"] += counts["overlap_count"]
                overall_summary["merged_with_photo_total"] += counts["merged_with_photo"]
                overall_summary["missing_photo_after_merge_total"] += counts["missing_photo_after_merge"]
                overall_summary["hydration_only_total"] += counts["hydration_only_count"]
                overall_summary["ssr_photo_only_total"] += counts["ssr_photo_only_count"]
            
            overall_summary["duration_ms_total"] = int((time.time() - start_total) * 1000)
            
            # Record final status in diagnostic registry
            await registry.record_check(monitor_id, f"job_{job_id}", {d: res_counts[d]["hydration_items"] for d in res_counts}, None)
            
        finally:
            await client.close()
