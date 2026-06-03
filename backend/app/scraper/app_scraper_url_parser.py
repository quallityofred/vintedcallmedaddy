# app/scraper/url_parser.py
"""
Parse Vinted catalog URLs into API query parameters.

Vinted catalog URL example:
  https://www.vinted.fr/catalog?brand_ids[]=53&brand_ids[]=16&search_text=nike&catalog_ids[]=5&price_from=5&price_to=100&currency=EUR&order=newest_first&size_ids[]=207
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# Vinted API parameter names that carry array values
_ARRAY_PARAMS = {
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
        qs = parse_qs(parsed.query, keep_blank_values=False)
    except Exception as exc:
        logger.warning("Failed to parse URL %r: %s", url, exc)
        return params

    for key, values in qs.items():
        # Normalise both "brand_ids[]" and "brand_ids" forms
        normalised_key = key if key.endswith("[]") else key

        if normalised_key in _ARRAY_PARAMS or (key + "[]") in _ARRAY_PARAMS:
            array_key = normalised_key if normalised_key in _ARRAY_PARAMS else key + "[]"
            # Ensure array parameters are always lists, containing ints.
            # Convert values (which is a list from parse_qs) to a list of ints.
            params[array_key] = [int(v) for v in values if v.isdigit()]
            # Re-verify it is a list
            if not isinstance(params[array_key], list):
                params[array_key] = list(params[array_key])

        elif key in _SCALAR_PARAMS:
            params[key] = values[0] if values else ""

        elif key in {"page", "time", "search_id"}:
            # Ignore junk parameters
            pass

        else:
            # Preserve any unknown scalar param as-is
            params[key] = values[0] if len(values) == 1 else values

    # Default sort to newest
    if "order" not in params:
        params["order"] = "newest_first"

    return params


def extract_domains_from_url(url: str) -> list[str]:
    """
    Extract the Vinted domain from a URL.

    Returns a single-element list with the host domain (e.g. ``["vinted.fr"]``),
    or an empty list if it cannot be determined.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        # Strip leading "www."
        domain = host.removeprefix("www.")
        if domain:
            return [domain]
    except Exception:
        pass
    return []
