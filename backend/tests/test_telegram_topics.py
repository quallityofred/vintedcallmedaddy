from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.models import FoundItem, Monitor, MonitorTelegramTopic, User, UserSession
from app.scheduler.tasks import process_pending_notifications
from app.scraper.parser import VintedItem
from app.telegram import notifications
from app.telegram import topic_service
from app.web.csrf import csrf_token_for_session
from app.web.dependencies import get_db


async def _create_user(
    db_session,
    username: str,
    *,
    is_admin: bool = False,
    telegram_bot_token: str = "",
    telegram_chat_id: str = "",
    telegram_topics_enabled: bool = False,
    telegram_topics_chat_id: str | None = None,
) -> User:
    user = User(
        username=username,
        is_admin=is_admin,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        telegram_topics_enabled=telegram_topics_enabled,
        telegram_topics_chat_id=telegram_topics_chat_id,
    )
    user.set_password("password")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _create_monitor(db_session, user: User, *, name: str = "Nike Deals") -> Monitor:
    monitor = Monitor(
        user_id=user.id,
        name=name,
        original_url="https://www.vinted.fr/catalog?search_text=nike",
        params_json="{}",
        domains_json='["vinted.fr"]',
        interval_sec=120,
        is_active=True,
        last_check_at=datetime.now(timezone.utc),
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    return monitor


async def _create_session(db_session, user: User, token: str) -> str:
    db_session.add(UserSession(user_id=user.id, token=token))
    await db_session.commit()
    return token


def _override_db(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: db_session


async def _authenticated_client(user: User, db_session, token: str):
    session_token = await _create_session(db_session, user, token)
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    client.cookies.set("session_token", session_token)
    return client, csrf_token_for_session(session_token)


class FakeTopicBot:
    def __init__(
        self,
        *,
        chat_type: str = "supergroup",
        is_forum: bool = True,
        member_status: str = "administrator",
        can_manage_topics: bool = True,
        create_exc: Exception | None = None,
    ) -> None:
        self.chat_type = chat_type
        self.is_forum = is_forum
        self.member_status = member_status
        self.can_manage_topics = can_manage_topics
        self.create_exc = create_exc
        self.created_topics: list[tuple[str, str]] = []
        self.sent_messages: list[dict[str, object]] = []

    async def get_chat(self, chat_id: str):
        return SimpleNamespace(type=self.chat_type, is_forum=self.is_forum)

    async def get_me(self):
        return SimpleNamespace(id=42)

    async def get_chat_member(self, chat_id: str, user_id: int):
        return SimpleNamespace(status=self.member_status, can_manage_topics=self.can_manage_topics)

    async def create_forum_topic(self, chat_id: str, name: str):
        if self.create_exc is not None:
            raise self.create_exc
        self.created_topics.append((chat_id, name))
        return SimpleNamespace(message_thread_id=987654321)

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)


@pytest.mark.asyncio
async def test_telegram_topic_settings_defaults_and_patch_are_safe(db_session):
    user = await _create_user(db_session, "topic_settings_user")
    _override_db(db_session)

    client, csrf_token = await _authenticated_client(user, db_session, "topic-settings-session")
    async with client:
        default_response = await client.get("/api/v1/settings/telegram/topics")
        assert default_response.status_code == 200
        assert default_response.json() == {
            "enabled": False,
            "chat_configured": False,
            "chat_id_masked": "",
            "auto_create": True,
            "recreate_deleted": False,
            "fallback_to_main_chat": False,
            "status": "not_verified",
            "message": None,
        }

        missing_csrf = await client.patch(
            "/api/v1/settings/telegram/topics",
            json={"enabled": True, "chat_id": "123456789"},
        )
        assert missing_csrf.status_code == 403

        update_response = await client.patch(
            "/api/v1/settings/telegram/topics",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "enabled": True,
                "chat_id": "123456789",
                "auto_create": False,
                "recreate_deleted": True,
                "fallback_to_main_chat": False,
            },
        )
        assert update_response.status_code == 200
        assert update_response.json()["enabled"] is True
        assert update_response.json()["chat_configured"] is True
        assert update_response.json()["auto_create"] is False
        assert update_response.json()["recreate_deleted"] is True
        assert "123456789" not in update_response.text

        blank_chat = await client.patch(
            "/api/v1/settings/telegram/topics",
            headers={"X-CSRF-Token": csrf_token},
            json={"chat_id": ""},
        )
        assert blank_chat.status_code == 200

    await db_session.refresh(user)
    assert user.telegram_topics_chat_id == "123456789"
    assert user.telegram_topics_enabled is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_verify_group_success_and_permission_failures(db_session, monkeypatch):
    user = await _create_user(
        db_session,
        "topic_verify_user",
        telegram_bot_token="secret-token-value",
        telegram_topics_chat_id="123456789",
    )
    _override_db(db_session)

    good_bot = FakeTopicBot()
    monkeypatch.setattr("app.telegram.bot.get_or_create_bot", lambda token: (good_bot, MagicMock()))

    client, csrf_token = await _authenticated_client(user, db_session, "topic-verify-session")
    async with client:
        ok_response = await client.post(
            "/api/v1/settings/telegram/topics/verify-group",
            headers={"X-CSRF-Token": csrf_token},
            json={},
        )
        assert ok_response.status_code == 200
        ok_payload = ok_response.json()
        assert ok_payload["ok"] is True
        assert ok_payload["code"] == "ok"
        assert ok_payload["chat_type"] == "supergroup"
        assert ok_payload["is_forum"] is True
        assert "secret-token-value" not in ok_response.text
        assert "123456789" not in ok_response.text

        normal_group_bot = FakeTopicBot(chat_type="group", is_forum=False)
        monkeypatch.setattr("app.telegram.bot.get_or_create_bot", lambda token: (normal_group_bot, MagicMock()))
        forum_response = await client.post(
            "/api/v1/settings/telegram/topics/verify-group",
            headers={"X-CSRF-Token": csrf_token},
            json={},
        )
        assert forum_response.status_code == 400
        assert forum_response.json()["code"] == "not_forum_group"

        no_admin_bot = FakeTopicBot(member_status="member", can_manage_topics=False)
        monkeypatch.setattr("app.telegram.bot.get_or_create_bot", lambda token: (no_admin_bot, MagicMock()))
        admin_response = await client.post(
            "/api/v1/settings/telegram/topics/verify-group",
            headers={"X-CSRF-Token": csrf_token},
            json={},
        )
        assert admin_response.status_code == 400
        assert admin_response.json()["code"] == "bot_not_admin"

        no_topics_bot = FakeTopicBot(member_status="administrator", can_manage_topics=False)
        monkeypatch.setattr("app.telegram.bot.get_or_create_bot", lambda token: (no_topics_bot, MagicMock()))
        manage_topics_response = await client.post(
            "/api/v1/settings/telegram/topics/verify-group",
            headers={"X-CSRF-Token": csrf_token},
            json={},
        )
        assert manage_topics_response.status_code == 400
        assert manage_topics_response.json()["code"] == "missing_manage_topics"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ensure_topic_creates_idempotent_mapping(db_session):
    user = await _create_user(
        db_session,
        "topic_ensure_user",
        telegram_bot_token="secret-token-value",
        telegram_topics_enabled=True,
        telegram_topics_chat_id="123456789",
    )
    monitor = await _create_monitor(db_session, user)
    bot = FakeTopicBot()

    first = await topic_service.ensure_monitor_topic(db_session, bot=bot, user=user, monitor=monitor)
    assert first.ok is True
    assert first.topic is not None
    assert first.topic.status == "active"
    assert first.topic.message_thread_id == 987654321

    second = await topic_service.ensure_monitor_topic(db_session, bot=bot, user=user, monitor=monitor)
    assert second.ok is True
    assert second.code == "active"
    assert len(bot.created_topics) == 1

    rows = (await db_session.execute(select(MonitorTelegramTopic))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_ensure_topic_treats_creating_mapping_as_in_progress(db_session):
    user = await _create_user(
        db_session,
        "topic_creating_user",
        telegram_bot_token="secret-token-value",
        telegram_topics_enabled=True,
        telegram_topics_chat_id="123456789",
    )
    monitor = await _create_monitor(db_session, user)
    db_session.add(
        MonitorTelegramTopic(
            user_id=user.id,
            monitor_id=monitor.id,
            chat_id="123456789",
            topic_name="Nike Deals - vinted.fr #1",
            status="creating",
        )
    )
    await db_session.commit()
    bot = FakeTopicBot()

    result = await topic_service.ensure_monitor_topic(db_session, bot=bot, user=user, monitor=monitor)

    assert result.ok is False
    assert result.code == "topic_creation_in_progress"
    assert bot.created_topics == []


@pytest.mark.asyncio
async def test_ensure_topic_stores_permission_error(db_session):
    user = await _create_user(
        db_session,
        "topic_permission_user",
        telegram_bot_token="secret-token-value",
        telegram_topics_enabled=True,
        telegram_topics_chat_id="123456789",
    )
    monitor = await _create_monitor(db_session, user)
    bot = FakeTopicBot(create_exc=RuntimeError("Bad Request: not enough rights to manage topics"))

    result = await topic_service.ensure_monitor_topic(db_session, bot=bot, user=user, monitor=monitor)

    assert result.ok is False
    assert result.code == "missing_manage_topics"
    mapping = (
        await db_session.execute(
            select(MonitorTelegramTopic).where(MonitorTelegramTopic.monitor_id == monitor.id)
        )
    ).scalar_one()
    assert mapping.status == "permission_error"
    assert mapping.last_error_code == "missing_manage_topics"
    assert "secret-token-value" not in (mapping.last_error or "")
    assert "123456789" not in (mapping.last_error or "")


@pytest.mark.asyncio
async def test_ensure_topic_handles_missing_thread_status(db_session):
    user = await _create_user(
        db_session,
        "topic_missing_user",
        telegram_bot_token="secret-token-value",
        telegram_topics_enabled=True,
        telegram_topics_chat_id="123456789",
    )
    monitor = await _create_monitor(db_session, user)
    db_session.add(
        MonitorTelegramTopic(
            user_id=user.id,
            monitor_id=monitor.id,
            chat_id="123456789",
            message_thread_id=555555,
            topic_name="Nike Deals - vinted.fr #1",
            status="missing",
            last_error="Previous topic was deleted.",
            last_error_code="message_thread_not_found",
        )
    )
    await db_session.commit()
    bot = FakeTopicBot()

    result = await topic_service.ensure_monitor_topic(db_session, bot=bot, user=user, monitor=monitor)

    assert result.ok is False
    assert result.code == "message_thread_not_found"
    assert result.status == "missing"
    assert bot.created_topics == []


@pytest.mark.asyncio
async def test_monitor_topic_endpoints_are_authenticated_and_user_scoped(db_session, monkeypatch):
    owner = await _create_user(
        db_session,
        "topic_owner",
        telegram_bot_token="owner-secret-token",
        telegram_topics_enabled=True,
        telegram_topics_chat_id="123456789",
    )
    other = await _create_user(
        db_session,
        "topic_other",
        telegram_bot_token="other-secret-token",
        telegram_topics_enabled=True,
        telegram_topics_chat_id="987654321",
    )
    monitor = await _create_monitor(db_session, owner)
    _override_db(db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as unauthenticated:
        unauth_response = await unauthenticated.get(f"/api/v1/monitors/{monitor.id}/telegram-topic")
        assert unauth_response.status_code == 401

    client, csrf_token = await _authenticated_client(owner, db_session, "topic-owner-session")
    bot = FakeTopicBot()
    monkeypatch.setattr("app.telegram.bot.get_or_create_bot", lambda token: (bot, MagicMock()))
    async with client:
        ensure_response = await client.post(
            f"/api/v1/monitors/{monitor.id}/telegram-topic/ensure",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert ensure_response.status_code == 200
        assert ensure_response.json()["topic"]["status"] == "active"
        assert "owner-secret-token" not in ensure_response.text
        assert "123456789" not in ensure_response.text

        get_response = await client.get(f"/api/v1/monitors/{monitor.id}/telegram-topic")
        assert get_response.status_code == 200
        assert get_response.json()["topic"]["status"] == "active"

    other_client, other_csrf = await _authenticated_client(other, db_session, "topic-other-session")
    async with other_client:
        forbidden_response = await other_client.post(
            f"/api/v1/monitors/{monitor.id}/telegram-topic/ensure",
            headers={"X-CSRF-Token": other_csrf},
        )
        assert forbidden_response.status_code == 404

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_topic_test_endpoint_sends_to_thread(db_session, monkeypatch):
    user = await _create_user(
        db_session,
        "topic_test_user",
        telegram_bot_token="secret-token-value",
        telegram_topics_enabled=True,
        telegram_topics_chat_id="123456789",
    )
    monitor = await _create_monitor(db_session, user)
    _override_db(db_session)

    bot = FakeTopicBot()
    monkeypatch.setattr("app.telegram.bot.get_or_create_bot", lambda token: (bot, MagicMock()))

    client, csrf_token = await _authenticated_client(user, db_session, "topic-test-session")
    async with client:
        response = await client.post(
            f"/api/v1/monitors/{monitor.id}/telegram-topic/test",
            headers={"X-CSRF-Token": csrf_token},
        )

    assert response.status_code == 200
    assert response.json()["code"] == "test_sent"
    assert bot.sent_messages[0]["chat_id"] == "123456789"
    assert bot.sent_messages[0]["message_thread_id"] == 987654321
    assert "secret-token-value" not in response.text
    assert "123456789" not in response.text
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_topic_notification_failure_keeps_found_item_pending(db_session):
    user = await _create_user(
        db_session,
        "topic_notify_failure_user",
        telegram_bot_token="topic-secret-token",
        telegram_chat_id="111111",
        telegram_topics_enabled=True,
        telegram_topics_chat_id="123456789",
    )
    user.is_telegram_enabled = True
    monitor = await _create_monitor(db_session, user)
    db_session.add(
        MonitorTelegramTopic(
            user_id=user.id,
            monitor_id=monitor.id,
            chat_id="123456789",
            message_thread_id=987654321,
            topic_name="Nike Deals - vinted.fr #1",
            status="active",
        )
    )
    item = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=1234,
        domain="vinted.fr",
        title="Thread Missing",
        price=10.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/1234",
        seller_id=1,
        notified=False,
    )
    db_session.add(item)
    await db_session.commit()

    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(side_effect=RuntimeError("Bad Request: message thread not found"))

    with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory), \
         patch("app.telegram.bot.get_or_create_bot", return_value=(fake_bot, MagicMock())):
        await process_pending_notifications()

    fake_bot.send_message.assert_awaited_once()
    _, kwargs = fake_bot.send_message.await_args
    assert kwargs["chat_id"] == 123456789
    assert kwargs["message_thread_id"] == 987654321
    await db_session.refresh(item)
    assert item.notified is False


@pytest.mark.asyncio
async def test_send_item_notification_passes_optional_thread_id():
    item = VintedItem(
        id=1,
        title="Topic Item",
        price=10.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/1",
        domain="vinted.fr",
        seller_id=1,
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch("app.telegram.notifications.asyncio.sleep", AsyncMock()):
        await notifications.send_item_notification(bot, 12345, item, message_thread_id=67890)

    _, kwargs = bot.send_message.await_args
    assert kwargs["chat_id"] == 12345
    assert kwargs["message_thread_id"] == 67890


@pytest.mark.asyncio
async def test_send_item_notification_passes_optional_thread_id_to_photo():
    item = VintedItem(
        id=1,
        title="Topic Photo Item",
        price=10.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="https://example.test/photo.jpg",
        item_url="https://www.vinted.fr/items/1",
        domain="vinted.fr",
        seller_id=1,
    )
    bot = MagicMock()
    bot.send_photo = AsyncMock()

    with patch("app.telegram.notifications.asyncio.sleep", AsyncMock()):
        await notifications.send_item_notification(bot, 12345, item, message_thread_id=67890)

    _, kwargs = bot.send_photo.await_args
    assert kwargs["chat_id"] == 12345
    assert kwargs["message_thread_id"] == 67890


@pytest.mark.asyncio
async def test_send_item_notification_omits_thread_id_by_default():
    item = VintedItem(
        id=1,
        title="Main Chat Item",
        price=10.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/1",
        domain="vinted.fr",
        seller_id=1,
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch("app.telegram.notifications.asyncio.sleep", AsyncMock()):
        await notifications.send_item_notification(bot, 12345, item)

    _, kwargs = bot.send_message.await_args
    assert kwargs["chat_id"] == 12345
    assert "message_thread_id" not in kwargs
