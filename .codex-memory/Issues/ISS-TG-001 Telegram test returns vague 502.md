---
type: issue
project: vintedbot
status: fixed
severity: high
component: Telegram Bot
tags:
  - vintedbot
  - issue/fixed
  - severity/high
  - component/telegram
  - component/api
  - component/frontend
created: 2026-06-04
fixed: 2026-06-04
---

# ISS-TG-001 Telegram test returns vague 502

## Summary

`POST /api/v1/telegram/test` collapsed all Telegram failures into a generic `502` response. The settings UI could not distinguish missing credentials, invalid tokens, chat access problems, bot polling conflicts, rate limits, or upstream timeouts.

## Impact

- Users saw vague failures during Telegram setup.
- Actionable setup errors were hidden behind a generic upstream error.
- The route still avoided secret leakage, but it did not return enough safe detail for the frontend.

## Resolution

Fixed by [[Fixes/FIX-TG-001 Telegram test error classification]].
