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
    assert skeleton["id"] == "<int>"
    assert skeleton["title"] == "<str>"
    assert "price" in skeleton

def test_collect_redacted_candidate_structures_generates_token_windows():
    # Synthetic payload with items
    # Ensure it's not parseable as a single dict to trigger marker_context fallback
    chunk = '{"id": 123, "title": "T", "path": "/items/1", "brand_title": "B", "price": {"amount": "10", "currency_code": "PLN"}}'
    html = 'self.__next_f.push([1,"{}"])'.format(chunk.replace("\"", "\\\""))
    
    # This chunk *should* be parsed as structured, so let's make it not parseable as a single dict
    # by making it a string segment that needs unescaping in a way that breaks _find_candidate_items
    # Actually, just pass a chunk that looks like valid JSON to it, it will be handled by structured.
    # To test fallback, I need a marker_context that isn't structurally found.
    # Let's provide a payload that contains markers but isn't a valid JSON object.
    
    html = 'self.__next_f.push([1,"{\\"id\\": 123, \\"path\\": \\"/items/123\\" - garbage"])'
    
    samples = collect_redacted_candidate_structures(html)
    
    assert len(samples) == 1
    assert "token_windows" in samples[0]
    assert len(samples[0]["token_windows"]) > 0
    
    # Verify no raw values in token windows
    for window in samples[0]["token_windows"]:
        for token in window["tokens"]:
            assert token["value"] not in ["123", "/items/123"]
            assert token["kind"] in ["field", "value"]
