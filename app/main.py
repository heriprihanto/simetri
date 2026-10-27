"""
SIMETRI — Sistem Informasi Memori dan Riwayat Perencanaan Pembangunan Daerah
Badan Perencanaan Pembangunan Daerah (Bappeda) Kota Tegal

Main FastAPI Application Entrypoint.
"""

import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import engine
from sqlmodel import SQLModel
import app.models  # noqa: F401

from app.routers import (
    auth,
    kronologi,
    dokumen,
    arsip,
    agenda,
    lampiran,
    users,
    audit,
    whatsapp,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events: startup & shutdown."""
    # Ensure static directories exist
    os.makedirs("app/static/css", exist_ok=True)
    os.makedirs("app/static/js", exist_ok=True)
    os.makedirs("app/static/img", exist_ok=True)
    os.makedirs("uploads", exist_ok=True)

    # Ensure database tables exist
    SQLModel.metadata.create_all(engine)

    yield


app = FastAPI(
    title="SIMETRI Bappeda Kota Tegal",
    description="Sistem Informasi Memori dan Riwayat Perencanaan Pembangunan Daerah",
    version="1.0.0",
    root_path=settings.ROOT_PATH,
    lifespan=lifespan,
)

# Reverse proxy headers middleware (trust forwarded proto & for)
try:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
except ImportError:
    pass

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Centralized Templates
from app.templates_config import templates

# Register Routers
app.include_router(auth.router)
app.include_router(kronologi.router)
app.include_router(dokumen.router)
app.include_router(arsip.router)
app.include_router(agenda.router)
app.include_router(lampiran.router)
app.include_router(users.router)
app.include_router(audit.router)
app.include_router(whatsapp.router)


@app.get("/")
async def root():
    """Redirect ke halaman utama (kronologi)."""
    return RedirectResponse(url=settings.url_path("/kronologi"))


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    """Redirect ke login jika tidak terotentikasi."""
    login_url = settings.url_path("/login")
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            content=f'<script>window.location.href="{login_url}";</script>',
            status_code=200,
            headers={"HX-Redirect": login_url},
        )
    return RedirectResponse(url=login_url)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    """Tampilkan halaman atau pesan Forbidden."""
    return HTMLResponse(
        content="<h2 style='text-align:center;margin-top:50px;font-family:sans-serif;'>403 — Anda tidak memiliki akses ke halaman ini.</h2>",
        status_code=403,
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Tampilkan halaman 404."""
    return HTMLResponse(
        content="<h2 style='text-align:center;margin-top:50px;font-family:sans-serif;'>404 — Halaman tidak ditemukan.</h2>",
        status_code=404,
    )
