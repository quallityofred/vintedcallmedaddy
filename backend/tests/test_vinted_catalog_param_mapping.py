from urllib.parse import parse_qs, urlsplit

from app.scheduler.tasks import _runtime_search_params
from app.scraper.url_parser import build_vinted_catalog_url

def test_runtime_params_catalog_mapping():
    # Input params as parsed from URL
    params = {
        'order': 'newest_first',
        'brand_ids[]': [53],
        'catalog[]': [1231],
        'search_id': '123'
    }
    
    runtime_params = _runtime_search_params(params)
    
    assert 'order' in runtime_params
    assert runtime_params['order'] == 'newest_first'
    assert 'brand_ids[]' in runtime_params
    assert runtime_params['brand_ids[]'] == [53]
    assert 'catalog_ids[]' in runtime_params
    assert runtime_params['catalog_ids[]'] == [1231]
    assert 'catalog[]' not in runtime_params
    assert 'search_id' not in runtime_params

def test_runtime_params_multiple_catalog_values():
    params = {
        'catalog[]': [1231, 1232]
    }
    
    runtime_params = _runtime_search_params(params)
    assert 'catalog_ids[]' in runtime_params
    assert runtime_params['catalog_ids[]'] == [1231, 1232]

def test_runtime_params_no_catalog():
    params = {'brand_ids[]': [53]}
    runtime_params = _runtime_search_params(params)
    assert 'catalog_ids[]' not in runtime_params
    assert 'brand_ids[]' in runtime_params


def test_runtime_params_canonicalize_catalog_aliases_and_drop_internal_values():
    runtime_params = _runtime_search_params({
        "brand_ids": [53],
        "catalog_id": 1231,
        "_original_interval": 120,
        "page": 4,
    })

    assert runtime_params == {
        "brand_ids[]": [53],
        "catalog_ids[]": [1231],
        "order": "newest_first",
    }


def test_catalog_url_uses_effective_params_when_original_query_is_broad():
    url = build_vinted_catalog_url(
        "https://www.vinted.pl/catalog?brand_ids[]=53",
        "vinted.fr",
        {
            "brand_ids[]": [53],
            "catalog[]": [1231],
            "order": "newest_first",
        },
    )

    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    assert parsed.hostname == "www.vinted.fr"
    assert params["brand_ids[]"] == ["53"]
    assert params["catalog_ids[]"] == ["1231"]
    assert params["order"] == ["newest_first"]
