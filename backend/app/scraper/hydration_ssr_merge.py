from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol

from app.scraper.catalog_ssr_parser import parse_catalog_ssr_photo_map
from app.scraper.hydration_parser import extract_hydration_items


class CatalogHtmlClient(Protocol):
    async def fetch_catalog_html(self, url: str, *, domain: str | None = None) -> str: ...


@dataclass(frozen=True)
class HydrationSsrMergeStats:
    html_fetch_count: int = 0
    hydration_items: int = 0
    ssr_photo_map_items: int = 0
    overlap_count: int = 0
    overlap_ratio: float = 0.0
    merged_with_photo: int = 0
    missing_photo_after_merge: int = 0
    hydration_only_count: int = 0
    ssr_photo_only_count: int = 0
    photo_hosts: tuple[str, ...] = ()
    fetch_duration_ms: int = 0
    parse_duration_ms: int = 0
    duration_ms: int = 0
    photo_merge_fallback_used: bool = False
    photo_merge_error: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "html_fetch_count": self.html_fetch_count,
            "duration_ms": self.duration_ms,
            "fetch_duration_ms": self.fetch_duration_ms,
            "parse_duration_ms": self.parse_duration_ms,
            "hydration_items": self.hydration_items,
            "ssr_photo_map_items": self.ssr_photo_map_items,
            "overlap_count": self.overlap_count,
            "overlap_ratio": self.overlap_ratio,
            "merged_with_photo": self.merged_with_photo,
            "missing_photo_after_merge": self.missing_photo_after_merge,
            "hydration_only_count": self.hydration_only_count,
            "ssr_photo_only_count": self.ssr_photo_only_count,
            "photo_hosts": list(self.photo_hosts),
            "photo_merge_fallback_used": self.photo_merge_fallback_used,
            "photo_merge_error": self.photo_merge_error,
        }


@dataclass(frozen=True)
class HydrationSsrMergeResult:
    records: list[dict[str, Any]]
    stats: HydrationSsrMergeStats
    ssr_photo_item_ids: frozenset[str] = frozenset()


def _item_id(record: Mapping[str, Any]) -> str:
    value = record.get("id")
    return "" if value is None else str(value)


def _photo_hosts(photo_map: Mapping[str, str]) -> tuple[str, ...]:
    hosts = {
        host
        for value in photo_map.values()
        if isinstance(value, str)
        and value
        and (host := urllib.parse.urlsplit(value).hostname)
    }
    return tuple(sorted(hosts))


def merge_hydration_items_with_ssr_photo_map(
    hydration_items: list[dict[str, Any]],
    ssr_photo_map: Mapping[str, str],
    *,
    photo_merge_fallback_used: bool = False,
    photo_merge_error: str | None = None,
) -> HydrationSsrMergeResult:
    normalized_photo_map = {
        str(item_id): photo_url
        for item_id, photo_url in ssr_photo_map.items()
        if isinstance(photo_url, str) and photo_url
    }
    hydration_ids = {_item_id(item) for item in hydration_items if _item_id(item)}
    ssr_ids = set(normalized_photo_map)
    overlap_ids = hydration_ids & ssr_ids

    merged_records: list[dict[str, Any]] = []
    merged_with_photo = 0
    for hydration_item in hydration_items:
        merged_item = dict(hydration_item)
        photo_url = normalized_photo_map.get(_item_id(hydration_item))
        if photo_url:
            merged_item["photo_url"] = photo_url
            merged_with_photo += 1
        merged_records.append(merged_item)

    missing_photo_after_merge = sum(
        1 for item in merged_records if not item.get("photo_url")
    )
    stats = HydrationSsrMergeStats(
        hydration_items=len(hydration_items),
        ssr_photo_map_items=len(normalized_photo_map),
        overlap_count=len(overlap_ids),
        overlap_ratio=round(len(overlap_ids) / len(hydration_items), 4)
        if hydration_items
        else 0.0,
        merged_with_photo=merged_with_photo,
        missing_photo_after_merge=missing_photo_after_merge,
        hydration_only_count=len(hydration_ids - ssr_ids),
        ssr_photo_only_count=len(ssr_ids - hydration_ids),
        photo_hosts=_photo_hosts(normalized_photo_map),
        photo_merge_fallback_used=photo_merge_fallback_used,
        photo_merge_error=photo_merge_error,
    )
    return HydrationSsrMergeResult(
        records=merged_records,
        stats=stats,
        ssr_photo_item_ids=frozenset(overlap_ids),
    )


def parse_hydration_with_ssr_photos_from_html(
    html: str,
    *,
    domain: str,
    max_items: int | None = None,
) -> HydrationSsrMergeResult:
    parse_started = time.monotonic()
    hydration_items = extract_hydration_items(html, domain=domain)
    if max_items is not None:
        hydration_items = hydration_items[: max(0, max_items)]

    fallback_used = False
    safe_error = None
    try:
        ssr_photo_map = parse_catalog_ssr_photo_map(html)
    except Exception as exc:
        ssr_photo_map = {}
        fallback_used = True
        safe_error = type(exc).__name__

    result = merge_hydration_items_with_ssr_photo_map(
        hydration_items,
        ssr_photo_map,
        photo_merge_fallback_used=fallback_used,
        photo_merge_error=safe_error,
    )
    return HydrationSsrMergeResult(
        records=result.records,
        stats=replace(
            result.stats,
            parse_duration_ms=int((time.monotonic() - parse_started) * 1000),
        ),
        ssr_photo_item_ids=result.ssr_photo_item_ids,
    )


async def fetch_and_parse_hydration_ssr_photos(
    client: CatalogHtmlClient,
    url: str,
    *,
    domain: str,
    max_items: int | None = None,
) -> HydrationSsrMergeResult:
    started = time.monotonic()
    fetch_started = time.monotonic()
    html = await client.fetch_catalog_html(url, domain=domain)
    fetch_duration_ms = int((time.monotonic() - fetch_started) * 1000)
    result = parse_hydration_with_ssr_photos_from_html(
        html,
        domain=domain,
        max_items=max_items,
    )
    return HydrationSsrMergeResult(
        records=result.records,
        stats=replace(
            result.stats,
            html_fetch_count=1,
            fetch_duration_ms=fetch_duration_ms,
            duration_ms=int((time.monotonic() - started) * 1000),
        ),
        ssr_photo_item_ids=result.ssr_photo_item_ids,
    )
