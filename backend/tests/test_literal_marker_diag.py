import pytest
import json
from app.scraper.hydration_parser import collect_literal_marker_diagnostics

def test_collect_literal_marker_diagnostics_emits_windows():
    # Synthetic chunk with markers
    chunk = '{"path": "/items/1", "brand_title": "B", "price": {"amount": "10", "currency_code": "PLN"}}'
    html = 'self.__next_f.push([1,"{}"])'.format(chunk.replace("\"", "\\\""))
    
    diag = collect_literal_marker_diagnostics(html)
    
    assert 'items_path' in diag['literal_marker_samples']
    assert len(diag['literal_marker_samples']['items_path']) > 0
    assert 'tokens' in diag['literal_marker_samples']['items_path'][0]
    
    # Verify redacted fields
    tokens = diag['literal_marker_samples']['items_path'][0]['tokens']
    for token in tokens:
        assert token['value'] not in ["/items/1", "B", "10", "PLN"]
