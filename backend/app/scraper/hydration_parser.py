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
    """
    chunks = extract_next_f_chunks(html)
    
    # Reconstruct the payload to search for items
    full_payload = ""
    for chunk in chunks:
        # Unescape quotes and slashes
        decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
        full_payload += decoded
    
    # Locate items.items array
    # Looking for a structure like "items":{"items":[{...}]}
    match = re.search(r'"items":\{"items":(\[.*?\])\}', full_payload)
    if not match:
        return []
    
    try:
        raw_items = json.loads(match[1])
    except json.JSONDecodeError:
        return []

    normalized = []
    seen_ids = set()
    
    for i in raw_items:
        item_id = str(i.get("id"))
        if not item_id or item_id in seen_ids:
            continue
        
        seen_ids.add(item_id)
        
        price = i.get("price") or {}
        user = i.get("user") or {}
        
        normalized.append({
            "id": item_id,
            "title": i.get("title"),
            "brand_title": i.get("brand_title"),
            "url": f"https://www.{domain}" + i.get("path", ""),
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

def find_item_field_paths(raw: dict | list, current_path: str = "") -> dict[str, list[str]]:
    """
    Diagnostic helper to find field paths.
    """
    found = {}
    
    if isinstance(raw, dict):
        for k, v in raw.items():
            path = f"{current_path}.{k}" if current_path else k
            if "catalog" in k.lower() or "category" in k.lower() or "created" in k.lower() or "uploaded" in k.lower() or "timestamp" in k.lower():
                found.setdefault(k, []).append(path)
            found.update(find_item_field_paths(v, path))
    elif isinstance(raw, list):
        for i, v in enumerate(raw):
            found.update(find_item_field_paths(v, f"{current_path}[{i}]"))
            
    return found
