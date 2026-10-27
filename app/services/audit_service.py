"""
Audit Service — mencatat setiap aktivitas pengguna ke database.
"""

import json
from datetime import datetime
from typing import Any, Optional
from fastapi import Request
from sqlmodel import Session
from app.models.audit import AuditLog
from app.models.user import User


def log_activity(
    db: Session,
    action: str,  # "LOGIN", "LOGOUT", "CREATE", "UPDATE", "DELETE", "UPLOAD"
    entity: str,  # "kejadian", "dokumen", "surat", "agenda", "lampiran", "user"
    entity_id: str | int = "",
    description: str = "",
    user: Optional[User] = None,
    request: Optional[Request] = None,
    details: Optional[dict[str, Any]] = None,
) -> AuditLog:
    """Helper untuk menyimpan entri audit log."""
    ip_address = ""
    user_agent = ""

    if request:
        ip_address = request.client.host if request.client else ""
        user_agent = request.headers.get("user-agent", "")

    details_str = json.dumps(details, default=str) if details else ""

    audit = AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else "",
        user_name=user.name if user else "",
        user_bidang=user.bidang if user else "",
        action=action,
        entity=entity,
        entity_id=str(entity_id),
        description=description,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details_str,
        created_at=datetime.now(),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit
