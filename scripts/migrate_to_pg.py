import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.models import Base, User, Monitor, FoundItem, ScraperSession, HiddenSeller, AppSettings
from app.config import get_settings

async def migrate():
    settings = get_settings()
    
    sqlite_url = "sqlite+aiosqlite:///C:/Users/egory/Desktop/vinted_bot/vintedbot/data/vinted.db"
    pg_url = settings.database_url
    
    if "sqlite" in pg_url:
        print("Error: DATABASE_URL in .env is still SQLite. Please set it to PostgreSQL URL.")
        return

    print(f"Migrating from {sqlite_url} to {pg_url}...")
    
    sqlite_engine = create_async_engine(sqlite_url)
    pg_engine = create_async_engine(pg_url)
    
    # Create tables in PG
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session_sqlite = async_sessionmaker(sqlite_engine, class_=AsyncSession)
    async_session_pg = async_sessionmaker(pg_engine, class_=AsyncSession)
    
    async with async_session_sqlite() as sqlite_session:
        async with async_session_pg() as pg_session:
            # Order of migration to respect foreign keys
            models = [User, Monitor, FoundItem, ScraperSession, HiddenSeller, AppSettings]
            
            for model in models:
                print(f"Migrating {model.__tablename__}...")
                result = await sqlite_session.execute(select(model))
                items = result.scalars().all()
                
                if items:
                    for item in items:
                        # Copy data to a new instance of the model
                        data = {k: v for k, v in item.__dict__.items() if not k.startswith('_')}
                        new_item = model(**data)
                        pg_session.add(new_item)
                    
                    await pg_session.commit()
                    print(f"  Migrated {len(items)} records.")
                else:
                    print("  No records found.")
                    
    print("Migration completed successfully!")

if __name__ == "__main__":
    asyncio.run(migrate())
