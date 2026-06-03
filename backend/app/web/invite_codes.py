from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InviteCode


async def consume_invite_code(db: AsyncSession, code: str) -> InviteCode | None:
    invite_code = code.strip()
    if not invite_code:
        return None

    now = datetime.now(timezone.utc)
    dialect_name = db.bind.dialect.name if db.bind is not None else ""

    if dialect_name == "postgresql":
        stmt = (
            update(InviteCode)
            .where(
                InviteCode.code == invite_code,
                InviteCode.is_active == True,  # noqa: E712
                InviteCode.used_count < InviteCode.max_uses,
                ((InviteCode.expires_at == None) | (InviteCode.expires_at > now)),  # noqa: E711
            )
            .values(used_count=InviteCode.used_count + 1)
            .returning(InviteCode)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    result = await db.execute(select(InviteCode).where(InviteCode.code == invite_code))
    invite = result.scalar_one_or_none()
    if invite is None or not invite.is_valid:
        return None
    invite.used_count += 1
    return invite
