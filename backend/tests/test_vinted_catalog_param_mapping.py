import pytest
from app.scheduler.tasks import _runtime_search_params

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
