"""
SIMETRI Chatbot Service — Gemini AI + Database Context Retrieval.

Chatbot percakapan cerdas yang menjawab pertanyaan pengguna berdasarkan data
Arsip Surat, Kronologi Kejadian, Dokumen Perencanaan, dan Agenda Kegiatan
yang tersimpan di database SIMETRI.
"""

import json
import re
import logging
from datetime import datetime, date
from html import unescape
from typing import Optional

import httpx
from sqlmodel import Session, select, or_, func, false

from app.config import get_settings
from app.models.user import User
from app.models.surat import Surat, AttachmentSurat
from app.models.kejadian import Kejadian, LampiranKejadian
from app.models.dokumen import DokumenPerencanaan
from app.models.agenda import Agenda
from app.models.master import MasterBidang, MasterJenisKejadian

logger = logging.getLogger(__name__)
settings = get_settings()

# Maximum context items per category to send to Gemini
MAX_CONTEXT_ITEMS = 10
# Maximum conversation history turns to keep
MAX_HISTORY_TURNS = 20


def _strip_html(value: str) -> str:
    """Strip HTML tags and decode entities."""
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", value or "")).split())


def _truncate(text: str, limit: int = 300) -> str:
    """Truncate text to a given limit."""
    text = _strip_html(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _date_str(d) -> str:
    """Format date/datetime to readable string."""
    if isinstance(d, datetime):
        return d.strftime("%d/%m/%Y %H:%M")
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    return str(d) if d else ""


def _escape_like(q: str) -> str:
    """Escape LIKE metacharacters for safe substring search."""
    return "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


# ──────────────────────────────────────────────────────────────
# Database Context Retrieval
# ──────────────────────────────────────────────────────────────

def _extract_keywords(question: str) -> list[str]:
    """Extract meaningful keywords from a user question."""
    # Remove common Indonesian stop words and question words
    stop_words = {
        "apa", "siapa", "kapan", "dimana", "bagaimana", "mengapa", "kenapa",
        "yang", "dan", "atau", "di", "ke", "dari", "untuk", "dengan",
        "ini", "itu", "adalah", "ada", "tidak", "bisa", "buat", "bikin",
        "tolong", "cari", "carikan", "tampilkan", "tunjukkan", "jelaskan",
        "berikan", "sebutkan", "ceritakan", "apakah", "berapa", "mana",
        "saya", "kami", "kita", "nya", "pada", "akan", "sudah", "telah",
        "belum", "baru", "lama", "semua", "beberapa", "tentang", "mengenai",
        "terkait", "soal", "perihal", "ya", "dong", "deh", "sih", "lah",
        "kan", "kok", "gimana", "gimna", "gmn", "gak", "nggak", "enggak",
        "jadi", "juga", "lalu", "kemudian", "serta", "maupun", "ataupun",
        "sebuah", "suatu", "hal", "bisa", "mohon", "tolong", "dong",
        "dalam", "luar", "atas", "bawah", "antara", "terhadap", "oleh",
        "melalui", "sejak", "sampai", "hingga", "selama", "saat",
        "ketika", "sebelum", "setelah", "sesudah", "dulu", "nanti",
        "sedang", "masih", "pernah", "harus", "perlu", "wajib", "mesti",
        "boleh", "tak", "tanpa", "bukan", "selain", "kecuali",
    }

    # Normalize and split
    words = re.findall(r"[a-zA-Z0-9]+", question.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    return keywords[:8]  # Max 8 keywords


def retrieve_arsip_context(
    session: Session, question: str, user: User
) -> list[dict]:
    """Search arsip surat based on question keywords."""
    keywords = _extract_keywords(question)
    if not keywords:
        return []

    conditions = []
    for kw in keywords:
        pattern = _escape_like(kw)
        conditions.append(
            or_(
                Surat.nomor_surat.ilike(pattern, escape="!"),
                Surat.pihak.ilike(pattern, escape="!"),
                Surat.perihal.ilike(pattern, escape="!"),
                Surat.keterangan.ilike(pattern, escape="!"),
                Surat.jenis_surat.ilike(pattern, escape="!"),
            )
        )

    stmt = (
        select(Surat)
        .where(or_(*conditions))
        .order_by(Surat.tanggal_surat.desc(), Surat.id.desc())
        .limit(MAX_CONTEXT_ITEMS)
    )

    results = session.exec(stmt).all()

    return [
        {
            "id": s.id,
            "jenis_surat": s.jenis_surat,
            "nomor_surat": s.nomor_surat,
            "tanggal_surat": _date_str(s.tanggal_surat),
            "pihak": s.pihak,
            "perihal": s.perihal,
            "keterangan": _truncate(s.keterangan, 200),
        }
        for s in results
    ]


def retrieve_kejadian_context(
    session: Session, question: str, user: User
) -> list[dict]:
    """Search kronologi kejadian based on question keywords, respecting role access."""
    keywords = _extract_keywords(question)
    if not keywords:
        return []

    conditions = []
    for kw in keywords:
        pattern = _escape_like(kw)
        conditions.append(
            or_(
                Kejadian.judul_kejadian.ilike(pattern, escape="!"),
                Kejadian.uraian_kronologi.ilike(pattern, escape="!"),
                Kejadian.jenis_kejadian.ilike(pattern, escape="!"),
                Kejadian.pihak_pengusul.ilike(pattern, escape="!"),
                Kejadian.hasil_pembahasan.ilike(pattern, escape="!"),
                Kejadian.dasar_dokumen_keputusan.ilike(pattern, escape="!"),
                DokumenPerencanaan.nama.ilike(pattern, escape="!"),
            )
        )

    stmt = (
        select(Kejadian, DokumenPerencanaan)
        .join(DokumenPerencanaan, Kejadian.dokumen_id == DokumenPerencanaan.id)
        .where(DokumenPerencanaan.is_active == True)
        .where(or_(*conditions))
    )

    # Role-based filtering
    if user.is_user_opd:
        stmt = stmt.where(
            DokumenPerencanaan.opd_id == user.opd_id
            if user.opd_id is not None
            else false()
        )
    elif user.is_user_bidang:
        stmt = stmt.where(DokumenPerencanaan.opd_id.is_(None))

    stmt = stmt.order_by(
        Kejadian.tanggal_kejadian.desc(), Kejadian.id.desc()
    ).limit(MAX_CONTEXT_ITEMS)

    results = session.exec(stmt).all()

    return [
        {
            "id": k.id,
            "dokumen_perencanaan": d.nama,
            "jenis_dokumen": d.jenis,
            "tanggal_kejadian": _date_str(k.tanggal_kejadian),
            "jenis_kejadian": k.jenis_kejadian,
            "judul_kejadian": k.judul_kejadian,
            "uraian_kronologi": _truncate(k.uraian_kronologi, 400),
            "pihak_pengusul": _truncate(k.pihak_pengusul, 150),
            "hasil_pembahasan": _truncate(k.hasil_pembahasan, 300),
            "bidang_pj": k.bidang_pj,
        }
        for k, d in results
    ]


def retrieve_dokumen_context(
    session: Session, question: str, user: User
) -> list[dict]:
    """Search dokumen perencanaan based on question keywords."""
    keywords = _extract_keywords(question)
    if not keywords:
        return []

    conditions = []
    for kw in keywords:
        pattern = _escape_like(kw)
        conditions.append(
            or_(
                DokumenPerencanaan.nama.ilike(pattern, escape="!"),
                DokumenPerencanaan.jenis.ilike(pattern, escape="!"),
                DokumenPerencanaan.alias.ilike(pattern, escape="!"),
                DokumenPerencanaan.deskripsi.ilike(pattern, escape="!"),
            )
        )

    stmt = (
        select(DokumenPerencanaan)
        .where(DokumenPerencanaan.is_active == True)
        .where(or_(*conditions))
    )

    # Role-based filtering
    if user.is_user_opd:
        stmt = stmt.where(
            DokumenPerencanaan.opd_id == user.opd_id
            if user.opd_id is not None
            else false()
        )
    elif user.is_user_bidang:
        stmt = stmt.where(DokumenPerencanaan.opd_id.is_(None))

    stmt = stmt.order_by(
        DokumenPerencanaan.updated_at.desc()
    ).limit(MAX_CONTEXT_ITEMS)

    results = session.exec(stmt).all()

    return [
        {
            "id": d.id,
            "nama": d.nama,
            "alias": d.alias,
            "jenis": d.jenis,
            "tahun_awal": d.tahun_awal,
            "tahun_akhir": d.tahun_akhir,
            "status": d.status,
            "cakupan": d.label_cakupan,
            "deskripsi": _truncate(d.deskripsi, 200),
        }
        for d in results
    ]


def retrieve_agenda_context(
    session: Session, question: str, user: User
) -> list[dict]:
    """Search agenda kegiatan based on question keywords."""
    keywords = _extract_keywords(question)
    if not keywords:
        return []

    conditions = []
    for kw in keywords:
        pattern = _escape_like(kw)
        conditions.append(
            or_(
                Agenda.judul.ilike(pattern, escape="!"),
                Agenda.kategori.ilike(pattern, escape="!"),
                Agenda.tempat.ilike(pattern, escape="!"),
                Agenda.keterangan.ilike(pattern, escape="!"),
                Agenda.bidang.ilike(pattern, escape="!"),
            )
        )

    stmt = (
        select(Agenda)
        .where(or_(*conditions))
        .order_by(Agenda.tanggal.desc(), Agenda.id.desc())
        .limit(MAX_CONTEXT_ITEMS)
    )

    results = session.exec(stmt).all()

    return [
        {
            "id": a.id,
            "judul": a.judul,
            "kategori": a.kategori,
            "tanggal": _date_str(a.tanggal),
            "jam": a.rentang_jam,
            "tempat": a.tempat,
            "bidang": a.bidang,
            "keterangan": _truncate(a.keterangan, 200),
        }
        for a in results
    ]


def retrieve_summary_stats(session: Session, user: User) -> dict:
    """Retrieve summary statistics for general questions."""
    total_arsip = session.exec(select(func.count(Surat.id))).one()
    total_agenda = session.exec(select(func.count(Agenda.id))).one()

    kejadian_stmt = (
        select(func.count(Kejadian.id))
        .join(DokumenPerencanaan, Kejadian.dokumen_id == DokumenPerencanaan.id)
        .where(DokumenPerencanaan.is_active == True)
    )
    if user.is_user_opd:
        kejadian_stmt = kejadian_stmt.where(
            DokumenPerencanaan.opd_id == user.opd_id
            if user.opd_id is not None
            else false()
        )
    elif user.is_user_bidang:
        kejadian_stmt = kejadian_stmt.where(DokumenPerencanaan.opd_id.is_(None))
    total_kejadian = session.exec(kejadian_stmt).one()

    total_dokumen = session.exec(
        select(func.count(DokumenPerencanaan.id)).where(
            DokumenPerencanaan.is_active == True
        )
    ).one()

    return {
        "total_arsip_surat": total_arsip,
        "total_kronologi_kejadian": total_kejadian,
        "total_dokumen_perencanaan": total_dokumen,
        "total_agenda_kegiatan": total_agenda,
    }


# ──────────────────────────────────────────────────────────────
# Gemini AI Integration
# ──────────────────────────────────────────────────────────────

SYSTEM_INSTRUCTION = """Kamu adalah **Asisten SIMETRI**, chatbot cerdas milik Badan Perencanaan Pembangunan Daerah (Bappeda) Kota Tegal.

SIMETRI (Sistem Informasi Memori dan Riwayat Perencanaan Pembangunan Daerah) adalah sistem untuk menyimpan jejak proses perencanaan pembangunan, termasuk:
- **Kronologi Kejadian**: Timeline besar proses perencanaan (musrenbang, rapat TAPD, asistensi, evaluasi, dll)
- **Arsip Surat**: Arsip surat kedinasan (surat masuk, keluar, SK, peraturan, dokumen, materi paparan)
- **Dokumen Perencanaan**: RPJPD, RPJMD, RKPD, Perubahan RKPD, Renstra, Renja
- **Agenda Kegiatan**: Rapat, undangan, kunjungan, dan kegiatan lainnya

Tugas kamu:
1. Jawab pertanyaan pengguna BERDASARKAN data konteks yang diberikan dari database SIMETRI.
2. Jika data konteks relevan ditemukan, sajikan informasi secara jelas, terstruktur, dan mudah dipahami.
3. Jika tidak ada data konteks yang relevan, sampaikan bahwa data yang dicari tidak ditemukan di SIMETRI dan sarankan kata kunci lain.
4. Gunakan format markdown untuk jawaban yang terstruktur (bold, list, tabel singkat).
5. Jawab dalam Bahasa Indonesia yang formal namun ramah.
6. Sertakan referensi ID data jika relevan agar pengguna bisa menelusuri lebih lanjut di aplikasi.
7. Jangan mengarang data. Hanya gunakan data konteks yang diberikan.
8. Untuk pertanyaan umum tentang SIMETRI (cara pakai, fitur), jawab dari pengetahuan sistem di atas.

Format konteks data yang diberikan:
- [ARSIP]: Data arsip surat dari database
- [KRONOLOGI]: Data kronologi kejadian dari database
- [DOKUMEN]: Data dokumen perencanaan dari database
- [AGENDA]: Data agenda kegiatan dari database
- [STATISTIK]: Ringkasan jumlah data di sistem
"""


async def call_gemini_api(
    question: str,
    context_data: dict,
    conversation_history: list[dict],
    user: User,
) -> str:
    """Call Google Gemini API with database context and conversation history."""
    gemini_api_key = settings.GEMINI_API_KEY
    if not gemini_api_key:
        return _fallback_response(question, context_data)

    # Build context string from retrieved data
    context_parts = []

    if context_data.get("statistik"):
        stats = context_data["statistik"]
        context_parts.append(
            f"[STATISTIK]\n"
            f"Total Arsip Surat: {stats['total_arsip_surat']}\n"
            f"Total Kronologi Kejadian: {stats['total_kronologi_kejadian']}\n"
            f"Total Dokumen Perencanaan: {stats['total_dokumen_perencanaan']}\n"
            f"Total Agenda Kegiatan: {stats['total_agenda_kegiatan']}"
        )

    if context_data.get("arsip"):
        arsip_items = "\n".join(
            f"- [{a['id']}] {a['jenis_surat']} | No: {a['nomor_surat']} | Tgl: {a['tanggal_surat']} | "
            f"Pihak: {a['pihak']} | Perihal: {a['perihal']}"
            + (f" | Ket: {a['keterangan']}" if a.get("keterangan") else "")
            for a in context_data["arsip"]
        )
        context_parts.append(f"[ARSIP]\n{arsip_items}")

    if context_data.get("kejadian"):
        kej_items = "\n".join(
            f"- [{k['id']}] {k['tanggal_kejadian']} | {k['jenis_kejadian']} | {k['judul_kejadian']} | "
            f"Dokumen: {k['dokumen_perencanaan']} | Bidang: {k['bidang_pj']}"
            + (f"\n  Uraian: {k['uraian_kronologi']}" if k.get("uraian_kronologi") else "")
            + (f"\n  Hasil: {k['hasil_pembahasan']}" if k.get("hasil_pembahasan") else "")
            for k in context_data["kejadian"]
        )
        context_parts.append(f"[KRONOLOGI]\n{kej_items}")

    if context_data.get("dokumen"):
        dok_items = "\n".join(
            f"- [{d['id']}] {d['nama']} | Jenis: {d['jenis']} | "
            f"Tahun: {d['tahun_awal']}-{d['tahun_akhir']} | Status: {d['status']} | Cakupan: {d['cakupan']}"
            for d in context_data["dokumen"]
        )
        context_parts.append(f"[DOKUMEN]\n{dok_items}")

    if context_data.get("agenda"):
        agd_items = "\n".join(
            f"- [{a['id']}] {a['tanggal']} | {a['kategori']} | {a['judul']} | "
            f"Jam: {a['jam']} | Tempat: {a['tempat']} | Bidang: {a['bidang']}"
            for a in context_data["agenda"]
        )
        context_parts.append(f"[AGENDA]\n{agd_items}")

    context_str = "\n\n".join(context_parts) if context_parts else "(Tidak ada data konteks yang ditemukan untuk pertanyaan ini)"

    # Build messages for Gemini
    contents = []

    # Add conversation history
    for msg in conversation_history[-MAX_HISTORY_TURNS:]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    # Add current user message with context
    user_message = (
        f"Pengguna: {user.display_name} (Role: {user.role})\n\n"
        f"Data konteks dari database SIMETRI:\n{context_str}\n\n"
        f"Pertanyaan pengguna:\n{question}"
    )
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    # Call Gemini API with fallback models
    models_to_try = [settings.GEMINI_MODEL, "gemini-3.5-flash", "gemini-3-flash-preview"]
    # Preserve order while eliminating duplicates
    unique_models = list(dict.fromkeys(m for m in models_to_try if m))

    payload = {
        "contents": contents,
        "systemInstruction": {
            "parts": [{"text": SYSTEM_INSTRUCTION}]
        },
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 2048,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        for model in unique_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}"
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()

                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "Maaf, saya tidak bisa memberikan jawaban saat ini.")

                return "Maaf, saya tidak bisa memberikan jawaban saat ini. Silakan coba lagi."

            except httpx.HTTPStatusError as e:
                logger.warning(f"Gemini API model {model} HTTP error: {e.response.status_code} - trying fallback if available")
                continue
            except Exception as e:
                logger.warning(f"Gemini API model {model} error: {e} - trying fallback if available")
                continue

    logger.error("All Gemini API models failed, falling back to local database search.")
    return _fallback_response(question, context_data)


def _fallback_response(question: str, context_data: dict) -> str:
    """Generate a simple response when Gemini API is unavailable."""
    parts = ["**Hasil Pencarian SIMETRI**\n"]

    has_data = False

    if context_data.get("arsip"):
        has_data = True
        parts.append("📋 **Arsip Surat yang ditemukan:**")
        for a in context_data["arsip"]:
            parts.append(
                f"- **{a['perihal']}**\n"
                f"  {a['jenis_surat']} | No: {a['nomor_surat']} | "
                f"Tanggal: {a['tanggal_surat']} | Pihak: {a['pihak']}"
            )
        parts.append("")

    if context_data.get("kejadian"):
        has_data = True
        parts.append("📅 **Kronologi Kejadian yang ditemukan:**")
        for k in context_data["kejadian"]:
            parts.append(
                f"- **{k['judul_kejadian']}**\n"
                f"  {k['tanggal_kejadian']} | {k['jenis_kejadian']} | "
                f"Dokumen: {k['dokumen_perencanaan']}"
            )
        parts.append("")

    if context_data.get("dokumen"):
        has_data = True
        parts.append("📑 **Dokumen Perencanaan yang ditemukan:**")
        for d in context_data["dokumen"]:
            parts.append(
                f"- **{d['nama']}**\n"
                f"  Jenis: {d['jenis']} | Tahun: {d['tahun_awal']}-{d['tahun_akhir']} | "
                f"Status: {d['status']}"
            )
        parts.append("")

    if context_data.get("agenda"):
        has_data = True
        parts.append("📆 **Agenda Kegiatan yang ditemukan:**")
        for a in context_data["agenda"]:
            parts.append(
                f"- **{a['judul']}**\n"
                f"  {a['tanggal']} | {a['kategori']} | Tempat: {a['tempat']}"
            )
        parts.append("")

    if not has_data:
        if context_data.get("statistik"):
            stats = context_data["statistik"]
            parts.append(
                f"Saat ini SIMETRI memiliki:\n"
                f"- **{stats['total_arsip_surat']}** arsip surat\n"
                f"- **{stats['total_kronologi_kejadian']}** kronologi kejadian\n"
                f"- **{stats['total_dokumen_perencanaan']}** dokumen perencanaan\n"
                f"- **{stats['total_agenda_kegiatan']}** agenda kegiatan\n\n"
                f"Silakan ajukan pertanyaan spesifik untuk mencari data."
            )
        else:
            parts.append(
                "Tidak ditemukan data yang sesuai dengan pencarian Anda. "
                "Coba gunakan kata kunci yang berbeda atau lebih spesifik."
            )

    parts.append("\n_⚠️ Jawaban berbasis pencarian database (AI tidak tersedia)._")

    return "\n".join(parts)


async def process_chat_message(
    question: str,
    user: User,
    session: Session,
    conversation_history: list[dict] | None = None,
) -> dict:
    """Process a chat message: retrieve context, call AI, return response."""
    if not question or not question.strip():
        return {
            "status": "error",
            "reply": "Silakan ketik pertanyaan Anda.",
        }

    question = question.strip()
    history = conversation_history or []

    # Retrieve context data from all sources
    context_data = {
        "arsip": retrieve_arsip_context(session, question, user),
        "kejadian": retrieve_kejadian_context(session, question, user),
        "dokumen": retrieve_dokumen_context(session, question, user),
        "agenda": retrieve_agenda_context(session, question, user),
        "statistik": retrieve_summary_stats(session, user),
    }

    # Count total results found
    total_found = (
        len(context_data["arsip"])
        + len(context_data["kejadian"])
        + len(context_data["dokumen"])
        + len(context_data["agenda"])
    )

    # Call Gemini AI
    reply = await call_gemini_api(question, context_data, history, user)

    return {
        "status": "success",
        "reply": reply,
        "context_count": {
            "arsip": len(context_data["arsip"]),
            "kejadian": len(context_data["kejadian"]),
            "dokumen": len(context_data["dokumen"]),
            "agenda": len(context_data["agenda"]),
            "total": total_found,
        },
    }
