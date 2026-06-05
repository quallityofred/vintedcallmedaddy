from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseTemporarilyUnavailable, run_db_with_retry
from app.models import User, UserSession
from app.web.auth import clear_session_cookie, generate_session_token, get_current_user, set_session_cookie
from app.web.csrf import API_CSRF_COOKIE, api_csrf_token_for_request, csrf_token_for_session, require_api_csrf
from app.web.dependencies import get_db
from app.web.invite_codes import consume_invite_code

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=150)
    password: str = Field(..., min_length=4, max_length=256)
    password_confirm: str = Field(..., min_length=4, max_length=256)
    invite_code: str = Field(..., min_length=1, max_length=256)


def _user_payload(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
    }


def _session_response(user: User, session_token: str, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(
        {
            "user": _user_payload(user),
            "csrf_token": csrf_token_for_session(session_token),
        },
        status_code=status_code,
    )
    set_session_cookie(response, session_token)
    response.delete_cookie(API_CSRF_COOKIE)
    return response


async def _run_auth_api_operation(db: AsyncSession, operation, *, operation_name: str):
    try:
        return await run_db_with_retry(db, operation, operation_name=operation_name)
    except DatabaseTemporarilyUnavailable as exc:
        raise HTTPException(status_code=503, detail="Database temporarily unavailable") from exc


async def _create_login_session(
    db: AsyncSession,
    *,
    username: str,
    password: str,
) -> tuple[User, str]:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not user.check_password(password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    session_token = generate_session_token()
    db.add(UserSession(user_id=user.id, token=session_token))
    await db.commit()
    return user, session_token


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
    user, session_token = await _run_auth_api_operation(
        db,
        lambda active_db: _create_login_session(
            active_db,
            username=username,
            password=request.password,
        ),
        operation_name="login",
    )

    return _session_response(user, session_token)


@router.post("/register", dependencies=[Depends(require_api_csrf)])
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    username = request.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=422, detail="Username must be at least 3 characters")
    if request.password != request.password_confirm:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    async def create_registered_user(active_db: AsyncSession) -> tuple[User, str]:
        existing = await active_db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Username is not available")

        code_obj = await consume_invite_code(active_db, request.invite_code)
        if code_obj is None:
            raise HTTPException(status_code=400, detail="Invalid or used invite code")

        user = User(
            username=username,
            password_hash="",
            password_salt="",
            invite_code_id=code_obj.id,
        )
        user.set_password(request.password)
        active_db.add(user)

        try:
            await active_db.flush()
            session_token = generate_session_token()
            active_db.add(UserSession(user_id=user.id, token=session_token))
            await active_db.commit()
        except IntegrityError:
            await active_db.rollback()
            raise HTTPException(status_code=409, detail="Username is not available") from None

        await active_db.refresh(user)
        return user, session_token

    user, session_token = await _run_auth_api_operation(
        db,
        create_registered_user,
        operation_name="register",
    )
    return _session_response(user, session_token, status_code=201)


@router.post("/logout", dependencies=[Depends(require_api_csrf)])
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async def delete_session(active_db: AsyncSession) -> None:
        result = await active_db.execute(select(UserSession).where(UserSession.token == session_token))
        session = result.scalar_one_or_none()
        if session is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        await active_db.delete(session)
        await active_db.commit()

    await _run_auth_api_operation(db, delete_session, operation_name="logout")

    response = JSONResponse({"status": "ok"})
    clear_session_cookie(response)
    response.delete_cookie(API_CSRF_COOKIE)
    return response
