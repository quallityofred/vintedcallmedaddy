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

    # Use a basic engine to connect
    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        print("Checking hidden_sellers table...")
        
        # Check if table exists
        result = await conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_name = 'hidden_sellers'"))
        if not result.fetchone():
            print("Table hidden_sellers not found.")
            return

        # Check columns
        result = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'hidden_sellers'"))
        existing_columns = [row[0] for row in result.fetchall()]
        
        if "user_id" not in existing_columns:
            print("Adding column user_id...")
            # Default to nullable to avoid breaking existing data, though constraint logic needs care
            await conn.execute(text("ALTER TABLE hidden_sellers ADD COLUMN user_id INTEGER"))
            print("Added user_id.")
        else:
            print("Column user_id already exists.")
            
        # Index on user_id if missing
        result = await conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'hidden_sellers' AND indexname = 'ix_hidden_sellers_user_id'"))
        if not result.fetchone():
            print("Adding index ix_hidden_sellers_user_id...")
            await conn.execute(text("CREATE INDEX ix_hidden_sellers_user_id ON hidden_sellers (user_id)"))
            print("Added index.")
        else:
            print("Index ix_hidden_sellers_user_id already exists.")

        print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(migrate())
