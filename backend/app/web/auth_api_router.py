from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserSession
from app.web.auth import clear_session_cookie, generate_session_token, get_current_user, set_session_cookie
from app.web.csrf import API_CSRF_COOKIE, api_csrf_token_for_request, csrf_token_for_session, require_api_csrf
from app.web.dependencies import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1, max_length=256)


def _user_payload(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
    }


@router.get("/csrf")
async def csrf(request: Request, response: Response):
    return {"csrf_token": api_csrf_token_for_request(request, response)}


@router.get("/me")
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user": _user_payload(user)}


@router.post("/login", dependencies=[Depends(require_api_csrf)])
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    username = request.username.strip()
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not user.check_password(request.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    session_token = generate_session_token()
    db.add(UserSession(user_id=user.id, token=session_token))
    await db.commit()

    response = JSONResponse(
        {
            "user": _user_payload(user),
            "csrf_token": csrf_token_for_session(session_token),
        }
    )
    set_session_cookie(response, session_token)
    response.delete_cookie(API_CSRF_COOKIE)
    return response


@router.post("/logout", dependencies=[Depends(require_api_csrf)])
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(select(UserSession).where(UserSession.token == session_token))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await db.delete(session)
    await db.commit()

    response = JSONResponse({"status": "ok"})
    clear_session_cookie(response)
    response.delete_cookie(API_CSRF_COOKIE)
    return response
