from __future__ import annotations

import inspect
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.scheduler import tasks
from app.telegram.pipeline_v2 import (
    NotificationAttemptResult,
    NotificationDeliveryTarget,
    NotificationFailureCode,
    NotificationPipelineV2,
    NotificationQueueItem,
    NotificationRedactor,
    TelegramNotificationTransport,
    select_notification_pipeline_v2,
)


def item(found_item_id: int = 1) -> NotificationQueueItem:
    return NotificationQueueItem(
        found_item_id=found_item_id,
        monitor_id=22,
        vinted_item_id=9000000000 + found_item_id,
        domain="vinted.pl",
        title="Fresh item",
        has_photo_url=True,
        found_at=datetime.now(timezone.utc),
    )


def test_notification_pipeline_v2_defaults_off_and_live_path_is_unchanged():
    settings = Settings(_env_file=None)

    selected = select_notification_pipeline_v2(
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        settings=settings,
    )

    assert settings.notification_pipeline_v2_enabled is False
    assert selected is None
    assert "pipeline_v2" not in inspect.getsource(tasks.process_pending_notifications)


def test_notification_pipeline_v2_can_be_instantiated_when_enabled():
    settings = Settings(_env_file=None, notification_pipeline_v2_enabled=True)

    selected = select_notification_pipeline_v2(
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        settings=settings,
    )

    assert isinstance(selected, NotificationPipelineV2)


@pytest.mark.asyncio
async def test_pipeline_marks_only_successful_delivery_and_keeps_failures_retryable():
    queue_reader = AsyncMock()
    queue_reader.read_pending.return_value = [item(1), item(2)]
    resolver = AsyncMock()
    resolver.resolve.return_value = NotificationDeliveryTarget(
        route_kind="main_chat",
        transport_target=object(),
    )
    transport = AsyncMock()
    transport.deliver.side_effect = [
        NotificationAttemptResult(success=True, delivery_mode="photo", retryable=False),
        NotificationAttemptResult(
            success=False,
            failure_code=NotificationFailureCode.RATE_LIMITED,
            retryable=True,
        ),
    ]

    result = await NotificationPipelineV2(queue_reader, resolver, transport).process(
        monitor_id=22,
        limit=10,
    )

    assert result.selected_count == 2
    assert result.delivered_count == 1
    assert result.failed_count == 1
    assert result.retryable_count == 1
    queue_reader.mark_delivered.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_telegram_transport_adapter_preserves_existing_sender_contract():
    sender = AsyncMock(return_value="fallback_text")
    target = NotificationDeliveryTarget(route_kind="topic", transport_target=object())

    result = await TelegramNotificationTransport(sender).deliver(item(), target)

    assert result.success is True
    assert result.delivery_mode == "fallback_text"
    sender.assert_awaited_once()


def test_notification_redactor_exposes_no_transport_target_or_photo_url():
    sample = NotificationRedactor.sample(item())

    assert sample["has_photo_url"] is True
    assert "photo_url" not in sample
    assert "chat_id" not in sample
    assert "transport_target" not in sample
