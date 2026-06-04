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
        print("Checking monitors table...")
        
        result = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'monitors'"))
        existing_columns = [row[0] for row in result.fetchall()]
        
        new_columns = {
            "last_check_status": "VARCHAR",
            "last_error": "VARCHAR",
            "last_check_started_at": "TIMESTAMP WITH TIME ZONE",
            "last_check_completed_at": "TIMESTAMP WITH TIME ZONE"
        }
        
        for col, col_type in new_columns.items():
            if col not in existing_columns:
                print(f"Adding column {col}...")
                await conn.execute(text(f"ALTER TABLE monitors ADD COLUMN {col} {col_type}"))
                print(f"Added {col}.")
            else:
                print(f"Column {col} already exists.")
        
        print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(migrate())
