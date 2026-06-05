from __future__ import annotations

import asyncio
import argparse
import json

from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import FoundItem, Monitor, SeenItem, User
from app.scraper.monitor_filters import extract_monitor_filters, has_restrictive_filters
from app.scraper.url_parser import parse_vinted_url


def _safe_json_loads(value: str) -> dict:
    try:
        data = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _derived_params_differ(monitor: Monitor, stored_params: dict) -> bool:
    try:
        derived = parse_vinted_url(monitor.original_url)
    except Exception:
        return True

    stored_without_runtime = dict(stored_params)
    stored_without_runtime.pop("_original_interval", None)
    return derived != stored_without_runtime


async def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only monitor filter diagnostics.")
    parser.add_argument("--username", help="Limit diagnostics to one username.")
    parser.add_argument("--latest-items", type=int, default=5, help="Latest found items per monitor to include.")
    args = parser.parse_args()

    session_factory = get_session_factory()
    async with session_factory() as db:
        user_id: int | None = None
        if args.username:
            user_result = await db.execute(select(User.id, User.username).where(User.username == args.username))
            user_row = user_result.one_or_none()
            if user_row is None:
                print(json.dumps({"username": args.username, "found": False}, sort_keys=True))
                return
            user_map = user_row._mapping
            user_id = user_map["id"]
            print(json.dumps({"username": user_map["username"], "user_id": user_id, "found": True}, sort_keys=True))

        monitor_stmt = select(Monitor).order_by(Monitor.id.asc())
        if user_id is not None:
            monitor_stmt = monitor_stmt.where(Monitor.user_id == user_id)
        result = await db.execute(monitor_stmt)
        monitors = result.scalars().all()
        print("MONITOR FILTER DIAGNOSTICS")
        print(f"monitor_count: {len(monitors)}")
        for monitor in monitors:
            stored_params = _safe_json_loads(monitor.params_json)
            filters = extract_monitor_filters(stored_params)
            url_params = parse_vinted_url(monitor.original_url)
            url_filters = extract_monitor_filters(url_params)
            seen_count = await db.scalar(
                select(func.count(SeenItem.id)).where(SeenItem.user_id == monitor.user_id)
            )
            found_count = await db.scalar(
                select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id)
            )
            latest_result = await db.execute(
                select(FoundItem)
                .where(FoundItem.monitor_id == monitor.id)
                .order_by(FoundItem.found_at.desc())
                .limit(max(args.latest_items, 0))
            )
            latest_items = [
                {
                    "found_item_id": item.id,
                    "vinted_item_id": item.vinted_item_id,
                    "brand": item.brand,
                    "title": item.title,
                    "domain": item.domain,
                    "item_url": item.item_url,
                    "found_at": item.found_at.isoformat() if item.found_at else None,
                    "notified": item.notified,
                }
                for item in latest_result.scalars().all()
            ]
            print(
                json.dumps(
                    {
                        "monitor_id": monitor.id,
                        "monitor_name": monitor.name,
                        "original_url": monitor.original_url,
                        "stored_filter_keys": filters.filter_keys,
                        "url_filter_keys": url_filters.filter_keys,
                        "stored_brand_ids": sorted(filters.brand_ids),
                        "url_brand_ids": sorted(url_filters.brand_ids),
                        "stored_has_restrictive_filters": has_restrictive_filters(filters),
                        "url_has_restrictive_filters": has_restrictive_filters(url_filters),
                        "seen_count": seen_count,
                        "found_count": found_count,
                        "params_differ_from_original_url": _derived_params_differ(monitor, stored_params),
                        "latest_found_items": latest_items,
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
