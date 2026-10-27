"""
Middleware autentikasi: session JWT via cookie.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from functools import wraps

import jwt
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.models.user import User

settings = get_settings()
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # 7 hari
COOKIE_NAME = "simetri_session"


def create_token(user_id: int, email: str) -> str:
    """Buat JWT token untuk session."""
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode JWT token, return None jika invalid/expired."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def get_current_user(request: Request) -> Optional[User]:
    """Ambil user yang sedang login dari session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    payload = decode_token(token)
    if not payload:
        return None

    user_id = int(payload.get("sub", 0))
    if not user_id:
        return None

    with Session(engine) as session:
        user = session.get(User, user_id)
        if user and user.is_active:
            if user.opd_id:
                _ = user.opd
            session.expunge_all()
            return user

    return None


def set_session_cookie(response, user: User) -> str:
    """Set JWT session cookie pada response."""
    token = create_token(user.id, user.email)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRY_HOURS * 3600,
        secure=settings.COOKIE_SECURE,
        path="/",
    )
    return token


def clear_session_cookie(response):
    """Hapus session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")


def require_login(request: Request) -> User:
    """Dependency: pastikan user sudah login, redirect ke /login jika belum."""
    user = get_current_user(request)
    if not user:
        login_url = settings.url_path("/login")
        raise HTTPException(status_code=302, headers={"Location": login_url})
    return user


def require_admin(request: Request) -> User:
    """Dependency: pastikan user adalah admin."""
    user = require_login(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Akses ditolak. Hanya admin.")
    return user


def require_admin_or_bidang(request: Request) -> User:
    """Dependency: pastikan user adalah admin atau staf bidang Bappeda."""
    user = require_login(request)
    if not (user.is_admin or user.is_user_bidang):
        raise HTTPException(
            status_code=403,
            detail="Akses ditolak. Hanya admin atau user bidang Bappeda.",
        )
    return user
