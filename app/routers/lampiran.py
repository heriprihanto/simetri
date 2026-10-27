"""
Router Lampiran — upload & manajemen lampiran Google Drive (Kejadian, Surat, Agenda).
"""

import os
import shutil
import tempfile
from typing import Optional

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlmodel import Session

from app.database import get_db
from app.middleware import get_current_user
from app.models.user import User
from app.models.kejadian import Kejadian, LampiranKejadian
from app.models.surat import Surat, AttachmentSurat
from app.models.agenda import Agenda, Foto
from app.services.audit_service import log_activity
from app.services.gdrive_service import (
    upload_file,
    delete_file,
    get_folder_for_kejadian,
    get_or_create_folder,
)
from app.config import get_settings

router = APIRouter(prefix="/lampiran", tags=["lampiran"])
settings = get_settings()


# ==========================================
# 1. LAMPIRAN KEJADIAN (KRONOLOGI)
# ==========================================

@router.post("/kejadian/{kejadian_id}/upload")
async def upload_lampiran_kejadian(
    kejadian_id: int,
    request: Request,
    tipe: str = Form("file_gdrive"),  # "file_gdrive" atau "link_eksternal"
    judul: str = Form(""),
    external_url: str = Form(""),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload file lampiran ke Google Drive atau simpan tautan eksternal untuk kejadian."""
    kejadian = db.get(Kejadian, kejadian_id)
    if not kejadian:
        raise HTTPException(status_code=404, detail="Kejadian tidak ditemukan")

    if tipe == "link_eksternal":
        url_clean = (external_url or "").strip()
        if not url_clean:
            raise HTTPException(status_code=400, detail="URL eksternal harus diisi")
        if not (url_clean.startswith("http://") or url_clean.startswith("https://")):
            url_clean = "https://" + url_clean
        lampiran = LampiranKejadian(
            kejadian_id=kejadian_id,
            tipe_lampiran="link_eksternal",
            judul=judul.strip() or url_clean,
            external_url=url_clean,
        )
        db.add(lampiran)
        db.commit()
        db.refresh(lampiran)
        log_activity(
            db=db,
            action="CREATE",
            entity="lampiran",
            entity_id=lampiran.id,
            description=f"Tambah link eksternal pada kejadian #{kejadian_id}: {judul}",
            user=current_user,
            request=request,
        )
        return JSONResponse({"status": "ok", "id": lampiran.id, "type": "link"})

    # Upload file ke Google Drive
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="File harus dipilih")

    # Ambil/buat folder Drive untuk kejadian ini
    folder_id = get_folder_for_kejadian(
        tahun=kejadian.tanggal_kejadian.year,
        bidang_pj=kejadian.bidang_pj or "LAINNYA",
        dokumen_nama=f"Dokumen_{kejadian.dokumen_id}",
    )

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        file_size = os.path.getsize(tmp_path)
        drive_res = upload_file(
            local_path=tmp_path,
            filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            folder_id=folder_id,
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    g_drive_id = drive_res.get("id", "") if drive_res else ""
    g_view = drive_res.get("webViewLink", "") if drive_res else ""
    g_download = drive_res.get("webContentLink", "") if drive_res else ""

    lampiran = LampiranKejadian(
        kejadian_id=kejadian_id,
        tipe_lampiran="file_gdrive",
        judul=judul or file.filename,
        file_name=file.filename,
        mime_type=file.content_type or "",
        file_size=file_size,
        g_drive_file_id=g_drive_id,
        g_drive_web_view_link=g_view,
        g_drive_download_link=g_download,
    )
    db.add(lampiran)
    db.commit()
    db.refresh(lampiran)

    log_activity(
        db=db,
        action="UPLOAD",
        entity="lampiran",
        entity_id=lampiran.id,
        description=f"Upload lampiran ke Drive pada kejadian #{kejadian_id}: {file.filename}",
        user=current_user,
        request=request,
    )

    return JSONResponse({
        "status": "ok",
        "id": lampiran.id,
        "filename": lampiran.file_name,
        "view_link": lampiran.g_drive_web_view_link,
    })


@router.delete("/kejadian/{lampiran_id}")
async def delete_lampiran_kejadian(
    lampiran_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hapus lampiran kejadian."""
    lampiran = db.get(LampiranKejadian, lampiran_id)
    if not lampiran:
        raise HTTPException(status_code=404, detail="Lampiran tidak ditemukan")

    if lampiran.g_drive_file_id:
        delete_file(lampiran.g_drive_file_id)

    db.delete(lampiran)
    db.commit()

    log_activity(
        db=db,
        action="DELETE",
        entity="lampiran",
        entity_id=lampiran_id,
        description=f"Hapus lampiran #{lampiran_id}",
        user=current_user,
        request=request,
    )

    return HTMLResponse("", status_code=200)


# ==========================================
# 2. ATTACHMENT SURAT (ARSIP)
# ==========================================

@router.post("/surat/{surat_id}/upload")
async def upload_attachment_surat(
    surat_id: int,
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload attachment arsip surat ke Google Drive."""
    surat = db.get(Surat, surat_id)
    if not surat:
        raise HTTPException(status_code=404, detail="Surat tidak ditemukan")

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="File harus dipilih")

    # Folder arsip surat
    parent_folder = settings.GDRIVE_PARENT_FOLDER_ID or None
    arsip_folder_id = get_or_create_folder(
        settings.GDRIVE_ARSIP_FOLDER_NAME, parent_id=parent_folder
    )

    # Subfolder per tahun
    tahun_str = str(surat.tanggal_surat.year)
    tahun_folder_id = get_or_create_folder(tahun_str, parent_id=arsip_folder_id)

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        file_size = os.path.getsize(tmp_path)
        drive_res = upload_file(
            local_path=tmp_path,
            filename=file.filename,
            mime_type=file.content_type or "application/pdf",
            folder_id=tahun_folder_id,
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    g_drive_id = drive_res.get("id", "") if drive_res else ""
    g_view = drive_res.get("webViewLink", "") if drive_res else ""

    att = AttachmentSurat(
        surat_id=surat_id,
        drive_file_id=g_drive_id,
        drive_link=g_view,
        filename=file.filename,
        mime_type=file.content_type or "",
        size_bytes=file_size,
        uploaded_by_id=current_user.id,
    )
    db.add(att)
    db.commit()
    db.refresh(att)

    log_activity(
        db=db,
        action="UPLOAD",
        entity="surat",
        entity_id=surat_id,
        description=f"Upload attachment surat #{surat_id}: {file.filename}",
        user=current_user,
        request=request,
    )

    return JSONResponse({
        "status": "ok",
        "id": att.id,
        "filename": att.filename,
        "drive_link": att.drive_link,
    })


@router.delete("/surat/{attachment_id}")
async def delete_attachment_surat(
    attachment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hapus attachment surat."""
    att = db.get(AttachmentSurat, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment tidak ditemukan")

    if att.drive_file_id:
        delete_file(att.drive_file_id)

    db.delete(att)
    db.commit()

    log_activity(
        db=db,
        action="DELETE",
        entity="surat",
        entity_id=att.surat_id,
        description=f"Hapus attachment #{attachment_id} ({att.filename})",
        user=current_user,
        request=request,
    )

    return HTMLResponse("", status_code=200)


# ==========================================
# 3. FOTO AGENDA
# ==========================================

@router.post("/agenda/{agenda_id}/upload")
async def upload_foto_agenda(
    agenda_id: int,
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload foto dokumentasi kegiatan ke Google Drive."""
    agenda = db.get(Agenda, agenda_id)
    if not agenda:
        raise HTTPException(status_code=404, detail="Agenda tidak ditemukan")

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="File foto harus dipilih")

    # Folder galeri kegiatan
    parent_folder = settings.GDRIVE_PARENT_FOLDER_ID or None
    galeri_folder_id = get_or_create_folder(
        settings.GDRIVE_GALERI_FOLDER_NAME, parent_id=parent_folder
    )

    # Subfolder per kegiatan
    kegiatan_folder_name = f"{agenda.tanggal.strftime('%Y-%m-%d')}_{agenda.judul[:30].strip()}"
    kegiatan_folder_id = get_or_create_folder(kegiatan_folder_name, parent_id=galeri_folder_id)

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        file_size = os.path.getsize(tmp_path)
        drive_res = upload_file(
            local_path=tmp_path,
            filename=file.filename,
            mime_type=file.content_type or "image/jpeg",
            folder_id=kegiatan_folder_id,
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    g_drive_id = drive_res.get("id", "") if drive_res else ""
    g_view = drive_res.get("webViewLink", "") if drive_res else ""

    foto = Foto(
        agenda_id=agenda_id,
        drive_file_id=g_drive_id,
        drive_link=g_view,
        filename=file.filename,
        mime_type=file.content_type or "",
        size_bytes=file_size,
        uploaded_by_id=current_user.id,
    )
    db.add(foto)
    db.commit()
    db.refresh(foto)

    log_activity(
        db=db,
        action="UPLOAD",
        entity="agenda",
        entity_id=agenda_id,
        description=f"Upload foto agenda #{agenda_id}: {file.filename}",
        user=current_user,
        request=request,
    )

    return JSONResponse({
        "status": "ok",
        "id": foto.id,
        "filename": foto.filename,
        "drive_link": foto.drive_link,
    })


@router.delete("/agenda/{foto_id}")
async def delete_foto_agenda(
    foto_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hapus foto agenda."""
    foto = db.get(Foto, foto_id)
    if not foto:
        raise HTTPException(status_code=404, detail="Foto tidak ditemukan")

    if foto.drive_file_id:
        delete_file(foto.drive_file_id)

    db.delete(foto)
    db.commit()

    log_activity(
        db=db,
        action="DELETE",
        entity="agenda",
        entity_id=foto.agenda_id,
        description=f"Hapus foto #{foto_id} ({foto.filename})",
        user=current_user,
        request=request,
    )

    return HTMLResponse("", status_code=200)
