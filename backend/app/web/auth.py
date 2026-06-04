# app/web/auth.py
import secrets
import os
import logging

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserSession
from app.config import get_settings
from app.database import is_db_disconnect_error
from app.web.dependencies import get_db

SESSION_COOKIE = "session_token"
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 days
logger = logging.getLogger(__name__)


def generate_session_token() -> str:
    return secrets.token_hex(32)


async def _execute_auth_query(db: AsyncSession, statement):
    for attempt in range(2):
        try:
            return await db.execute(statement)
        except DBAPIError as exc:
            if not is_db_disconnect_error(exc):
                raise
            try:
                await db.rollback()
            except Exception:
                logger.debug("Auth DB rollback after disconnect failed", exc_info=True)
            if attempt == 0:
                logger.warning("Retrying auth query after database disconnect")
                continue
            logger.warning("Auth query failed after database disconnect retry")
            raise HTTPException(status_code=503, detail="Database temporarily unavailable") from exc


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    result = await _execute_auth_query(
        db,
        select(UserSession).where(UserSession.token == token)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    user_result = await _execute_auth_query(
        db,
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


def _secure_cookie_required() -> bool:
    settings = get_settings()
    if settings.session_cookie_secure:
        return True
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER"))


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie_required(),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)
