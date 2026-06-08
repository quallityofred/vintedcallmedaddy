from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.scheduler import tasks
from app.scraper.engine_v2 import (
    HydrationSsrMergedSource,
    MonitorScrapeContext,
    build_catalog_fetch_plan,
    select_scrape_engine_v2,
)


def context(domains: tuple[str, ...] = ("vinted.pl", "vinted.de")) -> MonitorScrapeContext:
    return MonitorScrapeContext(
        monitor_id=22,
        original_url="https://www.vinted.pl/catalog?catalog[]=1231&order=newest_first",
        selected_domains=domains,
        params={"catalog[]": ["1231"], "order": "newest_first"},
    )


def record(item_id: str, title: str) -> dict:
    return {
        "id": item_id,
        "title": title,
        "brand_title": "Nike",
        "price": {"amount": "10", "currency_code": "EUR"},
        "path": f"/items/{item_id}-item",
    }


def test_scraper_engine_v2_defaults_off_and_scheduler_path_is_unchanged():
    settings = Settings(_env_file=None)
    client = AsyncMock()

    assert settings.scraper_engine_v2_enabled is False
    assert select_scrape_engine_v2(client, settings=settings) is None
    assert "engine_v2" not in inspect.getsource(tasks._fetch_domain_results)


def test_scraper_engine_v2_selector_can_be_instantiated_when_enabled():
    settings = Settings(_env_file=None, scraper_engine_v2_enabled=True)

    selected = select_scrape_engine_v2(AsyncMock(), settings=settings)

    assert isinstance(selected, HydrationSsrMergedSource)


def test_catalog_fetch_plan_preserves_all_selected_domains_and_delta_defaults():
    selected_domains = ("vinted.fr", "vinted.de", "vinted.pl", "vinted.es")

    plan = build_catalog_fetch_plan(context(selected_domains))

    assert plan.domains == selected_domains
    assert plan.order == "newest_first"
    assert plan.max_pages_per_domain == 1
    assert plan.per_item_detail_fetches is False


@pytest.mark.asyncio
async def test_engine_fetches_once_per_domain_and_introduces_no_detail_fetches():
    client = AsyncMock()
    client.fetch_catalog_html.side_effect = ["PL-HTML", "DE-HTML"]
    client.fetch_item_detail = AsyncMock(side_effect=AssertionError("detail fetch forbidden"))

    def hydration_parser(html: str, *, domain: str):
        return [record("101" if domain == "vinted.pl" else "202", domain)]

    with patch(
        "app.scraper.hydration_ssr_merge.extract_hydration_items",
        side_effect=hydration_parser,
    ), patch(
        "app.scraper.hydration_ssr_merge.parse_catalog_ssr_photo_map",
        return_value={},
    ):
        result = await HydrationSsrMergedSource(client).scrape(context())

    assert client.fetch_catalog_html.await_count == 2
    assert [call.kwargs["domain"] for call in client.fetch_catalog_html.await_args_list] == [
        "vinted.pl",
        "vinted.de",
    ]
    client.fetch_item_detail.assert_not_awaited()
    assert tuple(domain.domain for domain in result.domains) == ("vinted.pl", "vinted.de")
    assert all(domain.diagnostics.html_fetch_count == 1 for domain in result.domains)
