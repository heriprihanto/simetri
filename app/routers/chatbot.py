"""
Router Chatbot SIMETRI — Halaman chatbot dan API endpoint.
Menyediakan antarmuka percakapan berbasis AI untuk mencari dan memahami
data arsip, kronologi kejadian, dokumen perencanaan, dan agenda.
"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from sqlmodel import Session

from app.database import engine
from app.middleware import require_login
from app.models.user import User
from app.services.chatbot_service import process_chat_message, retrieve_summary_stats
from app.templates_config import templates
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(tags=["chatbot"])


@router.get("/chatbot", response_class=HTMLResponse)
async def chatbot_page(request: Request, user: User = Depends(require_login)):
    """Render halaman chatbot SIMETRI."""
    with Session(engine) as session:
        stats = retrieve_summary_stats(session, user)

    return templates.TemplateResponse(
        request=request,
        name="chatbot/index.html",
        context={
            "user": user,
            "title": "Chatbot SIMETRI",
            "page_title": "Chatbot Asisten SIMETRI",
            "stats": stats,
            "gemini_model": settings.GEMINI_MODEL,
        },
    )


@router.post("/api/chatbot")
async def chatbot_api(request: Request, user: User = Depends(require_login)):
    """API endpoint untuk proses pesan chatbot."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "reply": "Format request tidak valid."},
        )

    question = body.get("message", "").strip()
    conversation_history = body.get("history", [])

    if not question:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "reply": "Pesan tidak boleh kosong."},
        )

    with Session(engine) as session:
        result = await process_chat_message(
            question=question,
            user=user,
            session=session,
            conversation_history=conversation_history,
        )

    return JSONResponse(content=result)
