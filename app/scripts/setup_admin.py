# scripts/setup_admin.py
import asyncio
import logging
from sqlalchemy import select
from app.database import get_engine, get_session_factory
from app.models import User, Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def setup_admin():
    session_factory = get_session_factory()
    async with session_factory() as db:
        # 1. Add missing columns explicitly for migration (SQLAlchemy create_all doesn't do this)
        from sqlalchemy import text
        try:
            await db.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"))
            await db.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS invite_code_id INTEGER REFERENCES invite_codes(id)"))
            await db.commit()
            logger.info("Database columns verified/added.")
        except Exception as e:
            await db.rollback()
            logger.warning(f"Note: Some columns might already exist or table doesn't exist yet: {e}")

        # 2. Ensure tables exist (including the new invite_codes table)
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        username = "qwe"
        password = "123123"
        
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        
        if user:
            logger.info(f"User {username} exists, promoting to admin...")
            user.is_admin = True
            user.set_password(password) # Update password just in case
        else:
            logger.info(f"Creating admin user {username}...")
            user = User(username=username, is_admin=True)
            user.set_password(password)
            db.add(user)
            
        await db.commit()
        logger.info("Admin setup complete.")

if __name__ == "__main__":
    asyncio.run(setup_admin())
