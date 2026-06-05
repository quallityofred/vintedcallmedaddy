import pytest
import pytest_asyncio
from sqlalchemy import text

import app.app_config as app_config
import app.app_database as app_database
import app.database as database_wrapper
import app.web.app_web_dependencies as web_dependencies


class FakeSqliteSettings:
    database_url_validated = "sqlite+aiosqlite:///:memory:"

    def is_sqlite(self) -> bool:
        return True

    def get_sqlite_data_dir(self):
        return None


class FakePostgresSettings:
    database_url_validated = "postgresql+asyncpg://user:pass@example.test/db"
    db_pool_size = 3
    db_max_overflow = 0
    db_pool_timeout = 10
    db_pool_recycle_seconds = 120
    db_connect_timeout_seconds = 10
    db_operation_timeout_seconds = 10
    db_use_null_pool = False

    def is_sqlite(self) -> bool:
        return False


@pytest_asyncio.fixture
async def isolated_database_state(monkeypatch):
    old_engine = app_database.engine
    old_session_factory = app_database.AsyncSessionLocal
    old_wrapper_session_factory = getattr(database_wrapper, "AsyncSessionLocal", None)

    app_database.engine = None
    app_database.AsyncSessionLocal = None
    database_wrapper.AsyncSessionLocal = None
    monkeypatch.setattr(app_database, "get_settings", lambda: FakeSqliteSettings())

    yield

    if app_database.engine is not None:
        await app_database.engine.dispose()
    app_database.engine = old_engine
    app_database.AsyncSessionLocal = old_session_factory
    database_wrapper.AsyncSessionLocal = old_wrapper_session_factory


@pytest.mark.asyncio
async def test_web_get_db_uses_initialized_factory_after_stale_import(isolated_database_state):
    assert not hasattr(web_dependencies, "AsyncSessionLocal")
    assert database_wrapper.AsyncSessionLocal is None

    session_factory = web_dependencies.get_session_factory()
    assert callable(session_factory)
    assert app_database.AsyncSessionLocal is not None
    assert database_wrapper.AsyncSessionLocal is None

    async with session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_web_get_db_import_before_initialization_does_not_capture_none(isolated_database_state):
    db_generator = web_dependencies.get_db()
    session = await anext(db_generator)
    try:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    finally:
        await db_generator.aclose()


def test_missing_session_factory_raises_clear_error(monkeypatch):
    monkeypatch.setattr(app_database, "AsyncSessionLocal", None)
    monkeypatch.setattr(app_database, "_ensure_engine_initialized", lambda: None)

    with pytest.raises(RuntimeError, match="Database session factory is not initialized"):
        app_database.get_session_factory()


def test_postgres_engine_kwargs_enable_connection_resilience():
    kwargs = app_database.build_async_engine_kwargs(FakePostgresSettings())

    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == 120
    assert kwargs["pool_size"] == 3
    assert kwargs["pool_size"] <= 5
    assert kwargs["max_overflow"] == 0
    assert kwargs["pool_timeout"] == 10
    assert kwargs["connect_args"] == {
        "statement_cache_size": 0,
        "timeout": 10,
        "command_timeout": 10,
        "server_settings": {"statement_timeout": "10000"},
    }


def test_sqlite_engine_kwargs_keep_static_pool():
    kwargs = app_database.build_async_engine_kwargs(FakeSqliteSettings())

    assert kwargs["connect_args"] == {"check_same_thread": False}
    assert "pool_pre_ping" not in kwargs
    assert "pool_recycle" not in kwargs


def test_postgres_engine_kwargs_support_null_pool():
    class NullPoolSettings(FakePostgresSettings):
        db_use_null_pool = True

    kwargs = app_database.build_async_engine_kwargs(NullPoolSettings())

    assert kwargs["poolclass"].__name__ == "NullPool"
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == 120
    assert kwargs["connect_args"] == {
        "statement_cache_size": 0,
        "timeout": 10,
        "command_timeout": 10,
        "server_settings": {"statement_timeout": "10000"},
    }
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs
    assert "pool_timeout" not in kwargs


def test_postgres_pool_env_overrides_still_work(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "9")
    monkeypatch.setenv("DB_POOL_RECYCLE_SECONDS", "180")

    settings = app_config.Settings(_env_file=None)

    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 1
    assert settings.db_pool_timeout == 9
    assert settings.db_pool_recycle_seconds == 180


def test_monitor_check_backpressure_defaults_are_conservative():
    settings = app_config.Settings(_env_file=None)

    assert settings.monitor_check_global_concurrency == 2
    assert settings.monitor_check_per_user_concurrency == 1
    assert settings.monitor_check_acquire_timeout_seconds == 2.0
    assert settings.monitor_check_max_pages_per_domain == 1
    assert settings.monitor_candidate_detail_max_per_check == 10
    assert settings.monitor_freshness_grace_seconds == 600
    assert settings.monitor_detail_guard_enabled is True
    assert settings.monitor_detail_category_guard_enabled is True
    assert settings.monitor_detail_freshness_guard_enabled is True


def test_monitor_check_backpressure_env_overrides(monkeypatch):
    monkeypatch.setenv("MONITOR_CHECK_GLOBAL_CONCURRENCY", "4")
    monkeypatch.setenv("MONITOR_CHECK_PER_USER_CONCURRENCY", "2")
    monkeypatch.setenv("MONITOR_CHECK_ACQUIRE_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("MONITOR_CHECK_MAX_PAGES_PER_DOMAIN", "3")
    monkeypatch.setenv("MONITOR_CANDIDATE_DETAIL_MAX_PER_CHECK", "7")
    monkeypatch.setenv("MONITOR_FRESHNESS_GRACE_SECONDS", "120")
    monkeypatch.setenv("MONITOR_DETAIL_GUARD_ENABLED", "false")
    monkeypatch.setenv("MONITOR_DETAIL_CATEGORY_GUARD_ENABLED", "false")
    monkeypatch.setenv("MONITOR_DETAIL_FRESHNESS_GUARD_ENABLED", "false")

    settings = app_config.Settings(_env_file=None)

    assert settings.monitor_check_global_concurrency == 4
    assert settings.monitor_check_per_user_concurrency == 2
    assert settings.monitor_check_acquire_timeout_seconds == 1.5
    assert settings.monitor_check_max_pages_per_domain == 3
    assert settings.monitor_candidate_detail_max_per_check == 7
    assert settings.monitor_freshness_grace_seconds == 120
    assert settings.monitor_detail_guard_enabled is False
    assert settings.monitor_detail_category_guard_enabled is False
    assert settings.monitor_detail_freshness_guard_enabled is False


@pytest.mark.parametrize("value", ["true", "1", "yes"])
def test_db_use_null_pool_env_parses_truthy_values(monkeypatch, value):
    monkeypatch.setenv("DB_USE_NULL_POOL", value)

    settings = app_config.Settings(_env_file=None)

    assert settings.db_use_null_pool is True
