import asyncio
import os
import argparse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def reset_monitoring(confirm=False):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set.")
        return
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        tables = ['monitors', 'found_items', 'seen_items', 'users', 'hidden_sellers']
        
        print("--- Pre-reset counts ---")
        for table in tables:
            count = (await conn.execute(text(f'SELECT count(*) FROM {table}'))).scalar()
            print(f'{table}: {count}')
        
        if not confirm:
            print("\nDry run mode: No changes made. Run with --confirm to delete.")
            return

        print("\n--- Deleting monitor-related data ---")
        # Deletion order: found_items, seen_items, monitors
        # Use DELETE to avoid cascade issues if any, although schemas should handle it.
        # Explicit deletion is safer here.
        await conn.execute(text('DELETE FROM found_items'))
        await conn.execute(text('DELETE FROM seen_items'))
        await conn.execute(text('DELETE FROM monitors'))
        print("Monitor data deleted.")

        print("\n--- Post-reset counts ---")
        for table in tables:
            count = (await conn.execute(text(f'SELECT count(*) FROM {table}'))).scalar()
            print(f'{table}: {count}')
        
        print("\nReset complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Confirm deletion")
    args = parser.parse_args()
    asyncio.run(reset_monitoring(confirm=args.confirm))
