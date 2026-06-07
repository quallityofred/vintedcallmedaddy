import json

from app.scraper.hydration_parser import (
    analyze_item_detail_html,
    collect_hydration_media_token_diagnostics,
)


def _flight_html(*chunks: str) -> str:
    return "".join(
        f"self.__next_f.push([1,{json.dumps(chunk)}])" for chunk in chunks
    )


def test_media_token_diagnostics_counts_image_tokens_without_exposing_values():
    private_image_url = "https://images1.vinted.net/private/item.webp"
    html = _flight_html(
        f'{{"path":"/items/9113341349-test","photo":{{"url":"{private_image_url}"}},"thumbnail":"x"}}'
    )

    diagnostics = collect_hydration_media_token_diagnostics(html, domain="vinted.pl")

    assert diagnostics["chunks_with_image_tokens"] == 1
    assert diagnostics["chunks_with_vinted_cdn_image_urls"] == 1
    assert diagnostics["image_token_presence"]["photo"] == 1
    assert diagnostics["image_token_presence"]["images1.vinted.net"] == 1
    serialized = json.dumps(diagnostics)
    assert private_image_url not in serialized
    assert "/private/item.webp" not in serialized


def test_media_token_diagnostics_counts_timestamp_tokens_without_exposing_values():
    raw_timestamp = "2026-06-07T12:34:56Z"
    html = _flight_html(
        f'{{"path":"/items/9113341350-test","created_at":"{raw_timestamp}","uploaded_at":123}}'
    )

    diagnostics = collect_hydration_media_token_diagnostics(html)

    assert diagnostics["chunks_with_timestamp_tokens"] == 1
    assert diagnostics["timestamp_token_presence"]["created_at"] == 1
    assert diagnostics["timestamp_token_presence"]["uploaded_at"] == 1
    assert raw_timestamp not in json.dumps(diagnostics)


def test_media_token_diagnostics_anchor_window_uses_item_id_and_distance_buckets():
    html = _flight_html(
        '"path":"/items/9113341351-test","photo":{},"listed_at":123'
    )

    diagnostics = collect_hydration_media_token_diagnostics(html, domain="vinted.pl")
    sample = diagnostics["sample_anchor_windows"][0]

    assert sample["item_id"] == "9113341351"
    assert sample["domain"] == "vinted.pl"
    assert sample["nearest_image_token_distance_bucket"] == "0-20"
    assert sample["nearest_timestamp_token_distance_bucket"] == "0-20"
    assert sample["image_field_names_near_anchor"] == ["photo"]
    assert sample["timestamp_field_names_near_anchor"] == ["listed_at"]


def test_media_token_diagnostics_does_not_return_raw_urls_or_chunks():
    raw_chunk = '"path":"/items/9113341352-secret-slug","image":"https://cdn.example/secret.png"'
    diagnostics = collect_hydration_media_token_diagnostics(_flight_html(raw_chunk))
    serialized = json.dumps(diagnostics)

    assert "secret-slug" not in serialized
    assert "cdn.example" not in serialized
    assert "secret.png" not in serialized
    assert diagnostics["sample_anchor_windows"][0]["item_id"] == "9113341352"


def test_media_token_diagnostics_handles_no_photo_no_timestamp():
    diagnostics = collect_hydration_media_token_diagnostics(
        _flight_html('"path":"/items/9113341353-plain","title":"Plain"')
    )

    assert diagnostics["chunks_with_image_tokens"] == 0
    assert diagnostics["chunks_with_timestamp_tokens"] == 0
    sample = diagnostics["sample_anchor_windows"][0]
    assert sample["nearest_image_token_distance_bucket"] == "none"
    assert sample["nearest_timestamp_token_distance_bucket"] == "none"


def test_media_token_diagnostics_limits_samples():
    chunk = " ".join(f'"path":"/items/{9000 + index}-item"' for index in range(15))
    diagnostics = collect_hydration_media_token_diagnostics(
        _flight_html(chunk),
        max_samples=3,
    )

    assert len(diagnostics["sample_anchor_windows"]) == 3


def test_detail_html_parser_detects_og_image_without_returning_raw_html():
    image_url = "https://images.example/private-og.jpg"
    html = f'<html><head><meta property="og:image" content="{image_url}"></head></html>'

    diagnostics = analyze_item_detail_html(html)

    assert diagnostics["image_present"] is True
    assert diagnostics["image_sources"] == ["og:image"]
    assert image_url not in json.dumps(diagnostics)


def test_detail_html_parser_detects_json_ld_image_without_returning_raw_html():
    image_url = "https://images.example/private-json-ld.jpg"
    html = (
        '<script type="application/ld+json">'
        + json.dumps({"@type": "Product", "image": [image_url]})
        + "</script>"
    )

    diagnostics = analyze_item_detail_html(html)

    assert diagnostics["image_present"] is True
    assert diagnostics["image_sources"] == ["json_ld:image"]
    assert image_url not in json.dumps(diagnostics)


def test_detail_html_parser_detects_timestamp_if_present():
    html = '<meta property="article:published_time" content="2026-06-07T12:34:56Z">'

    diagnostics = analyze_item_detail_html(html)

    assert diagnostics["timestamp_present"] is True
    assert diagnostics["timestamp"] == "2026-06-07T12:34:56+00:00"
    assert diagnostics["timestamp_source"] == "meta:article:published_time"


def test_backend_import_ok():
    from app.main import app

    assert app is not None


def test_diagnostics_router_import_ok():
    from app.web.diagnostics_api_router import router

    assert router is not None
