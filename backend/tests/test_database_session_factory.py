import pytest
import pytest_asyncio
from sqlalchemy import text

import app.app_database as app_database
import app.database as database_wrapper
import app.web.app_web_dependencies as web_dependencies


class FakeSqliteSettings:
    database_url_validated = "sqlite+aiosqlite:///:memory:"

    def is_sqlite(self) -> bool:
        return True

    def get_sqlite_data_dir(self):
        return None


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
