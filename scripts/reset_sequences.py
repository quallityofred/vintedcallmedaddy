import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import get_settings

async def reset_sequences():
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url_validated,
        connect_args={"statement_cache_size": 0}
    )
    
    tables = ['users', 'monitors', 'found_items', 'scraper_sessions', 'hidden_sellers']
    
    async with engine.begin() as conn:
        for table in tables:
            print(f"Resetting sequence for {table}...")
            # Set the sequence to max(id)
            await conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1), false);"))
            # Force next value to be max + 1
            await conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) + 1 FROM {table}), true);"))
            print(f"  Done.")

    await engine.dispose()
    print("All sequences reset successfully.")

if __name__ == "__main__":
    asyncio.run(reset_sequences())
