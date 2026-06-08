from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Awaitable, Callable, Protocol

from app.config import Settings, get_settings


class NotificationFailureCode(StrEnum):
    RATE_LIMITED = "rate_limited"
    TELEGRAM_DISABLED = "telegram_disabled"
    TARGET_UNAVAILABLE = "target_unavailable"
    TRANSPORT_FAILED = "transport_failed"


@dataclass(frozen=True)
class NotificationQueueItem:
    found_item_id: int
    monitor_id: int
    vinted_item_id: int
    domain: str
    title: str
    has_photo_url: bool
    found_at: datetime


@dataclass(frozen=True)
class NotificationDeliveryTarget:
    route_kind: str
    transport_target: Any = field(repr=False)


@dataclass(frozen=True)
class NotificationAttemptResult:
    success: bool
    delivery_mode: str | None = None
    failure_code: NotificationFailureCode | None = None
    retryable: bool = True


@dataclass(frozen=True)
class NotificationResult:
    selected_count: int
    delivered_count: int
    failed_count: int
    retryable_count: int


@dataclass(frozen=True)
class NotificationJobStatus:
    job_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    result: NotificationResult | None = None
    safe_error: str | None = None


class NotificationQueueReader(Protocol):
    async def read_pending(
        self,
        *,
        monitor_id: int | None,
        limit: int,
    ) -> list[NotificationQueueItem]: ...

    async def mark_delivered(self, found_item_id: int) -> None: ...


class NotificationDeliveryTargetResolver(Protocol):
    async def resolve(self, item: NotificationQueueItem) -> NotificationDeliveryTarget | None: ...


class NotificationTransport(Protocol):
    async def deliver(
        self,
        item: NotificationQueueItem,
        target: NotificationDeliveryTarget,
    ) -> NotificationAttemptResult: ...


class NotificationRedactor:
    @staticmethod
    def sample(item: NotificationQueueItem) -> dict[str, object]:
        return {
            "found_item_id": item.found_item_id,
            "vinted_item_id": str(item.vinted_item_id),
            "domain": item.domain,
            "title_preview": item.title[:80],
            "has_photo_url": item.has_photo_url,
            "found_at": item.found_at.isoformat(),
        }


class TelegramNotificationTransport:
    """Adapter for the existing rate-limited Telegram sender; not wired by default."""

    def __init__(
        self,
        sender: Callable[
            [NotificationQueueItem, NotificationDeliveryTarget],
            Awaitable[str],
        ],
    ) -> None:
        self.sender = sender

    async def deliver(
        self,
        item: NotificationQueueItem,
        target: NotificationDeliveryTarget,
    ) -> NotificationAttemptResult:
        try:
            mode = await self.sender(item, target)
            return NotificationAttemptResult(success=True, delivery_mode=mode, retryable=False)
        except Exception as exc:
            failure_code = (
                NotificationFailureCode.RATE_LIMITED
                if type(exc).__name__ == "TelegramRetryAfter"
                else NotificationFailureCode.TRANSPORT_FAILED
            )
            return NotificationAttemptResult(
                success=False,
                failure_code=failure_code,
                retryable=True,
            )


class NotificationPipelineV2:
    """Future pipeline coordinator. Failed attempts stay pending and retryable."""

    def __init__(
        self,
        queue_reader: NotificationQueueReader,
        target_resolver: NotificationDeliveryTargetResolver,
        transport: NotificationTransport,
    ) -> None:
        self.queue_reader = queue_reader
        self.target_resolver = target_resolver
        self.transport = transport

    async def process(
        self,
        *,
        monitor_id: int | None,
        limit: int,
    ) -> NotificationResult:
        items = await self.queue_reader.read_pending(monitor_id=monitor_id, limit=limit)
        delivered_count = 0
        failed_count = 0
        retryable_count = 0

        for item in items:
            target = await self.target_resolver.resolve(item)
            if target is None:
                failed_count += 1
                retryable_count += 1
                continue
            attempt = await self.transport.deliver(item, target)
            if attempt.success:
                await self.queue_reader.mark_delivered(item.found_item_id)
                delivered_count += 1
            else:
                failed_count += 1
                retryable_count += int(attempt.retryable)

        return NotificationResult(
            selected_count=len(items),
            delivered_count=delivered_count,
            failed_count=failed_count,
            retryable_count=retryable_count,
        )


def select_notification_pipeline_v2(
    queue_reader: NotificationQueueReader,
    target_resolver: NotificationDeliveryTargetResolver,
    transport: NotificationTransport,
    *,
    settings: Settings | None = None,
) -> NotificationPipelineV2 | None:
    effective_settings = settings or get_settings()
    if not effective_settings.notification_pipeline_v2_enabled:
        return None
    return NotificationPipelineV2(queue_reader, target_resolver, transport)


def new_notification_job_status(job_id: str) -> NotificationJobStatus:
    return NotificationJobStatus(
        job_id=job_id,
        status="queued",
        started_at=datetime.now(timezone.utc),
    )
