"""
Router Penyusunan Pagu — Modul Penyusunan Pagu Anggaran Perencanaan Pembangunan.
Menyediakan:
- Tampilan matriks rekapitulasi pagu: Baris OPD (ta_opd), Kolom Kategori (kategori_belanja)
- Halaman rincian belanja Perangkat Daerah (/pagu/opd/{id_pd})
- CRUD rincian_anggaran (Tambah, Edit, Hapus)
- Seeding fake data rincian anggaran
"""

import json
import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_db
from app.middleware import require_login
from app.models.pagu import KategoriBelanja, RincianAnggaran
from app.models.user import TaOpd, User
from app.services.audit_service import log_activity
from app.services.pagu_service import (
    generate_fake_rincian_anggaran,
    get_opd_pagu_summary,
    get_pagu_matrix,
    get_rincian_anggaran_list,
)
from app.templates_config import format_rupiah, templates

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/pagu", tags=["pagu"])


@router.get("", response_class=HTMLResponse)
async def pagu_index(
    request: Request,
    jenis: Optional[str] = None,
    q_opd: Optional[str] = None,
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    """
    Halaman utama modul Penyusunan Pagu:
    Menampilkan Matriks Rekapitulasi Pagu Perangkat Daerah (ta_opd x kategori_belanja).
    Nama Perangkat Daerah dapat diklik untuk membuka halaman rincian belanja OPD.
    """
    matrix_data = get_pagu_matrix(db, jenis_filter=jenis, q_opd=q_opd)

    all_opds = db.exec(
        select(TaOpd).where(TaOpd.is_pd == 1, TaOpd.aktif == 1).order_by(TaOpd.kode)
    ).all()
    all_kategoris = db.exec(
        select(KategoriBelanja).order_by(KategoriBelanja.nomor, KategoriBelanja.id)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="pagu/index.html",
        context={
            "user": user,
            "title": "Penyusunan Pagu — SIMETRI",
            "page_title": "Penyusunan Pagu",
            "matrix_data": matrix_data,
            "all_opds": all_opds,
            "all_kategoris": all_kategoris,
            "format_rupiah": format_rupiah,
        },
    )


@router.get("/opd/{id_pd}", response_class=HTMLResponse)
async def pagu_detail_opd(
    id_pd: int,
    request: Request,
    id_kategori: Optional[int] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    """
    Halaman rincian belanja untuk satu Perangkat Daerah:
    - Menampilkan detail OPD dan ringkasan pagu
    - Filter kategori belanja & pencarian keyword
    - Tabel CRUD rincian anggaran OPD
    """
    opd = db.get(TaOpd, id_pd)
    if not opd:
        raise HTTPException(status_code=404, detail="Perangkat Daerah tidak ditemukan")

    # Ambil daftar rincian belanja untuk OPD ini
    rincian_items, total_rincian, total_pages = get_rincian_anggaran_list(
        db, id_pd=id_pd, id_kategori=id_kategori, q=q, page=page, per_page=20
    )

    opd_summary = get_opd_pagu_summary(db, id_pd)
    page_total = sum(Decimal(r.anggaran or 0) for r in rincian_items)

    all_kategoris = db.exec(
        select(KategoriBelanja).order_by(KategoriBelanja.nomor, KategoriBelanja.id)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="pagu/detail_opd.html",
        context={
            "user": user,
            "title": f"Rincian Belanja {opd.nama_pd} — SIMETRI",
            "page_title": f"Rincian Belanja — {opd.nama_pd_singkat or opd.nama_pd}",
            "opd": opd,
            "opd_summary": opd_summary,
            "rincian_items": rincian_items,
            "total_rincian": total_rincian,
            "total_pages": total_pages,
            "current_page": page,
            "page_total": page_total,
            "id_kategori": id_kategori,
            "q": q or "",
            "all_kategoris": all_kategoris,
            "format_rupiah": format_rupiah,
        },
    )


@router.get("/form", response_class=HTMLResponse)
async def form_tambah_rincian(
    request: Request,
    id_pd: Optional[int] = None,
    id_kategori: Optional[int] = None,
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    """Modal form tambah rincian anggaran."""
    if user.is_user_opd and user.opd_id:
        id_pd = user.opd_id

    opds = db.exec(
        select(TaOpd).where(TaOpd.is_pd == 1, TaOpd.aktif == 1).order_by(TaOpd.nama_pd)
    ).all()
    kategoris = db.exec(
        select(KategoriBelanja).order_by(KategoriBelanja.nomor, KategoriBelanja.id)
    ).all()
    current_opd = db.get(TaOpd, id_pd) if id_pd else None

    return templates.TemplateResponse(
        request=request,
        name="pagu/form_modal.html",
        context={
            "user": user,
            "rincian": None,
            "current_opd": current_opd,
            "opds": opds,
            "kategoris": kategoris,
            "selected_id_pd": id_pd,
            "selected_id_kategori": id_kategori,
            "format_rupiah": format_rupiah,
        },
    )


@router.get("/form/{id}", response_class=HTMLResponse)
async def form_edit_rincian(
    id: int,
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    """Modal form edit rincian anggaran."""
    rincian = db.get(RincianAnggaran, id)
    if not rincian:
        raise HTTPException(status_code=404, detail="Rincian anggaran tidak ditemukan")

    if user.is_user_opd and user.opd_id and rincian.id_pd != user.opd_id:
        raise HTTPException(status_code=403, detail="Tidak memiliki akses mengedit OPD lain")

    opds = db.exec(
        select(TaOpd).where(TaOpd.is_pd == 1, TaOpd.aktif == 1).order_by(TaOpd.nama_pd)
    ).all()
    kategoris = db.exec(
        select(KategoriBelanja).order_by(KategoriBelanja.nomor, KategoriBelanja.id)
    ).all()
    current_opd = db.get(TaOpd, rincian.id_pd) if rincian.id_pd else None

    return templates.TemplateResponse(
        request=request,
        name="pagu/form_modal.html",
        context={
            "user": user,
            "rincian": rincian,
            "current_opd": current_opd,
            "opds": opds,
            "kategoris": kategoris,
            "selected_id_pd": rincian.id_pd,
            "selected_id_kategori": rincian.id_kategori,
            "format_rupiah": format_rupiah,
        },
    )


@router.post("/save")
async def save_rincian(
    request: Request,
    id: Optional[int] = Form(None),
    id_pd: int = Form(...),
    id_kategori: int = Form(...),
    uraian: str = Form(...),
    uraian_belanja: Optional[str] = Form(""),
    anggaran: str = Form(...),
    tags: Optional[str] = Form(""),
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    """Menyimpan (tambah atau edit) rincian anggaran."""
    if user.is_user_opd and user.opd_id:
        id_pd = user.opd_id

    # Bersihkan nominal anggaran (hilangkan Rp, titik, koma spasi)
    clean_num = "".join(c for c in anggaran if c.isdigit() or c in (".", ","))
    clean_num = clean_num.replace(",", ".")
    try:
        nominal = Decimal(clean_num) if clean_num else Decimal(0)
    except Exception:
        nominal = Decimal(0)

    if id:
        rincian = db.get(RincianAnggaran, id)
        if not rincian:
            raise HTTPException(status_code=404, detail="Rincian anggaran tidak ditemukan")
        if user.is_user_opd and user.opd_id and rincian.id_pd != user.opd_id:
            raise HTTPException(status_code=403, detail="Akses ditolak")

        rincian.id_pd = id_pd
        rincian.id_kategori = id_kategori
        rincian.uraian = uraian.strip()
        rincian.uraian_belanja = (uraian_belanja or "").strip()
        rincian.anggaran = nominal
        rincian.tags = (tags or "").strip()
        db.add(rincian)
        action_name = "UPDATE"
        msg = "Rincian anggaran berhasil diperbarui"
    else:
        rincian = RincianAnggaran(
            id_pd=id_pd,
            id_kategori=id_kategori,
            uraian=uraian.strip(),
            uraian_belanja=(uraian_belanja or "").strip(),
            anggaran=nominal,
            tags=(tags or "").strip(),
        )
        db.add(rincian)
        action_name = "CREATE"
        msg = "Rincian anggaran baru berhasil ditambahkan"

    db.commit()
    db.refresh(rincian)

    log_activity(
        db=db,
        action=action_name,
        entity="rincian_anggaran",
        entity_id=rincian.id,
        description=f"{action_name} rincian anggaran: {rincian.uraian} (Rp {int(nominal):,})",
        user=user,
        request=request,
    )

    if request.headers.get("HX-Request"):
        trigger_payload = json.dumps({
            "refreshPagu": {
                "message": msg,
            }
        })
        return HTMLResponse(
            content="",
            headers={
                "HX-Trigger": trigger_payload,
            },
        )

    redirect_url = settings.url_path(f"/pagu/opd/{id_pd}")
    return RedirectResponse(url=redirect_url, status_code=303)


@router.delete("/delete/{id}")
async def delete_rincian(
    id: int,
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    """Menghapus rincian anggaran."""
    rincian = db.get(RincianAnggaran, id)
    if not rincian:
        raise HTTPException(status_code=404, detail="Rincian anggaran tidak ditemukan")

    if user.is_user_opd and user.opd_id and rincian.id_pd != user.opd_id:
        raise HTTPException(status_code=403, detail="Akses ditolak")

    target_opd_id = rincian.id_pd
    uraian_info = rincian.uraian
    nominal_info = int(rincian.anggaran or 0)

    db.delete(rincian)
    db.commit()

    log_activity(
        db=db,
        action="DELETE",
        entity="rincian_anggaran",
        entity_id=id,
        description=f"DELETE rincian anggaran id={id}: {uraian_info} (Rp {nominal_info:,})",
        user=user,
        request=request,
    )

    if request.headers.get("HX-Request"):
        trigger_payload = json.dumps({
            "refreshPagu": {
                "message": "Data rincian anggaran berhasil dihapus",
            }
        })
        return HTMLResponse(
            content="",
            headers={
                "HX-Trigger": trigger_payload,
            },
        )

    return RedirectResponse(url=settings.url_path(f"/pagu/opd/{target_opd_id}"), status_code=303)


@router.post("/seed-fake-data")
async def seed_fake_data_endpoint(
    request: Request,
    total: int = Form(40),
    clear: Optional[str] = Form(None),
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    """Endpoint untuk men-generate fake data rincian anggaran secara instan dari UI."""
    clear_existing = (clear == "1" or clear == "true")
    count = generate_fake_rincian_anggaran(db, total_target=total, clear_existing=clear_existing)

    log_activity(
        db=db,
        action="SEED",
        entity="rincian_anggaran",
        description=f"Generate {count} fake data rincian anggaran (clear={clear_existing})",
        user=user,
        request=request,
    )

    redirect_url = settings.url_path("/pagu?seeded=1")
    return RedirectResponse(url=redirect_url, status_code=303)
