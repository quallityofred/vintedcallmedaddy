# app/scraper/url_parser.py
import re
from urllib.parse import parse_qs, urlencode, urlparse

PARAM_MAP: dict[str, str] = {
    "brand_ids[]": "brand_ids",
    "catalog[]": "catalog_ids",
    "catalog_ids[]": "catalog_ids",
    "color_ids[]": "color_ids",
    "material_ids[]": "material_ids",
    "status_ids[]": "status_ids",
    "size_ids[]": "size_ids",
    "order": "order",
    "search_text": "search_text",
    "price_from": "price_from",
    "price_to": "price_to",
}

_BRAND_PATH_RE = re.compile(r"^/brand/(\d+)")


def parse_vinted_url(url: str) -> dict[str, str | dict[str, str | int]]:
    parsed_url = urlparse(url.strip())
    domain = parsed_url.netloc.lower().removeprefix("www.")
    query_params = parse_qs(parsed_url.query, keep_blank_values=False)
    api_params: dict[str, str | int] = {}

    brand_match = _BRAND_PATH_RE.match(parsed_url.path)
    if brand_match:
        api_params["brand_ids"] = brand_match.group(1)

    for web_key, values in query_params.items():
        if web_key == "page":
            continue

        api_key = PARAM_MAP.get(web_key)
        if api_key is None:
            continue

        cleaned_values = [value.strip() for value in values if value.strip()]
        if not cleaned_values:
            continue

        if api_key in api_params:
            existing_value = str(api_params[api_key])
            api_params[api_key] = ",".join([existing_value, *cleaned_values])
        elif len(cleaned_values) == 1:
            api_params[api_key] = cleaned_values[0]
        else:
            api_params[api_key] = ",".join(cleaned_values)

    api_params["order"] = "newest_first"
    api_params["per_page"] = 20

    return {"domain": domain, "params": api_params}


def build_api_url(domain: str, params: dict[str, str | int | float | bool]) -> str:
    query_string = urlencode(params)
    return f"https://www.{domain}/api/v2/catalog/items?{query_string}"
