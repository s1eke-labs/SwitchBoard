from __future__ import annotations

import base64
import hashlib
import hmac
import time

from fastapi import HTTPException, Request, Response, status

from config import Settings


def _signature(settings: Settings, issued_at: int) -> str:
    message = str(issued_at).encode("utf-8")
    digest = hmac.new(settings.app_password.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def make_session_cookie(settings: Settings) -> str:
    issued_at = int(time.time())
    return f"{issued_at}.{_signature(settings, issued_at)}"


def verify_session_cookie(settings: Settings, value: str | None) -> bool:
    if not value or "." not in value:
        return False
    issued_raw, sig = value.split(".", 1)
    try:
        issued_at = int(issued_raw)
    except ValueError:
        return False
    if issued_at + settings.cookie_max_age_seconds < time.time():
        return False
    return hmac.compare_digest(sig, _signature(settings, issued_at))


def set_login_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        settings.cookie_name,
        make_session_cookie(settings),
        max_age=settings.cookie_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def clear_login_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.cookie_name,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def require_auth(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if not verify_session_cookie(settings, request.cookies.get(settings.cookie_name)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
