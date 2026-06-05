import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Monitor, User
from app.scheduler import tasks


@pytest.fixture(autouse=True)
def reset_scheduler_backpressure(monkeypatch):
    monkeypatch.setattr(tasks.settings, "monitor_check_global_concurrency", 2)
    monkeypatch.setattr(tasks.settings, "monitor_check_per_user_concurrency", 1)
    monkeypatch.setattr(tasks.settings, "monitor_check_acquire_timeout_seconds", 0.05)
    tasks.reset_backpressure_state_for_tests()
    yield
    tasks.reset_backpressure_state_for_tests()


@pytest.mark.asyncio
async def test_global_concurrency_limit_allows_only_configured_number(monkeypatch):
    monkeypatch.setattr(tasks.settings, "monitor_check_global_concurrency", 2)
    monkeypatch.setattr(tasks.settings, "monitor_check_per_user_concurrency", 5)
    monkeypatch.setattr(tasks.settings, "monitor_check_acquire_timeout_seconds", 0.01)
    tasks.reset_backpressure_state_for_tests()

    first = await tasks._acquire_check_capacity(1, 1)
    second = await tasks._acquire_check_capacity(2, 2)
    third = await tasks._acquire_check_capacity(3, 3)

    assert first is not None
    assert second is not None
    assert third is None
    state = tasks.get_backpressure_state()
    assert state["monitor_check_global_active"] == 2
    assert state["monitor_check_capacity_timeouts"] == 1

    first.release()
    second.release()
    assert tasks.get_backpressure_state()["monitor_check_global_active"] == 0


@pytest.mark.asyncio
async def test_per_user_concurrency_limit_allows_only_configured_number(monkeypatch):
    monkeypatch.setattr(tasks.settings, "monitor_check_global_concurrency", 5)
    monkeypatch.setattr(tasks.settings, "monitor_check_per_user_concurrency", 1)
    monkeypatch.setattr(tasks.settings, "monitor_check_acquire_timeout_seconds", 0.01)
    tasks.reset_backpressure_state_for_tests()

    first = await tasks._acquire_check_capacity(1, 10)
    second = await tasks._acquire_check_capacity(2, 10)

    assert first is not None
    assert second is None
    assert tasks.get_backpressure_state()["monitor_check_user_active"] == 1

    first.release()
    assert tasks.get_backpressure_state()["monitor_check_user_active"] == 0


@pytest.mark.asyncio
async def test_same_monitor_overlap_is_prevented():
    assert await tasks._try_start_monitor_check(99) is True
    assert await tasks._try_start_monitor_check(99) is False
    assert tasks.is_monitor_check_running(99) is True
    assert tasks.get_backpressure_state()["monitor_check_already_running_skips"] == 1

    await tasks._finish_monitor_check(99)
    assert tasks.is_monitor_check_running(99) is False


@pytest.mark.asyncio
async def test_capacity_release_after_successful_check(monkeypatch):
    release_scraper = asyncio.Event()
    scraper_started = asyncio.Event()

    context = SimpleNamespace(
        monitor_id=1,
        user_id=20,
        cf_worker_url="",
        cf_worker_mode="auto",
        cf_worker_block_threshold=2,
        cf_worker_recovery_minutes=10,
        params={},
        domains=["vinted.fr"],
    )

    async def fake_load_context(monitor_id):
        return context

    async def fake_mark_running(monitor_id):
        return None

    class FakeClient:
        async def search_all_domains(self, params, domains, mode="auto"):
            scraper_started.set()
            await release_scraper.wait()
            return []

    class NoopSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    monkeypatch.setattr(tasks, "_load_monitor_check_context", fake_load_context)
    monkeypatch.setattr(tasks, "_mark_monitor_check_running", fake_mark_running)
    monkeypatch.setattr(tasks, "_new_session", lambda: NoopSession())

    check_task = asyncio.create_task(tasks.check_monitor(1, scraper_client=FakeClient()))
    await asyncio.wait_for(scraper_started.wait(), timeout=1)
    assert tasks.is_monitor_check_running(1) is True
    assert tasks.get_backpressure_state()["monitor_check_global_active"] == 1

    release_scraper.set()
    await check_task

    assert tasks.is_monitor_check_running(1) is False
    assert tasks.get_backpressure_state()["monitor_check_global_active"] == 0


@pytest.mark.asyncio
async def test_capacity_release_after_failing_check(monkeypatch):
    context = SimpleNamespace(
        monitor_id=1,
        user_id=30,
        cf_worker_url="",
        cf_worker_mode="auto",
        cf_worker_block_threshold=2,
        cf_worker_recovery_minutes=10,
        params={},
        domains=["vinted.fr"],
    )

    async def fake_load_context(monitor_id):
        return context

    async def fake_mark_running(monitor_id):
        return None

    class FailingClient:
        async def search_all_domains(self, params, domains, mode="auto"):
            raise RuntimeError("scraper failed")

    class NoopSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    monkeypatch.setattr(tasks, "_load_monitor_check_context", fake_load_context)
    monkeypatch.setattr(tasks, "_mark_monitor_check_running", fake_mark_running)
    monkeypatch.setattr(tasks, "_new_session", lambda: NoopSession())

    with pytest.raises(RuntimeError):
        await tasks.check_monitor(1, scraper_client=FailingClient())

    assert tasks.is_monitor_check_running(1) is False
    assert tasks.get_backpressure_state()["monitor_check_global_active"] == 0


@pytest.mark.asyncio
async def test_db_session_is_not_held_during_mocked_scraper_network_call(monkeypatch):
    session_open = False
    scraper_saw_session_open = None

    class TrackingSession:
        async def __aenter__(self):
            nonlocal session_open
            session_open = True
            return self

        async def __aexit__(self, exc_type, exc, tb):
            nonlocal session_open
            session_open = False
            return False

    async def fake_load_context(monitor_id):
        async with TrackingSession():
            return SimpleNamespace(
                monitor_id=monitor_id,
                user_id=40,
                cf_worker_url="",
                cf_worker_mode="auto",
                cf_worker_block_threshold=2,
                cf_worker_recovery_minutes=10,
                params={},
                domains=["vinted.fr"],
            )

    async def fake_mark_running(monitor_id):
        return None

    class FakeClient:
        async def search_all_domains(self, params, domains, mode="auto"):
            nonlocal scraper_saw_session_open
            scraper_saw_session_open = session_open
            return []

    class NoopSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    monkeypatch.setattr(tasks, "_load_monitor_check_context", fake_load_context)
    monkeypatch.setattr(tasks, "_mark_monitor_check_running", fake_mark_running)
    monkeypatch.setattr(tasks, "_new_session", lambda: NoopSession())

    await tasks.check_monitor(1, scraper_client=FakeClient())

    assert scraper_saw_session_open is False


@pytest.mark.asyncio
async def test_check_context_uses_url_brand_filter_when_stored_params_are_stale(db_session, monkeypatch):
    user = User(username="stale_params_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name="number (n)ine",
        original_url="https://www.vinted.fr/brands/123-number-nine",
        params_json=json.dumps({"order": "newest_first", "_original_interval": 120}),
        domains_json='["vinted.fr"]',
        interval_sec=120,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", session_factory)

    context = await tasks._load_monitor_check_context(monitor.id)

    assert context is not None
    assert context.params["brand_ids[]"] == [123]
    assert context.monitor_filters.brand_ids == {"123"}
    assert "brand_ids" in context.monitor_filters.filter_keys


@pytest.mark.asyncio
async def test_unfiltered_vinted_monitor_is_refused_before_marketplace_check(db_session, monkeypatch):
    user = User(username="unfiltered_monitor_user", telegram_bot_token="", telegram_chat_id="")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name="Unfiltered",
        original_url="https://www.vinted.fr/catalog",
        params_json=json.dumps({"order": "newest_first"}),
        domains_json='["vinted.fr"]',
        interval_sec=120,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", session_factory)

    context = await tasks._load_monitor_check_context(monitor.id)

    assert context is None
    await db_session.refresh(monitor)
    assert monitor.last_check_status == "failed"
    assert "no searchable filters" in monitor.last_error
