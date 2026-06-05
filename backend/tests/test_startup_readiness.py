from types import SimpleNamespace

import pytest

import app.app_main as app_main


@pytest.mark.asyncio
async def test_background_startup_marks_ready_without_secret_config(monkeypatch):
    calls: list[str] = []
    app = SimpleNamespace(state=SimpleNamespace())

    async def fake_init_db():
        calls.append("db")

    async def fake_apply_settings():
        calls.append("settings")

    class FakeScheduler:
        job_ids = {}

        async def start(self):
            calls.append("scheduler")

    async def fake_restore_bots(app_state):
        calls.append("bots")

    monkeypatch.setattr(app_main, "init_db", fake_init_db)
    monkeypatch.setattr("app.runtime_settings.apply_db_runtime_settings", fake_apply_settings)
    monkeypatch.setattr("app.scheduler.tasks.MonitorScheduler", FakeScheduler)
    monkeypatch.setattr(app_main, "restore_persisted_bot", fake_restore_bots)
    monkeypatch.setattr(app_main.settings, "startup_db_timeout_seconds", 1)
    monkeypatch.setattr(app_main.settings, "startup_db_max_attempts", 1)
    monkeypatch.setattr(app_main.settings, "startup_optional_timeout_seconds", 1)

    await app_main._run_startup_services(app)

    assert calls == ["db", "settings", "scheduler", "bots"]
    assert app.state.db_ready is True
    assert app.state.scheduler_ready is True
    assert app.state.startup_status == "ready"
    assert app.state.startup_error is None


@pytest.mark.asyncio
async def test_background_startup_degrades_when_db_never_becomes_ready(monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace())

    async def failing_init_db():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(app_main, "init_db", failing_init_db)
    monkeypatch.setattr(app_main.settings, "startup_db_timeout_seconds", 1)
    monkeypatch.setattr(app_main.settings, "startup_db_max_attempts", 1)
    monkeypatch.setattr(app_main.settings, "startup_db_retry_interval_seconds", 0)

    await app_main._run_startup_services(app)

    assert app.state.db_ready is False
    assert app.state.startup_status == "degraded"
    assert app.state.startup_error == "database_startup_failed"
