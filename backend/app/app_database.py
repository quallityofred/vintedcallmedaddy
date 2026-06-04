# app/database.py
import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import inspect, text

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)

# Lazily-created engine and sessionmaker. Creating the async engine at import
# time can trigger attempts to connect to Postgres (asyncpg) which is
# undesirable during test collection. Ensure initialization happens on
# first use (e.g., in init_db or when a session is requested).
engine = None
AsyncSessionLocal = None


def _ensure_engine_initialized() -> None:
    """Create the async engine and sessionmaker if not already initialized."""
    global engine, AsyncSessionLocal
    if engine is not None and AsyncSessionLocal is not None:
        return
    settings = get_settings()
    if settings.is_sqlite():
        data_dir = settings.get_sqlite_data_dir()
        if data_dir is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
    if settings.is_sqlite():
        from sqlalchemy.pool import StaticPool

        engine = create_async_engine(
            settings.database_url_validated,
            echo=False,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_async_engine(
            settings.database_url_validated,
            echo=False,
            future=True,
            pool_size=20,
            max_overflow=10,
            pool_timeout=30,
            pool_pre_ping=True,
            connect_args={"statement_cache_size": 0},
        )
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the current async session factory, initializing it if needed."""
    _ensure_engine_initialized()
    if AsyncSessionLocal is None:
        raise RuntimeError("Database session factory is not initialized")
    return AsyncSessionLocal


def get_engine() -> AsyncEngine:
    """Return the current async engine, initializing it if needed."""
    _ensure_engine_initialized()
    if engine is None:
        raise RuntimeError("Database engine is not initialized")
    return engine


def _get_effective_engine():
    """Return the engine to use for migration/inspection.

    This prefers the module-level `engine` if set, but also checks the
    public `app.database` wrapper module so tests can monkeypatch
    `app.database.engine` (tests set that attribute). This keeps
    compatibility with the test-suite which sets the engine on the
    wrapper module.
    """
    global engine
    if engine is not None:
        return engine
    try:
        from app import database as db_wrapper
        wrapped = getattr(db_wrapper, "engine", None)
        if wrapped is not None:
            return wrapped
    except Exception:
        pass
    return engine


async def init_db() -> None:
    """Initialize the database, creating all tables and running migrations."""
    max_retries = 5
    for i in range(max_retries):
        try:
            logger.info(f"Attempting to connect to database (attempt {i + 1}/{max_retries})...")
            _ensure_engine_initialized()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await validate_and_migrate_db(conn)
            logger.info("Database initialized and migrated successfully.")
            return
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            if i < max_retries - 1:
                await asyncio.sleep(5)
            else:
                raise e


async def validate_and_migrate_db(conn) -> None:
    """Validate schema and apply lightweight in-place migrations."""
    logger.info("Validating database schema...")

    def get_columns(connection, table_name: str) -> list[str]:
        inspector = inspect(connection)
        try:
            return [c["name"] for c in inspector.get_columns(table_name)]
        except Exception:
            return []

    columns_users = await conn.run_sync(get_columns, "users")

    user_column_migrations = {
        "cf_worker_url": "ALTER TABLE users ADD COLUMN cf_worker_url VARCHAR DEFAULT '' NOT NULL",
        "cf_worker_block_threshold": "ALTER TABLE users ADD COLUMN cf_worker_block_threshold INTEGER DEFAULT 2 NOT NULL",
        "cf_worker_recovery_minutes": "ALTER TABLE users ADD COLUMN cf_worker_recovery_minutes INTEGER DEFAULT 10 NOT NULL",
        "is_telegram_enabled": "ALTER TABLE users ADD COLUMN is_telegram_enabled BOOLEAN DEFAULT FALSE NOT NULL",
        "cf_worker_mode": "ALTER TABLE users ADD COLUMN cf_worker_mode VARCHAR DEFAULT 'auto' NOT NULL",
        "telegram_topics_enabled": "ALTER TABLE users ADD COLUMN telegram_topics_enabled BOOLEAN DEFAULT FALSE NOT NULL",
        "telegram_topics_chat_id": "ALTER TABLE users ADD COLUMN telegram_topics_chat_id VARCHAR",
        "telegram_topics_auto_create": "ALTER TABLE users ADD COLUMN telegram_topics_auto_create BOOLEAN DEFAULT TRUE NOT NULL",
        "telegram_topics_recreate_deleted": "ALTER TABLE users ADD COLUMN telegram_topics_recreate_deleted BOOLEAN DEFAULT FALSE NOT NULL",
        "telegram_topics_fallback_to_main_chat": "ALTER TABLE users ADD COLUMN telegram_topics_fallback_to_main_chat BOOLEAN DEFAULT FALSE NOT NULL",
    }
    for column_name, migration_sql in user_column_migrations.items():
        if columns_users and column_name not in columns_users:
            logger.warning("Migration: adding '%s' to 'users'", column_name)
            await conn.execute(text(migration_sql))
            logger.info("Added '%s' to 'users'", column_name)

    if columns_users:
        try:
            await conn.execute(
                text(
                    "UPDATE users SET cf_worker_mode = 'auto' "
                    "WHERE cf_worker_mode IS NULL OR cf_worker_mode NOT IN ('auto', 'direct', 'worker')"
                )
            )
            await conn.execute(
                text(
                    "UPDATE users SET telegram_topics_enabled = FALSE "
                    "WHERE telegram_topics_enabled IS NULL"
                )
            )
            await conn.execute(
                text(
                    "UPDATE users SET telegram_topics_auto_create = TRUE "
                    "WHERE telegram_topics_auto_create IS NULL"
                )
            )
            await conn.execute(
                text(
                    "UPDATE users SET telegram_topics_recreate_deleted = FALSE "
                    "WHERE telegram_topics_recreate_deleted IS NULL"
                )
            )
            await conn.execute(
                text(
                    "UPDATE users SET telegram_topics_fallback_to_main_chat = FALSE "
                    "WHERE telegram_topics_fallback_to_main_chat IS NULL"
                )
            )
        except Exception as e:
            logger.warning("Note: Could not normalize users settings columns: %s", e)

    columns_seen = await conn.run_sync(get_columns, "seen_items")

    if "user_id" not in columns_seen:
        logger.warning("Migration: adding 'user_id' to 'seen_items'")
        await conn.execute(
            text("ALTER TABLE seen_items ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
        )
        logger.info("Added 'user_id' to 'seen_items'")

    columns_found = await conn.run_sync(get_columns, "found_items")

    if "notified" not in columns_found:
        logger.warning("Migration: adding 'notified' to 'found_items'")
        await conn.execute(text("ALTER TABLE found_items ADD COLUMN notified BOOLEAN DEFAULT FALSE"))
        logger.info("Added 'notified' to 'found_items'")

    if "monitor_id" not in columns_found:
        logger.warning("Migration: adding 'monitor_id' to 'found_items'")
        await conn.execute(
            text("ALTER TABLE found_items ADD COLUMN monitor_id INTEGER REFERENCES monitors(id) ON DELETE CASCADE")
        )
        logger.info("Added 'monitor_id' to 'found_items'")

    try:
        eng = _get_effective_engine()
        dialect_name = eng.dialect.name if eng is not None else None
        # Use the same SQL for both Postgres and SQLite; the function
        # execution context may differ in tests so we avoid relying on
        # `engine` being the one from this module.
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_seen_items_user_item_domain "
                "ON seen_items (user_id, vinted_item_id, domain)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_found_items_monitor_item_domain "
                "ON found_items (monitor_id, vinted_item_id, domain)"
            )
        )
    except Exception as e:
        logger.warning(f"Note: Could not ensure unique indexes: {e}")

    logger.info("Database schema validation completed.")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
