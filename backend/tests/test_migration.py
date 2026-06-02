# tests/test_migration.py
import pytest
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from app.database import validate_and_migrate_db

@pytest.mark.asyncio
async def test_validate_and_migrate_db_adds_columns():
    # 1. Create a fresh in-memory DB
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    
    async with test_engine.begin() as conn:
        # Create tables WITHOUT the new columns and WITHOUT foreign keys to users/monitors for simplicity in this test
        # We just need to check if columns are added
        await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE monitors (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE seen_items (id INTEGER PRIMARY KEY, vinted_item_id BIGINT, domain TEXT, seen_at DATETIME)"))
        await conn.execute(text("CREATE TABLE found_items (id INTEGER PRIMARY KEY, vinted_item_id BIGINT, domain TEXT)"))

    # 2. Run the migration
    async with test_engine.begin() as conn:
        # We need to mock 'engine' inside validate_and_migrate_db or just pass a connection
        # Since it uses 'engine.dialect.name', we might need to be careful
        from app import database
        original_engine = database.engine
        database.engine = test_engine
        try:
            await validate_and_migrate_db(conn)
        finally:
            database.engine = original_engine

    # 3. Verify columns exist
    async with test_engine.connect() as conn:
        def get_columns(connection, table_name):
            inspector = inspect(connection)
            return [c["name"] for c in inspector.get_columns(table_name)]

        def get_indexes(connection, table_name):
            inspector = inspect(connection)
            return [i["name"] for i in inspector.get_indexes(table_name)]

        columns_seen = await conn.run_sync(get_columns, "seen_items")
        assert "user_id" in columns_seen
        
        columns_found = await conn.run_sync(get_columns, "found_items")
        assert "notified" in columns_found
        assert "monitor_id" in columns_found

        indexes_seen = await conn.run_sync(get_indexes, "seen_items")
        assert any("uq_seen_items_user_item_domain" in idx for idx in indexes_seen)

        indexes_found = await conn.run_sync(get_indexes, "found_items")
        assert any("uq_found_items_monitor_item_domain" in idx for idx in indexes_found)

    await test_engine.dispose()
