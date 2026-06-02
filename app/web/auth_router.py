# app/web/auth_router.py
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InviteCode, User, UserSession
from app.web.auth import (
    clear_session_cookie,
    generate_session_token,
    get_current_user,
    set_session_cookie,
)
from app.web.csrf import require_csrf
from app.web.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


async def consume_invite_code(db: AsyncSession, code: str) -> InviteCode | None:
    normalized = code.strip()
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(InviteCode)
        .where(
            InviteCode.code == normalized,
            InviteCode.is_active == True,  # noqa: E712
            InviteCode.used_count < InviteCode.max_uses,
            or_(InviteCode.expires_at.is_(None), InviteCode.expires_at > now),
        )
        .values(used_count=InviteCode.used_count + 1)
    )
    if result.rowcount != 1:
        return None

    code_result = await db.execute(select(InviteCode).where(InviteCode.code == normalized))
    return code_result.scalar_one()


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
            {"request": request, "error": "РќРµРІРµСЂРЅРѕРµ РёРјСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РёР»Рё РїР°СЂРѕР»СЊ"},
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
    invite_code: str = Form(...),
):
    if len(username) < 3:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "РРјСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РјРёРЅРёРјСѓРј 3 СЃРёРјРІРѕР»Р°"},
        )

    if len(password) < 4:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "РџР°СЂРѕР»СЊ РјРёРЅРёРјСѓРј 4 СЃРёРјРІРѕР»Р°"},
        )

    if password != password_confirm:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "РџР°СЂРѕР»Рё РЅРµ СЃРѕРІРїР°РґР°СЋС‚"},
        )

    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none() is not None:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "Р­С‚Рѕ РёРјСЏ СѓР¶Рµ Р·Р°РЅСЏС‚Рѕ"},
        )

    code_obj = await consume_invite_code(db, invite_code)
    if not code_obj:
        return request.app.state.templates.TemplateResponse(
            request,
            "auth/register.html",
            {"request": request, "error": "РќРµРІРµСЂРЅС‹Р№ РёР»Рё РёСЃРїРѕР»СЊР·РѕРІР°РЅРЅС‹Р№ РёРЅРІР°Р№С‚-РєРѕРґ"},
        )


    user = User(
        username=username, 
        password_hash="", 
        password_salt="",
        invite_code_id=code_obj.id
    )
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


@router.post("/logout", dependencies=[Depends(require_csrf)])
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
