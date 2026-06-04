---
type: fix
project: vintedbot
status: completed
severity: medium
component: Frontend Next.js
tags:
  - vintedbot
  - fix/completed
  - severity/medium
  - component/frontend
  - component/web
  - component/tests
created: 2026-06-04
---

# FIX-FE-010 Checkbox and settings polish pass

## Summary

Polished shared checkbox styling, domain marketplace selection cards, compact monitor bulk-selection controls, and Telegram settings feedback.

## Changes

- Updated the shared Base UI checkbox to match the dark green/glass visual language while preserving semantic checkbox behavior.
- Domain selection now renders unique marketplaces as selectable cards with clearer labels and selected/focus states.
- Monitor select-all and row selection now use the shared checkbox component.
- Settings shows masked Telegram credential status cards, credential safety copy, disabled-action help, loading labels, and safe inline success/error notices.
- Frontend lint/build/E2E and backend tests passed.
