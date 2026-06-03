
from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def legacy_auth_disabled(path: str):
    raise HTTPException(status_code=404, detail="Legacy auth route disabled.")
