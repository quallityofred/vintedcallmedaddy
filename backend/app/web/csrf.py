from __future__ import annotations

import hmac
import os
from hashlib import sha256

from fastapi import HTTPException, Request

from app.config import get_settings
CSRF_FIELD = "_csrf_token"
CSRF_HEADER = "X-CSRF-Token"
SESSION_COOKIE = "session_token"


def _csrf_secret() -> str:
    settings = get_settings()
    return settings.secret_key or "development-csrf-secret"


def csrf_token_for_session(session_token: str | None) -> str:
    if not session_token:
        return ""
    return hmac.new(
        _csrf_secret().encode("utf-8"),
        session_token.encode("utf-8"),
        sha256,
    ).hexdigest()


def csrf_token_for_request(request: Request) -> str:
    return csrf_token_for_session(request.cookies.get(SESSION_COOKIE))


async def require_csrf(request: Request) -> None:
    session_token = request.cookies.get(SESSION_COOKIE)
    expected = csrf_token_for_session(session_token)
    if not expected:
        raise HTTPException(status_code=403, detail="Missing CSRF token")

    submitted = (
        request.headers.get(CSRF_HEADER)
        or request.headers.get("X-CSRFToken")
        or request.query_params.get(CSRF_FIELD)
    )
    if not submitted:
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.form()
            value = form.get(CSRF_FIELD)
            submitted = str(value) if value is not None else None

    if not submitted or not hmac.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def secure_cookie_required() -> bool:
    settings = get_settings()
    if settings.session_cookie_secure:
        return True
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER"))
