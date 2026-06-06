from __future__ import annotations
import json
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

def extract_next_f_chunks(html: str) -> list[str]:
    """
    Extract all self.__next_f.push(...) chunks from HTML/script text.
    """
    # Regex to find the chunk payload. 
    # Example: self.__next_f.push([1,"..."])
    return re.findall(r'self\.__next_f\.push\(\[1,\"(.*?)\"\]\)', html)

def extract_hydration_items(html: str, domain: str = "vinted.pl") -> list[dict]:
    """
    Extract and normalize item dicts from hydration payload.
    Uses a hybrid approach: rigid structure check, then recursive search.
    """
    chunks = extract_next_f_chunks(html)
    print(f"DEBUG: chunks count={len(chunks)}")
    
    # Reconstruct the payload to search for items
    full_payload = ""
    for chunk in chunks:
        # Unescape quotes and slashes
        decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
        full_payload += decoded
    
    print(f"DEBUG: full_payload={full_payload}")
    # ...
    match = re.search(r'"items":\s*\{\s*"items":\s*(\[.*?\])', full_payload)
    if match:
        try:
            raw_items = json.loads(match[1])
            return _normalize_items(raw_items, domain)
        except json.JSONDecodeError:
            pass

    # Strategy 2: Recursive search for item-like objects
    # Attempt to parse the entire full_payload first
    try:
        data = json.loads(full_payload)
        candidate_items = _find_candidate_items(data)
        print(f"DEBUG: strategy 2 candidates={len(candidate_items)}")
        if candidate_items:
            return _normalize_items(candidate_items, domain)
    except json.JSONDecodeError:
        pass

    # Strategy 3: Try parsing individual chunks if full_payload fails
    for chunk in chunks:
        decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
        try:
            data = json.loads(decoded)
            candidate_items = _find_candidate_items(data)
            if candidate_items:
                return _normalize_items(candidate_items, domain)
        except json.JSONDecodeError:
            continue

    return []

def _find_candidate_items(data: Any) -> list[dict]:
    """
    Recursively search for objects that look like Vinted items.
    """
    candidates = []
    if isinstance(data, dict):
        # Look for IDs and minimal evidence
        if "id" in data:
            if "title" in data or "path" in data or "price" in data or "brand_title" in data:
                candidates.append(data)
        for v in data.values():
            candidates.extend(_find_candidate_items(v))
    elif isinstance(data, list):
        for v in data:
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
        user = i.get("user") or {}
        
        normalized.append({
            "id": item_id_str,
            "title": i.get("title"),
            "brand_title": i.get("brand_title"),
            "url": f"https://www.{domain}" + (i.get("path") or ""),
            "path": i.get("path"),
            "price": float(price.get("amount") or 0.0),
            "currency": price.get("currency_code"),
            "photo_url": i.get("photo", {}).get("url") if i.get("photo") else None,
            "user_id": str(user.get("id")) if user.get("id") else None,
            "user_login": user.get("login"),
            "raw_source": "hydration"
        })
    return normalized

def hydration_record_to_vinted_item(record: dict, domain: str) -> VintedItem:
    """
    Convert a normalized hydration record to a VintedItem.
    """
    from app.scraper.parser import VintedItem
    
    url = record.get("url")
    if not url and record.get("path"):
        url = f"https://www.{domain}{record['path']}"

    return VintedItem(
        id=int(record["id"]),
        title=record.get("title", ""),
        price=float(record.get("price") or 0.0),
        currency=record.get("currency", "EUR"),
        brand=record.get("brand_title", ""),
        size="",
        condition="",
        photo_url=record.get("photo_url", ""),
        item_url=url or "",
        domain=domain,
        seller_id=int(record.get("user_id") or 0),
        brand_id=None,
        raw_source="hydration",
    )

def analyze_hydration_html(html: str) -> dict:
    """
    Diagnostic helper to analyze hydration payload structure safely.
    """
    chunks = extract_next_f_chunks(html)
    
    # Reconstruct the payload to search for items
    full_payload = ""
    for chunk in chunks:
        # Unescape quotes and slashes
        decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
        full_payload += decoded
    
    # Analyze presence of markers
    return {
        "html_contains_next_f": bool(chunks),
        "next_f_chunks": len(chunks),
        "chunks_with_item_text_markers": len(re.findall(r'"title":', full_payload)),
        "chunks_with_brand_title_marker": len(re.findall(r'"brand_title":', full_payload)),
        "chunks_with_price_marker": len(re.findall(r'"price":', full_payload)),
        "chunks_with_items_path_marker": len(re.findall(r'"path":', full_payload)),
        "candidate_item_objects_count": len(re.findall(r'\{"id":', full_payload)),
    }
