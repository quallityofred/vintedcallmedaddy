# app/database.py
import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)

settings = get_settings()

if settings.is_sqlite():
    data_dir = settings.get_sqlite_data_dir()
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)

# Set statement_cache_size to 0 for PgBouncer compatibility
engine = create_async_engine(
    settings.database_url_validated, 
    echo=False, 
    future=True,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,
    connect_args={"statement_cache_size": 0}
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


from sqlalchemy import inspect, text
from sqlalchemy.engine import reflection

async def init_db() -> None:
    max_retries = 5
    for i in range(max_retries):
        try:
            logger.info(f"Attempting to connect to database (attempt {i+1}/{max_retries})...")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Perform manual migrations for existing tables
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
    """Safely adds missing columns and indexes to existing tables with detailed logging."""
    logger.info("Validating database schema...")
    
    def get_columns(connection, table_name):
        inspector = inspect(connection)
        return [c["name"] for c in inspector.get_columns(table_name)]

    # 1. Migrate seen_items
    columns_seen = await conn.run_sync(get_columns, "seen_items")
    if "user_id" not in columns_seen:
        logger.warning("Migration required: column 'user_id' missing in 'seen_items'")
        await conn.execute(text("ALTER TABLE seen_items ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"))
        logger.info("Successfully added 'user_id' to 'seen_items'")
    else:
        logger.debug("'seen_items' schema is up to date (user_id exists)")
        
    try:
        if engine.dialect.name == 'postgresql':
            await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_seen_items_user_item_domain ON seen_items (user_id, vinted_item_id, domain)"))
        else:
            await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_seen_items_user_item_domain ON seen_items (user_id, vinted_item_id, domain)"))
    except Exception as e:
        logger.warning(f"Note: Could not ensure unique index on seen_items (might already exist): {e}")

    # 2. Migrate found_items
    columns_found = await conn.run_sync(get_columns, "found_items")
    if "notified" not in columns_found:
        logger.warning("Migration required: column 'notified' missing in 'found_items'")
        await conn.execute(text("ALTER TABLE found_items ADD COLUMN notified BOOLEAN DEFAULT FALSE"))
        logger.info("Successfully added 'notified' to 'found_items'")
    
    if "monitor_id" not in columns_found:
        logger.warning("Migration required: column 'monitor_id' missing in 'found_items'")
        await conn.execute(text("ALTER TABLE found_items ADD COLUMN monitor_id INTEGER REFERENCES monitors(id) ON DELETE CASCADE"))
        logger.info("Successfully added 'monitor_id' to 'found_items'")

    try:
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_found_items_monitor_item_domain ON found_items (monitor_id, vinted_item_id, domain)"))
    except Exception as e:
        logger.warning(f"Note: Could not ensure unique index on found_items (might already exist): {e}")
    
    logger.info("Database schema validation completed.")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
