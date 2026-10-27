import os
import shutil
import tempfile
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select, func, col, desc

from app.database import get_session
from app.middleware import get_current_user
from app.models.kejadian import Kejadian, LampiranKejadian
from app.models.dokumen import DokumenPerencanaan
from app.models.master import MasterJenisKejadian, MasterBidang
from app.models.user import User, TaOpd
from app.services.audit_service import log_activity
from app.services.gdrive_service import (
    upload_file,
    delete_file,
    get_folder_for_kejadian,
)
from app.config import get_settings
from app.templates_config import templates

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/kronologi", tags=["Kronologi"])


def _filter_dokumen_for_user(session: Session, user: User):
    """Filter dokumen perencanaan berdasarkan role user."""
    stmt = select(DokumenPerencanaan).where(DokumenPerencanaan.is_active == True)

    if user.is_user_opd:
        # User OPD hanya bisa lihat dokumen OPD mereka
        stmt = stmt.where(DokumenPerencanaan.opd_id == user.opd_id)
    elif user.is_user_bidang:
        # User Bidang hanya bisa lihat dokumen tingkat kota
        stmt = stmt.where(DokumenPerencanaan.opd_id == None)

    # Admin bisa lihat semua, urutkan dokumen default terlebih dahulu lalu nama
    return session.exec(
        stmt.order_by(desc(DokumenPerencanaan.is_default), DokumenPerencanaan.nama)
    ).all()


@router.get("", response_class=HTMLResponse)
async def timeline(
    request: Request,
    dokumen_id: Optional[str] = Query(None),
    jenis: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    session: Session = Depends(get_session),
):
    """Halaman timeline kronologi kejadian."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url=settings.url_path("/login", request), status_code=302)

    per_page = 20
    dokumen_list = _filter_dokumen_for_user(session, user)
    jenis_list = session.exec(
        select(MasterJenisKejadian).order_by(MasterJenisKejadian.urutan)
    ).all()
    bidang_list = session.exec(select(MasterBidang).order_by(MasterBidang.nama)).all()

    # Default filter dokumen jika tidak ada parameter dokumen_id di query URL
    # (misal saat pertama kali user membuka halaman /kronologi)
    parsed_dokumen_id: Optional[int] = None
    if "dokumen_id" not in request.query_params and dokumen_list:
        # 1. Dokumen yang ditandai is_default
        default_doc = next((d for d in dokumen_list if getattr(d, "is_default", False)), None)
        # 2. Fallback: dokumen dalam proses (RKPD / RPJMD)
        if not default_doc:
            default_doc = next(
                (d for d in dokumen_list if d.status == "dalam proses" and d.jenis in ("RKPD", "Perubahan RKPD", "RPJMD")),
                None,
            )
        # 3. Fallback: dokumen dalam proses apapun
        if not default_doc:
            default_doc = next((d for d in dokumen_list if d.status == "dalam proses"), None)
        # 4. Fallback: dokumen pertama
        if not default_doc:
            default_doc = dokumen_list[0]

        if default_doc:
            parsed_dokumen_id = default_doc.id
    elif dokumen_id and dokumen_id.strip().isdigit():
        parsed_dokumen_id = int(dokumen_id.strip())

    # Build query kejadian
    stmt = select(Kejadian)

    if parsed_dokumen_id:
        stmt = stmt.where(Kejadian.dokumen_id == parsed_dokumen_id)
    else:
        # Filter berdasarkan role
        dokumen_ids = [d.id for d in dokumen_list]
        if dokumen_ids:
            stmt = stmt.where(col(Kejadian.dokumen_id).in_(dokumen_ids))

    if jenis:
        stmt = stmt.where(Kejadian.jenis_kejadian == jenis)

    if q:
        like_q = f"%{q}%"
        stmt = stmt.where(
            (Kejadian.judul_kejadian.ilike(like_q))
            | (Kejadian.uraian_kronologi.ilike(like_q))
            | (Kejadian.hasil_pembahasan.ilike(like_q))
            | (Kejadian.pihak_pengusul.ilike(like_q))
        )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = session.exec(count_stmt).one()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)

    # Fetch kejadian
    kejadian_list = session.exec(
        stmt.order_by(Kejadian.tanggal_kejadian.desc(), Kejadian.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    # Fetch lampiran untuk tiap kejadian
    for k in kejadian_list:
        k.lampiran = session.exec(
            select(LampiranKejadian).where(LampiranKejadian.kejadian_id == k.id)
        ).all()

    # Ambil nama dokumen
    dokumen_map = {d.id: d for d in dokumen_list}

    # Jika htmx request, kembalikan partial
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/timeline_list.html",
            context={
                "kejadian_list": kejadian_list,
                "dokumen_map": dokumen_map,
                "page": page,
                "total_pages": total_pages,
                "total": total,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="kronologi/index.html",
        context={
            "user": user,
            "title": "Kronologi Kejadian",
            "kejadian_list": kejadian_list,
            "dokumen_list": dokumen_list,
            "dokumen_map": dokumen_map,
            "jenis_list": jenis_list,
            "bidang_list": bidang_list,
            "current_dokumen_id": parsed_dokumen_id,
            "current_jenis": jenis,
            "current_q": q or "",
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "menu_active": "kronologi",
        },
    )


@router.get("/detail/{kejadian_id}", response_class=HTMLResponse)
async def detail_kejadian(
    request: Request,
    kejadian_id: int,
    session: Session = Depends(get_session),
):
    """Detail satu kejadian (htmx partial)."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    kejadian = session.get(Kejadian, kejadian_id)
    if not kejadian:
        return HTMLResponse("Tidak ditemukan", status_code=404)

    kejadian.lampiran = session.exec(
        select(LampiranKejadian).where(LampiranKejadian.kejadian_id == kejadian_id)
    ).all()

    dokumen = session.get(DokumenPerencanaan, kejadian.dokumen_id)
    creator = session.get(User, kejadian.created_by_id) if kejadian.created_by_id else None

    return templates.TemplateResponse(
        request=request,
        name="kronologi/detail.html",
        context={
            "user": user,
            "kejadian": kejadian,
            "dokumen": dokumen,
            "creator": creator,
        },
    )


@router.get("/form", response_class=HTMLResponse)
@router.get("/form/{kejadian_id}", response_class=HTMLResponse)
async def form_kejadian(
    request: Request,
    kejadian_id: Optional[int] = None,
    dokumen_id: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Form entri/edit kejadian (htmx modal)."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    kejadian = None
    if kejadian_id:
        kejadian = session.get(Kejadian, kejadian_id)
        if kejadian:
            kejadian.lampiran = session.exec(
                select(LampiranKejadian).where(LampiranKejadian.kejadian_id == kejadian_id)
            ).all()

    dokumen_list = _filter_dokumen_for_user(session, user)

    # Tentukan default dokumen untuk form baru
    parsed_dok_id = int(dokumen_id.strip()) if dokumen_id and dokumen_id.strip().isdigit() else None
    default_dokumen_id = parsed_dok_id
    if not default_dokumen_id and not kejadian and dokumen_list:
        def_doc = next((d for d in dokumen_list if getattr(d, "is_default", False)), None)
        if not def_doc:
            def_doc = next(
                (d for d in dokumen_list if d.status == "dalam proses" and d.jenis in ("RKPD", "Perubahan RKPD", "RPJMD")),
                None,
            )
        if not def_doc:
            def_doc = next((d for d in dokumen_list if d.status == "dalam proses"), None)
        if not def_doc:
            def_doc = dokumen_list[0]
        if def_doc:
            default_dokumen_id = def_doc.id

    jenis_list = session.exec(
        select(MasterJenisKejadian).order_by(MasterJenisKejadian.urutan)
    ).all()
    bidang_list = session.exec(select(MasterBidang).order_by(MasterBidang.nama)).all()

    now = datetime.now()
    default_tanggal = now.strftime("%Y-%m-%d")
    default_waktu = now.strftime("%H:%M")
    default_datetime = now.strftime("%Y-%m-%dT%H:%M")

    # Bidang default otomatis berdasarkan user
    default_bidang = ""
    user_opd_nama = ""
    if user.is_user_opd and user.opd_id:
        opd_rec = session.get(TaOpd, user.opd_id)
        if opd_rec:
            user_opd_nama = opd_rec.nama_pd
            default_bidang = opd_rec.nama_pd
    elif user.bidang:
        mb = session.exec(
            select(MasterBidang).where(
                (MasterBidang.kode == user.bidang) | (MasterBidang.nama == user.bidang)
            )
        ).first()
        default_bidang = mb.nama if mb else user.bidang
    elif bidang_list:
        default_bidang = bidang_list[0].nama

    return templates.TemplateResponse(
        request=request,
        name="kronologi/form.html",
        context={
            "user": user,
            "kejadian": kejadian,
            "dokumen_list": dokumen_list,
            "default_dokumen_id": default_dokumen_id,
            "jenis_list": jenis_list,
            "bidang_list": bidang_list,
            "default_tanggal": default_tanggal,
            "default_waktu": default_waktu,
            "default_datetime": default_datetime,
            "default_bidang": default_bidang,
            "user_opd_nama": user_opd_nama,
        },
    )


@router.post("/save", response_class=HTMLResponse)
async def save_kejadian(
    request: Request,
    session: Session = Depends(get_session),
):
    """Simpan kejadian baru atau update."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    form = await request.form()
    kejadian_id = form.get("id")

    if kejadian_id:
        kejadian = session.get(Kejadian, int(kejadian_id))
        if not kejadian:
            return HTMLResponse("Tidak ditemukan", status_code=404)
    else:
        kejadian = Kejadian(created_by_id=user.id)

    kejadian.dokumen_id = int(form.get("dokumen_id", 0))

    # Waktu & Tanggal kejadian (datetime input: %Y-%m-%dT%H:%M)
    now = datetime.now()
    tgl_waktu = form.get("waktu_kejadian") or form.get("tanggal_kejadian")
    if tgl_waktu:
        val_str = str(tgl_waktu).strip()
        try:
            if "T" in val_str:
                dt = datetime.strptime(val_str[:16], "%Y-%m-%dT%H:%M")
            else:
                dt = datetime.strptime(val_str[:10], "%Y-%m-%d")
            kejadian.tanggal_kejadian = dt
            kejadian.waktu_mulai = dt.strftime("%H:%M")
        except ValueError:
            kejadian.tanggal_kejadian = now
            kejadian.waktu_mulai = now.strftime("%H:%M")
    else:
        kejadian.tanggal_kejadian = now
        kejadian.waktu_mulai = now.strftime("%H:%M")

    # Waktu selesai & lokasi dihapus dari form (opsional/preserve jika ada)
    if "waktu_selesai" in form:
        kejadian.waktu_selesai = str(form.get("waktu_selesai", "")).strip()
    elif not kejadian_id:
        kejadian.waktu_selesai = ""

    if "lokasi" in form:
        kejadian.lokasi = str(form.get("lokasi", "")).strip()
    elif not kejadian_id:
        kejadian.lokasi = ""

    kejadian.jenis_kejadian = str(form.get("jenis_kejadian", "")).strip()
    kejadian.judul_kejadian = str(form.get("judul_kejadian", "")).strip()
    kejadian.uraian_kronologi = str(form.get("uraian_kronologi", "")).strip()

    # Optional fields removed from simplified form: preserve existing if edit or default empty
    if "pihak_pengusul" in form:
        kejadian.pihak_pengusul = str(form.get("pihak_pengusul", ""))
    elif not kejadian_id:
        kejadian.pihak_pengusul = ""

    if "hasil_pembahasan" in form:
        kejadian.hasil_pembahasan = str(form.get("hasil_pembahasan", ""))
    elif not kejadian_id:
        kejadian.hasil_pembahasan = ""

    if "dasar_dokumen_keputusan" in form:
        kejadian.dasar_dokumen_keputusan = str(form.get("dasar_dokumen_keputusan", ""))
    elif not kejadian_id:
        kejadian.dasar_dokumen_keputusan = ""

    if "perubahan_indikator_target" in form:
        kejadian.perubahan_indikator_target = str(form.get("perubahan_indikator_target", ""))
    elif not kejadian_id:
        kejadian.perubahan_indikator_target = ""

    if "perubahan_pagu" in form:
        kejadian.perubahan_pagu = str(form.get("perubahan_pagu", ""))
    elif not kejadian_id:
        kejadian.perubahan_pagu = ""

    if "program_kegiatan_terkait" in form:
        kejadian.program_kegiatan_terkait = str(form.get("program_kegiatan_terkait", ""))
    elif not kejadian_id:
        kejadian.program_kegiatan_terkait = ""

    kejadian.updated_at = now

    # Bidang PJ: untuk user_opd otomatis nama OPD, untuk user bappeda otomatis bidang default jika kosong
    if user.is_user_opd and user.opd_id:
        opd_rec = session.get(TaOpd, user.opd_id)
        kejadian.bidang_pj = opd_rec.nama_pd if opd_rec else str(form.get("bidang_pj", "")).strip()
    else:
        bidang_input = str(form.get("bidang_pj", "")).strip()
        if not bidang_input and user.bidang:
            mb = session.exec(
                select(MasterBidang).where(
                    (MasterBidang.kode == user.bidang) | (MasterBidang.nama == user.bidang)
                )
            ).first()
            bidang_input = mb.nama if mb else user.bidang
        kejadian.bidang_pj = bidang_input

    session.add(kejadian)
    session.commit()
    session.refresh(kejadian)

    # 1. Proses upload file ke Google Drive jika ada
    uploaded_files = form.getlist("files")
    valid_files = [f for f in uploaded_files if hasattr(f, "filename") and f.filename]

    if valid_files:
        dok_rec = session.get(DokumenPerencanaan, kejadian.dokumen_id)
        dok_nama = dok_rec.nama if dok_rec else f"Dokumen_{kejadian.dokumen_id}"
        folder_id = get_folder_for_kejadian(
            tahun=kejadian.tanggal_kejadian.year,
            bidang_pj=kejadian.bidang_pj or "LAINNYA",
            dokumen_nama=dok_nama,
        )

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
                        folder_id=folder_id,
                    )
                except Exception as ex:
                    logger.error("[GDrive] Gagal upload lampiran kejadian '%s': %s", file_obj.filename, ex)

                g_drive_id = drive_res.get("id", "") if drive_res else ""
                g_view = drive_res.get("webViewLink", "") if drive_res else ""
                g_download = drive_res.get("webContentLink", "") if drive_res else ""

                lampiran_file = LampiranKejadian(
                    kejadian_id=kejadian.id,
                    tipe_lampiran="file_gdrive",
                    judul=file_obj.filename,
                    file_name=file_obj.filename,
                    mime_type=mime,
                    file_size=file_size,
                    g_drive_file_id=g_drive_id,
                    g_drive_web_view_link=g_view,
                    g_drive_download_link=g_download,
                )
                session.add(lampiran_file)
            except Exception as e:
                logger.error("[Kronologi] Error memproses file lampiran '%s': %s", getattr(file_obj, "filename", "unnamed"), e)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
        session.commit()

    # 2. Proses entri tautan / link dokumen yang tersimpan di cloud
    link_urls = form.getlist("link_urls")
    link_juduls = form.getlist("link_juduls")
    if not link_urls and form.get("link_url"):
        link_urls = [form.get("link_url")]
        link_juduls = [form.get("link_judul", "")]

    added_links_count = 0
    for idx, raw_url in enumerate(link_urls):
        url_str = str(raw_url).strip()
        if not url_str:
            continue
        if not (url_str.startswith("http://") or url_str.startswith("https://")):
            url_str = "https://" + url_str

        judul_str = ""
        if idx < len(link_juduls) and link_juduls[idx]:
            judul_str = str(link_juduls[idx]).strip()
        if not judul_str:
            judul_str = url_str

        lampiran_link = LampiranKejadian(
            kejadian_id=kejadian.id,
            tipe_lampiran="link_eksternal",
            judul=judul_str,
            external_url=url_str,
        )
        session.add(lampiran_link)
        added_links_count += 1

    if added_links_count > 0:
        session.commit()

    # Log audit activity
    desc_info = []
    if valid_files:
        desc_info.append(f"{len(valid_files)} file")
    if added_links_count > 0:
        desc_info.append(f"{added_links_count} link cloud")
    lampiran_str = f" ({', '.join(desc_info)})" if desc_info else ""

    log_activity(
        db=session,
        action="UPDATE" if kejadian_id else "CREATE",
        entity="kejadian",
        entity_id=kejadian.id,
        description=f"Simpan kejadian: {kejadian.judul_kejadian}{lampiran_str}",
        user=user,
        request=request,
    )

    # Return trigger untuk close modal dan refresh timeline
    return HTMLResponse(
        content="",
        status_code=200,
        headers={
            "HX-Trigger": "refreshTimeline",
            "HX-Reswap": "none",
        },
    )


@router.delete("/delete/{kejadian_id}", response_class=HTMLResponse)
async def delete_kejadian(
    request: Request,
    kejadian_id: int,
    session: Session = Depends(get_session),
):
    """Hapus kejadian."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    kejadian = session.get(Kejadian, kejadian_id)
    if not kejadian:
        return HTMLResponse("Tidak ditemukan", status_code=404)

    # Hapus lampiran terkait
    lampiran_list = session.exec(
        select(LampiranKejadian).where(LampiranKejadian.kejadian_id == kejadian_id)
    ).all()
    for l in lampiran_list:
        if l.g_drive_file_id:
            try:
                delete_file(l.g_drive_file_id)
            except Exception as e:
                logger.error("[GDrive] Gagal hapus file drive '%s': %s", l.g_drive_file_id, e)
        session.delete(l)

    session.delete(kejadian)
    session.commit()

    log_activity(
        db=session,
        action="DELETE",
        entity="kejadian",
        entity_id=kejadian_id,
        description=f"Hapus kejadian: {kejadian.judul_kejadian}",
        user=user,
        request=request,
    )

    return HTMLResponse(
        content="",
        status_code=200,
        headers={"HX-Trigger": "refreshTimeline"},
    )
