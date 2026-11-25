"""Batas akses dokumen untuk pencatatan kronologi dan lampirannya."""
from fastapi import HTTPException
from sqlmodel import Session

from app.models.dokumen import DokumenPerencanaan
from app.models.user import User


def require_document_access(session: Session, user: User, document_id: int):
    document = session.get(DokumenPerencanaan, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
    allowed = user.is_admin or (
        document.is_active and (
            (user.is_user_bidang and document.opd_id is None)
            or (user.is_user_opd and user.opd_id is not None and document.opd_id == user.opd_id)
        )
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Dokumen di luar cakupan akses pengguna")
    return document
