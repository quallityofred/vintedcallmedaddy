from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Monitor, User, FoundItem, HiddenSeller
from app.web.auth import get_current_user
from app.web.csrf import require_csrf
from app.web.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["items"])


# ---------------------------------------------------------------------------
# Found Items
# ---------------------------------------------------------------------------

class FoundItemResponse(BaseModel):
    id: int
    monitor_id: int
    vinted_item_id: int
    domain: str
    title: str
    price: float
    currency: str
    brand: str
    size: str
    condition: str
    photo_url: str
    item_url: str
    seller_id: int
    found_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ItemsListResponse(BaseModel):
    items: List[FoundItemResponse]
    limit: int
    offset: int
    total: int


async def require_api_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/items", response_model=ItemsListResponse)
async def list_items(
    monitor_id: Optional[int] = None,
    domain: Optional[str] = None,
    seller_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """List found items for the current user's monitors."""
    base_stmt = select(FoundItem).join(Monitor).where(Monitor.user_id == user.id)
    
    if monitor_id:
        base_stmt = base_stmt.where(FoundItem.monitor_id == monitor_id)
    if domain:
        base_stmt = base_stmt.where(FoundItem.domain == domain)
    if seller_id:
        base_stmt = base_stmt.where(FoundItem.seller_id == seller_id)

    # Count
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Data
    stmt = base_stmt.order_by(FoundItem.found_at.desc()).limit(limit).offset(offset)
    items = (await db.execute(stmt)).scalars().all()
    
    return {
        "items": items,
        "limit": limit,
        "offset": offset,
        "total": total
    }


@router.get("/items/{item_id}", response_model=FoundItemResponse)
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Get item details, scoped by monitor ownership."""
    stmt = (
        select(FoundItem)
        .join(Monitor)
        .where(FoundItem.id == item_id, Monitor.user_id == user.id)
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


# ---------------------------------------------------------------------------
# Hidden Sellers
# ---------------------------------------------------------------------------

class HiddenSellerResponse(BaseModel):
    seller_id: int
    hidden_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HiddenSellerCreate(BaseModel):
    seller_id: int
    # seller_name/domain are accepted for compatibility but not stored
    seller_name: Optional[str] = None
    domain: Optional[str] = None


@router.get("/hidden-sellers", response_model=List[HiddenSellerResponse])
async def list_hidden_sellers(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """List all hidden sellers for the current user."""
    result = await db.execute(
        select(HiddenSeller).where(HiddenSeller.user_id == user.id).order_by(HiddenSeller.hidden_at.desc())
    )
    return result.scalars().all()


@router.post("/hidden-sellers", response_model=HiddenSellerResponse, dependencies=[Depends(require_csrf)])
async def add_hidden_seller(
    data: HiddenSellerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Hide a seller for the current user (idempotent)."""
    # Check if already hidden
    result = await db.execute(
        select(HiddenSeller).where(HiddenSeller.user_id == user.id, HiddenSeller.seller_id == data.seller_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Seller already hidden")

    hidden = HiddenSeller(user_id=user.id, seller_id=data.seller_id)
    db.add(hidden)
    await db.commit()
    await db.refresh(hidden)
    return hidden


@router.delete("/hidden-sellers/{seller_id}", status_code=204, dependencies=[Depends(require_csrf)])
async def remove_hidden_seller(
    seller_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_user),
):
    """Unhide a seller for the current user."""
    stmt = delete(HiddenSeller).where(HiddenSeller.user_id == user.id, HiddenSeller.seller_id == seller_id)
    result = await db.execute(stmt)
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Hidden seller not found")
    
    return None
