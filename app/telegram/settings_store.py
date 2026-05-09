from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, User

ACTIVE_TELEGRAM_USER_ID_KEY = "active_telegram_user_id"


async def get_active_telegram_user_id(db: AsyncSession) -> int | None:
    setting = await db.get(AppSettings, ACTIVE_TELEGRAM_USER_ID_KEY)
    if setting is None or not setting.value:
        return None
    try:
        return int(setting.value)
    except ValueError:
        return None


async def set_active_telegram_user_id(db: AsyncSession, user_id: int | None) -> None:
    setting = await db.get(AppSettings, ACTIVE_TELEGRAM_USER_ID_KEY)
    if user_id is None:
        if setting is not None:
            await db.delete(setting)
        return

    if setting is None:
        db.add(AppSettings(key=ACTIVE_TELEGRAM_USER_ID_KEY, value=str(user_id)))
        return

    setting.value = str(user_id)


async def get_active_telegram_user(db: AsyncSession) -> User | None:
    user_id = await get_active_telegram_user_id(db)
    if user_id is None:
        return None

    user = await db.get(User, user_id)
    if user is None or not user.telegram_bot_token:
        return None
    return user


async def update_user_chat_id_by_bot_token(
    db: AsyncSession,
    bot_token: str,
    chat_id: str,
) -> bool:
    result = await db.execute(
        select(User).where(User.telegram_bot_token == bot_token)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False

    user.telegram_chat_id = chat_id
    return True