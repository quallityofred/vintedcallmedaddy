---
type: component
project: vintedbot
tags:
  - vintedbot
  - component/pricing
---

# Pricing

## Purpose

- Provides deterministic display-only currency helpers for user-facing notifications.

## Key Files

- `backend/app/pricing/currency.py`
- `backend/app/telegram/notifications.py`

## Runtime Flow

- Scraper parsing and database storage keep the original item price and currency unchanged.
- Telegram notification formatting calls `format_price_with_usd()` to append an approximate USD value for supported non-USD currencies.
- Conversion uses static fallback rates only; it does not call external APIs, use the database, or depend on network access.
- USD prices are displayed without duplicate approximate conversion text.
- Unknown/missing currency falls back to the original price display, and missing/malformed/non-positive amounts return `Not listed`.

## Notes

- Supported currencies as of 2026-06-05: USD, PLN, EUR, GBP, SEK, DKK, CZK, HUF, RON, BGN.
- Rates are approximate presentation hints, not financial data.
