# app/web/auth_router.py
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserSession
from app.web.auth import (
    clear_session_cookie,
    generate_session_token,
    get_current_user,
    set_session_cookie,
)
from app.web.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: User | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse(url="/", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request, "auth/login.html", {"request": request, "error": None}
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not user.check_password(password):
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/login.html",
            {"request": request, "error": "Неверное имя пользователя или пароль"},
            status_code=401,
        )

    token = generate_session_token()
    db.add(UserSession(user_id=user.id, token=token))
    await db.commit()

    response = RedirectResponse(url="/", status_code=303)
    set_session_cookie(response, token)
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, user: User | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse(url="/", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request, "auth/register.html", {"request": request, "error": None}
    )


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    if len(username) < 3:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "Имя пользователя минимум 3 символа"},
        )

    if len(password) < 4:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "Пароль минимум 4 символа"},
        )

    if password != password_confirm:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "Пароли не совпадают"},
        )

    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none() is not None:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "Это имя уже занято"},
        )

    user = User(username=username, password_hash="", password_salt="")
    user.set_password(password)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = generate_session_token()
    db.add(UserSession(user_id=user.id, token=token))
    await db.commit()

    response = RedirectResponse(url="/", status_code=303)
    set_session_cookie(response, token)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    token = request.cookies.get("session_token")
    if token:
        result = await db.execute(
            select(UserSession).where(UserSession.token == token)
        )
        session = result.scalar_one_or_none()
        if session:
            await db.delete(session)
            await db.commit()

    response = RedirectResponse(url="/login", status_code=303)
    clear_session_cookie(response)
    return response
