"""
Layanan WhatsApp untuk fitur cek Agenda Kegiatan (simetri-agenda).
Menyediakan pengecekan agenda hari ini, besok, atau tanggal tertentu (YYYY-MM-DD / DD-MM-YYYY).
Hanya dapat diakses oleh nomor yang terdaftar dan aktif di Daftar Pengguna SIMETRI.
"""

import re
from datetime import date, datetime, timedelta
from html import unescape
from zoneinfo import ZoneInfo
from typing import Optional

from sqlmodel import Session, select

from app.models.agenda import Agenda
from app.models.user import User

COMMAND = re.compile(r'^[!/#]?simetri-agenda(?=\s|$)', re.IGNORECASE)

DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS_ID = [
    "",
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
]

MONTH_NAMES_ID = {
    "januari": 1, "jan": 1,
    "februari": 2, "feb": 2,
    "maret": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "agustus": 8, "agu": 8, "agt": 8,
    "september": 9, "sep": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "desember": 12, "des": 12,
}

NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def is_agenda_request(text: str) -> bool:
    """Cek apakah pesan merupakan perintah simetri-agenda."""
    if not text:
        return False
    return bool(COMMAND.match(text.strip()))


def _clean_html(value: str) -> str:
    """Bersihkan tag HTML dari teks keterangan agenda."""
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", value or "")).split())


def _format_date_id(d: date) -> str:
    """Format tanggal ke bahasa Indonesia: Hari, DD Bulan YYYY."""
    day_name = DAYS_ID[d.weekday()]
    month_name = MONTHS_ID[d.month]
    return f"{day_name}, {d.day} {month_name} {d.year}"


def parse_agenda_date(text: str, now_jkt: Optional[datetime] = None) -> date:
    """
    Parse tanggal dari argumen pesan simetri-agenda.
    Mendukung:
    - hari ini / today / tanpa parameter
    - besok / tomorrow
    - kemarin / yesterday
    - tanggal YYYY-MM-DD (contoh: simetri-agenda tanggal 2026-10-29)
    - tanggal DD-MM-YYYY (contoh: simetri-agenda tanggal 29-10-2026)
    - format garis miring (DD/MM/YYYY atau YYYY/MM/DD)
    - format nama bulan (29 Oktober 2026)
    """
    if now_jkt is None:
        now_jkt = datetime.now(ZoneInfo("Asia/Jakarta"))
    today = now_jkt.date()

    match = COMMAND.match(text.strip())
    raw_query = text.strip()[match.end():].strip() if match else text.strip()

    q = raw_query.lower()
    # Bersihkan awalan tanggal / tgl
    q = re.sub(r'^(tanggal|tgl)\s*[:=]?\s*', '', q).strip()
    # Bersihkan tanda petik jika ada
    q = q.strip('"\'“”‘’')

    if not q or q in ("hari ini", "hariini", "today"):
        return today
    if q in ("besok", "tomorrow"):
        return today + timedelta(days=1)
    if q in ("kemarin", "yesterday"):
        return today - timedelta(days=1)
    if q in ("lusa",):
        return today + timedelta(days=2)

    # 1. Format YYYY-MM-DD atau YYYY/MM/DD atau YYYY.MM.DD
    m1 = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$', q)
    if m1:
        try:
            return date(int(m1.group(1)), int(m1.group(2)), int(m1.group(3)))
        except ValueError:
            raise ValueError(f"Tanggal '{raw_query}' tidak valid.")

    # 2. Format DD-MM-YYYY atau DD/MM/YYYY atau DD.MM.YYYY
    m2 = re.match(r'^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$', q)
    if m2:
        try:
            return date(int(m2.group(3)), int(m2.group(2)), int(m2.group(1)))
        except ValueError:
            raise ValueError(f"Tanggal '{raw_query}' tidak valid.")

    # 3. Format DD Nama_Bulan YYYY (misal: 29 Oktober 2026)
    m3 = re.match(r'^(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})$', q)
    if m3:
        d = int(m3.group(1))
        m_name = m3.group(2).lower()
        y = int(m3.group(3))
        if m_name in MONTH_NAMES_ID:
            try:
                return date(y, MONTH_NAMES_ID[m_name], d)
            except ValueError:
                raise ValueError(f"Tanggal '{raw_query}' tidak valid.")

    raise ValueError(
        f"Format tanggal '{raw_query}' tidak dikenali.\n"
        "Gunakan format: YYYY-MM-DD atau DD-MM-YYYY."
    )


def format_agenda_reply(target_date: date, items: list[Agenda], user: User) -> str:
    """Format balasan WhatsApp untuk daftar agenda."""
    display_name = user.display_name if user else "Bapak/Ibu"
    tgl_formatted = _format_date_id(target_date)

    if not items:
        return (
            f"Halo *{display_name}*,\n\n"
            f"📅 *AGENDA BAPPEDA KOTA TEGAL*\n"
            f"🗓️ *{tgl_formatted}*\n\n"
            f"_Tidak ada agenda kegiatan yang tercatat pada tanggal ini._\n\n"
            f"💡 *Contoh format pertanyaan lain:*\n"
            f"• *simetri-agenda hari ini*\n"
            f"• *simetri-agenda besok*\n"
            f"• *simetri-agenda tanggal 2026-10-29*\n"
            f"• *simetri-agenda tanggal 29-10-2026*\n\n"
            f"_SIMETRI — Bappeda Kota Tegal_"
        )

    lines = [
        f"Halo *{display_name}*,",
        "",
        f"📅 *AGENDA BAPPEDA KOTA TEGAL*",
        f"🗓️ *{tgl_formatted}*",
        f"📊 Total: *{len(items)} Agenda Kegiatan*",
        "────────────────────",
    ]

    for idx, item in enumerate(items):
        icon = NUMBER_EMOJIS[idx] if idx < len(NUMBER_EMOJIS) else f"{idx + 1}."
        kategori_tag = f"[{item.kategori}]" if item.kategori else ""
        lines.append(f"{icon} *{kategori_tag} {item.judul}*")
        
        # Waktu
        jam_str = item.rentang_jam
        if jam_str and jam_str != "Sehari penuh":
            jam_str += " WIB"
        lines.append(f"   ⏰ *Waktu:* {jam_str or 'Sehari penuh'}")

        # Tempat
        if item.tempat:
            lines.append(f"   📍 *Tempat:* {item.tempat}")

        # Bidang penanggung jawab
        if item.bidang:
            lines.append(f"   🏢 *Bidang:* {item.bidang}")

        # Keterangan ringkas
        if item.keterangan:
            ket_clean = _clean_html(item.keterangan)
            if len(ket_clean) > 160:
                ket_clean = ket_clean[:157] + "…"
            lines.append(f"   📝 *Ket:* {ket_clean}")

        lines.append("")

    lines.append("────────────────────")
    lines.append("_SIMETRI — Bappeda Kota Tegal_")

    return "\n".join(lines)


def handle_whatsapp_agenda(
    text: str,
    user: Optional[User],
    session: Session,
    now_jkt: Optional[datetime] = None,
) -> dict:
    """
    Eksekusi pengecekan agenda via WhatsApp.
    Hanya menerima dari pengguna terdaftar dan aktif.
    """
    if not user or not user.is_active:
        return {
            "status": "unauthorized",
            "reply": (
                "⚠️ *AKSES AGENDA DITOLAK*\n\n"
                "Nomor WhatsApp Anda belum terdaftar atau tidak aktif di Daftar Pengguna SIMETRI.\n\n"
                "Sesuai kebijakan keamanan, fitur pengecekan agenda melalui WhatsApp hanya dapat diakses "
                "oleh pengguna resmi yang telah terdaftar di sistem SIMETRI Bappeda Kota Tegal.\n\n"
                "Silakan hubungi Administrator untuk mendaftarkan nomor Anda."
            ),
        }

    try:
        target_date = parse_agenda_date(text, now_jkt=now_jkt)
    except ValueError as exc:
        return {
            "status": "invalid_date",
            "reply": (
                f"⚠️ *PERINTAH TIDAK SESUAI*\n\n"
                f"{str(exc)}\n\n"
                f"💡 *Contoh format perintah agenda:*\n"
                f"• *simetri-agenda hari ini*\n"
                f"• *simetri-agenda besok*\n"
                f"• *simetri-agenda tanggal 2026-10-29*\n"
                f"• *simetri-agenda tanggal 29-10-2026*"
            ),
        }

    # Query agenda berdasarkan tanggal
    stmt = (
        select(Agenda)
        .where(Agenda.tanggal == target_date)
        .order_by(Agenda.jam_mulai.asc(), Agenda.id.asc())
    )
    items = session.exec(stmt).all()

    reply = format_agenda_reply(target_date, items, user)

    return {
        "status": "success",
        "reply": reply,
        "count": len(items),
        "target_date": target_date.isoformat(),
    }
