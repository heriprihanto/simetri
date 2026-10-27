"""
Router Agenda Kegiatan — kalender dan CRUD agenda.
"""

import json
from datetime import datetime, date
from typing import Optional
from calendar import monthrange

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

from app.database import get_session
from app.middleware import get_current_user
from app.models.agenda import Agenda, Foto, KATEGORI_AGENDA, WARNA_KATEGORI_AGENDA
from app.models.master import MasterBidang
from app.models.surat import Surat
from app.services.audit_service import log_activity

router = APIRouter(prefix="/agenda", tags=["Agenda"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def halaman_agenda(
    request: Request,
    bulan: Optional[str] = Query(None),  # format: "YYYY-MM"
    session: Session = Depends(get_session),
):
    """Halaman agenda kalender bulanan."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Tentukan bulan yang ditampilkan
    today = date.today()
    if bulan:
        try:
            tahun, bln = bulan.split("-")
            current_year = int(tahun)
            current_month = int(bln)
        except (ValueError, IndexError):
            current_year = today.year
            current_month = today.month
    else:
        current_year = today.year
        current_month = today.month

    ym = f"{current_year:04d}-{current_month:02d}"

    # Navigasi bulan
    prev_month = current_month - 1 if current_month > 1 else 12
    prev_year = current_year if current_month > 1 else current_year - 1
    next_month = current_month + 1 if current_month < 12 else 1
    next_year = current_year if current_month < 12 else current_year + 1

    # Fetch agenda bulan ini
    stmt = select(Agenda).where(
        func.to_char(Agenda.tanggal, "YYYY-MM") == ym
    ).order_by(Agenda.tanggal, Agenda.jam_mulai, Agenda.id)

    agenda_list = session.exec(stmt).all()

    # Kelompokkan per tanggal
    agenda_per_tanggal: dict[str, list] = {}
    for a in agenda_list:
        tgl_str = a.tanggal.isoformat()
        if tgl_str not in agenda_per_tanggal:
            agenda_per_tanggal[tgl_str] = []
        agenda_per_tanggal[tgl_str].append(a)

    # Data kalender
    _, days_in_month = monthrange(current_year, current_month)
    first_day_weekday = date(current_year, current_month, 1).weekday()  # 0=Monday

    # Statistik
    stats = {
        "total": len(agenda_list),
        "rapat": sum(1 for a in agenda_list if a.kategori == "Rapat"),
        "undangan": sum(1 for a in agenda_list if a.kategori == "Undangan"),
        "akan_datang": sum(1 for a in agenda_list if a.tanggal >= today),
    }

    # Daftar surat untuk tautan
    surat_list = session.exec(
        select(Surat).order_by(Surat.tanggal_surat.desc()).limit(100)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="agenda/index.html",
        context={
            "user": user,
            "title": "Agenda Kegiatan",
            "agenda_list": agenda_list,
            "agenda_per_tanggal": agenda_per_tanggal,
            "warna": WARNA_KATEGORI_AGENDA,
            "kategori_list": KATEGORI_AGENDA,
            "stats": stats,
            "surat_list": surat_list,
            "current_year": current_year,
            "current_month": current_month,
            "ym": ym,
            "days_in_month": days_in_month,
            "first_day_weekday": first_day_weekday,
            "prev_ym": f"{prev_year:04d}-{prev_month:02d}",
            "next_ym": f"{next_year:04d}-{next_month:02d}",
            "today": today,
            "menu_active": "agenda",
        },
    )


@router.get("/form", response_class=HTMLResponse)
@router.get("/form/{agenda_id}", response_class=HTMLResponse)
async def form_agenda(
    request: Request,
    agenda_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    """Form entri/edit agenda (htmx modal)."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    agenda = None
    if agenda_id:
        agenda = session.get(Agenda, agenda_id)

    surat_list = session.exec(
        select(Surat).order_by(Surat.tanggal_surat.desc()).limit(200)
    ).all()
    bidang_list = session.exec(
        select(MasterBidang).order_by(MasterBidang.id)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="agenda/form.html",
        context={
            "user": user,
            "agenda": agenda,
            "kategori_list": KATEGORI_AGENDA,
            "surat_list": surat_list,
            "bidang_list": bidang_list,
        },
    )


@router.post("/save", response_class=HTMLResponse)
async def save_agenda(
    request: Request,
    session: Session = Depends(get_session),
):
    """Simpan agenda baru atau update."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    form = await request.form()
    agenda_id = form.get("id")

    if agenda_id:
        agenda = session.get(Agenda, int(agenda_id))
        if not agenda:
            return HTMLResponse("Tidak ditemukan", status_code=404)
        agenda.updated_at = datetime.now()
        action = "UPDATE"
    else:
        agenda = Agenda(created_by_id=user.id, created_at=datetime.now())
        action = "CREATE"

    agenda.judul = str(form.get("judul", ""))
    agenda.kategori = str(form.get("kategori", "Rapat"))
    agenda.tanggal = date.fromisoformat(str(form.get("tanggal", "")))
    agenda.jam_mulai = str(form.get("jam_mulai", ""))
    agenda.jam_selesai = str(form.get("jam_selesai", ""))
    agenda.tempat = str(form.get("tempat", "")).strip()
    agenda.bidang = str(form.get("bidang", "")).strip()
    agenda.keterangan = str(form.get("keterangan", ""))

    surat_id = form.get("surat_id")
    agenda.surat_id = int(surat_id) if surat_id else None

    session.add(agenda)
    session.commit()
    session.refresh(agenda)

    log_activity(
        db=session,
        action=action,
        entity="agenda",
        entity_id=agenda.id,
        description=f"{action} agenda: {agenda.judul}",
        user=user,
        request=request,
    )

    bulan_ym = agenda.tanggal.strftime("%Y-%m")
    redirect_url = f"/agenda?bulan={bulan_ym}&saved=1"
    trigger_data = json.dumps({
        "refreshAgenda": {
            "url": redirect_url,
            "message": "Data agenda kegiatan berhasil disimpan",
        }
    })

    return HTMLResponse(
        content="",
        status_code=200,
        headers={
            "HX-Redirect": redirect_url,
            "HX-Trigger": trigger_data,
            "HX-Reswap": "none",
        },
    )


@router.delete("/delete/{agenda_id}", response_class=HTMLResponse)
async def delete_agenda(
    request: Request,
    agenda_id: int,
    session: Session = Depends(get_session),
):
    """Hapus agenda beserta foto-fotonya."""
    user = get_current_user(request)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    agenda = session.get(Agenda, agenda_id)
    if not agenda:
        return HTMLResponse("Tidak ditemukan", status_code=404)

    judul_agenda = agenda.judul
    bulan_ym = agenda.tanggal.strftime("%Y-%m")

    # Hapus foto terkait
    foto_list = session.exec(
        select(Foto).where(Foto.agenda_id == agenda_id)
    ).all()
    for f in foto_list:
        session.delete(f)

    session.delete(agenda)
    session.commit()

    log_activity(
        db=session,
        action="DELETE",
        entity="agenda",
        entity_id=agenda_id,
        description=f"Hapus agenda: {judul_agenda}",
        user=user,
        request=request,
    )

    redirect_url = f"/agenda?bulan={bulan_ym}&deleted=1"
    trigger_data = json.dumps({
        "refreshAgenda": {
            "url": redirect_url,
            "message": "Agenda kegiatan berhasil dihapus",
        }
    })

    return HTMLResponse(
        content="",
        status_code=200,
        headers={
            "HX-Redirect": redirect_url,
            "HX-Trigger": trigger_data,
        },
    )
