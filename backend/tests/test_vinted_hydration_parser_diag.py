import pytest
import json
from app.scraper.hydration_parser import get_candidate_samples, collect_redacted_candidate_structures

def test_get_candidate_samples_returns_redacted_skeleton():
    # Synthetic item
    data = {
        "id": 123, 
        "title": "Nike Shox", 
        "brand_title": "Nike", 
        "path": "/items/123", 
        "price": {"amount": "100", "currency_code": "PLN"}
    }
    html = 'self.__next_f.push([1,"{}"])'.format(json.dumps(data).replace("\"", "\\\""))
    samples = get_candidate_samples(html)
    
    assert len(samples) == 1
    assert "key_paths" in samples[0]
    assert "redacted_skeleton" in samples[0]
    skeleton = samples[0]["redacted_skeleton"]
    assert "id" in skeleton
    assert "title" in skeleton
    assert "price" in skeleton

def test_collect_redacted_candidate_structures_generates_token_windows():
    # Synthetic payload with items
    # Chunk with all markers
    chunk = '{"id": 123, "title": "T", "path": "/items/1", "brand_title": "B", "price": {"amount": "10", "currency_code": "PLN"}}'
    html = 'self.__next_f.push([1,"{}"])'.format(chunk.replace("\"", "\\\""))
    
    # We must ensure this does NOT parse as a structured item for the fallback to trigger
    # In this case _find_candidate_items WILL find it, so this test doesn't trigger fallback.
    # To test fallback, need invalid JSON that contains markers
    html_invalid = 'self.__next_f.push([1,"{\\"id\\": 123, \\"path\\": \\"/items/123\\" - garbage"])'
    
    samples = collect_redacted_candidate_structures(html_invalid)
    
    assert len(samples) == 1
    assert "token_windows" in samples[0]
    assert len(samples[0]["token_windows"]) > 0
    
    # Verify no raw values in token windows
    for window in samples[0]["token_windows"]:
        for token in window["tokens"]:
            assert token["value"] not in ["123", "/items/123"]
            assert token["kind"] in ["field", "value"]
