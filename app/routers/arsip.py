import logging
import os
import shutil
import tempfile
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

from app.config import get_settings
from app.database import get_session
from app.middleware import get_current_user
from app.models.surat import Surat, AttachmentSurat, JENIS_SURAT, WARNA_JENIS_SURAT
from app.services.audit_service import log_activity
from app.services.gdrive_service import get_or_create_folder, upload_file

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/arsip", tags=["Arsip"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def daftar_surat(
    request: Request,
    q: Optional[str] = Query(None),
    jenis: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    session: Session = Depends(get_session),
):
    """Halaman daftar arsip surat."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url=settings.url_path("/login"), status_code=302)

    per_page = 20

    stmt = select(Surat)

    if jenis and jenis in JENIS_SURAT:
        stmt = stmt.where(Surat.jenis_surat == jenis)

    if q:
        like_q = f"%{q}%"
        stmt = stmt.where(
            (Surat.nomor_surat.ilike(like_q))
            | (Surat.pihak.ilike(like_q))
            | (Surat.perihal.ilike(like_q))
            | (Surat.keterangan.ilike(like_q))
        )

    # Count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = session.exec(count_stmt).one()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)

    # Fetch
    surat_list = session.exec(
        stmt.order_by(Surat.tanggal_surat.desc(), Surat.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    # Fetch attachments
    for s in surat_list:
        s.attachments = session.exec(
            select(AttachmentSurat).where(AttachmentSurat.surat_id == s.id)
        ).all()

    # Statistik ringkas
    stats = session.exec(
        select(
            func.count(Surat.id),
            func.count(Surat.id).filter(Surat.jenis_surat == "Surat Masuk"),
            func.count(Surat.id).filter(Surat.jenis_surat == "Surat Keluar"),
        )
    ).one()

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/surat_table.html",
            context={
                "surat_list": surat_list,
                "warna": WARNA_JENIS_SURAT,
                "page": page,
                "total_pages": total_pages,
                "total": total,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="arsip/index.html",
        context={
            "user": user,
            "title": "Arsip Surat",
            "surat_list": surat_list,
            "jenis_list": JENIS_SURAT,
            "warna": WARNA_JENIS_SURAT,
            "stats": {"total": stats[0], "masuk": stats[1], "keluar": stats[2]},
            "current_jenis": jenis,
            "current_q": q or "",
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "menu_active": "arsip",
        },
    )


@router.get("/form", response_class=HTMLResponse)
@router.get("/form/{surat_id}", response_class=HTMLResponse)
async def form_surat(
    request: Request,
    surat_id: Optional[int] = None,
    id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Form entri/edit surat (htmx modal)."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    target_id = surat_id or id
    surat = None
    attachments = []
    if target_id:
        surat = session.get(Surat, target_id)
        if surat:
            attachments = session.exec(
                select(AttachmentSurat).where(AttachmentSurat.surat_id == target_id)
            ).all()

    today_str = date.today().isoformat()

    return templates.TemplateResponse(
        request=request,
        name="arsip/form.html",
        context={
            "user": user,
            "surat": surat,
            "attachments": attachments,
            "jenis_list": JENIS_SURAT,
            "today_str": today_str,
        },
    )


@router.post("/save", response_class=HTMLResponse)
async def save_surat(
    request: Request,
    session: Session = Depends(get_session),
):
    """Simpan surat baru atau update, beserta multi-file lampiran ke Google Drive."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    form = await request.form()
    raw_id = form.get("id")
    surat_id = int(str(raw_id).strip()) if raw_id and str(raw_id).strip().isdigit() else None

    if surat_id:
        surat = session.get(Surat, surat_id)
        if not surat:
            return HTMLResponse("Surat tidak ditemukan", status_code=404)
        surat.updated_at = datetime.now()
    else:
        surat = Surat(created_by_id=user.id, created_at=datetime.now())

    surat.jenis_surat = str(form.get("jenis_surat", "")).strip()
    surat.nomor_surat = str(form.get("nomor_surat", "")).strip()
    
    tgl_surat_str = form.get("tanggal_surat")
    if tgl_surat_str:
        try:
            surat.tanggal_surat = date.fromisoformat(str(tgl_surat_str))
        except ValueError:
            surat.tanggal_surat = date.today()
    else:
        surat.tanggal_surat = date.today()

    surat.pihak = str(form.get("pihak", "")).strip()
    surat.perihal = str(form.get("perihal", "")).strip()
    surat.keterangan = str(form.get("keterangan", "")).strip()

    session.add(surat)
    session.commit()
    session.refresh(surat)

    # Proses Upload Attachment Files ke Google Drive (Bisa lebih dari 1 file)
    uploaded_files = form.getlist("files")
    valid_files = [f for f in uploaded_files if hasattr(f, "filename") and f.filename]

    if valid_files:
        parent_folder = settings.GDRIVE_PARENT_FOLDER_ID or None
        arsip_folder_id = get_or_create_folder(
            settings.GDRIVE_ARSIP_FOLDER_NAME, parent_id=parent_folder
        )
        tahun_str = str(surat.tanggal_surat.year)
        tahun_folder_id = get_or_create_folder(tahun_str, parent_id=arsip_folder_id)

        for file_obj in valid_files:
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    shutil.copyfileobj(file_obj.file, tmp)
                    tmp_path = tmp.name

                file_size = os.path.getsize(tmp_path)
                mime = file_obj.content_type or "application/octet-stream"

                drive_res = None
                try:
                    drive_res = upload_file(
                        local_path=tmp_path,
                        filename=file_obj.filename,
                        mime_type=mime,
                        folder_id=tahun_folder_id,
                    )
                except Exception as ex:
                    logger.error("[GDrive] Gagal upload file '%s': %s", file_obj.filename, ex)

                g_drive_id = drive_res.get("id", "") if drive_res else ""
                g_view = drive_res.get("webViewLink", "") if drive_res else ""

                att = AttachmentSurat(
                    surat_id=surat.id,
                    drive_file_id=g_drive_id,
                    drive_link=g_view,
                    filename=file_obj.filename,
                    mime_type=mime,
                    size_bytes=file_size,
                    uploaded_by_id=user.id,
                    uploaded_at=datetime.now(),
                )
                session.add(att)

            except Exception as e:
                logger.error("[Arsip] Error memproses file lampiran '%s': %s", getattr(file_obj, 'filename', 'unnamed'), e)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

        session.commit()

    log_activity(
        db=session,
        action="UPDATE" if surat_id else "CREATE",
        entity="surat",
        entity_id=surat.id,
        description=f"Simpan arsip surat {surat.nomor_surat} ({len(valid_files)} lampiran)",
        user=user,
        request=request,
    )

    return HTMLResponse(
        content="",
        status_code=200,
        headers={"HX-Trigger": "refreshSurat", "HX-Reswap": "none"},
    )


@router.delete("/delete/{surat_id}", response_class=HTMLResponse)
async def delete_surat(
    request: Request,
    surat_id: int,
    session: Session = Depends(get_session),
):
    """Hapus surat beserta attachment-nya."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    surat = session.get(Surat, surat_id)
    if not surat:
        return HTMLResponse("Tidak ditemukan", status_code=404)

    # Hapus attachments
    attachments = session.exec(
        select(AttachmentSurat).where(AttachmentSurat.surat_id == surat_id)
    ).all()
    for a in attachments:
        session.delete(a)

    session.delete(surat)
    session.commit()

    return HTMLResponse(
        content="",
        status_code=200,
        headers={"HX-Trigger": "refreshSurat"},
    )
