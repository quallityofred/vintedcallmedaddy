from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Monitor, MonitorTelegramTopic, User
from app.runtime_settings import mask_secret

TOPIC_STATUS_PENDING = "pending"
TOPIC_STATUS_CREATING = "creating"
TOPIC_STATUS_ACTIVE = "active"
TOPIC_STATUS_MISSING = "missing"
TOPIC_STATUS_CLOSED = "closed"
TOPIC_STATUS_PERMISSION_ERROR = "permission_error"
TOPIC_STATUS_CHAT_UNREACHABLE = "chat_unreachable"
TOPIC_STATUS_FAILED = "failed"
TOPIC_STATUS_DISABLED = "disabled"

FINAL_OR_BLOCKED_STATUSES = {
    TOPIC_STATUS_MISSING,
    TOPIC_STATUS_CLOSED,
    TOPIC_STATUS_PERMISSION_ERROR,
    TOPIC_STATUS_CHAT_UNREACHABLE,
}

CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
MAX_TOPIC_NAME_LENGTH = 128


@dataclass(frozen=True)
class TelegramTopicErrorInfo:
    code: str
    message: str
    status: str


@dataclass
class TelegramTopicResult:
    ok: bool
    code: str
    message: str
    status: str | None = None
    chat_id_masked: str | None = None
    chat_type: str | None = None
    is_forum: bool | None = None
    bot_is_admin: bool | None = None
    can_manage_topics: bool | None = None
    topic: MonitorTelegramTopic | None = None

    def to_response(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
        }
        if self.status is not None:
            payload["status"] = self.status
        if self.chat_id_masked is not None:
            payload["chat_id_masked"] = self.chat_id_masked
        if self.chat_type is not None:
            payload["chat_type"] = self.chat_type
        if self.is_forum is not None:
            payload["is_forum"] = self.is_forum
        if self.bot_is_admin is not None:
            payload["bot_is_admin"] = self.bot_is_admin
        if self.can_manage_topics is not None:
            payload["can_manage_topics"] = self.can_manage_topics
        if self.topic is not None:
            payload["topic"] = topic_payload(self.topic)
        return payload


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def mask_identifier(value: object | None, *, visible: int = 4) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return mask_secret(text, visible=visible)


def topic_payload(topic: MonitorTelegramTopic | None) -> dict[str, Any] | None:
    if topic is None:
        return None
    return {
        "status": topic.status,
        "topic_name": topic.topic_name,
        "message_thread_id_masked": mask_identifier(topic.message_thread_id),
        "last_error": topic.last_error,
        "last_error_code": topic.last_error_code,
        "last_verified_at": topic.last_verified_at.isoformat() if topic.last_verified_at else None,
    }


def _safe_error_message(exc: BaseException, *, limit: int = 240) -> str:
    text = str(exc).replace("\n", " ").replace("\r", " ").strip()
    if len(text) > limit:
        return f"{text[: limit - 3]}..."
    return text


def classify_telegram_topic_error(exc: BaseException) -> TelegramTopicErrorInfo:
    class_name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    text = f"{class_name}: {message}"

    if "message thread not found" in text or "thread not found" in text or "topic not found" in text:
        return TelegramTopicErrorInfo(
            code="message_thread_not_found",
            message="Telegram topic was not found. Recreate the topic mapping before sending.",
            status=TOPIC_STATUS_MISSING,
        )
    if "topic closed" in text or "message thread closed" in text or "thread closed" in text:
        return TelegramTopicErrorInfo(
            code="topic_closed",
            message="Telegram topic is closed. Reopen it or create a new topic.",
            status=TOPIC_STATUS_CLOSED,
        )
    if "retry after" in text or "too many requests" in text or "flood" in text:
        return TelegramTopicErrorInfo(
            code="telegram_rate_limited",
            message="Telegram rate limit reached. Try again later.",
            status=TOPIC_STATUS_FAILED,
        )
    if "not enough rights" in text or "can_manage_topics" in text or "manage topics" in text:
        return TelegramTopicErrorInfo(
            code="missing_manage_topics",
            message="The bot does not have permission to manage topics in this group.",
            status=TOPIC_STATUS_PERMISSION_ERROR,
        )
    if "bot was kicked" in text or "kicked" in text or "bot is not a member" in text:
        return TelegramTopicErrorInfo(
            code="bot_not_member",
            message="The bot is not a member of this Telegram group.",
            status=TOPIC_STATUS_CHAT_UNREACHABLE,
        )
    if "chat not found" in text or "user not found" in text:
        return TelegramTopicErrorInfo(
            code="chat_not_found",
            message="Telegram chat was not found. Check the group chat ID and bot access.",
            status=TOPIC_STATUS_CHAT_UNREACHABLE,
        )
    if "forbidden" in text or "cannot message" in text or "bot was blocked" in text:
        return TelegramTopicErrorInfo(
            code="chat_unreachable",
            message="The bot cannot access or message this Telegram chat.",
            status=TOPIC_STATUS_CHAT_UNREACHABLE,
        )
    return TelegramTopicErrorInfo(
        code="telegram_api_error",
        message="Telegram topic operation failed. Check group access and bot permissions.",
        status=TOPIC_STATUS_FAILED,
    )


def normalize_topic_name(monitor: Monitor) -> str:
    raw_name = CONTROL_CHARS.sub(" ", (monitor.name or "")).strip()
    if not raw_name:
        raw_name = f"Monitor {monitor.id}"

    domain = ""
    try:
        import json

        domains = json.loads(monitor.domains_json or "[]")
        if isinstance(domains, list) and domains:
            domain = str(domains[0]).replace("www.", "").strip()
    except Exception:
        domain = ""

    parts = [raw_name]
    if domain:
        parts.append(domain)
    parts.append(f"#{monitor.id}")
    topic_name = " · ".join(parts)
    topic_name = CONTROL_CHARS.sub(" ", topic_name).strip()
    if len(topic_name) <= MAX_TOPIC_NAME_LENGTH:
        return topic_name

    suffix = f" #{monitor.id}"
    available = MAX_TOPIC_NAME_LENGTH - len(suffix)
    if available <= 0:
        return f"Monitor {monitor.id}"[:MAX_TOPIC_NAME_LENGTH]
    return f"{topic_name[:available].rstrip()}{suffix}"


def _status_value(status: object) -> str:
    value = getattr(status, "value", status)
    return str(value or "").lower()


async def verify_forum_group(bot: Bot, chat_id: str) -> TelegramTopicResult:
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        return TelegramTopicResult(
            ok=False,
            code="chat_id_missing",
            message="Telegram topic group chat ID is not configured.",
            status=TOPIC_STATUS_CHAT_UNREACHABLE,
        )

    try:
        chat = await bot.get_chat(chat_id)
        chat_type = _status_value(getattr(chat, "type", None))
        is_forum = bool(getattr(chat, "is_forum", False))
        if chat_type != "supergroup" or not is_forum:
            return TelegramTopicResult(
                ok=False,
                code="not_forum_group",
                message="Telegram topics require a forum-enabled supergroup.",
                status=TOPIC_STATUS_PERMISSION_ERROR,
                chat_id_masked=mask_identifier(chat_id),
                chat_type=chat_type,
                is_forum=is_forum,
                bot_is_admin=False,
                can_manage_topics=False,
            )

        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, getattr(me, "id"))
        member_status = _status_value(getattr(member, "status", None))
        bot_is_admin = member_status in {"administrator", "creator"}
        can_manage_topics = bool(getattr(member, "can_manage_topics", False)) or member_status == "creator"

        if not bot_is_admin:
            return TelegramTopicResult(
                ok=False,
                code="bot_not_admin",
                message="The bot must be an admin in the Telegram forum group.",
                status=TOPIC_STATUS_PERMISSION_ERROR,
                chat_id_masked=mask_identifier(chat_id),
                chat_type=chat_type,
                is_forum=is_forum,
                bot_is_admin=False,
                can_manage_topics=False,
            )
        if not can_manage_topics:
            return TelegramTopicResult(
                ok=False,
                code="missing_manage_topics",
                message="The bot needs the Manage Topics permission in this group.",
                status=TOPIC_STATUS_PERMISSION_ERROR,
                chat_id_masked=mask_identifier(chat_id),
                chat_type=chat_type,
                is_forum=is_forum,
                bot_is_admin=True,
                can_manage_topics=False,
            )

        return TelegramTopicResult(
            ok=True,
            code="ok",
            message="Bot can create topics in this group.",
            status=TOPIC_STATUS_ACTIVE,
            chat_id_masked=mask_identifier(chat_id),
            chat_type=chat_type,
            is_forum=True,
            bot_is_admin=True,
            can_manage_topics=True,
        )
    except Exception as exc:
        info = classify_telegram_topic_error(exc)
        return TelegramTopicResult(
            ok=False,
            code=info.code,
            message=info.message,
            status=info.status,
            chat_id_masked=mask_identifier(chat_id),
        )


async def get_topic_mapping(
    db: AsyncSession,
    *,
    monitor_id: int,
    chat_id: str,
) -> MonitorTelegramTopic | None:
    result = await db.execute(
        select(MonitorTelegramTopic).where(
            MonitorTelegramTopic.monitor_id == monitor_id,
            MonitorTelegramTopic.chat_id == chat_id,
        )
    )
    return result.scalar_one_or_none()


async def _create_pending_mapping(
    db: AsyncSession,
    *,
    user: User,
    monitor: Monitor,
    chat_id: str,
    topic_name: str,
) -> MonitorTelegramTopic:
    mapping = MonitorTelegramTopic(
        user_id=user.id,
        monitor_id=monitor.id,
        chat_id=chat_id,
        topic_name=topic_name,
        status=TOPIC_STATUS_CREATING,
    )
    db.add(mapping)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await get_topic_mapping(db, monitor_id=monitor.id, chat_id=chat_id)
        if existing is not None:
            return existing
        raise
    await db.refresh(mapping)
    return mapping


async def create_monitor_topic(
    db: AsyncSession,
    *,
    bot: Bot,
    user: User,
    monitor: Monitor,
    chat_id: str,
) -> TelegramTopicResult:
    chat_id = str(chat_id or "").strip()
    topic_name = normalize_topic_name(monitor)
    mapping = await get_topic_mapping(db, monitor_id=monitor.id, chat_id=chat_id)

    if mapping and mapping.status == TOPIC_STATUS_ACTIVE and mapping.message_thread_id:
        return TelegramTopicResult(
            ok=True,
            code="active",
            message="Telegram topic is already active.",
            status=mapping.status,
            chat_id_masked=mask_identifier(chat_id),
            topic=mapping,
        )
    if mapping and mapping.status == TOPIC_STATUS_CREATING:
        return TelegramTopicResult(
            ok=False,
            code="topic_creation_in_progress",
            message="Telegram topic creation is already in progress.",
            status=mapping.status,
            chat_id_masked=mask_identifier(chat_id),
            topic=mapping,
        )
    if mapping is None:
        mapping = await _create_pending_mapping(
            db,
            user=user,
            monitor=monitor,
            chat_id=chat_id,
            topic_name=topic_name,
        )

    mapping.status = TOPIC_STATUS_CREATING
    mapping.topic_name = topic_name
    mapping.last_error = None
    mapping.last_error_code = None
    await db.commit()
    await db.refresh(mapping)

    try:
        topic = await bot.create_forum_topic(chat_id=chat_id, name=topic_name)
        mapping.message_thread_id = int(getattr(topic, "message_thread_id"))
        mapping.status = TOPIC_STATUS_ACTIVE
        mapping.last_error = None
        mapping.last_error_code = None
        mapping.last_verified_at = utc_now()
        await db.commit()
        await db.refresh(mapping)
        return TelegramTopicResult(
            ok=True,
            code="created",
            message="Telegram topic is ready.",
            status=mapping.status,
            chat_id_masked=mask_identifier(chat_id),
            topic=mapping,
        )
    except Exception as exc:
        info = classify_telegram_topic_error(exc)
        mapping.status = info.status
        mapping.last_error = _safe_error_message(exc)
        mapping.last_error_code = info.code
        mapping.last_verified_at = utc_now()
        await db.commit()
        await db.refresh(mapping)
        return TelegramTopicResult(
            ok=False,
            code=info.code,
            message=info.message,
            status=mapping.status,
            chat_id_masked=mask_identifier(chat_id),
            topic=mapping,
        )


async def ensure_monitor_topic(
    db: AsyncSession,
    *,
    bot: Bot,
    user: User,
    monitor: Monitor,
) -> TelegramTopicResult:
    if not user.telegram_topics_enabled:
        return TelegramTopicResult(
            ok=False,
            code="topics_disabled",
            message="Telegram topic routing is disabled.",
            status=TOPIC_STATUS_DISABLED,
        )

    chat_id = str(user.telegram_topics_chat_id or "").strip()
    if not chat_id:
        return TelegramTopicResult(
            ok=False,
            code="topic_chat_missing",
            message="Telegram topic group chat ID is not configured.",
            status=TOPIC_STATUS_DISABLED,
        )

    mapping = await get_topic_mapping(db, monitor_id=monitor.id, chat_id=chat_id)
    if mapping and mapping.status == TOPIC_STATUS_ACTIVE and mapping.message_thread_id:
        return TelegramTopicResult(
            ok=True,
            code="active",
            message="Telegram topic is active.",
            status=mapping.status,
            chat_id_masked=mask_identifier(chat_id),
            topic=mapping,
        )

    if mapping and mapping.status in FINAL_OR_BLOCKED_STATUSES and not user.telegram_topics_recreate_deleted:
        return TelegramTopicResult(
            ok=False,
            code=mapping.last_error_code or mapping.status,
            message=mapping.last_error or "Telegram topic needs manual attention.",
            status=mapping.status,
            chat_id_masked=mask_identifier(chat_id),
            topic=mapping,
        )

    if not user.telegram_topics_auto_create:
        return TelegramTopicResult(
            ok=False,
            code="auto_create_disabled",
            message="Automatic Telegram topic creation is disabled.",
            status=mapping.status if mapping else TOPIC_STATUS_PENDING,
            chat_id_masked=mask_identifier(chat_id),
            topic=mapping,
        )

    return await create_monitor_topic(db, bot=bot, user=user, monitor=monitor, chat_id=chat_id)


async def send_topic_test(
    db: AsyncSession,
    *,
    bot: Bot,
    user: User,
    monitor: Monitor,
) -> TelegramTopicResult:
    result = await ensure_monitor_topic(db, bot=bot, user=user, monitor=monitor)
    if not result.ok or result.topic is None or not result.topic.message_thread_id:
        return result

    try:
        await bot.send_message(
            chat_id=result.topic.chat_id,
            message_thread_id=result.topic.message_thread_id,
            text="Telegram topic test from Vinted Monitor.",
            parse_mode="HTML",
        )
        result.code = "test_sent"
        result.message = "Telegram topic test message sent."
        return result
    except Exception as exc:
        info = classify_telegram_topic_error(exc)
        result.topic.status = info.status
        result.topic.last_error = _safe_error_message(exc)
        result.topic.last_error_code = info.code
        result.topic.last_verified_at = utc_now()
        await db.commit()
        await db.refresh(result.topic)
        return TelegramTopicResult(
            ok=False,
            code=info.code,
            message=info.message,
            status=result.topic.status,
            chat_id_masked=mask_identifier(result.topic.chat_id),
            topic=result.topic,
        )
