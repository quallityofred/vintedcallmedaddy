from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import FoundItem, Monitor, SeenItem
from app.scraper.monitor_filters import extract_monitor_filters
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
    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(select(Monitor).order_by(Monitor.id.asc()))
        monitors = result.scalars().all()
        print("MONITOR FILTER DIAGNOSTICS")
        print(f"monitor_count: {len(monitors)}")
        for monitor in monitors:
            stored_params = _safe_json_loads(monitor.params_json)
            filters = extract_monitor_filters(stored_params)
            seen_count = await db.scalar(
                select(func.count(SeenItem.id)).where(SeenItem.user_id == monitor.user_id)
            )
            found_count = await db.scalar(
                select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id)
            )
            print(
                json.dumps(
                    {
                        "monitor_id": monitor.id,
                        "monitor_name": monitor.name,
                        "original_url": monitor.original_url,
                        "filter_keys": filters.filter_keys,
                        "brand_ids_count": len(filters.brand_ids),
                        "seen_count": seen_count,
                        "found_count": found_count,
                        "params_differ_from_original_url": _derived_params_differ(monitor, stored_params),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
