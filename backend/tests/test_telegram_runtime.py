from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.telegram import bot as bot_module
from app.web.app_web_dependencies import is_bot_running, start_bot, stop_bot


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBot:
    def __init__(self, token: str) -> None:
        self.token = token
        self.session = FakeSession()


class FakeDispatcher:
    def __init__(self) -> None:
        self.started = 0

    async def start_polling(self, bot: FakeBot) -> None:
        self.started += 1
        await asyncio.Event().wait()


@pytest_asyncio.fixture(autouse=True)
async def clear_telegram_runtime():
    for task in list(bot_module._polling_tasks.values()):
        task.cancel()
    if bot_module._polling_tasks:
        await asyncio.gather(*bot_module._polling_tasks.values(), return_exceptions=True)
    bot_module._polling_tasks.clear()
    bot_module._bots.clear()
    yield
    for task in list(bot_module._polling_tasks.values()):
        task.cancel()
    if bot_module._polling_tasks:
        await asyncio.gather(*bot_module._polling_tasks.values(), return_exceptions=True)
    bot_module._polling_tasks.clear()
    bot_module._bots.clear()


@pytest.mark.asyncio
async def test_start_bot_is_idempotent_for_same_token(monkeypatch):
    token = "runtime-token"
    fake_bot = FakeBot(token)
    fake_dp = FakeDispatcher()

    async def fake_terminate_all_sessions(token: str) -> None:
        return None

    def fake_get_or_create_bot(token: str):
        bot_module._bots[token] = fake_bot
        return fake_bot, fake_dp

    monkeypatch.setattr(bot_module, "terminate_all_sessions", fake_terminate_all_sessions)
    monkeypatch.setattr(bot_module, "get_or_create_bot", fake_get_or_create_bot)

    await start_bot(token, owner_user_id=1)
    await start_bot(token, owner_user_id=1)

    assert is_bot_running(token) is True
    assert len(bot_module._polling_tasks) == 1
    assert fake_dp.started == 1

    result = await stop_bot(token, timeout=0.5)
    assert result.ok is True


@pytest.mark.asyncio
async def test_stop_bot_cancels_task_then_removes_runtime(monkeypatch):
    token = "runtime-stop-token"
    fake_bot = FakeBot(token)
    fake_dp = FakeDispatcher()

    async def fake_terminate_all_sessions(token: str) -> None:
        return None

    def fake_get_or_create_bot(token: str):
        bot_module._bots[token] = fake_bot
        return fake_bot, fake_dp

    monkeypatch.setattr(bot_module, "terminate_all_sessions", fake_terminate_all_sessions)
    monkeypatch.setattr(bot_module, "get_or_create_bot", fake_get_or_create_bot)

    await start_bot(token, owner_user_id=2)
    assert is_bot_running(token) is True

    result = await stop_bot(token, timeout=0.5)

    assert result.ok is True
    assert result.running is False
    assert is_bot_running(token) is False
    assert token not in bot_module._polling_tasks
    assert token not in bot_module._bots
    assert fake_bot.session.closed is True


@pytest.mark.asyncio
async def test_stop_bot_timeout_keeps_live_task_registered():
    token = "runtime-timeout-token"
    release = asyncio.Event()
    fake_bot = FakeBot(token)

    async def stubborn_polling() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    task = asyncio.create_task(stubborn_polling())
    bot_module._polling_tasks[token] = task
    bot_module._bots[token] = fake_bot
    await asyncio.sleep(0)

    result = await stop_bot(token, timeout=0.01)

    assert result.ok is False
    assert result.state == "stop_timeout"
    assert result.running is True
    assert bot_module._polling_tasks[token] is task
    assert fake_bot.session.closed is False
    assert is_bot_running(token) is False
    release.set()
    try:
        await asyncio.wait_for(task, timeout=0.5)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    cleanup_result = await stop_bot(token, timeout=0.5)
    assert cleanup_result.ok is True
    assert fake_bot.session.closed is True

@pytest.mark.asyncio
async def test_api_health_counts_live_bot_tasks_only():
    token = "runtime-health-token"

    async def polling() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(polling())
    bot_module._polling_tasks[token] = task

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["bots_running"] == 1

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        response = await client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["bots_running"] == 0


@pytest.mark.asyncio
async def test_cleanup_script_does_not_print_token(monkeypatch, capsys):
    from scripts import cleanup_telegram_bot_connections as cleanup

    secret_token = "secret-token-value"

    class FakeWebhookInfo:
        url = "https://example.invalid/hook"

    class FakeCleanupBot:
        def __init__(self, token: str) -> None:
            assert token == secret_token
            self.session = FakeSession()

        async def get_webhook_info(self):
            return FakeWebhookInfo()

        async def delete_webhook(self, drop_pending_updates: bool = False):
            assert drop_pending_updates is True

        async def get_updates(self, offset: int, limit: int, timeout: int):
            assert offset == -1
            assert limit == 1
            assert timeout == 0
            return []

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", secret_token)
    monkeypatch.setattr(cleanup, "Bot", FakeCleanupBot)

    exit_code = await cleanup.cleanup_telegram_connections()

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Webhook present: yes" in output
    assert secret_token not in output
