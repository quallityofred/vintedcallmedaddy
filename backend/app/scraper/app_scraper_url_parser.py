# app/scraper/url_parser.py
"""
Parse Vinted catalog URLs into API query parameters.

Vinted catalog URL example:
  https://www.vinted.fr/catalog?brand_ids[]=53&brand_ids[]=16&search_text=nike&catalog_ids[]=5&price_from=5&price_to=100&currency=EUR&order=newest_first&size_ids[]=207
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse, urlunparse, urlencode

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
        # Normalise both "brand_ids[]" and "brand_ids" forms
        normalised_key = key if key.endswith("[]") else key
        val = values[0] if values else ""

        if normalised_key in _ARRAY_PARAMS or (key + "[]") in _ARRAY_PARAMS:
            array_key = normalised_key if normalised_key in _ARRAY_PARAMS else key + "[]"
            # Ensure array parameters are always lists, containing ints.
            params[array_key] = [int(v) for v in values if v.isdigit()]

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

    # Always enforce sort to newest
    params["order"] = "newest_first"

    return params


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
