import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


USER_COLUMNS = {
    "telegram_topics_enabled": "ALTER TABLE users ADD COLUMN telegram_topics_enabled BOOLEAN DEFAULT FALSE NOT NULL",
    "telegram_topics_chat_id": "ALTER TABLE users ADD COLUMN telegram_topics_chat_id VARCHAR",
    "telegram_topics_auto_create": "ALTER TABLE users ADD COLUMN telegram_topics_auto_create BOOLEAN DEFAULT TRUE NOT NULL",
    "telegram_topics_recreate_deleted": "ALTER TABLE users ADD COLUMN telegram_topics_recreate_deleted BOOLEAN DEFAULT FALSE NOT NULL",
    "telegram_topics_fallback_to_main_chat": (
        "ALTER TABLE users ADD COLUMN telegram_topics_fallback_to_main_chat BOOLEAN DEFAULT FALSE NOT NULL"
    ),
}


async def migrate() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set.")
        return
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        print("Checking Telegram topic schema...")

        result = await conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
        )
        existing_columns = {row[0] for row in result.fetchall()}

        for column_name, migration_sql in USER_COLUMNS.items():
            if column_name not in existing_columns:
                print(f"Adding users.{column_name}...")
                await conn.execute(text(migration_sql))
            else:
                print(f"users.{column_name} already exists.")

        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS monitor_telegram_topics (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    monitor_id INTEGER NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
                    chat_id VARCHAR NOT NULL,
                    message_thread_id BIGINT,
                    topic_name VARCHAR NOT NULL,
                    status VARCHAR DEFAULT 'pending' NOT NULL,
                    last_error VARCHAR,
                    last_error_code VARCHAR,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    last_verified_at TIMESTAMP WITH TIME ZONE,
                    CONSTRAINT uq_monitor_telegram_topics_monitor_chat UNIQUE (monitor_id, chat_id)
                )
                """
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_monitor_telegram_topics_user_id ON monitor_telegram_topics (user_id)")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_monitor_telegram_topics_chat_thread "
                "ON monitor_telegram_topics (chat_id, message_thread_id)"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_monitor_telegram_topics_status ON monitor_telegram_topics (status)")
        )

        print("Telegram topic migration complete.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
