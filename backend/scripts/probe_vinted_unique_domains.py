"""Probe candidate Vinted domains and group likely marketplace aliases.

This script is for manual developer use only. It does not run during app
startup and does not print secrets.
"""

from __future__ import annotations

import argparse
import asyncio

from app.scraper.client import VintedClient
from app.scraper.domains import normalize_vinted_host
from app.scraper.rate_limiter import TokenBucketLimiter


CANDIDATE_DOMAINS = (
    "www.vinted.fr",
    "www.vinted.de",
    "www.vinted.pl",
    "www.vinted.es",
    "www.vinted.it",
    "www.vinted.nl",
    "www.vinted.be",
    "www.vinted.pt",
    "www.vinted.co.uk",
    "www.vinted.com",
    "www.vinted.lu",
    "www.vinted.at",
    "www.vinted.cz",
    "www.vinted.sk",
    "www.vinted.hu",
    "www.vinted.ro",
    "www.vinted.lt",
    "www.vinted.dk",
    "www.vinted.se",
    "www.vinted.fi",
    "www.vinted.hr",
    "www.vinted.gr",
    "www.vinted.ie",
)


def _jaccard(left: set[int], right: set[int]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


async def probe(query: str, limit: int, overlap: float) -> None:
    client = VintedClient(rate_limiter=TokenBucketLimiter(rate=20, per=60.0))
    params = {"search_text": query, "order": "newest_first", "per_page": limit}
    results: dict[str, set[int]] = {}

    try:
        for candidate in CANDIDATE_DOMAINS:
            domain = normalize_vinted_host(candidate)
            try:
                items = await client.search(domain, params)
                results[candidate] = {item.id for item in items[:limit]}
            except Exception as exc:
                print(f"{candidate}: probe failed ({type(exc).__name__})")
                results[candidate] = set()
    finally:
        await client.close()

    groups: list[list[str]] = []
    assigned: set[str] = set()
    for domain, ids in results.items():
        if domain in assigned:
            continue
        group = [domain]
        assigned.add(domain)
        for other, other_ids in results.items():
            if other in assigned:
                continue
            if _jaccard(ids, other_ids) >= overlap:
                group.append(other)
                assigned.add(other)
        groups.append(group)

    print("\nLikely unique marketplace groups:")
    for group in groups:
        representative = group[0]
        aliases = group[1:]
        count = len(results.get(representative, set()))
        print(f"- representative={representative} ids={count} aliases={aliases}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Vinted domains for overlapping item IDs.")
    parser.add_argument("--query", default="nike", help="Safe catalog search query.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum item IDs per domain.")
    parser.add_argument("--overlap", type=float, default=0.85, help="Jaccard overlap threshold for grouping.")
    args = parser.parse_args()
    asyncio.run(probe(args.query, args.limit, args.overlap))


if __name__ == "__main__":
    main()
