from __future__ import annotations

import argparse
import asyncio
import time

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import get_session_factory


def _pool_mode() -> str:
    settings = get_settings()
    if settings.is_sqlite():
        return "static"
    return "null" if settings.db_use_null_pool else "queue"


async def _time_query(db, label: str, statement, params: dict | None = None) -> None:
    started = time.monotonic()
    try:
        await db.execute(statement, params or {})
        elapsed_ms = int((time.monotonic() - started) * 1000)
        print(f"{label}_ms={elapsed_ms}")
    except SQLAlchemyError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        print(f"{label}_error={exc.__class__.__name__}")
        print(f"{label}_ms={elapsed_ms}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run safe database latency checks.")
    parser.add_argument("--check-auth-username", default="", help="Time an auth username lookup without printing it.")
    args = parser.parse_args()

    print(f"pool_mode={_pool_mode()}")
    session_factory = get_session_factory()
    async with session_factory() as db:
        await _time_query(db, "select_1", text("SELECT 1"))
        await _time_query(db, "users_limit_1", text("SELECT id FROM users LIMIT 1"))
        await _time_query(db, "user_sessions_limit_1", text("SELECT id FROM user_sessions LIMIT 1"))
        if args.check_auth_username:
            await _time_query(
                db,
                "auth_username_lookup",
                text("SELECT id FROM users WHERE username = :username LIMIT 1"),
                {"username": args.check_auth_username},
            )


if __name__ == "__main__":
    asyncio.run(main())
