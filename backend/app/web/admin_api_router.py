from __future__ import annotations

import secrets
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InviteCode
from app.web.csrf import require_csrf
from app.web.dependencies import get_db, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class InviteCodeResponse(BaseModel):
    id: int
    code: str
    is_active: bool
    max_uses: int
    used_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InviteCodeCreate(BaseModel):
    code: str = ""
    max_uses: int = 1


@router.get("/invites", response_model=List[InviteCodeResponse])
async def list_invites(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """List all invite codes."""
    result = await db.execute(select(InviteCode).order_by(InviteCode.created_at.desc()))
    return result.scalars().all()


@router.post("/invites", response_model=InviteCodeResponse, dependencies=[Depends(require_csrf)])
async def create_invite(
    data: InviteCodeCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Create a new invite code."""
    code = data.code.strip() or secrets.token_urlsafe(12)
    max_uses = max(1, min(data.max_uses, 1000))

    existing = await db.execute(select(InviteCode).where(InviteCode.code == code))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Invite code already exists")

    invite = InviteCode(
        code=code,
        max_uses=max_uses,
        used_count=0,
        is_active=True,
        created_by_id=user.id,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite


@router.delete("/invites/{invite_id}", status_code=204, dependencies=[Depends(require_csrf)])
async def delete_invite(
    invite_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Delete/revoke an invite code."""
    invite = await db.get(InviteCode, invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite code not found")

    await db.delete(invite)
    await db.commit()
    return None


@router.get("/logs")
async def get_admin_logs(_user=Depends(require_admin)):
    """Placeholder for admin logs."""
    return {"message": "Logs access is restricted for security."}
