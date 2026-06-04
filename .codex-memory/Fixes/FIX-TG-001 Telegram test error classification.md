---
type: fix
project: vintedbot
status: completed
severity: high
component: Telegram Bot
tags:
  - vintedbot
  - fix/completed
  - severity/high
  - component/telegram
  - component/api
  - component/frontend
created: 2026-06-04
---

# FIX-TG-001 Telegram test error classification

## Summary

Added safe Telegram test error classification for `/api/v1/telegram/test`.

## Changes

- Missing credentials now return `telegram_credentials_missing`.
- Invalid token, invalid chat ID, chat-not-found, blocked bot, polling conflict, rate limit, timeout/unavailable, and unknown failures now return safe `code` and `detail` fields.
- The frontend settings page displays the safe backend detail and shows clearer disabled/loading/success states.
- Backend tests cover the classified failure cases and confirm saved token/chat values are not returned in responses.
