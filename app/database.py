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


async def init_db() -> None:
    max_retries = 5
    for i in range(max_retries):
        try:
            logger.info(f"Attempting to connect to database (attempt {i+1}/{max_retries})...")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database initialized successfully.")
            return
        except SQLAlchemyError as e:
            logger.error(f"Database initialization failed: {e}")
            if i < max_retries - 1:
                await asyncio.sleep(5)
            else:
                raise e


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
