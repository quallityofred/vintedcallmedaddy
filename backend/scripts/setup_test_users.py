import asyncio
import secrets
import string
import sys
import os

# Add root directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import init_db, get_session_factory
from app.models import User
from sqlalchemy import select

def generate_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

async def setup_users():
    # 1. Ensure DB is initialized
    try:
        await init_db()
    except Exception as e:
        print(f"Error: Database initialization failed: {e}")
        sys.exit(1)

    # 2. Get the factory
    SessionLocal = get_session_factory()

    async with SessionLocal() as db:
        users_to_create = [
            {"username": "test_user", "is_admin": False},
            {"username": "test_admin", "is_admin": True},
        ]

        for u_data in users_to_create:
            # Idempotent check
            result = await db.execute(select(User).where(User.username == u_data["username"]))
            existing = result.scalar_one_or_none()
            
            password = generate_password()
            
            if existing:
                print(f"Updating user: {u_data['username']}")
                user = existing
            else:
                print(f"Creating user: {u_data['username']}")
                user = User(username=u_data["username"], is_admin=u_data["is_admin"])
                db.add(user)
            
            # Update/Set password
            user.set_password(password)
            user.is_admin = u_data["is_admin"]
            
            await db.commit()
            await db.refresh(user)

            if u_data["is_admin"]:
                print("Admin user:")
            else:
                print("Normal user:")
            print(f"username: {user.username}")
            print(f"password: {password}")
            print("-" * 20)

if __name__ == "__main__":
    asyncio.run(setup_users())
