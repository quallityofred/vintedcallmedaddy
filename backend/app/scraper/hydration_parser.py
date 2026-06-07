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
        
        # Strategy 1: Try parsing as JSON
        try:
            data = json.loads(decoded)
            candidate_items.extend(_find_candidate_items(data))
        except json.JSONDecodeError:
            pass

    # Strategy 2: If no candidates found, try field-sequence scan
    if not candidate_items:
        for chunk in chunks:
            decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
            candidate_items.extend(_extract_items_from_field_sequence(decoded))

    return _normalize_items(candidate_items, domain)

def _is_vinted_item(obj: dict) -> bool:
    """Strict signature check for Vinted items."""
    # Allow items to be extracted if they have an ID and enough evidence
    if "id" not in obj:
        return False
    path = obj.get("path") or obj.get("url") or ""
    # Allow lenient path checking, but require presence of path or title for item-like evidence
    if not isinstance(path, str):
        return False
    if not (obj.get("title") or obj.get("name") or obj.get("path") or obj.get("brand_title")):
        return False
    return True

def _extract_items_from_field_sequence(chunk: str) -> list[dict]:
    """Extract item records from React Flight field-sequence segments."""
    items = []
    # Look for IDs as anchors
    for match in re.finditer(r'"id":\s*(\d+)', chunk):
        start = max(0, match.start() - 200)
        end = min(len(chunk), match.end() + 200)
        window = chunk[start:end]
        
        # Check for marker evidence in the window
        # Require: path, title, brand, price markers (lenient check)
        
        # Extract fields
        path_match = re.search(r'"(?:path|url)":\s*"(.*?)"', window)
        title_match = re.search(r'"(?:title|name)":\s*"(.*?)"', window)
        brand_match = re.search(r'"(?:brand_title|brand)":\s*"(.*?)"', window)
        price_match = re.search(r'"amount":\s*"(.*?)"', window)
        currency_match = re.search(r'"currency_code":\s*"(.*?)"', window)
        
        items.append({
            "id": match.group(1),
            "title": title_match.group(1) if title_match else "Unknown",
            "brand_title": brand_match.group(1) if brand_match else "Unknown",
            "path": path_match.group(1) if path_match else "",
            "price": float(price_match.group(1)) if price_match else 0.0,
            "currency": currency_match.group(1) if currency_match else "EUR"
        })
    return items

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
                "token_windows": []
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
    Prioritizes chunks with the most item-like markers.
    """
    chunks = extract_next_f_chunks(html)
    
    # Analyze all chunks to find the best candidates
    scored_chunks = []
    for i, chunk in enumerate(chunks):
        decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
        
        # Check for item markers in this chunk
        markers = {
            "id": '"id":' in decoded,
            "title": '"title":' in decoded or '"name":' in decoded,
            "path": '"path":' in decoded or '"url":' in decoded,
            "brand": '"brand_title":' in decoded or '"brand":' in decoded,
            "price": '"price":' in decoded or '"amount":' in decoded
        }
        score = sum(markers.values())
        
        # Only consider chunks that have an ID
        if not markers["id"]:
            continue
            
        # Check if this chunk is already covered by structured extraction
        try:
            data = json.loads(decoded)
            if _find_candidate_items(data):
                continue
        except json.JSONDecodeError:
            pass
            
        scored_chunks.append((score, i, decoded, markers))
        
    # Sort by score descending (most markers first)
    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    
    samples = []
    marker_map = [
        ("path", '"path":'),
        ("brand", '"brand_title":'),
        ("price", '"price":'),
        ("title", '"title":')
    ]
    
    for _, i, decoded, markers in scored_chunks[:max_samples]:
        # Capture marker context with tokens for all found markers
        token_windows = []
        
        for marker_type, marker_str in marker_map:
            if marker_str in decoded:
                window = get_token_window_diagnostics(decoded, marker_str)
                if window:
                    token_windows.append(window)

        samples.append({
            "sample_index": len(samples),
            "chunk_index": i,
            "candidate_kind": "marker_context",
            "markers_present": markers,
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
        if isinstance(price, (int, float)):
             price_amount = float(price)
             currency = "EUR"
        elif isinstance(price, dict):
             price_amount = float(price.get("amount") or 0.0)
             currency = price.get("currency_code") or "EUR"
        else:
             price_amount = 0.0
             currency = "EUR"
        
        user = i.get("user") or {}
        normalized.append({
            "id": item_id_str,
            "title": i.get("title") or i.get("name"),
            "brand_title": i.get("brand_title") or i.get("brand"),
            "url": f"https://www.{domain}" + (i.get("path") or ""),
            "path": i.get("path"),
            "price": price_amount,
            "currency": currency,
            "photo_url": i.get("photo", {}).get("url") if isinstance(i.get("photo"), dict) else None,
            "user_id": str(user.get("id")) if isinstance(user, dict) and user.get("id") else None,
            "user_login": user.get("login") if isinstance(user, dict) else None,
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

def collect_literal_marker_diagnostics(html: str, max_samples: int = 3) -> dict:
    """
    Extract safe, redacted literal-marker samples when structured candidate extraction fails.
    """
    chunks = extract_next_f_chunks(html)
    
    samples = {
        "items_path": [],
        "brand_title": [],
        "price": []
    }
    chunk_summary = {
        "top_chunks_with_all_core_markers": []
    }

    marker_map = [
        ("items_path", '"path":'),
        ("brand_title", '"brand_title":'),
        ("price", '"price":'),
    ]
    
    scored_chunks = []
    
    for i, chunk in enumerate(chunks):
        decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
        
        # Check for markers in this chunk
        markers = {
            "id": '"id":' in decoded,
            "title": '"title":' in decoded or '"name":' in decoded,
            "path": '"path":' in decoded or '"url":' in decoded,
            "brand": '"brand_title":' in decoded or '"brand":' in decoded,
            "price": '"price":' in decoded or '"amount":' in decoded
        }
        score = sum(markers.values())
        
        # Populate summary data
        if markers["id"] and markers["title"] and markers["path"] and markers["brand"] and markers["price"]:
            scored_chunks.append({
                "chunk_index": i,
                "items_path_count": decoded.count('"path":'),
                "brand_title_count": decoded.count('"brand_title":'),
                "price_count": decoded.count('"price":'),
                "title_count": decoded.count('"title":'),
                "id_count": decoded.count('"id":')
            })

        # Capture marker samples for markers that exist
        for marker_type, marker_str in marker_map:
            if marker_str in decoded and len(samples[marker_type]) < max_samples:
                window = get_token_window_diagnostics(decoded, marker_str)
                if window:
                    samples[marker_type].append({
                        "chunk_index": i,
                        "marker": marker_type,
                        "tokens": window["tokens"]
                    })
                
    # Sort and take top chunks for summary
    scored_chunks.sort(key=lambda x: x["items_path_count"] + x["brand_title_count"] + x["price_count"], reverse=True)
    chunk_summary["top_chunks_with_all_core_markers"] = scored_chunks[:10]
    
    return {
        "literal_marker_samples": samples,
        "literal_marker_chunk_summary": chunk_summary
    }
