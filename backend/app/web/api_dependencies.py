from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.web.auth import get_current_user
from app.web.dependencies import get_db


from app.config import get_settings


async def require_api_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    # API Key Fallback
    settings = get_settings()
    api_key = request.headers.get("X-API-Key")
    if settings.diagnostic_api_key and api_key == settings.diagnostic_api_key:
        # Return a mock admin user if API key matches
        return User(id=0, username="api_key_admin", is_admin=True)

    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def require_api_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await require_api_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
