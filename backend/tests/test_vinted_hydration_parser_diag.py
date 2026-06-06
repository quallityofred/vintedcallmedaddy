import pytest
import json
from app.scraper.hydration_parser import get_candidate_samples

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
