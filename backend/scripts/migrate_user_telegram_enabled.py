import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def migrate():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set.")
        return
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        print("Checking users table...")
        
        result = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"))
        existing_columns = [row[0] for row in result.fetchall()]
        
        if "is_telegram_enabled" not in existing_columns:
            print("Adding column is_telegram_enabled...")
            # Default to False
            await conn.execute(text("ALTER TABLE users ADD COLUMN is_telegram_enabled BOOLEAN DEFAULT FALSE NOT NULL"))
            print("Added is_telegram_enabled.")
        else:
            print("Column is_telegram_enabled already exists.")
        
        print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(migrate())
