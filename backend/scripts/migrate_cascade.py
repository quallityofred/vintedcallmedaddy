import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal, engine
from app.models import Base

async def reset_db():
    print("Running migration: Adding CASCADE DELETE to found_items...")
    async with engine.begin() as conn:
        # Drop and recreate constraints to add CASCADE
        await conn.execute(text("ALTER TABLE found_items DROP CONSTRAINT IF EXISTS found_items_monitor_id_fkey"))
        await conn.execute(text("ALTER TABLE found_items ADD CONSTRAINT found_items_monitor_id_fkey FOREIGN KEY (monitor_id) REFERENCES monitors(id) ON DELETE CASCADE"))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(reset_db())
