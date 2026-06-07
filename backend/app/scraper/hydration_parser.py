from __future__ import annotations
import json
import re
import logging
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_ITEM_PATH_PATTERN = re.compile(
    r'(?P<value>(?:https?://[^"\'\s\\]+)?/items/(?P<id>\d+)(?:-[^"\'\s\\]*)?)',
    re.IGNORECASE,
)
_ITEMS_LITERAL_PATTERN = re.compile(r"/items/", re.IGNORECASE)
_FIELD_SEQUENCE_RADIUS = 1500


def _empty_field_sequence_diagnostics() -> dict:
    return {
        "field_sequence_path_markers": 0,
        "field_sequence_records_before_validation": 0,
        "field_sequence_records_after_validation": 0,
        "field_sequence_records_after_dedup": 0,
        "field_sequence_rejections": {
            "missing_path_id": 0,
            "missing_title": 0,
            "missing_brand": 0,
            "missing_price": 0,
            "missing_currency": 0,
            "duplicate_path_id": 0,
            "generic_id_mismatch_ignored": 0,
            "unknown_title": 0,
        },
        "parser_strategy_used": "structured_json",
    }

def extract_next_f_chunks(html: str) -> list[str]:
    return re.findall(r'self\.__next_f\.push\(\[1,\"(.*?)\"\]\)', html)

def extract_hydration_items(
    html: str,
    domain: str = "vinted.pl",
    diagnostics: dict | None = None,
) -> list[dict]:
    chunks = extract_next_f_chunks(html)
    candidate_items: list[dict] = []
    field_sequence_diagnostics = _empty_field_sequence_diagnostics()

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
        field_sequence_diagnostics["parser_strategy_used"] = (
            "react_flight_field_sequence_path_anchored"
        )
        for chunk in chunks:
            decoded = chunk.replace('\\\"', '"').replace('\\\\', '\\')
            candidate_items.extend(
                _extract_items_from_field_sequence(
                    decoded,
                    diagnostics=field_sequence_diagnostics,
                )
            )
        deduplicated_candidates: list[dict] = []
        seen_path_ids: set[str] = set()
        seen_paths: set[str] = set()
        for candidate in candidate_items:
            candidate_path = _normalized_item_path(candidate.get("path"))
            candidate_id = _path_item_id(candidate_path)
            if (
                candidate_id in seen_path_ids
                or (candidate_path is not None and candidate_path in seen_paths)
            ):
                field_sequence_diagnostics["field_sequence_rejections"][
                    "duplicate_path_id"
                ] += 1
                continue
            if candidate_id is not None:
                seen_path_ids.add(candidate_id)
            if candidate_path is not None:
                seen_paths.add(candidate_path)
            deduplicated_candidates.append(candidate)
        candidate_items = deduplicated_candidates

    normalized = _normalize_items(candidate_items, domain)
    if field_sequence_diagnostics["parser_strategy_used"] == (
        "react_flight_field_sequence_path_anchored"
    ):
        field_sequence_diagnostics["field_sequence_records_after_dedup"] = len(normalized)
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(field_sequence_diagnostics)
    return normalized

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

def _decode_string_value(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except (json.JSONDecodeError, TypeError):
        return value


def _nearest_string_field(
    segment: str,
    field_names: tuple[str, ...],
    anchor_offset: int,
) -> str | None:
    for field_name in field_names:
        matches = list(
            re.finditer(
                rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"',
                segment,
                re.IGNORECASE,
            )
        )
        if matches:
            match = min(matches, key=lambda candidate: abs(candidate.start() - anchor_offset))
            value = _decode_string_value(match.group(1)).strip()
            if value:
                return value
    return None


def _nearest_amount_field(segment: str, anchor_offset: int) -> str | None:
    matches = list(
        re.finditer(
            r'"amount"\s*:\s*(?:"((?:\\.|[^"\\])*)"|(-?\d+(?:\.\d+)?))',
            segment,
            re.IGNORECASE,
        )
    )
    if not matches:
        return None
    match = min(matches, key=lambda candidate: abs(candidate.start() - anchor_offset))
    value = match.group(1) if match.group(1) is not None else match.group(2)
    return _decode_string_value(value).strip() if value else None


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _normalized_item_path(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.lower().startswith(("http://", "https://")):
        text = urlsplit(text).path
    match = _ITEM_PATH_PATTERN.search(text)
    if not match:
        return text
    path = match.group("value")
    if path.lower().startswith(("http://", "https://")):
        path = urlsplit(path).path
    return path.split("?", 1)[0].split("#", 1)[0]


def _path_item_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    match = _ITEM_PATH_PATTERN.search(value)
    return match.group("id") if match else None


def _extract_items_from_field_sequence(
    chunk: str,
    diagnostics: dict | None = None,
) -> list[dict]:
    """Extract strict item records anchored to canonical `/items/<id>` paths."""
    local_diagnostics = (
        diagnostics if diagnostics is not None else _empty_field_sequence_diagnostics()
    )
    rejections = local_diagnostics["field_sequence_rejections"]
    path_matches = list(_ITEM_PATH_PATTERN.finditer(chunk))
    local_diagnostics["field_sequence_path_markers"] += len(path_matches)
    local_diagnostics["field_sequence_records_before_validation"] += len(path_matches)
    rejections["missing_path_id"] += max(
        0,
        len(_ITEMS_LITERAL_PATTERN.findall(chunk)) - len(path_matches),
    )

    items: list[dict] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, path_match in enumerate(path_matches):
        previous_start = path_matches[index - 1].start() if index > 0 else None
        next_start = path_matches[index + 1].start() if index + 1 < len(path_matches) else None
        start = max(0, path_match.start() - _FIELD_SEQUENCE_RADIUS)
        end = min(len(chunk), path_match.end() + _FIELD_SEQUENCE_RADIUS)
        if previous_start is not None:
            start = max(start, (previous_start + path_match.start()) // 2)
        if next_start is not None:
            end = min(end, (path_match.start() + next_start) // 2)

        segment = chunk[start:end]
        anchor_offset = path_match.start() - start
        path = _normalized_item_path(path_match.group("value"))
        path_id = path_match.group("id")
        generic_ids = re.findall(r'"id"\s*:\s*"?(\d+)"?', segment)
        rejections["generic_id_mismatch_ignored"] += sum(
            generic_id != path_id for generic_id in generic_ids
        )

        title = _nearest_string_field(segment, ("title", "name"), anchor_offset)
        brand = _nearest_string_field(segment, ("brand_title", "brand"), anchor_offset)
        amount = _nearest_amount_field(segment, anchor_offset)
        currency = _nearest_string_field(segment, ("currency_code",), anchor_offset)

        rejected = False
        if not path or not path_id:
            rejections["missing_path_id"] += 1
            rejected = True
        if not title:
            rejections["missing_title"] += 1
            rejected = True
        elif title.casefold() == "unknown":
            rejections["unknown_title"] += 1
            rejected = True
        if not brand or brand.casefold() == "unknown":
            rejections["missing_brand"] += 1
            rejected = True
        if amount is None or _safe_float(amount) is None:
            rejections["missing_price"] += 1
            rejected = True
        if not currency:
            rejections["missing_currency"] += 1
            rejected = True
        if rejected:
            continue

        local_diagnostics["field_sequence_records_after_validation"] += 1
        if path_id in seen_ids or path in seen_paths:
            rejections["duplicate_path_id"] += 1
            continue
        seen_ids.add(path_id)
        seen_paths.add(path)
        items.append({
            "id": path_id,
            "title": title,
            "brand_title": brand,
            "path": path,
            "price": {
                "amount": amount,
                "currency_code": currency,
            },
            "raw_source": "hydration",
            "_extraction_strategy": "react_flight_field_sequence_path_anchored",
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
    normalized: list[dict] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    
    for i in raw_items:
        raw_path = i.get("path") or i.get("url")
        normalized_path = _normalized_item_path(raw_path)
        path_item_id = _path_item_id(raw_path)
        item_id = path_item_id or i.get("id")
        if item_id is None:
            continue
        item_id_str = str(item_id)
        is_field_sequence = i.get("_extraction_strategy") == (
            "react_flight_field_sequence_path_anchored"
        )
        title = i.get("title") or i.get("name")
        brand = i.get("brand_title") or i.get("brand")
        if is_field_sequence:
            if not path_item_id or not normalized_path:
                continue
            if not title or str(title).strip().casefold() == "unknown":
                continue
            if not brand or str(brand).strip().casefold() == "unknown":
                continue

        if item_id_str in seen_ids or (
            normalized_path is not None and normalized_path in seen_paths
        ):
            continue
        
        seen_ids.add(item_id_str)
        if normalized_path is not None:
            seen_paths.add(normalized_path)
        
        price = i.get("price") or {}
        raw_price_amount: Any = None
        if isinstance(price, (int, float)):
             raw_price_amount = price
             price_amount = _safe_float(price) or 0.0
             currency = i.get("currency") or "EUR"
        elif isinstance(price, dict):
             raw_price_amount = price.get("amount")
             price_amount = _safe_float(price.get("amount")) or 0.0
             currency = price.get("currency_code") or i.get("currency") or "EUR"
        else:
             price_amount = 0.0
             currency = i.get("currency") or "EUR"

        if is_field_sequence and (
            _safe_float(raw_price_amount) is None or not currency
        ):
            continue
        
        user = i.get("user") or {}
        if normalized_path:
            item_url = f"https://www.{domain}{normalized_path}"
        elif isinstance(raw_path, str) and raw_path.lower().startswith(("http://", "https://")):
            item_url = raw_path
        else:
            item_url = f"https://www.{domain}" + (raw_path or "")
        normalized.append({
            "id": item_id_str,
            "title": title,
            "brand_title": brand,
            "url": item_url,
            "path": normalized_path or raw_path,
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
