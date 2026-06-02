from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InviteCode, User
from app.web.csrf import require_csrf
from app.web.dependencies import get_db, require_admin

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _generate_invite_code() -> str:
    return secrets.token_urlsafe(12)


@router.get("/invites", response_class=HTMLResponse)
async def admin_invites_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    result = await db.execute(select(InviteCode).order_by(InviteCode.created_at.desc()))
    invites = result.scalars().all()
    return _templates(request).TemplateResponse(
        request,
        "admin/invites.html",
        {"request": request, "user": user, "invites": invites},
    )


@router.post("/invites", dependencies=[Depends(require_csrf)])
async def admin_create_invite(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    code: str = Form(default=""),
    max_uses: int = Form(default=1),
):
    value = code.strip() or _generate_invite_code()
    max_uses = max(1, min(max_uses, 1000))

    existing = await db.execute(select(InviteCode).where(InviteCode.code == value))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Invite code already exists")

    db.add(
        InviteCode(
            code=value,
            max_uses=max_uses,
            used_count=0,
            is_active=True,
            created_by_id=user.id,
        )
    )
    await db.commit()
    return RedirectResponse(url="/admin/invites", status_code=303)


@router.post("/invites/{invite_id}/toggle", dependencies=[Depends(require_csrf)])
async def admin_toggle_invite(
    invite_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    invite = await db.get(InviteCode, invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite code not found")

    invite.is_active = not invite.is_active
    await db.commit()
    return RedirectResponse(url="/admin/invites", status_code=303)


@router.delete("/invites/{invite_id}", dependencies=[Depends(require_csrf)])
async def admin_delete_invite(
    invite_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    invite = await db.get(InviteCode, invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite code not found")

    await db.delete(invite)
    await db.commit()
    return Response(status_code=204)
