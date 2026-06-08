import asyncio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models import MonitorTelegramTopic
from app.telegram import topic_service

class SlowFakeBot:
    def __init__(self, message_thread_id=123, delay=0.1):
        self.message_thread_id = message_thread_id
        self.delay = delay
        self.create_calls = 0
        self.created_topics = []

    async def create_forum_topic(self, chat_id, name):
        self.create_calls += 1
        await asyncio.sleep(self.delay)
        self.created_topics.append((chat_id, name))
        class FakeTopic:
            def __init__(self, thread_id):
                self.message_thread_id = thread_id
        return FakeTopic(self.message_thread_id)

    async def get_chat(self, chat_id):
        class FakeChat:
            type = "supergroup"
            is_forum = True
        return FakeChat()

    async def get_me(self):
        class FakeMe:
            id = 12345
        return FakeMe()

    async def get_chat_member(self, chat_id, user_id):
        class FakeMember:
            status = "administrator"
            can_manage_topics = True
        return FakeMember()

    async def edit_forum_topic(self, chat_id, message_thread_id, name):
        pass

async def _create_user(db_session, username, **kwargs):
    from app.models import User
    user = User(
        username=username,
        password_hash="fake-hash",
        password_salt="fake-salt",
        **kwargs
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

async def _create_monitor(db_session, user, name="Test Monitor"):
    from app.models import Monitor
    monitor = Monitor(
        user_id=user.id,
        name=name,
        original_url="https://www.vinted.fr/catalog?search_text=nike",
        params_json="{}",
        domains_json='["vinted.fr"]'
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)
    return monitor

@pytest.mark.asyncio
async def test_ensure_monitor_topic_concurrency(engine):
    # Use a separate session to setup data
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as db_session:
        user = await _create_user(
            db_session,
            "concurrent_user",
            telegram_bot_token="bot-token",
            telegram_topics_enabled=True,
            telegram_topics_chat_id="123456789",
            telegram_topics_auto_create=True,
        )
        monitor = await _create_monitor(db_session, user)
        user_id = user.id
        monitor_id = monitor.id
    
    bot = SlowFakeBot(delay=0.2)
    
    # Define a helper that uses its own session
    async def call_ensure(m_id, u_id):
        async with session_factory() as db:
            # We need to re-fetch or merge objects since they belong to another session
            from app.models import User, Monitor
            u = await db.get(User, u_id)
            m = await db.get(Monitor, m_id)
            return await topic_service.ensure_monitor_topic(db, bot=bot, user=u, monitor=m)

    # Simulate 3 concurrent calls with separate sessions
    results = await asyncio.gather(
        call_ensure(monitor_id, user_id),
        call_ensure(monitor_id, user_id),
        call_ensure(monitor_id, user_id),
        return_exceptions=True
    )
    
    for r in results:
        if isinstance(r, Exception):
            print(f"Call failed with: {r}")

    async with session_factory() as db:
        mappings = (await db.execute(select(MonitorTelegramTopic).where(MonitorTelegramTopic.monitor_id == monitor_id))).scalars().all()
        assert len(mappings) == 1
        assert mappings[0].status == "active"
    
    # Check how many times create_forum_topic was called
    assert bot.create_calls == 1

@pytest.mark.asyncio
async def test_ensure_monitor_topic_recreation_concurrency(engine):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as db_session:
        user = await _create_user(
            db_session,
            "recreate_concurrent_user",
            telegram_bot_token="bot-token",
            telegram_topics_enabled=True,
            telegram_topics_chat_id="123456789",
            telegram_topics_auto_create=True,
            telegram_topics_recreate_deleted=True,
        )
        monitor = await _create_monitor(db_session, user)
        user_id = user.id
        monitor_id = monitor.id
        
        # Pre-create a FAILED mapping
        db_session.add(MonitorTelegramTopic(
            user_id=user.id,
            monitor_id=monitor.id,
            chat_id="123456789",
            topic_name="Old Name",
            status="failed",
            last_error_code="message_thread_not_found"
        ))
        await db_session.commit()
    
    bot = SlowFakeBot(delay=0.2)
    
    async def call_ensure(m_id, u_id):
        async with session_factory() as db:
            from app.models import User, Monitor
            u = await db.get(User, u_id)
            m = await db.get(Monitor, m_id)
            return await topic_service.ensure_monitor_topic(db, bot=bot, user=u, monitor=m)

    # Simulate 3 concurrent calls for an existing FAILED mapping
    results = await asyncio.gather(
        call_ensure(monitor_id, user_id),
        call_ensure(monitor_id, user_id),
        call_ensure(monitor_id, user_id),
        return_exceptions=True
    )
    
    async with session_factory() as db:
        mappings = (await db.execute(select(MonitorTelegramTopic).where(MonitorTelegramTopic.monitor_id == monitor_id))).scalars().all()
        assert len(mappings) == 1
        assert mappings[0].status == "active"
    
    assert bot.create_calls == 1
