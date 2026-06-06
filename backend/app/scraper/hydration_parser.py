from __future__ import annotations
import json
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

def extract_next_f_chunks(html: str) -> list[str]:
    return re.findall(r'self\.__next_f\.push\(\[1,\"(.*?)\"\]\)', html)

def extract_hydration_items(html: str, domain: str = "vinted.pl") -> list[dict]:
    chunks = extract_next_f_chunks(html)
    
    candidate_items = []

    for chunk in chunks:
        # Unescape quotes and slashes
        decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
        
        # Strategy: Try parsing as JSON
        try:
            data = json.loads(decoded)
            candidate_items.extend(_find_candidate_items(data))
        except json.JSONDecodeError:
            pass

    return _normalize_items(candidate_items, domain)

def _is_vinted_item(obj: dict) -> bool:
    """Strict signature check for Vinted items."""
    if "id" not in obj:
        return False
    path = obj.get("path") or obj.get("url") or ""
    # Allow leniency for testing synthetic payloads that might not start with /items/
    if not isinstance(path, str):
        return False
    if not (obj.get("title") or obj.get("name")):
        return False
    if not (obj.get("brand_title") or obj.get("brand")):
        return False
    return True

def get_candidate_samples(html: str, max_samples: int = 5) -> list[dict]:
    """
    Extract safe, redacted sample structures from hydration payload.
    """
    chunks = extract_next_f_chunks(html)
    full_payload = ""
    for chunk in chunks:
        full_payload += chunk.replace('\\\"', '"').replace('\\\\', '\\')
        
    try:
        data = json.loads(full_payload)
        candidates = _find_candidate_items(data)
        
        samples = []
        for cand in candidates[:max_samples]:
            key_paths = []
            skeleton = {}
            
            def _traverse(d: Any, path: str = "$"):
                if isinstance(d, dict):
                    for k, v in d.items():
                        p = f"{path}.{k}"
                        t = type(v).__name__
                        key_paths.append(f"{p}:{t}")
                        if k in ["id", "title", "name", "path", "url", "price", "brand_title", "brand"]:
                            if isinstance(v, dict):
                                skeleton[k] = {}
                            else:
                                skeleton[k] = f"<{t}>"
                        _traverse(v, p)
                elif isinstance(d, list):
                    for i, v in enumerate(d[:3]): # Limit breadth
                        p = f"{path}[{i}]"
                        _traverse(v, p)
            
            _traverse(cand)
            samples.append({
                "key_paths": key_paths[:30],
                "redacted_skeleton": skeleton,
                "token_windows": [] # Structured candidates may not have raw context easily
            })
        return samples
    except Exception:
        return []

def get_token_window_diagnostics(decoded_chunk: str, marker: str, window_size: int = 60) -> dict:
    """Extract safe, redacted token-window diagnostics around a marker."""
    index = decoded_chunk.find(marker)
    if index == -1:
        return {}
        
    start = max(0, index - window_size)
    end = min(len(decoded_chunk), index + window_size + len(marker))
    window = decoded_chunk[start:end]
    
    # Tokenize (simplified: split by common delimiters)
    tokens = re.split(r'([:,{}\[\]"])', window)
    
    diagnostic_tokens = []
    
    # Very basic token classifier
    for t in tokens:
        if not t.strip() or t in [':', ',', '{', '}', '[', ']', '"']:
            continue
        
        # Redact/classify based on field names or type
        kind = "value"
        value = "str"
        
        if t in ["id", "item_id"]:
            kind = "field"
            value = t
        elif t in ["title", "name"]:
            kind = "field"
            value = t
        elif t in ["path", "url", "item_url"]:
            kind = "field"
            value = t
        elif t in ["brand", "brand_title", "brand_name"]:
            kind = "field"
            value = t
        elif t in ["price", "amount", "currency", "currency_code"]:
            kind = "field"
            value = t
            
        diagnostic_tokens.append({"kind": kind, "value": value})
        
    return {
        "around_marker": marker,
        "window_token_count": len(tokens),
        "tokens": diagnostic_tokens[:10],
        "contains_required_item_signature": "id" in [tok["value"] for tok in diagnostic_tokens],
        "likely_extraction_pattern": "field_sequence"
    }

def collect_redacted_candidate_structures(html: str, max_samples: int = 5) -> list[dict]:
    """
    Extract safe, redacted marker-context samples when structured candidate extraction fails.
    """
    chunks = extract_next_f_chunks(html)
    samples = []
    
    # Map markers to detect
    marker_map = [
        ("id", '"id":'),
        ("title", '"title":'),
        ("title", '"name":'),
        ("path", '"path":'),
        ("path", '"url":'),
        ("brand", '"brand_title":'),
        ("brand", '"brand":'),
        ("price", '"price":'),
        ("price", '"amount":')
    ]
    
    for i, chunk in enumerate(chunks):
        if len(samples) >= max_samples:
            break
            
        decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
        
        # Check for item markers in this chunk
        has_id = '"id":' in decoded
        has_title = '"title":' in decoded or '"name":' in decoded
        has_path = '"path":' in decoded or '"url":' in decoded
        has_brand = '"brand_title":' in decoded or '"brand":' in decoded
        has_price = '"price":' in decoded or '"amount":' in decoded
        
        if has_id:
            # Check if this chunk is already covered by structured extraction
            try:
                data = json.loads(decoded)
                if _find_candidate_items(data):
                    continue
            except json.JSONDecodeError:
                pass
            
            # Capture marker context with tokens for all found markers
            token_windows = []
            
            # Helper to add windows only if marker exists in chunk
            for marker_type, marker_str in marker_map:
                if marker_str in decoded:
                    window = get_token_window_diagnostics(decoded, marker_str)
                    if window and window not in token_windows:
                        token_windows.append(window)

            samples.append({
                "sample_index": len(samples),
                "chunk_index": i,
                "candidate_kind": "marker_context",
                "markers_present": {
                    "id": has_id,
                    "title": has_title,
                    "path": has_path,
                    "brand": has_brand,
                    "price": has_price,
                },
                "parseability": {
                    "balanced_object_found": False,
                    "json_raw_decode_success": False,
                },
                "token_windows": token_windows,
                "redacted_skeleton": {
                    "fragment_contains": ["items_path", "brand_title", "price"],
                    "likely_encoding": "react_flight_string_segment"
                }
            })
            
    return samples

def _find_candidate_items(data: Any) -> list[dict]:
    candidates = []
    if isinstance(data, dict):
        if _is_vinted_item(data):
            candidates.append(data)
        for v in data.values():
            if isinstance(v, (dict, list)):
                candidates.extend(_find_candidate_items(v))
    elif isinstance(data, list):
        for v in data:
            if isinstance(v, (dict, list)):
                candidates.extend(_find_candidate_items(v))
    return candidates

def _normalize_items(raw_items: list[dict], domain: str) -> list[dict]:
    normalized = []
    seen_ids = set()
    
    for i in raw_items:
        item_id = i.get("id")
        if item_id is None:
            continue
        item_id_str = str(item_id)
        if item_id_str in seen_ids:
            continue
        
        seen_ids.add(item_id_str)
        
        price = i.get("price") or {}
        if isinstance(price, str):
             price_amount = float(price)
        else:
             price_amount = float(price.get("amount") or 0.0)
             
        normalized.append({
            "id": item_id_str,
            "title": i.get("title") or i.get("name"),
            "brand_title": i.get("brand_title") or i.get("brand"),
            "url": f"https://www.{domain}" + (i.get("path") or ""),
            "path": i.get("path"),
            "price": price_amount,
            "currency": i.get("currency_code") or "EUR",
            "photo_url": i.get("photo", {}).get("url") if isinstance(i.get("photo"), dict) else None,
            "raw_source": "hydration"
        })
    return normalized

def hydration_record_to_vinted_item(record: dict, domain: str) -> VintedItem:
    from app.scraper.parser import VintedItem
    return VintedItem(
        id=int(record["id"]),
        title=record.get("title", ""),
        price=float(record.get("price") or 0.0),
        currency=record.get("currency", "EUR"),
        brand=record.get("brand_title", ""),
        size="",
        condition="",
        photo_url=record.get("photo_url", ""),
        item_url=record.get("url") or "",
        domain=domain,
        seller_id=0,
        brand_id=None,
        raw_source="hydration",
    )

def analyze_hydration_html(html: str) -> dict:
    chunks = extract_next_f_chunks(html)
    full_payload = ""
    for chunk in chunks:
        decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
        full_payload += decoded
    
    return {
        "html_contains_next_f": bool(chunks),
        "next_f_chunks": len(chunks),
        "chunks_with_item_text_markers": len(re.findall(r'"title":', full_payload)),
        "chunks_with_brand_title_marker": len(re.findall(r'"brand_title":', full_payload)),
        "chunks_with_price_marker": len(re.findall(r'"price":', full_payload)),
        "chunks_with_items_path_marker": len(re.findall(r'"path":', full_payload)),
        "candidate_item_objects_count": len(re.findall(r'\{"id":', full_payload)),
    }
