"""Vinted marketplace domain registry.

The user-facing list intentionally contains only representative marketplaces.
Aliases are kept for URL normalization and developer probes, but aliases are
not selectable monitor targets.
"""

from __future__ import annotations

from urllib.parse import urlparse


UNIQUE_VINTED_MARKETPLACES: tuple[dict[str, object], ...] = (
    {
        "code": "fr",
        "label": "France / FR marketplace",
        "domain": "vinted.fr",
        "host": "www.vinted.fr",
        "currency": "EUR",
        "flag": "FR",
        "aliases": ("vinted.be", "vinted.lu"),
    },
    {
        "code": "de",
        "label": "Germany / DE marketplace",
        "domain": "vinted.de",
        "host": "www.vinted.de",
        "currency": "EUR",
        "flag": "DE",
        "aliases": ("vinted.at",),
    },
    {
        "code": "pl",
        "label": "Poland / CEE marketplace",
        "domain": "vinted.pl",
        "host": "www.vinted.pl",
        "currency": "PLN",
        "flag": "PL",
        "aliases": (
            "vinted.cz",
            "vinted.sk",
            "vinted.hu",
            "vinted.ro",
            "vinted.lt",
            "vinted.hr",
        ),
    },
    {
        "code": "es",
        "label": "Spain / ES marketplace",
        "domain": "vinted.es",
        "host": "www.vinted.es",
        "currency": "EUR",
        "flag": "ES",
        "aliases": (),
    },
    {
        "code": "it",
        "label": "Italy / IT marketplace",
        "domain": "vinted.it",
        "host": "www.vinted.it",
        "currency": "EUR",
        "flag": "IT",
        "aliases": (),
    },
    {
        "code": "nl",
        "label": "Netherlands / Benelux marketplace",
        "domain": "vinted.nl",
        "host": "www.vinted.nl",
        "currency": "EUR",
        "flag": "NL",
        "aliases": (),
    },
    {
        "code": "pt",
        "label": "Portugal / PT marketplace",
        "domain": "vinted.pt",
        "host": "www.vinted.pt",
        "currency": "EUR",
        "flag": "PT",
        "aliases": (),
    },
    {
        "code": "uk",
        "label": "United Kingdom marketplace",
        "domain": "vinted.co.uk",
        "host": "www.vinted.co.uk",
        "currency": "GBP",
        "flag": "UK",
        "aliases": ("vinted.ie",),
    },
)

VINTED_DOMAINS: dict[str, dict[str, object]] = {
    str(marketplace["domain"]): dict(marketplace)
    for marketplace in UNIQUE_VINTED_MARKETPLACES
}

_ALIASES_TO_REPRESENTATIVE: dict[str, str] = {
    alias: str(marketplace["domain"])
    for marketplace in UNIQUE_VINTED_MARKETPLACES
    for alias in marketplace["aliases"]  # type: ignore[union-attr]
}


def normalize_vinted_host(value: str) -> str:
    """Normalize a URL or hostname to a bare lowercase host without leading www."""
    candidate = (value or "").strip().lower()
    if not candidate:
        return ""

    if "://" in candidate:
        parsed = urlparse(candidate)
        candidate = parsed.hostname or ""
    else:
        candidate = candidate.split("/", 1)[0]
        candidate = candidate.split("?", 1)[0]
        candidate = candidate.split("#", 1)[0]
        candidate = candidate.rsplit("@", 1)[-1]
        candidate = candidate.split(":", 1)[0]

    candidate = candidate.strip().strip(".")
    if candidate.startswith("www."):
        candidate = candidate[4:]
    return candidate


def resolve_vinted_host_to_representative(value: str) -> str | None:
    """Resolve a Vinted URL/host to a selectable representative domain."""
    host = normalize_vinted_host(value)
    if host in VINTED_DOMAINS:
        return host
    return _ALIASES_TO_REPRESENTATIVE.get(host)


def validate_selected_domains(domains: list[str] | tuple[str, ...]) -> list[str]:
    """Validate user-selected target domains against representatives only."""
    if not domains:
        raise ValueError("At least one target domain is required")

    validated: list[str] = []
    invalid: list[str] = []
    for domain in domains:
        normalized = normalize_vinted_host(domain)
        if normalized in VINTED_DOMAINS:
            if normalized not in validated:
                validated.append(normalized)
        else:
            invalid.append(domain)

    if invalid:
        raise ValueError(f"Unsupported target domain: {invalid[0]}")
    if not validated:
        raise ValueError("At least one target domain is required")
    return validated


def get_unique_vinted_marketplaces() -> list[dict[str, object]]:
    """Return safe JSON-serializable user-facing marketplace metadata."""
    marketplaces: list[dict[str, object]] = []
    for marketplace in UNIQUE_VINTED_MARKETPLACES:
        aliases = tuple(str(alias) for alias in marketplace["aliases"])  # type: ignore[union-attr]
        marketplaces.append(
            {
                "code": marketplace["code"],
                "label": marketplace["label"],
                "domain": marketplace["domain"],
                "host": marketplace["host"],
                "flag": marketplace["flag"],
                "aliases": tuple(f"www.{alias}" for alias in aliases),
            }
        )
    return marketplaces


def get_all_domains() -> list[str]:
    return list(VINTED_DOMAINS.keys())


def get_flag(domain: str) -> str:
    representative = resolve_vinted_host_to_representative(domain) or normalize_vinted_host(domain)
    return str(VINTED_DOMAINS.get(representative, {}).get("flag", ""))
