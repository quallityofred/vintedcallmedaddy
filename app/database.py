# app/database.py
import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import inspect, text

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(**name**)

settings = get_settings()

if [settings.is](https://settings.is)_sqlite():
data_dir = settings.get_sqlite_data_dir()
if data_dir is not None:
data_dir.mkdir(parents=True, exist_ok=True)

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

async def init_db() -> None:
max_retries = 5
for i in range(max_retries):
try:
[logger.info](https://logger.info)(f"Attempting to connect to database (attempt {i+1}/{max_retries})...")
async with engine.begin() as conn:
await conn.run_sync(Base.metadata.create_all)
await validate_and_migrate_db(conn)
[logger.info](https://logger.info)("Database initialized and migrated successfully.")
return
except Exception as e:
logger.error(f"Database initialization failed: {e}")
if i < max_retries - 1:
await asyncio.sleep(5)
else:
raise e

async def validate_and_migrate_db(conn) -> None:
[logger.info](https://logger.info)("Validating database schema...")

def get_columns(connection, table_name):
inspector = inspect(connection)
return [c["name"] for c in inspector.get_columns(table_name)]

try:
columns_seen = await conn.run_sync(get_columns, "seen_items")
except Exception:
columns_seen = []

if "user_id" not in columns_seen:
logger.warning("Migration required: column 'user_id' missing in 'seen_items'")
await conn.execute(text("ALTER TABLE seen_items ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"))
[logger.info](https://logger.info)("Successfully added 'user_id' to 'seen_items'")

try:
columns_found = await conn.run_sync(get_columns, "found_items")
except Exception:
columns_found = []

if "notified" not in columns_found:
logger.warning("Migration required: column 'notified' missing in 'found_items'")
await conn.execute(text("ALTER TABLE found_items ADD COLUMN notified BOOLEAN DEFAULT FALSE"))
[logger.info](https://logger.info)("Successfully added 'notified' to 'found_items'")

if "monitor_id" not in columns_found:
logger.warning("Migration required: column 'monitor_id' missing in 'found_items'")
await conn.execute(text("ALTER TABLE found_items ADD COLUMN monitor_id INTEGER REFERENCES monitors(id) ON DELETE CASCADE"))
[logger.info](https://logger.info)("Successfully added 'monitor_id' to 'found_items'")

try:
if [engine.dialect.name](https://engine.dialect.name) == 'postgresql':
await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_seen_items_user_item_domain ON seen_items (user_id, vinted_item_id, domain)"))
await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_found_items_monitor_item_domain ON found_items (monitor_id, vinted_item_id, domain)"))
else:
await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_seen_items_user_item_domain ON seen_items (user_id, vinted_item_id, domain)"))
await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_found_items_monitor_item_domain ON found_items (monitor_id, vinted_item_id, domain)"))
except Exception as e:
logger.warning(f"Note: Could not ensure unique indexes: {e}")

[logger.info](https://logger.info)("Database schema validation completed.")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
async with AsyncSessionLocal() as session:
try:
yield session
finally:
await session.close()