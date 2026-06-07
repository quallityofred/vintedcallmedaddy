from __future__ import annotations
import json
import re
import logging
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_ITEM_PATH_PATTERN = re.compile(
    r'(?P<value>(?:https?://[^"\'\s\\]+)?/items/(?P<id>\d+)(?:-[^"\'\s\\]*)?)',
    re.IGNORECASE,
)
_ITEMS_LITERAL_PATTERN = re.compile(r"/items/", re.IGNORECASE)
_FIELD_SEQUENCE_RADIUS = 1500

_TIMESTAMP_FIELDS = (
    "listed_at",
    "created_at",
    "uploaded_at",
    "published_at",
    "publication_date",
    "updated_at",
    "bumped_at",
    "timestamp",
)

_IMAGE_TOKEN_PATTERNS = {
    "photo": re.compile(r"\bphoto\b", re.IGNORECASE),
    "photos": re.compile(r"\bphotos\b", re.IGNORECASE),
    "thumbnail": re.compile(r"\bthumbnail\b", re.IGNORECASE),
    "thumbnails": re.compile(r"\bthumbnails\b", re.IGNORECASE),
    "image": re.compile(r"\bimage\b", re.IGNORECASE),
    "images": re.compile(r"\bimages\b", re.IGNORECASE),
    "high_resolution": re.compile(r"\bhigh_resolution\b", re.IGNORECASE),
    "webp": re.compile(r"(?:\.webp\b|\bwebp\b)", re.IGNORECASE),
    ".jpg": re.compile(r"\.jpg\b", re.IGNORECASE),
    ".jpeg": re.compile(r"\.jpeg\b", re.IGNORECASE),
    ".png": re.compile(r"\.png\b", re.IGNORECASE),
    "images1.vinted.net": re.compile(r"\bimages1\.vinted\.net\b", re.IGNORECASE),
    "images2.vinted.net": re.compile(r"\bimages2\.vinted\.net\b", re.IGNORECASE),
    "vinted.net": re.compile(r"\bvinted\.net\b", re.IGNORECASE),
    "cdn": re.compile(r"\bcdn\b", re.IGNORECASE),
}

_TIMESTAMP_TOKEN_PATTERNS = {
    "created_at": re.compile(r"\bcreated_at\b", re.IGNORECASE),
    "updated_at": re.compile(r"\bupdated_at\b", re.IGNORECASE),
    "uploaded_at": re.compile(r"\buploaded_at\b", re.IGNORECASE),
    "listed_at": re.compile(r"\blisted_at\b", re.IGNORECASE),
    "bumped_at": re.compile(r"\bbumped_at\b", re.IGNORECASE),
    "timestamp": re.compile(r"\btimestamp\b", re.IGNORECASE),
    "time": re.compile(r"\btime\b", re.IGNORECASE),
    "published_at": re.compile(r"\bpublished_at\b", re.IGNORECASE),
    "photo_high_resolution.timestamp": re.compile(
        r"\bphoto_high_resolution\b.{0,80}\btimestamp\b",
        re.IGNORECASE | re.DOTALL,
    ),
}

_DISTANCE_BUCKETS = ("0-20", "21-50", "51-100", ">100", "none")


def _empty_item_field_diagnostics() -> dict:
    return {
        "sampled_items": 0,
        "photo_url_present": 0,
        "photo_url_missing": 0,
        "photo_field_presence": {
            "direct.photo_url": 0,
            "photo.url": 0,
            "photo.full_size_url": 0,
            "photo.thumbnail_url": 0,
            "photo.high_resolution.url": 0,
            "photo_high_resolution.url": 0,
            "photos[0].url": 0,
            "thumbnails[0].url": 0,
            "image.url": 0,
        },
        "timestamp_field_presence": {field: 0 for field in _TIMESTAMP_FIELDS},
        "timestamp_parsed": 0,
        "timestamp_missing": 0,
    }

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
    include_media_diagnostics: bool = False,
    media_diag_max_items: int = 10,
    media_diag_max_chunks: int = 20,
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

    item_field_diagnostics = _collect_item_field_diagnostics(candidate_items)
    normalized = _normalize_items(candidate_items, domain)
    item_field_diagnostics["photo_url_present"] = sum(
        bool(item.get("photo_url")) for item in normalized
    )
    item_field_diagnostics["photo_url_missing"] = (
        len(normalized) - item_field_diagnostics["photo_url_present"]
    )
    item_field_diagnostics["timestamp_parsed"] = sum(
        bool(item.get("listed_at")) for item in normalized
    )
    item_field_diagnostics["timestamp_missing"] = (
        len(normalized) - item_field_diagnostics["timestamp_parsed"]
    )
    if field_sequence_diagnostics["parser_strategy_used"] == (
        "react_flight_field_sequence_path_anchored"
    ):
        field_sequence_diagnostics["field_sequence_records_after_dedup"] = len(normalized)
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(field_sequence_diagnostics)
        diagnostics["item_field_diagnostics"] = item_field_diagnostics
        if include_media_diagnostics:
            try:
                diagnostics["media_token_diagnostics"] = collect_hydration_media_token_diagnostics(
                    chunks,
                    domain=domain,
                    max_items=media_diag_max_items,
                    max_chunks=media_diag_max_chunks,
                )
            except Exception as exc:
                logger.warning("media_diagnostics_failed domain=%s exception=%s", domain, exc)
                diagnostics["media_token_diagnostics"] = {"enabled": False, "error": str(exc)}
        else:
            diagnostics["media_token_diagnostics"] = {"enabled": False}
    return normalized


def _decoded_next_f_chunk(chunk: str) -> str:
    return chunk.replace('\\"', '"').replace('\\\\', '\\')


def _pattern_matches(text: str, patterns: dict[str, re.Pattern[str]]) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for name, pattern in patterns.items():
        matches.extend((match.start(), name) for match in pattern.finditer(text))
    return sorted(matches)


def _token_distance(text: str, first_offset: int, second_offset: int) -> int:
    start, end = sorted((first_offset, second_offset))
    return len(re.findall(r"/items/\d+|[A-Za-z0-9_]+", text[start:end]))


def _distance_bucket(distance: int | None) -> str:
    if distance is None:
        return "none"
    if distance <= 20:
        return "0-20"
    if distance <= 50:
        return "21-50"
    if distance <= 100:
        return "51-100"
    return ">100"


def _anchor_token_diagnostics(
    text: str,
    anchor_offset: int,
    matches: list[tuple[int, str]],
) -> tuple[str, list[str]]:
    if not matches:
        return "none", []
    distances = [(_token_distance(text, anchor_offset, offset), name) for offset, name in matches]
    nearest = min(distance for distance, _ in distances)
    nearby_names = sorted({name for distance, name in distances if distance <= 100})
    return _distance_bucket(nearest), nearby_names


def collect_hydration_media_token_diagnostics(
    html_or_chunks: str | list[str],
    *,
    domain: str | None = None,
    max_items: int = 10,
    max_chunks: int = 20,
) -> dict:
    """Return bounded media/time marker counts without returning marker values."""
    chunks = (
        extract_next_f_chunks(html_or_chunks)
        if isinstance(html_or_chunks, str)
        else list(html_or_chunks)
    )
    
    # Apply chunk bound
    chunks = chunks[:max_chunks]
    
    diagnostics = {
        "enabled": True,
        "chunks_scanned": len(chunks),
        "chunks_with_item_paths": 0,
        "chunks_with_image_tokens": 0,
        "chunks_with_timestamp_tokens": 0,
        "chunks_with_vinted_cdn_image_urls": 0,
        "image_token_presence": {name: 0 for name in _IMAGE_TOKEN_PATTERNS},
        "timestamp_token_presence": {name: 0 for name in _TIMESTAMP_TOKEN_PATTERNS},
        "image_anchor_distance_buckets": {bucket: 0 for bucket in _DISTANCE_BUCKETS},
        "timestamp_anchor_distance_buckets": {bucket: 0 for bucket in _DISTANCE_BUCKETS},
        "sample_anchor_windows": [],
    }
    seen_item_ids: set[str] = set()

    for chunk in chunks:
        decoded = _decoded_next_f_chunk(chunk)
        anchors = list(_ITEM_PATH_PATTERN.finditer(decoded))
        image_matches = _pattern_matches(decoded, _IMAGE_TOKEN_PATTERNS)
        timestamp_matches = _pattern_matches(decoded, _TIMESTAMP_TOKEN_PATTERNS)
        diagnostics["chunks_with_item_paths"] += int(
            bool(_ITEMS_LITERAL_PATTERN.search(decoded))
        )
        diagnostics["chunks_with_image_tokens"] += int(bool(image_matches))
        diagnostics["chunks_with_timestamp_tokens"] += int(bool(timestamp_matches))
        diagnostics["chunks_with_vinted_cdn_image_urls"] += int(
            bool(
                _IMAGE_TOKEN_PATTERNS["images1.vinted.net"].search(decoded)
                or _IMAGE_TOKEN_PATTERNS["images2.vinted.net"].search(decoded)
            )
        )
        for name, pattern in _IMAGE_TOKEN_PATTERNS.items():
            diagnostics["image_token_presence"][name] += len(pattern.findall(decoded))
        for name, pattern in _TIMESTAMP_TOKEN_PATTERNS.items():
            diagnostics["timestamp_token_presence"][name] += len(pattern.findall(decoded))

        for anchor in anchors:
            item_id = anchor.group("id")
            if item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
            image_bucket, image_names = _anchor_token_diagnostics(
                decoded,
                anchor.start(),
                image_matches,
            )
            timestamp_bucket, timestamp_names = _anchor_token_diagnostics(
                decoded,
                anchor.start(),
                timestamp_matches,
            )
            diagnostics["image_anchor_distance_buckets"][image_bucket] += 1
            diagnostics["timestamp_anchor_distance_buckets"][timestamp_bucket] += 1
            if len(diagnostics["sample_anchor_windows"]) < max_items:
                diagnostics["sample_anchor_windows"].append(
                    {
                        "item_id": item_id,
                        "domain": domain,
                        "has_image_token_near_anchor": image_bucket in {"0-20", "21-50", "51-100"},
                        "has_timestamp_token_near_anchor": timestamp_bucket in {"0-20", "21-50", "51-100"},
                        "nearest_image_token_distance_bucket": image_bucket,
                        "nearest_timestamp_token_distance_bucket": timestamp_bucket,
                        "image_field_names_near_anchor": image_names,
                        "timestamp_field_names_near_anchor": timestamp_names,
                    }
                )
    return diagnostics


class _DetailMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[dict[str, str]] = []
        self.json_ld: list[str] = []
        self._in_json_ld = False
        self._script_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "meta":
            self.meta.append(values)
        elif tag.casefold() == "script" and values.get("type", "").casefold() == "application/ld+json":
            self._in_json_ld = True
            self._script_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._script_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._in_json_ld:
            self.json_ld.append("".join(self._script_parts))
            self._in_json_ld = False
            self._script_parts = []


def _walk_json_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_objects(child)


def analyze_item_detail_html(html: str) -> dict:
    """Inspect public item-page metadata without returning HTML or metadata values."""
    parser = _DetailMetadataParser()
    try:
        parser.feed(html or "")
    except Exception:
        return {
            "image_present": False,
            "image_sources": [],
            "timestamp_present": False,
            "timestamp": None,
            "timestamp_source": None,
            "hydration_image_tokens_present": False,
            "safe_error": "detail_html_parse_failed",
        }

    image_sources: set[str] = set()
    timestamp: datetime | None = None
    timestamp_source: str | None = None
    timestamp_meta_names = {
        "article:published_time",
        "date",
        "datepublished",
        "datecreated",
        "uploaddate",
        "listed_at",
        "uploaded_at",
    }
    for meta in parser.meta:
        name = (meta.get("property") or meta.get("name") or meta.get("itemprop") or "").casefold()
        content = meta.get("content")
        if name == "og:image" and content:
            image_sources.add("og:image")
        elif name == "twitter:image" and content:
            image_sources.add("twitter:image")
        if timestamp is None and name in timestamp_meta_names:
            parsed = _parse_hydration_timestamp(content)
            if parsed is not None:
                timestamp = parsed
                timestamp_source = f"meta:{name}"

    json_ld_timestamp_keys = {
        "datepublished",
        "datecreated",
        "uploaddate",
        "listed_at",
        "uploaded_at",
    }
    for raw_json_ld in parser.json_ld:
        try:
            payload = json.loads(raw_json_ld)
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in _walk_json_objects(payload):
            for key, value in obj.items():
                key_text = str(key).casefold()
                if key_text == "image" and value not in (None, "", [], {}):
                    image_sources.add("json_ld:image")
                if timestamp is None and key_text in json_ld_timestamp_keys:
                    parsed = _parse_hydration_timestamp(value)
                    if parsed is not None:
                        timestamp = parsed
                        timestamp_source = f"json_ld:{key_text}"

    hydration_image_tokens_present = any(
        pattern.search(html or "")
        for name, pattern in _IMAGE_TOKEN_PATTERNS.items()
        if name in {"photo", "photos", "image", "images", "high_resolution"}
    )
    return {
        "image_present": bool(image_sources),
        "image_sources": sorted(image_sources),
        "timestamp_present": timestamp is not None,
        "timestamp": timestamp.isoformat() if timestamp else None,
        "timestamp_source": timestamp_source,
        "hydration_image_tokens_present": hydration_image_tokens_present,
        "safe_error": None,
    }

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


def _extract_photo_url(item: dict) -> str:
    """Extract the first supported public image URL, or an empty string."""
    direct = item.get("photo_url")
    if isinstance(direct, str) and direct:
        return direct

    def from_photo(value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        high_resolution = value.get("high_resolution")
        candidates = [
            value.get("url"),
            value.get("full_size_url"),
            value.get("thumbnail_url"),
            high_resolution.get("url")
            if isinstance(high_resolution, dict)
            else None,
        ]
        return next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, str) and candidate
            ),
            "",
        )

    for key in ("photo", "photo_high_resolution", "image"):
        candidate = from_photo(item.get(key))
        if candidate:
            return candidate

    for key in ("photos", "thumbnails"):
        values = item.get(key)
        if isinstance(values, list):
            for value in values:
                candidate = from_photo(value)
                if candidate:
                    return candidate
    return ""


def _has_non_empty_path(item: dict, *path: str) -> bool:
    value: Any = item
    for key in path:
        if not isinstance(value, dict):
            return False
        value = value.get(key)
    return isinstance(value, str) and bool(value.strip())


def _first_list_item_has_url(item: dict, key: str) -> bool:
    values = item.get(key)
    return bool(
        isinstance(values, list)
        and values
        and isinstance(values[0], dict)
        and isinstance(values[0].get("url"), str)
        and values[0]["url"].strip()
    )


def _collect_item_field_diagnostics(items: list[dict]) -> dict:
    diagnostics = _empty_item_field_diagnostics()
    diagnostics["sampled_items"] = len(items)
    photo_checks = {
        "direct.photo_url": lambda item: _has_non_empty_path(item, "photo_url"),
        "photo.url": lambda item: _has_non_empty_path(item, "photo", "url"),
        "photo.full_size_url": lambda item: _has_non_empty_path(item, "photo", "full_size_url"),
        "photo.thumbnail_url": lambda item: _has_non_empty_path(item, "photo", "thumbnail_url"),
        "photo.high_resolution.url": lambda item: _has_non_empty_path(item, "photo", "high_resolution", "url"),
        "photo_high_resolution.url": lambda item: _has_non_empty_path(item, "photo_high_resolution", "url"),
        "photos[0].url": lambda item: _first_list_item_has_url(item, "photos"),
        "thumbnails[0].url": lambda item: _first_list_item_has_url(item, "thumbnails"),
        "image.url": lambda item: _has_non_empty_path(item, "image", "url"),
    }
    for item in items:
        for name, check in photo_checks.items():
            if check(item):
                diagnostics["photo_field_presence"][name] += 1
        for field in _TIMESTAMP_FIELDS:
            if item.get(field) not in (None, ""):
                diagnostics["timestamp_field_presence"][field] += 1
    return diagnostics


def _parse_hydration_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return _parse_hydration_timestamp(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _extract_hydration_timestamp(item: dict) -> tuple[datetime | None, str | None]:
    for field in _TIMESTAMP_FIELDS:
        parsed = _parse_hydration_timestamp(item.get(field))
        if parsed is not None:
            return parsed, field
    return None, None


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
        
        listed_at, timestamp_source = _extract_hydration_timestamp(i)
        normalized.append({
            "id": item_id_str,
            "title": title,
            "brand_title": brand,
            "url": f"https://www.{domain}" + (normalized_path or ""),
            "path": normalized_path or raw_path,
            "price": price_amount,
            "currency": currency,
            "photo_url": _extract_photo_url(i),
            "listed_at": listed_at.isoformat() if listed_at else None,
            "timestamp_source": timestamp_source,
            "user_id": str(user.get("id")) if isinstance(user, dict) and user.get("id") else None,
            "user_login": user.get("login") if isinstance(user, dict) else None,
            "raw_source": "hydration"
        })
    return normalized

def hydration_record_to_vinted_item(record: dict, domain: str) -> VintedItem:
    from app.scraper.parser import VintedItem
    listed_at = _parse_hydration_timestamp(record.get("listed_at"))
    return VintedItem(
        id=int(record["id"]),
        title=record.get("title", ""),
        price=float(record.get("price") or 0.0),
        currency=record.get("currency", "EUR"),
        brand=record.get("brand_title", ""),
        size="",
        condition="",
        photo_url=str(record.get("photo_url") or ""),
        item_url=record.get("url") or "",
        domain=domain,
        seller_id=0,
        brand_id=None,
        raw_source="hydration",
        listed_at=listed_at,
        timestamp_source=record.get("timestamp_source"),
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
