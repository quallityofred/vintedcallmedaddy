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
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        print("Checking users table...")
        
        # Check columns
        result = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"))
        existing_columns = [row[0] for row in result.fetchall()]
        
        new_columns = {
            "cf_worker_url": "VARCHAR DEFAULT '' NOT NULL",
            "cf_worker_block_threshold": "INTEGER DEFAULT 2 NOT NULL",
            "cf_worker_recovery_minutes": "INTEGER DEFAULT 10 NOT NULL"
        }
        
        for col, col_type in new_columns.items():
            if col not in existing_columns:
                print(f"Adding column {col}...")
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))
                print(f"Added {col}.")
            else:
                print(f"Column {col} already exists.")
        
        print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(migrate())
