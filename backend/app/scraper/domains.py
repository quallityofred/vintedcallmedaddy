# app/scraper/domains.py
VINTED_DOMAINS: dict[str, dict[str, str]] = {
    "vinted.fr": {"code": "fr", "currency": "EUR", "flag": "🇫🇷"},
    "vinted.de": {"code": "de", "currency": "EUR", "flag": "🇩🇪"},
    "vinted.co.uk": {"code": "uk", "currency": "GBP", "flag": "🇬🇧"},
    "vinted.it": {"code": "it", "currency": "EUR", "flag": "🇮🇹"},
    "vinted.es": {"code": "es", "currency": "EUR", "flag": "🇪🇸"},
    "vinted.pl": {"code": "pl", "currency": "PLN", "flag": "🇵🇱"},
    "vinted.com": {"code": "com", "currency": "EUR", "flag": "🌍"},
}


def get_all_domains() -> list[str]:
    return list(VINTED_DOMAINS.keys())


def get_flag(domain: str) -> str:
    return VINTED_DOMAINS.get(domain, {}).get("flag", "🌍")
