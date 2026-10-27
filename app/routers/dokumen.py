"""
Router Dokumen Perencanaan — CRUD dokumen perencanaan pembangunan daerah.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, desc, select

from app.database import get_db
from app.middleware import get_current_user, require_admin_or_bidang
from app.models.dokumen import JENIS_DOKUMEN, DokumenPerencanaan
from app.models.kejadian import Kejadian, LampiranKejadian
from app.models.user import TaOpd, User
from app.services.audit_service import log_activity
from app.services.gdrive_service import delete_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dokumen", tags=["dokumen"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_dokumen(
    request: Request,
    jenis: Optional[str] = None,
    tahun: Optional[int] = None,
    cakupan: Optional[str] = None,  # "kota" | "opd" | "all"
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Halaman daftar dokumen perencanaan."""
    query = select(DokumenPerencanaan).order_by(
        desc(DokumenPerencanaan.is_default), desc(DokumenPerencanaan.id)
    )

    # User OPD hanya bisa melihat dokumen kota + dokumen OPD miliknya
    if current_user.is_user_opd:
        query = query.where(
            (DokumenPerencanaan.opd_id == None) | (DokumenPerencanaan.opd_id == current_user.opd_id)  # noqa: E711
        )
    elif cakupan == "kota":
        query = query.where(DokumenPerencanaan.opd_id == None)  # noqa: E711
    elif cakupan == "opd":
        query = query.where(DokumenPerencanaan.opd_id != None)  # noqa: E711

    if jenis:
        query = query.where(DokumenPerencanaan.jenis == jenis)
    if tahun:
        query = query.where(
            (DokumenPerencanaan.tahun_awal <= tahun) & (DokumenPerencanaan.tahun_akhir >= tahun)
        )

    dokumen_list = db.exec(query).all()
    opd_list = db.exec(select(TaOpd).where(TaOpd.aktif == 1).order_by(TaOpd.nama_pd)).all()

    # Create mapping opd_id -> nama_pd for easy display
    opd_map = {opd.id_sub_pd: opd.nama_pd for opd in opd_list}

    # Hitung jumlah catatan kejadian kronologi per dokumen
    kejadian_counts: dict[int, int] = {}
    for doc in dokumen_list:
        if doc.id:
            count = db.exec(
                select(func.count(Kejadian.id)).where(Kejadian.dokumen_id == doc.id)
            ).one()
            kejadian_counts[doc.id] = count

    return templates.TemplateResponse(
        request=request,
        name="kronologi/dokumen.html",
        context={
            "user": current_user,
            "dokumen_list": dokumen_list,
            "kejadian_counts": kejadian_counts,
            "opd_map": opd_map,
            "opd_list": opd_list,
            "jenis_list": JENIS_DOKUMEN,
            "current_jenis": jenis or "",
            "current_tahun": tahun or "",
            "current_cakupan": cakupan or "all",
            "page_title": "Dokumen Perencanaan - SIMETRI",
        },
    )


@router.post("/simpan")
async def save_dokumen(
    request: Request,
    id: Optional[str] = Form(None),
    nama: str = Form(...),
    alias: str = Form(""),
    jenis: str = Form(...),
    tahun_awal: int = Form(...),
    tahun_akhir: int = Form(...),
    tahun_rencana: int = Form(0),
    opd_id: Optional[str] = Form(None),
    status: str = Form("dalam proses"),
    deskripsi: str = Form(""),
    is_active: bool = Form(True),
    is_default: bool = Form(False),
    current_user: User = Depends(require_admin_or_bidang),
    db: Session = Depends(get_db),
):
    """Simpan dokumen perencanaan (baru atau update)."""
    parsed_id = int(id) if id and str(id).strip().isdigit() else None
    parsed_opd_id = int(opd_id) if opd_id and str(opd_id).strip().isdigit() else None
    alias_clean = alias.strip().lower() if isinstance(alias, str) else ""
    desc_clean = deskripsi.strip() if isinstance(deskripsi, str) else ""
    parsed_tahun_rencana = (
        int(tahun_rencana)
        if isinstance(tahun_rencana, (int, str)) and str(tahun_rencana).isdigit() and int(tahun_rencana) > 0
        else tahun_awal
    )
    is_active_val = is_active is True or is_active == "true" or is_active == 1 or str(is_active).lower() == "true"
    is_default_val = is_default is True or is_default == "true" or is_default == 1 or str(is_default).lower() == "true"

    # Jika diset sebagai default, reset dokumen lain
    if is_default_val:
        all_docs = db.exec(select(DokumenPerencanaan)).all()
        for d in all_docs:
            if not parsed_id or d.id != parsed_id:
                d.is_default = False

    if parsed_id:
        dokumen = db.get(DokumenPerencanaan, parsed_id)
        if not dokumen:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
        dokumen.nama = nama
        dokumen.alias = alias_clean
        dokumen.jenis = jenis
        dokumen.tahun_awal = tahun_awal
        dokumen.tahun_akhir = tahun_akhir
        dokumen.tahun_rencana = parsed_tahun_rencana
        dokumen.opd_id = parsed_opd_id
        dokumen.status = status
        dokumen.deskripsi = desc_clean
        dokumen.is_active = is_active_val
        dokumen.is_default = is_default_val
        dokumen.updated_at = datetime.now()
        action = "UPDATE"
    else:
        dokumen = DokumenPerencanaan(
            nama=nama,
            alias=alias_clean,
            jenis=jenis,
            tahun_awal=tahun_awal,
            tahun_akhir=tahun_akhir,
            tahun_rencana=parsed_tahun_rencana,
            opd_id=parsed_opd_id,
            status=status,
            deskripsi=desc_clean,
            is_active=is_active_val,
            is_default=is_default_val,
            created_by_id=current_user.id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(dokumen)
        action = "CREATE"

    db.commit()
    db.refresh(dokumen)

    log_activity(
        db=db,
        action=action,
        entity="dokumen",
        entity_id=dokumen.id,
        description=f"{action} dokumen perencanaan: {dokumen.nama}",
        user=current_user,
        request=request,
    )

    return RedirectResponse(url="/dokumen", status_code=303)


@router.post("/{dokumen_id}/hapus")
@router.post("/{dokumen_id}/delete")
async def delete_dokumen(
    dokumen_id: int,
    request: Request,
    current_user: User = Depends(require_admin_or_bidang),
    db: Session = Depends(get_db),
):
    """Hapus dokumen perencanaan beserta catatan kronologi kejadian terkait."""
    dokumen = db.get(DokumenPerencanaan, dokumen_id)
    if not dokumen:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")

    # Ambil seluruh kejadian kronologi yang terkait
    kejadians = db.exec(
        select(Kejadian).where(Kejadian.dokumen_id == dokumen_id)
    ).all()

    for k in kejadians:
        # Hapus lampiran terkait
        lampiran_list = db.exec(
            select(LampiranKejadian).where(LampiranKejadian.kejadian_id == k.id)
        ).all()
        for l in lampiran_list:
            if l.g_drive_file_id:
                try:
                    delete_file(l.g_drive_file_id)
                except Exception as ex:
                    logger.warning(f"[GDrive] Gagal hapus file drive {l.g_drive_file_id}: {ex}")
            db.delete(l)
        db.delete(k)

    nama_dokumen = dokumen.nama
    db.delete(dokumen)
    db.commit()

    log_activity(
        db=db,
        action="DELETE",
        entity="dokumen",
        entity_id=dokumen_id,
        description=f"Hapus dokumen perencanaan: {nama_dokumen} (beserta {len(kejadians)} kejadian terkait)",
        user=current_user,
        request=request,
    )

    return RedirectResponse(url="/dokumen", status_code=303)


@router.post("/{dokumen_id}/set-default")
async def set_default_dokumen(
    dokumen_id: int,
    request: Request,
    current_user: User = Depends(require_admin_or_bidang),
    db: Session = Depends(get_db),
):
    """Jadikan dokumen sebagai dokumen default untuk timeline kronologi."""
    target_dokumen = db.get(DokumenPerencanaan, dokumen_id)
    if not target_dokumen:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")

    # Set semua dokumen lain is_default = False, dan dokumen target = True
    all_docs = db.exec(select(DokumenPerencanaan)).all()
    for doc in all_docs:
        doc.is_default = (doc.id == dokumen_id)
        doc.updated_at = datetime.now()

    db.commit()

    log_activity(
        db=db,
        action="UPDATE",
        entity="dokumen",
        entity_id=target_dokumen.id,
        description=f"Set dokumen default ke: {target_dokumen.nama}",
        user=current_user,
        request=request,
    )

    return RedirectResponse(url="/dokumen", status_code=303)


@router.post("/{dokumen_id}/toggle-status")
async def toggle_dokumen_status(
    dokumen_id: int,
    request: Request,
    current_user: User = Depends(require_admin_or_bidang),
    db: Session = Depends(get_db),
):
    """Toggle status dokumen (aktif/nonaktif atau dalam proses/selesai)."""
    dokumen = db.get(DokumenPerencanaan, dokumen_id)
    if not dokumen:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")

    dokumen.status = "selesai" if dokumen.status == "dalam proses" else "dalam proses"
    dokumen.updated_at = datetime.now()
    db.commit()

    log_activity(
        db=db,
        action="UPDATE",
        entity="dokumen",
        entity_id=dokumen.id,
        description=f"Ubah status dokumen {dokumen.nama} ke {dokumen.status}",
        user=current_user,
        request=request,
    )

    return RedirectResponse(url="/dokumen", status_code=303)
