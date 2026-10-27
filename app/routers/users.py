"""
Router Manajemen Pengguna — Whitelist pengguna Google OAuth (Admin only).
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, desc

from app.database import get_db
from app.middleware import require_admin
from app.models.user import User, TaOpd
from app.models.master import MasterBidang
from app.services.audit_service import log_activity
from app.config import get_settings

from sqlalchemy import text

settings = get_settings()
router = APIRouter(prefix="/admin/users", tags=["admin-users"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Halaman daftar pengguna (whitelist)."""
    users = db.exec(select(User).order_by(desc(User.id))).all()
    opd_list = db.exec(select(TaOpd).where(TaOpd.aktif == 1).order_by(TaOpd.nama_pd)).all()
    bidang_list = db.exec(select(MasterBidang).order_by(MasterBidang.nama)).all()

    opd_map = {opd.id_sub_pd: opd.nama_pd for opd in opd_list}
    bidang_map = {b.kode: b.nama for b in bidang_list}

    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "user": current_user,
            "users": users,
            "opd_list": opd_list,
            "bidang_list": bidang_list,
            "opd_map": opd_map,
            "bidang_map": bidang_map,
            "page_title": "Manajemen Pengguna - SIMETRI",
        },
    )


@router.post("/simpan")
async def save_user(
    request: Request,
    id: Optional[int] = Form(None),
    email: str = Form(...),
    name: str = Form(""),
    no_hp: str = Form(""),
    role: str = Form("user_bidang"),
    bidang: str = Form(""),
    opd_id: Optional[str] = Form(None),
    is_active: bool = Form(True),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Tambah atau ubah pengguna whitelist."""
    parsed_opd_id = int(opd_id) if opd_id and opd_id.isdigit() else None
    email_clean = email.strip().lower()
    no_hp_clean = no_hp.strip()
    bidang_clean = bidang.strip() if role in ("user_bidang", "admin") else ""

    if id:
        user_obj = db.get(User, id)
        if not user_obj:
            raise HTTPException(status_code=404, detail="User tidak ditemukan")
        user_obj.email = email_clean
        user_obj.name = name.strip()
        user_obj.no_hp = no_hp_clean
        user_obj.role = role
        user_obj.bidang = bidang_clean
        user_obj.opd_id = parsed_opd_id if role == "user_opd" else None
        user_obj.is_active = is_active
        user_obj.updated_at = datetime.now()
        action = "UPDATE"
    else:
        # Check if email already exists
        existing = db.exec(select(User).where(User.email == email_clean)).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email sudah terdaftar")

        user_obj = User(
            email=email_clean,
            name=name.strip(),
            no_hp=no_hp_clean,
            role=role,
            bidang=bidang_clean,
            opd_id=parsed_opd_id if role == "user_opd" else None,
            is_active=is_active,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(user_obj)
        action = "CREATE"

    db.commit()
    db.refresh(user_obj)

    log_activity(
        db=db,
        action=action,
        entity="user",
        entity_id=user_obj.id,
        description=f"{action} user whitelist: {user_obj.email} ({user_obj.role}, HP: {user_obj.no_hp or '-'}, Bidang: {user_obj.bidang or '-'})",
        user=current_user,
        request=request,
    )

    return RedirectResponse(url=settings.url_path("/admin/users"), status_code=303)


@router.post("/{user_id}/hapus")
async def delete_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Hapus pengguna whitelist dari sistem."""
    user_obj = db.get(User, user_id)
    if not user_obj:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    if user_obj.id == current_user.id:
        raise HTTPException(status_code=400, detail="Tidak dapat menghapus akun Anda sendiri")

    user_email = user_obj.email
    user_name = user_obj.name or user_obj.email

    # Nullify referensi foreign key agar penghapusan user berjalan aman
    db.execute(text("UPDATE dokumen_perencanaans SET created_by_id = NULL WHERE created_by_id = :uid"), {"uid": user_id})
    db.execute(text("UPDATE kejadians SET created_by_id = NULL WHERE created_by_id = :uid"), {"uid": user_id})
    db.execute(text("UPDATE surat SET created_by_id = NULL WHERE created_by_id = :uid"), {"uid": user_id})
    db.execute(text("UPDATE attachment_surat SET uploaded_by_id = NULL WHERE uploaded_by_id = :uid"), {"uid": user_id})
    db.execute(text("UPDATE agenda SET created_by_id = NULL WHERE created_by_id = :uid"), {"uid": user_id})
    db.execute(text("UPDATE foto SET uploaded_by_id = NULL WHERE uploaded_by_id = :uid"), {"uid": user_id})

    db.delete(user_obj)
    db.commit()

    log_activity(
        db=db,
        action="DELETE",
        entity="user",
        entity_id=user_id,
        description=f"Hapus user whitelist: {user_email} ({user_name})",
        user=current_user,
        request=request,
    )

    return RedirectResponse(url=settings.url_path("/admin/users"), status_code=303)


@router.post("/{user_id}/toggle-status")
async def toggle_user_status(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Toggle status aktif pengguna."""
    user_obj = db.get(User, user_id)
    if not user_obj:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    if user_obj.id == current_user.id:
        raise HTTPException(status_code=400, detail="Tidak dapat menonaktifkan akun sendiri")

    user_obj.is_active = not user_obj.is_active
    user_obj.updated_at = datetime.now()
    db.commit()

    log_activity(
        db=db,
        action="UPDATE",
        entity="user",
        entity_id=user_obj.id,
        description=f"Ubah status user {user_obj.email} ke {'Aktif' if user_obj.is_active else 'Nonaktif'}",
        user=current_user,
        request=request,
    )

    return RedirectResponse(url=settings.url_path("/admin/users"), status_code=303)
