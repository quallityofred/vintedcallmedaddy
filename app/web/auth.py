# app/web/auth.py
import secrets

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserSession
from app.web.dependencies import get_db

SESSION_COOKIE = "session_token"
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 days


def generate_session_token() -> str:
    return secrets.token_hex(32)


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    result = await db.execute(
        select(UserSession).where(UserSession.token == token)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    user_result = await db.execute(
        select(User).where(User.id == session.user_id)
    )
    return user_result.scalar_one_or_none()


async def require_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    user = await get_current_user(request, db)
    if user is None:
        raise RequireLoginException()
    return user


async def require_admin(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    user = await require_user(request, db)
    if not user.is_admin:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Доступ запрещен: требуются права администратора")
    return user


class RequireLoginException(Exception):
    pass


def set_session_cookie(response: RedirectResponse, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(SESSION_COOKIE)
