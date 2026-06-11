# app/scraper/url_parser.py
"""
Parse Vinted catalog URLs into API query parameters.

Vinted catalog URL example:
  https://www.vinted.fr/catalog?brand_ids[]=53&brand_ids[]=16&search_text=nike&catalog_ids[]=5&price_from=5&price_to=100&currency=EUR&order=newest_first&size_ids[]=207
"""
from __future__ import annotations

import logging
import re
import json
from urllib.parse import parse_qs, urlparse, urlsplit, urlunparse, urlunsplit, urlencode

from app.scraper.domains import normalize_vinted_host, resolve_vinted_host_to_representative

logger = logging.getLogger(__name__)

# Vinted API parameter names that carry array values
_ARRAY_PARAMS = {
    "catalog[]",
    "brand_ids[]",
    "catalog_ids[]",
    "size_ids[]",
    "color_ids[]",
    "material_ids[]",
    "status_ids[]",
    "country_ids[]",
    "gender_ids[]",
}

# Scalar params that map directly to API params
_SCALAR_PARAMS = {
    "search_text",
    "price_from",
    "price_to",
    "currency",
    "order",
}

# Parameters to explicitly ignore
_IGNORED_PARAMS = {
    "page",
    "time",
    "search_id",
    "search_by_image_uuid",
    "search_by_image_id",
    "session_id",
    "source",
    "ref",
}


def _parse_int_values(values: list[str]) -> list[int]:
    parsed: list[int] = []
    for value in values:
        for part in str(value).split(","):
            text = part.strip()
            if text.isdigit():
                parsed.append(int(text))
    return parsed


def _first_path_id(path: str, *prefixes: str) -> int | None:
    normalized_path = path.strip("/")
    for prefix in prefixes:
        match = re.match(rf"^{re.escape(prefix.strip('/'))}/(\d+)(?:-|/|$)", normalized_path)
        if match:
            return int(match.group(1))
    return None


def _append_unique_int(params: dict, key: str, value: int | None) -> None:
    if value is None:
        return
    values = params.setdefault(key, [])
    if value not in values:
        values.append(value)


def parse_vinted_url(url: str) -> dict:
    """
    Parse a Vinted catalog URL and return a dict of API query parameters.

    The resulting dict is suitable for passing directly to
    ``VintedClient.search_all_domains(params, domains)``.

    Example::

        parse_vinted_url(
            "https://www.vinted.fr/catalog?brand_ids[]=53&search_text=nike"
        )
        # → {"brand_ids[]": [53], "search_text": "nike", "order": "newest_first"}

    Parameters
    ----------
    url:
        Full Vinted catalog URL, e.g. from the browser address bar.

    Returns
    -------
    dict
        API parameters ready for the scraper client.
    """
    params: dict = {}

    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
    except Exception as exc:
        logger.warning("Failed to parse URL %r: %s", url, exc)
        return params

    for key, values in qs.items():
        val = values[0] if values else ""

        if key in _ARRAY_PARAMS or (key + "[]") in _ARRAY_PARAMS:
            array_key = key if key.endswith("[]") else key + "[]"
            # Ensure array parameters are always lists, containing ints.
            params[array_key] = _parse_int_values(values)

        elif key in _SCALAR_PARAMS:
            if key == "order":
                params[key] = "newest_first"
            else:
                params[key] = val

        elif key in _IGNORED_PARAMS or key.startswith("utm_"):
            # Ignore unstable pagination/session/tracking parameters.
            pass
        
        elif not val:
            # Ignore any empty parameters
            pass

        else:
            # Preserve any unknown non-empty scalar param as-is
            params[key] = val

    _append_unique_int(params, "catalog[]", _first_path_id(parsed.path, "catalog"))
    _append_unique_int(params, "brand_ids[]", _first_path_id(parsed.path, "brand", "brands"))

    # Always enforce sort to newest
    params["order"] = "newest_first"

    return params


def get_effective_monitor_request_params(params_json: str, original_url: str) -> dict:
    """Canonical monitor parameter resolution: merge stored and URL-derived filters."""
    params = json.loads(params_json)
    url_params = parse_vinted_url(original_url)

    # Merge: URL-derived filters fill in missing ones
    for key, value in url_params.items():
        if key not in params or not params[key]:
            params[key] = value

    return normalize_catalog_search_params(params)


def normalize_catalog_search_params(params: dict) -> dict:
    """Return public catalog parameters in the canonical Vinted request shape."""
    search_params = {
        key: value
        for key, value in dict(params).items()
        if not str(key).startswith("_") and value not in (None, "")
    }
    
    # Preserve original order if provided, otherwise default to newest_first
    if "order" not in search_params:
        search_params["order"] = "newest_first"
    
    search_params.pop("page", None)
    search_params.pop("search_id", None)

    catalog_values: list[object] = []
    for alias in ("catalog[]", "catalog", "catalog_id", "catalog_ids", "catalog_ids[]"):
        if alias not in search_params:
            continue
        value = search_params.pop(alias)
        catalog_values.extend(value if isinstance(value, (list, tuple, set)) else [value])
    if catalog_values:
        # Canonical catalog key
        search_params["catalog_ids[]"] = list(dict.fromkeys(catalog_values))

    # All other array params
    for plain_key in (
        "brand_ids",
        "size_ids",
        "color_ids",
        "material_ids",
        "status_ids",
        "country_ids",
        "gender_ids",
    ):
        bracketed_key = f"{plain_key}[]"
        if bracketed_key in search_params:
             # Already have bracketed form, just clean up plain form if it exists
             search_params.pop(plain_key, None)
             # Ensure it's a list
             if not isinstance(search_params[bracketed_key], list):
                  search_params[bracketed_key] = [search_params[bracketed_key]]
        elif plain_key in search_params:
            val = search_params.pop(plain_key)
            search_params[bracketed_key] = val if isinstance(val, list) else [val]

    return search_params


def build_vinted_catalog_url(original_url: str, domain: str, params: dict) -> str:
    """Build a domain catalog URL from effective monitor parameters.

    Stored runtime parameters are authoritative. This prevents a stale or broad
    original query string from being used after monitor parameters were repaired
    or migrated.
    """
    parsed = urlsplit(original_url)
    path = parsed.path if parsed.path.startswith("/catalog") else "/catalog"
    query = urlencode(normalize_catalog_search_params(params), doseq=True, safe="[]")
    return urlunsplit((parsed.scheme or "https", f"www.{domain}", path, query, ""))


def normalize_vinted_monitor_url(url: str) -> str:
    """
    Clean and canonicalize a Vinted catalog URL.
    Removes transient parameters and enforces order=newest_first.
    """
    try:
        parsed = urlparse(url)
        if not parsed.netloc or not parsed.path:
            return url
            
        params = parse_vinted_url(url)
        
        # Build query string deterministically
        # order=newest_first should be first for readability
        query_items = [("order", "newest_first")]
        
        # Then other scalar params
        for key in sorted(_SCALAR_PARAMS):
            if key != "order" and key in params:
                query_items.append((key, params[key]))
                
        # Then array params
        for key in sorted(_ARRAY_PARAMS):
            if key in params:
                for val in sorted(params[key]):
                    query_items.append((key, str(val)))
                    
        # Then any other params
        known_keys = _SCALAR_PARAMS | _ARRAY_PARAMS
        for key in sorted(params.keys()):
            if key not in known_keys:
                query_items.append((key, str(params[key])))
        
        # Reconstruct URL
        # We use urlencode with doseq=False because we manually expanded arrays
        new_query = urlencode(query_items, safe="[]")
        
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
    except Exception as exc:
        logger.warning("Failed to normalize URL %r: %s", url, exc)
        return url


def extract_domains_from_url(url: str) -> list[str]:
    """
    Extract the Vinted domain from a URL.

    Returns a single-element list with the host domain (e.g. ``["vinted.fr"]``),
    or an empty list if it cannot be determined.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or normalize_vinted_host(url)
        representative = resolve_vinted_host_to_representative(host)
        if representative:
            return [representative]
        normalized = normalize_vinted_host(host)
        if normalized:
            return [normalized]
    except Exception:
        pass
    return []
