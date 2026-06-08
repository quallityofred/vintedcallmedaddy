from unittest.mock import patch

from app.scraper.hydration_ssr_merge import parse_hydration_with_ssr_photos_from_html


def test_hydration_with_ssr_photos_merges_data():
    synthetic_photo = "https://images.example.invalid/item.webp"
    with patch(
        "app.scraper.hydration_ssr_merge.extract_hydration_items",
        return_value=[
            {
                "id": "1",
                "title": "Nike Shoes",
                "price": 100.0,
                "currency": "PLN",
                "path": "/items/1-nike-shoes",
            }
        ],
    ), patch(
        "app.scraper.hydration_ssr_merge.parse_catalog_ssr_photo_map",
        return_value={"1": synthetic_photo},
    ):
        result = parse_hydration_with_ssr_photos_from_html(
            "<html>synthetic</html>",
            domain="vinted.pl",
        )

    assert result.stats.overlap_count == 1
    assert result.stats.merged_with_photo == 1
    assert result.records[0]["photo_url"] == synthetic_photo
    assert synthetic_photo not in str(result.stats.to_safe_dict())
