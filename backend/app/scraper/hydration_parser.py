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
            samples.append({
                "id": cand.get("id"),
                "keys": list(cand.keys()),
                "has_title": "title" in cand or "name" in cand,
                "has_brand": "brand" in cand or "brand_title" in cand,
                "has_price": "price" in cand,
                "has_path": "path" in cand or "url" in cand,
            })
        return samples
    except Exception:
        return []

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
            "currency": price.get("currency_code") or "EUR",
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
