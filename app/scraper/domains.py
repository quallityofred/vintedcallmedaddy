# app/scraper/domains.py
VINTED_DOMAINS: dict[str, dict[str, str]] = {
    "vinted.fr": {"code": "fr", "currency": "EUR", "flag": "🇫🇷"},
    "vinted.de": {"code": "de", "currency": "EUR", "flag": "🇩🇪"},
    "vinted.co.uk": {"code": "uk", "currency": "GBP", "flag": "🇬🇧"},
    "vinted.it": {"code": "it", "currency": "EUR", "flag": "🇮🇹"},
    "vinted.es": {"code": "es", "currency": "EUR", "flag": "🇪🇸"},
    "vinted.pl": {"code": "pl", "currency": "PLN", "flag": "🇵🇱"},
    "vinted.nl": {"code": "nl", "currency": "EUR", "flag": "🇳🇱"},
    "vinted.be": {"code": "be", "currency": "EUR", "flag": "🇧🇪"},
    "vinted.cz": {"code": "cz", "currency": "CZK", "flag": "🇨🇿"},
    "vinted.lt": {"code": "lt", "currency": "EUR", "flag": "🇱🇹"},
    "vinted.pt": {"code": "pt", "currency": "EUR", "flag": "🇵🇹"},
    "vinted.at": {"code": "at", "currency": "EUR", "flag": "🇦🇹"},
    "vinted.lu": {"code": "lu", "currency": "EUR", "flag": "🇱🇺"},
    "vinted.sk": {"code": "sk", "currency": "EUR", "flag": "🇸🇰"},
    "vinted.dk": {"code": "dk", "currency": "DKK", "flag": "🇩🇰"},
    "vinted.fi": {"code": "fi", "currency": "EUR", "flag": "🇫🇮"},
    "vinted.se": {"code": "se", "currency": "SEK", "flag": "🇸🇪"},
    "vinted.ro": {"code": "ro", "currency": "RON", "flag": "🇷🇴"},
    "vinted.hu": {"code": "hu", "currency": "HUF", "flag": "🇭🇺"},
    "vinted.hr": {"code": "hr", "currency": "EUR", "flag": "🇭🇷"},
    "vinted.gr": {"code": "gr", "currency": "EUR", "flag": "🇬🇷"},
    "vinted.com": {"code": "com", "currency": "EUR", "flag": "🌍"},
}


def get_all_domains() -> list[str]:
    return list(VINTED_DOMAINS.keys())


def get_flag(domain: str) -> str:
    return VINTED_DOMAINS.get(domain, {}).get("flag", "🌍")
