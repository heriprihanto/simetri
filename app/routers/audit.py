"""
Router Audit Trail — Melihat rekam jejak aktivitas pengguna (Admin only).
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, desc

from app.database import get_db
from app.middleware import require_admin
from app.models.user import User
from app.models.audit import AuditLog

router = APIRouter(prefix="/admin/audit", tags=["admin-audit"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_audit(
    request: Request,
    action: Optional[str] = None,
    entity: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=10, le=100),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Halaman daftar audit log dengan filter dan pagination."""
    query = select(AuditLog)

    if action:
        query = query.where(AuditLog.action == action)
    if entity:
        query = query.where(AuditLog.entity == entity)

    # Total count
    total_logs = len(db.exec(query).all())

    # Paginated logs
    offset = (page - 1) * limit
    logs = db.exec(query.order_by(desc(AuditLog.id)).offset(offset).limit(limit)).all()
    total_pages = (total_logs + limit - 1) // limit or 1

    return templates.TemplateResponse(
        request=request,
        name="admin/audit.html",
        context={
            "user": current_user,
            "logs": logs,
            "current_action": action or "",
            "current_entity": entity or "",
            "page": page,
            "limit": limit,
            "total_logs": total_logs,
            "total_pages": total_pages,
            "page_title": "Audit Trail - SIMETRI",
        },
    )
