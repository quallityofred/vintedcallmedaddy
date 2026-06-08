# Notification Pipeline V2 Design

Status: default-off skeleton. Production remains on the existing notification processor.

## Intended Durable Flow

1. An authenticated, CSRF-protected HTTP endpoint creates a durable database job.
2. A worker claims pending `FoundItem` rows and records bounded delivery attempts.
3. Target resolution preserves the existing main-chat and forum-topic behavior.
4. The Telegram transport retains the existing global and per-chat rate limiter.
5. A row is acknowledged only after successful Telegram delivery.
6. Rate limits and transport failures remain retryable; genuine notifications are not dropped.
7. Job status and errors expose safe codes and counts only.

The current skeleton deliberately adds no tables or migrations. A future release requires an
approved schema for durable jobs, attempts, leases, and restart recovery before switching the
`NOTIFICATION_PIPELINE_V2_ENABLED` flag on.
