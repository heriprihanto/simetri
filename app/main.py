"""
SIMETRI — Sistem Informasi Memori dan Riwayat Perencanaan Pembangunan Daerah
Badan Perencanaan Pembangunan Daerah (Bappeda) Kota Tegal

Main FastAPI Application Entrypoint.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

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
    pagu,
    lampiran,
    users,
    audit,
    whatsapp,
    chatbot,
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
    lifespan=lifespan,
    root_path=settings.ROOT_PATH,
)

# Uvicorn handles forwarded headers only from FORWARDED_ALLOW_IPS.
# Normalize stripped paths too, including the scope used by mounted StaticFiles.
@app.middleware("http")
async def normalize_proxy_path(request: Request, call_next):
    prefix = settings.ROOT_PATH
    path = request.scope["path"]
    if prefix and path != prefix and not path.startswith(prefix + "/"):
        request.scope["path"] = prefix + path
        request.scope["raw_path"] = prefix.encode() + request.scope.get("raw_path", path.encode())
    return await call_next(request)


app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Centralized Templates
from app.templates_config import templates

# Register each route once; root_path supplies the public prefix.
routers = [
    auth.router,
    kronologi.router,
    dokumen.router,
    arsip.router,
    agenda.router,
    pagu.router,
    lampiran.router,
    users.router,
    audit.router,
    whatsapp.router,
    chatbot.router,
]

for r in routers:
    app.include_router(r)


@app.get("/")
async def root(request: Request):
    """Fallback handler ke halaman utama (kronologi)."""
    target = settings.url_path("/kronologi", request)
    return RedirectResponse(
        url=target,
        status_code=302,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    """Redirect ke login jika tidak terotentikasi."""
    login_url = settings.url_path("/login", request)
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            content=f'<script>window.location.href="{login_url}";</script>',
            status_code=200,
            headers={"HX-Redirect": login_url},
        )
    return RedirectResponse(
        url=login_url,
        status_code=302,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


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
