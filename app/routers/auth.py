"""
Router Autentikasi — Google OAuth 2.0 login/callback/logout.
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlmodel import Session, select

from app.config import get_settings
from app.templates_config import templates
from app.database import get_session
from app.models.user import User
from app.middleware import (
    get_current_user,
    set_session_cookie,
    clear_session_cookie,
)
from app.services.audit_service import log_activity

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Halaman login."""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url=settings.url_path("/kronologi", request), status_code=302)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"title": "Login"},
    )


@router.get("/auth/dev-login")
async def dev_login(request: Request, session: Session = Depends(get_session)):
    """Auto-login untuk development/testing."""
    user = session.exec(select(User).where(User.role == "admin")).first()
    if not user:
        user = session.exec(select(User)).first()
    response = RedirectResponse(url=settings.url_path("/kronologi", request), status_code=302)
    set_session_cookie(response, user)
    return response


async def _handle_oauth_code(request: Request, code: str, session: Session) -> RedirectResponse:
    """Tukar auth code dengan token Google, validasi whitelist, dan buat session."""
    try:
        # Gunakan redirect URI yang terkonfigurasi
        redirect_uri = settings.GOOGLE_REDIRECT_URI

        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_data = token_resp.json()

            if "error" in token_data:
                logger.error("Google OAuth token error: %s", token_data)
                return RedirectResponse(
                    url=settings.url_path("/login?error=token_error", request), status_code=302
                )

            # Ambil profil user dari Google
            access_token = token_data.get("access_token")
            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo = userinfo_resp.json()
    except Exception as e:
        logger.error("OAuth exchange exception: %s", e)
        return RedirectResponse(url=settings.url_path("/login?error=oauth_error", request), status_code=302)

    email = userinfo.get("email", "").lower().strip()
    if not email:
        return RedirectResponse(url=settings.url_path("/login?error=no_email", request), status_code=302)

    # Cek apakah email terdaftar di whitelist
    stmt = select(User).where(User.email == email)
    user = session.exec(stmt).first()

    if not user:
        logger.warning("Login ditolak: %s tidak terdaftar di whitelist", email)
        return RedirectResponse(
            url=settings.url_path("/login?error=not_registered", request), status_code=302
        )

    if not user.is_active:
        logger.warning("Login ditolak: %s akun dinonaktifkan", email)
        return RedirectResponse(
            url=settings.url_path("/login?error=inactive", request), status_code=302
        )

    # Update nama & foto avatar dari Google jika ada
    if userinfo.get("name"):
        user.name = userinfo["name"]
    if userinfo.get("picture"):
        user.avatar = userinfo["picture"]
    session.add(user)
    session.commit()
    session.refresh(user)

    # Log aktivitas login
    log_activity(
        db=session,
        action="LOGIN",
        entity="auth",
        entity_id=user.id,
        description=f"Pengguna {user.display_name} ({user.email}) berhasil masuk via Google OAuth",
        user=user,
        request=request,
    )

    # Redirect ke halaman utama dengan cookie session
    response = RedirectResponse(url=settings.url_path("/kronologi", request), status_code=302)
    set_session_cookie(response, user)

    logger.info("Login berhasil: %s (%s)", user.name, user.email)
    return response


@router.get("/auth/google")
async def google_login(
    request: Request,
    code: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """
    Jika ada 'code', ini adalah callback dari Google.
    Jika tidak ada 'code', redirect user ke Google consent page.
    """
    if code:
        return await _handle_oauth_code(request, code, session)

    # Inisiasi OAuth consent screen
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    url = GOOGLE_AUTH_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url=url)


@router.get("/oauthcallback")
async def google_callback(
    request: Request,
    code: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Fallback callback jika Google redirect ke /oauthcallback."""
    if not code:
        return RedirectResponse(url=settings.url_path("/login?error=no_code", request), status_code=302)
    return await _handle_oauth_code(request, code, session)


@router.get("/logout")
async def logout(request: Request):
    """Logout dan hapus session cookie."""
    response = RedirectResponse(url=settings.url_path("/login", request), status_code=302)
    clear_session_cookie(response)
    return response
