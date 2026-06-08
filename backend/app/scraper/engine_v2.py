from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from app.config import Settings, get_settings
from app.scraper.hydration_ssr_merge import fetch_and_parse_hydration_ssr_photos


class ScrapeFailureCode(StrEnum):
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"
    RATE_LIMITED = "rate_limited"
    SOURCE_UNAVAILABLE = "source_unavailable"


@dataclass(frozen=True)
class MonitorScrapeContext:
    monitor_id: int
    original_url: str
    selected_domains: tuple[str, ...]
    params: dict[str, Any]


@dataclass(frozen=True)
class CatalogFetchPlan:
    domains: tuple[str, ...]
    order: str = "newest_first"
    max_pages_per_domain: int = 1
    per_item_detail_fetches: bool = False


@dataclass(frozen=True)
class ParserDiagnostics:
    source: str
    html_fetch_count: int
    item_count: int
    safe_error: str | None = None
    counters: dict[str, int | float | str | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class DomainScrapeResult:
    domain: str
    records: tuple[dict[str, Any], ...]
    diagnostics: ParserDiagnostics


@dataclass(frozen=True)
class ScrapeSourceResult:
    source: str
    domains: tuple[DomainScrapeResult, ...]


class ScrapeEngine(Protocol):
    async def scrape(
        self,
        context: MonitorScrapeContext,
        *,
        max_items_per_domain: int | None = None,
    ) -> ScrapeSourceResult: ...


class CatalogHtmlClient(Protocol):
    async def fetch_catalog_html(self, url: str, *, domain: str | None = None) -> str: ...


def build_catalog_fetch_plan(context: MonitorScrapeContext) -> CatalogFetchPlan:
    return CatalogFetchPlan(domains=tuple(context.selected_domains))


def _catalog_url_for_domain(original_url: str, domain: str) -> str:
    for known_domain in (
        "vinted.co.uk",
        "vinted.fr",
        "vinted.de",
        "vinted.pl",
        "vinted.es",
        "vinted.it",
        "vinted.nl",
        "vinted.pt",
    ):
        if known_domain in original_url:
            return original_url.replace(known_domain, domain, 1)
    return original_url


class HydrationSsrMergedSource:
    """Future engine adapter around the proven one-fetch hydration/SSR service."""

    source_name = "hydration_ssr_photo_merge"

    def __init__(self, client: CatalogHtmlClient) -> None:
        self.client = client

    async def scrape(
        self,
        context: MonitorScrapeContext,
        *,
        max_items_per_domain: int | None = None,
    ) -> ScrapeSourceResult:
        plan = build_catalog_fetch_plan(context)

        async def scrape_domain(domain: str) -> DomainScrapeResult:
            result = await fetch_and_parse_hydration_ssr_photos(
                self.client,
                _catalog_url_for_domain(context.original_url, domain),
                domain=domain,
                max_items=max_items_per_domain,
            )
            safe_stats = result.stats.to_safe_dict()
            counters = {
                key: value
                for key, value in safe_stats.items()
                if isinstance(value, (int, float, str, bool))
            }
            return DomainScrapeResult(
                domain=domain,
                records=tuple(result.records),
                diagnostics=ParserDiagnostics(
                    source=self.source_name,
                    html_fetch_count=result.stats.html_fetch_count,
                    item_count=len(result.records),
                    safe_error=result.stats.photo_merge_error,
                    counters=counters,
                ),
            )

        domains = await asyncio.gather(*(scrape_domain(domain) for domain in plan.domains))
        return ScrapeSourceResult(source=self.source_name, domains=tuple(domains))


def select_scrape_engine_v2(
    client: CatalogHtmlClient,
    *,
    settings: Settings | None = None,
) -> ScrapeEngine | None:
    effective_settings = settings or get_settings()
    if not effective_settings.scraper_engine_v2_enabled:
        return None
    return HydrationSsrMergedSource(client)
