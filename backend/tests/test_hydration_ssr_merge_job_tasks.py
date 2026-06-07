import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.diagnostics import registry
from app.scheduler.tasks import run_hydration_ssr_merge_job


def _monitor(domains: list[str]):
    monitor = MagicMock()
    monitor.id = 22
    monitor.original_url = "https://www.vinted.pl/catalog?catalog[]=1231"
    monitor.domains_json = json.dumps(domains)
    return monitor


def _session_patches(monitor):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = monitor
    db.execute.return_value = result
    context = AsyncMock()
    context.__aenter__.return_value = db
    session_factory = MagicMock(return_value=context)
    return db, patch(
        "app.scheduler.tasks.get_session_factory",
        return_value=session_factory,
    )


def _hydration_items(domain: str):
    return [
        {
            "id": "101",
            "title": f"First {domain}",
            "price": 10.0,
            "currency": "EUR",
            "path": "/items/101-first",
        },
        {
            "id": "102",
            "title": f"Second {domain}",
            "price": 20.0,
            "currency": "PLN",
            "path": "/items/102-second",
        },
    ]


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_processes_selected_domains_and_fetches_once():
    monitor = _monitor(["vinted.pl", "vinted.fr"])
    db, session_patch = _session_patches(monitor)
    client = AsyncMock()
    html_by_domain = {
        "vinted.pl": "HTML-PL",
        "vinted.fr": "HTML-FR",
    }
    entered: list[str] = []
    both_entered = asyncio.Event()

    async def fetch_once(url, *, domain):
        entered.append(domain)
        if len(entered) == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        return html_by_domain[domain]

    client.fetch_catalog_html.side_effect = fetch_once
    hydration_html_ids: dict[str, int] = {}
    ssr_html_ids: dict[str, int] = {}

    def parse_hydration(html, *, domain):
        hydration_html_ids[domain] = id(html)
        return _hydration_items(domain)

    def parse_ssr(html):
        domain = "vinted.pl" if html == "HTML-PL" else "vinted.fr"
        ssr_html_ids[domain] = id(html)
        return {
            "101": f"https://images1.vinted.net/{domain}/101.webp",
            "999": f"https://images2.vinted.net/{domain}/999.webp",
        }

    job_id = "merge_22_selected"
    await registry.start_job(job_id, 22, "hydration_with_ssr_photos")
    with session_patch, patch(
        "app.scheduler.tasks.VintedClient",
        return_value=client,
    ), patch(
        "app.scheduler.tasks.extract_hydration_items",
        side_effect=parse_hydration,
    ), patch(
        "app.scheduler.tasks.parse_catalog_ssr_photo_map",
        side_effect=parse_ssr,
    ):
        result = await run_hydration_ssr_merge_job(
            22,
            job_id,
            max_domains=8,
            max_items_per_domain=96,
            sample_limit=3,
        )

    assert result is not None
    assert entered == ["vinted.pl", "vinted.fr"]
    assert client.fetch_catalog_html.call_count == 2
    assert hydration_html_ids == ssr_html_ids
    assert result["summary"]["domains_requested_total"] == 2
    assert result["summary"]["domains_processed_total"] == 2
    assert result["summary"]["html_fetch_count_total"] == 2
    assert result["errors_by_domain"] == {}
    assert set(result["counts_by_domain"]) == {"vinted.pl", "vinted.fr"}
    assert db.add.call_count == 0
    assert db.delete.call_count == 0
    assert db.commit.await_count == 0
    assert db.flush.await_count == 0


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_processes_all_eight_selected_domains():
    domains = [
        "vinted.fr",
        "vinted.de",
        "vinted.pl",
        "vinted.es",
        "vinted.it",
        "vinted.nl",
        "vinted.pt",
        "vinted.co.uk",
    ]
    monitor = _monitor(domains)
    _, session_patch = _session_patches(monitor)
    client = AsyncMock()

    async def fetch(url, *, domain):
        await asyncio.sleep(0)
        return f"HTML-{domain}"

    client.fetch_catalog_html.side_effect = fetch
    job_id = "merge_22_eight_domains"
    await registry.start_job(job_id, 22, "hydration_with_ssr_photos")
    with session_patch, patch(
        "app.scheduler.tasks.VintedClient", return_value=client
    ), patch(
        "app.scheduler.tasks.extract_hydration_items", return_value=[]
    ), patch(
        "app.scheduler.tasks.parse_catalog_ssr_photo_map", return_value={}
    ):
        result = await run_hydration_ssr_merge_job(
            22,
            job_id,
            max_domains=8,
            max_items_per_domain=96,
            sample_limit=3,
        )

    assert result is not None
    assert client.fetch_catalog_html.await_count == 8
    assert [call.kwargs["domain"] for call in client.fetch_catalog_html.await_args_list] == domains
    assert list(result["counts_by_domain"]) == domains
    assert result["summary"]["domains_requested_total"] == 8
    assert result["summary"]["domains_processed_total"] == 8
    assert result["summary"]["html_fetch_count_total"] == 8


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_explicit_domain_processes_only_that_domain():
    monitor = _monitor(["vinted.pl", "vinted.fr", "vinted.de"])
    _, session_patch = _session_patches(monitor)
    client = AsyncMock()
    client.fetch_catalog_html.return_value = "HTML-PL"
    job_id = "merge_22_explicit_domain"
    await registry.start_job(job_id, 22, "hydration_with_ssr_photos")
    with session_patch, patch(
        "app.scheduler.tasks.VintedClient", return_value=client
    ), patch(
        "app.scheduler.tasks.extract_hydration_items", return_value=[]
    ), patch(
        "app.scheduler.tasks.parse_catalog_ssr_photo_map", return_value={}
    ):
        result = await run_hydration_ssr_merge_job(
            22,
            job_id,
            target_domain="vinted.pl",
            max_domains=8,
        )

    assert result is not None
    client.fetch_catalog_html.assert_awaited_once()
    assert client.fetch_catalog_html.await_args.kwargs["domain"] == "vinted.pl"
    assert list(result["counts_by_domain"]) == ["vinted.pl"]
    assert result["summary"]["domains_requested_total"] == 1


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_passes_max_domains_and_merges_by_item_id_only():
    monitor = _monitor(["vinted.pl", "vinted.fr", "vinted.de"])
    _, session_patch = _session_patches(monitor)
    client = AsyncMock()
    async def fetch(url, *, domain):
        await asyncio.sleep(0)
        return f"HTML-{domain}"

    client.fetch_catalog_html.side_effect = fetch
    job_id = "merge_22_max_domains"
    await registry.start_job(job_id, 22, "hydration_with_ssr_photos")
    with session_patch, patch(
        "app.scheduler.tasks.VintedClient", return_value=client
    ), patch(
        "app.scheduler.tasks.extract_hydration_items",
        side_effect=lambda html, *, domain: _hydration_items(domain),
    ), patch(
        "app.scheduler.tasks.parse_catalog_ssr_photo_map",
        return_value={
            "102": "https://images1.vinted.net/102.webp",
            "999": "https://images1.vinted.net/ssr-only.webp",
        },
    ):
        result = await run_hydration_ssr_merge_job(
            22,
            job_id,
            max_domains=2,
            sample_limit=10,
        )

    assert result is not None
    assert list(result["counts_by_domain"]) == ["vinted.pl", "vinted.fr"]
    for domain, counts in result["counts_by_domain"].items():
        assert counts["overlap_count"] == 1
        assert counts["merged_with_photo"] == 1
        assert counts["hydration_only_count"] == 1
        assert counts["ssr_photo_only_count"] == 1
        samples = result["samples_by_domain"][domain]
        assert [sample["item_id"] for sample in samples] == ["101", "102"]
        assert [sample["title_preview"] for sample in samples] == [
            f"First {domain}",
            f"Second {domain}",
        ]
        assert [sample["item_url_path"] for sample in samples] == [
            "/items/101-first",
            "/items/102-second",
        ]
        assert samples[0]["has_ssr_photo"] is False
        assert samples[1]["has_ssr_photo"] is True
        assert all(sample["item_id"] != "999" for sample in samples)


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_side_effects_false_and_redacts_photo_urls():
    monitor = _monitor(["vinted.pl"])
    _, session_patch = _session_patches(monitor)
    client = AsyncMock()
    client.fetch_catalog_html.return_value = "SAME-HTML"
    full_photo_url = "https://images1.vinted.net/private/secret-photo.webp"
    job_id = "merge_22_redaction"
    await registry.start_job(job_id, 22, "hydration_with_ssr_photos")
    with session_patch, patch(
        "app.scheduler.tasks.VintedClient", return_value=client
    ), patch(
        "app.scheduler.tasks.extract_hydration_items",
        return_value=_hydration_items("vinted.pl"),
    ), patch(
        "app.scheduler.tasks.parse_catalog_ssr_photo_map",
        return_value={"101": full_photo_url},
    ):
        result = await run_hydration_ssr_merge_job(22, job_id)

    assert result is not None
    assert result["side_effects"] == {
        "reads_database": True,
        "calls_vinted": True,
        "writes_seen_items": False,
        "writes_found_items": False,
        "enqueues_notifications": False,
        "sends_telegram": False,
        "runs_scheduler_check": False,
    }
    serialized = json.dumps(result)
    assert full_photo_url not in serialized
    assert "secret-photo.webp" not in serialized
    assert result["samples_by_domain"]["vinted.pl"][0]["photo_host"] == "images1.vinted.net"


@pytest.mark.asyncio
async def test_hydration_ssr_merge_job_reports_domain_errors_without_hiding_success():
    monitor = _monitor(["vinted.pl", "vinted.fr"])
    _, session_patch = _session_patches(monitor)
    client = AsyncMock()

    async def fetch(url, *, domain):
        if domain == "vinted.fr":
            raise TimeoutError("synthetic secret message")
        return "HTML-PL"

    client.fetch_catalog_html.side_effect = fetch
    job_id = "merge_22_partial"
    await registry.start_job(job_id, 22, "hydration_with_ssr_photos")
    with session_patch, patch(
        "app.scheduler.tasks.VintedClient", return_value=client
    ), patch(
        "app.scheduler.tasks.extract_hydration_items",
        side_effect=lambda html, *, domain: _hydration_items(domain),
    ), patch(
        "app.scheduler.tasks.parse_catalog_ssr_photo_map",
        return_value={"101": "https://images1.vinted.net/101.webp"},
    ):
        result = await run_hydration_ssr_merge_job(22, job_id)

    assert result is not None
    assert set(result["counts_by_domain"]) == {"vinted.pl"}
    assert result["errors_by_domain"] == {"vinted.fr": "TimeoutError"}
    assert result["summary"]["domains_processed_total"] == 2
    assert result["summary"]["domains_succeeded_total"] == 1
    assert result["summary"]["domains_failed_total"] == 1
    assert "synthetic secret message" not in json.dumps(result)
    stored = await registry.get_job(job_id, 22)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.result == result
