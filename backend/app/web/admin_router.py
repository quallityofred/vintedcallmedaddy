
from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def legacy_admin_disabled(path: str):
    raise HTTPException(status_code=404, detail="Legacy admin route disabled.")
