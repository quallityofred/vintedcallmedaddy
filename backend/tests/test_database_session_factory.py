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
    db_pool_size = 20
    db_max_overflow = 10
    db_pool_timeout = 30
    db_pool_recycle_seconds = 300
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
    assert kwargs["pool_recycle"] == 300
    assert kwargs["pool_size"] == 20
    assert kwargs["max_overflow"] == 10
    assert kwargs["pool_timeout"] == 30
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
    assert kwargs["pool_recycle"] == 300
    assert kwargs["connect_args"] == {
        "statement_cache_size": 0,
        "timeout": 10,
        "command_timeout": 10,
        "server_settings": {"statement_timeout": "10000"},
    }
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs
    assert "pool_timeout" not in kwargs


@pytest.mark.parametrize("value", ["true", "1", "yes"])
def test_db_use_null_pool_env_parses_truthy_values(monkeypatch, value):
    monkeypatch.setenv("DB_USE_NULL_POOL", value)

    settings = app_config.Settings(_env_file=None)

    assert settings.db_use_null_pool is True
