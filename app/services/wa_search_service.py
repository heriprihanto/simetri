"""Pencarian baca-saja dari perintah WhatsApp simetri-cari."""

import re
from html import unescape
from urllib.parse import urlencode

from sqlmodel import Session, select, or_, false

from app.config import get_settings
from app.models.user import User
from app.models.surat import Surat
from app.models.kejadian import Kejadian
from app.models.dokumen import DokumenPerencanaan

COMMAND = re.compile(r'^[!/#]?simetri-cari(?=\s|$)', re.IGNORECASE)
RESULT_LIMIT = 5
HELP = 'Format pencarian: simetri-cari "kata atau kalimat kunci"\nContoh: simetri-cari "rapat RKPD"'


def is_search_request(text: str) -> bool:
    return bool(COMMAND.match(text.strip()))


def parse_search_query(text: str) -> str:
    match = COMMAND.match(text.strip())
    if not match:
        raise ValueError(HELP)
    query = text.strip()[match.end():].strip()
    pairs = {'"': '"', "'": "'", '“': '”', '‘': '’'}
    if query and query[0] in pairs:
        if len(query) < 2 or query[-1] != pairs[query[0]]:
            raise ValueError('Tanda kutip belum ditutup.\n' + HELP)
        query = query[1:-1].strip()
    if not query:
        raise ValueError(HELP)
    if len(query) > 200:
        raise ValueError('Kata kunci maksimal 200 karakter.\n' + HELP)
    return query


def _summary(value: str, limit: int = 180) -> str:
    text = ' '.join(unescape(re.sub(r'<[^>]*>', ' ', value or '')).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def search_whatsapp(text: str, user: User, session: Session) -> dict:
    """Caller must resolve the active user from the sender's registered phone."""
    if not user or not user.is_active:
        return {'status': 'unauthorized', 'reply': 'Akses ditolak. Nomor WhatsApp harus terdaftar dan aktif di Daftar Pengguna SIMETRI.'}
    try:
        query = parse_search_query(text)
    except ValueError as exc:
        return {'status': 'invalid_query', 'reply': str(exc)}

    # Escape LIKE metacharacters: user input is a literal substring, not a pattern.
    pattern = '%' + query.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
    surat_stmt = select(Surat).where(or_(*[
        field.ilike(pattern, escape='!') for field in
        (Surat.nomor_surat, Surat.pihak, Surat.perihal, Surat.keterangan)
    ]))
    kejadian_stmt = select(Kejadian, DokumenPerencanaan).join(
        DokumenPerencanaan, Kejadian.dokumen_id == DokumenPerencanaan.id
    ).where(DokumenPerencanaan.is_active == True).where(or_(*[
        field.ilike(pattern, escape='!') for field in
        (Kejadian.judul_kejadian, Kejadian.uraian_kronologi,
         Kejadian.pihak_pengusul, Kejadian.hasil_pembahasan,
         Kejadian.dasar_dokumen_keputusan, DokumenPerencanaan.nama)
    ]))
    # Match document visibility in the app; missing OPD must never expose city data.
    if user.is_user_opd:
        kejadian_stmt = kejadian_stmt.where(
            DokumenPerencanaan.opd_id == user.opd_id if user.opd_id is not None else false()
        )
    elif user.is_user_bidang:
        kejadian_stmt = kejadian_stmt.where(DokumenPerencanaan.opd_id.is_(None))
    elif not user.is_admin:
        return {'status': 'unauthorized', 'reply': 'Peran pengguna tidak memiliki akses pencarian.'}

    surat_rows = session.exec(surat_stmt.order_by(Surat.tanggal_surat.desc(), Surat.id.desc()).limit(RESULT_LIMIT + 1)).all()
    kejadian_rows = session.exec(kejadian_stmt.order_by(Kejadian.tanggal_kejadian.desc(), Kejadian.id.desc()).limit(RESULT_LIMIT + 1)).all()
    base = get_settings().SERVER_URL.rstrip('/')
    lines = [f'*HASIL PENCARIAN SIMETRI*\nKata kunci: {_summary(query, 200)}']
    lines.append('\n*ARSIP SURAT*')
    for i, surat in enumerate(surat_rows[:RESULT_LIMIT], 1):
        link = base + '/arsip?' + urlencode({'q': query})
        lines.append(f'{i}. {_summary(surat.perihal)}\n   {surat.tanggal_surat:%d/%m/%Y} • {_summary(surat.jenis_surat, 40)}\n   Nomor: {_summary(surat.nomor_surat, 80)}\n   Pihak: {_summary(surat.pihak, 100)}\n   {link}')
    if not surat_rows:
        lines.append('Tidak ada arsip yang cocok.')
    lines.append('\n*KRONOLOGI KEJADIAN*')
    for i, (kejadian, dokumen) in enumerate(kejadian_rows[:RESULT_LIMIT], 1):
        link = base + '/kronologi?' + urlencode({'dokumen_id': dokumen.id, 'q': kejadian.judul_kejadian[:200]})
        lines.append(f'{i}. {_summary(kejadian.judul_kejadian)}\n   {kejadian.tanggal_kejadian:%d/%m/%Y} • {_summary(dokumen.nama, 100)}\n   {_summary(kejadian.uraian_kronologi)}\n   {link}')
    if not kejadian_rows:
        lines.append('Tidak ada kronologi yang cocok.')
    if len(surat_rows) > RESULT_LIMIT or len(kejadian_rows) > RESULT_LIMIT:
        lines.append('\nDitampilkan maksimal 5 hasil terbaru per kategori. Gunakan kata kunci lebih spesifik untuk mempersempit hasil.')
    lines.append('\nTautan dibuka melalui aplikasi SIMETRI (perlu login).')
    return {'status': 'success', 'reply': '\n'.join(lines),
            'arsip_count': min(len(surat_rows), RESULT_LIMIT),
            'kejadian_count': min(len(kejadian_rows), RESULT_LIMIT)}
