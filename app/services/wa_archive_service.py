"""
Service WhatsApp Archive — Otomatisasi Arsip Surat Masuk, Keluar, Dokumen via WhatsApp.
Menerima media foto/dokumen dari WhatsApp Gateway, mengunggah ke Google Drive,
dan mencatat arsip surat beserta lampirannya ke database SIMETRI.
"""

import asyncio
import logging
import mimetypes
import os
import re
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlmodel import Session, desc, select

from app.config import get_settings
from app.models.surat import AttachmentSurat, Surat, JENIS_SURAT, label_pihak
from app.models.user import User
from app.services.audit_service import log_activity
from app.services.gdrive_service import get_or_create_folder, upload_file

logger = logging.getLogger(__name__)
settings = get_settings()

# Sesi aktif arsip per pengirim untuk mendukung multi-file media dalam waktu berdekatan
ACTIVE_ARCHIVE_SESSIONS: dict[str, dict[str, Any]] = {}
SENDER_LOCKS: dict[str, asyncio.Lock] = {}
SESSION_EXPIRY_SECONDS = 120  # Window 2 menit

# Media yang baru diterima namun belum diarsipkan (window 3 menit)
RECENT_UNARCHIVED_MEDIA: dict[str, list[dict[str, Any]]] = {}

# Perintah arsip pending yang menunggu media (window 2 menit)
PENDING_ARCHIVE_COMMANDS: dict[str, dict[str, Any]] = {}


def normalize_phone_number(phone: Optional[str]) -> str:
    """
    Menstandarkan nomor telepon ke format digit Indonesia '628xxxxxxxx'.
    Menghapus domain WhatsApp (@s.whatsapp.net), karakter non-digit, spasi, tanda tambah/kurang,
    dan menyeragamkan awalan 08 / 8 / +62 menjadi 628.
    """
    if not phone:
        return ""
    clean = str(phone).split("@")[0]
    digits = re.sub(r"\D", "", clean)
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    return digits


def get_user_by_whatsapp_phone(
    phone: Optional[str], session: Optional[Session] = None
) -> Optional[User]:
    """
    Mencari pengguna aktif (is_active = True) di database SIMETRI yang nomor WhatsApp-nya
    cocok dengan nomor pengirim.
    """
    norm_phone = normalize_phone_number(phone)
    if not norm_phone:
        return None

    if session is None:
        from app.database import engine

        db_context = Session(engine)
        should_close = True
    else:
        db_context = session
        should_close = False

    try:
        users = db_context.exec(
            select(User)
            .where(User.is_active == True)
            .where(User.no_hp != "")
            .where(User.no_hp.is_not(None))
        ).all()
        for u in users:
            norm_u = normalize_phone_number(u.no_hp)
            if norm_u == norm_phone:
                return u
        return None
    finally:
        if should_close:
            db_context.close()


find_user_by_phone = get_user_by_whatsapp_phone


def get_sender_lock(clean_phone: str) -> asyncio.Lock:
    """Mendapatkan asyncio.Lock khusus per nomor pengirim untuk mencegah race condition."""
    if clean_phone not in SENDER_LOCKS:
        SENDER_LOCKS[clean_phone] = asyncio.Lock()
    return SENDER_LOCKS[clean_phone]


def register_active_archive(clean_phone: str, surat_id: int) -> None:
    """Mencatat sesi arsip aktif per nomor pengirim."""
    now = time.time()
    ACTIVE_ARCHIVE_SESSIONS[clean_phone] = {
        "surat_id": surat_id,
        "created_at": now,
        "last_activity": now,
    }


def get_active_archive(clean_phone: str, session: Optional[Session] = None) -> Optional[int]:
    """
    Mengambil ID surat arsip yang masih aktif dalam window waktu SESSION_EXPIRY_SECONDS.
    Mendukung pengecekan in-memory dan database fallback.
    """
    if not clean_phone:
        return None

    now = time.time()
    # 1. Cek in-memory session
    sess_data = ACTIVE_ARCHIVE_SESSIONS.get(clean_phone)
    if sess_data:
        if now - sess_data.get("last_activity", 0) <= SESSION_EXPIRY_SECONDS:
            sess_data["last_activity"] = now
            return sess_data["surat_id"]
        else:
            ACTIVE_ARCHIVE_SESSIONS.pop(clean_phone, None)

    # 2. Fallback: cek database jika surat baru dibuat dalam window waktu terakhir
    try:
        from app.database import engine

        db = session or Session(engine)
        should_close = session is None
        try:
            cutoff = datetime.now() - timedelta(seconds=SESSION_EXPIRY_SECONDS)
            query = (
                select(Surat)
                .where(Surat.created_at >= cutoff)
                .where(Surat.keterangan.like(f"%{clean_phone}%"))
                .order_by(desc(Surat.id))
            )
            recent_surat = db.exec(query).first()
            if recent_surat and recent_surat.id:
                register_active_archive(clean_phone, recent_surat.id)
                return recent_surat.id
        finally:
            if should_close:
                db.close()
    except Exception as e:
        logger.error(f"[WA Archive] Gagal memeriksa active archive dari database: {e}")

    return None


def register_unarchived_media(
    clean_phone: str,
    media_items: list[dict[str, Any]],
    msg_id: Optional[str] = None,
    caption: str = "",
) -> None:
    """Menyimpan media sementara yang belum diarsipkan per nomor pengirim."""
    if not clean_phone or not media_items:
        return
    now = time.time()
    entries = RECENT_UNARCHIVED_MEDIA.get(clean_phone, [])
    valid_entries = [e for e in entries if now - e.get("timestamp", 0) <= 180]
    valid_entries.append({
        "media_items": media_items,
        "msg_id": msg_id,
        "caption": caption,
        "timestamp": now,
    })
    RECENT_UNARCHIVED_MEDIA[clean_phone] = valid_entries


def pop_recent_unarchived_media(
    clean_phone: str,
    msg_id: Optional[str] = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Mengambil dan menghapus media unarchived terbaru.
    Mengembalikan tuple (media_items, caption).
    """
    if not clean_phone:
        return [], ""
    now = time.time()
    entries = RECENT_UNARCHIVED_MEDIA.get(clean_phone, [])
    valid_entries = [e for e in entries if now - e.get("timestamp", 0) <= 180]

    if not valid_entries:
        RECENT_UNARCHIVED_MEDIA.pop(clean_phone, None)
        return [], ""

    if msg_id:
        for idx, entry in enumerate(valid_entries):
            if entry.get("msg_id") == msg_id:
                matched = valid_entries.pop(idx)
                RECENT_UNARCHIVED_MEDIA[clean_phone] = valid_entries
                return matched.get("media_items", []), matched.get("caption", "")

    entry = valid_entries.pop()
    RECENT_UNARCHIVED_MEDIA[clean_phone] = valid_entries
    return entry.get("media_items", []), entry.get("caption", "")


def register_pending_archive_command(
    clean_phone: str,
    meta: dict[str, Any],
    raw_body: str,
) -> None:
    """Mencatat perintah arsip pending yang menunggu pengiriman/forward file."""
    if not clean_phone:
        return
    PENDING_ARCHIVE_COMMANDS[clean_phone] = {
        "meta": meta,
        "raw_body": raw_body,
        "timestamp": time.time(),
    }


def pop_pending_archive_command(clean_phone: str) -> Optional[dict[str, Any]]:
    """Mengambil dan menghapus perintah arsip pending jika masih dalam window 120s."""
    if not clean_phone:
        return None
    entry = PENDING_ARCHIVE_COMMANDS.pop(clean_phone, None)
    if entry and time.time() - entry.get("timestamp", 0) <= 120:
        return entry
    return None


def is_forwarded_message(payload: dict[str, Any], text: Optional[str] = None) -> bool:
    """
    Mengecek apakah pesan WhatsApp merupakan pesan terusan (forwarded message).
    Mendukung flag forwarded dari GoWA / whatsmeow, context_info, dan text marker.
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("forwarded") is True or payload.get("is_forwarded") is True:
        return True
    try:
        if int(payload.get("forwarding_score") or 0) > 0:
            return True
    except (ValueError, TypeError):
        pass

    ci = payload.get("context_info")
    if isinstance(ci, dict):
        if ci.get("is_forwarded") is True:
            return True
        try:
            if int(ci.get("forwarding_score") or 0) > 0:
                return True
        except (ValueError, TypeError):
            pass

    body = (text or payload.get("body") or payload.get("caption") or "").strip()
    if re.search(r'^(?:\[(?:forwarded|diteruskan)\]|(?:forwarded|diteruskan)\s*:)', body, re.IGNORECASE):
        return True
    if re.search(r'\b(?:terusan|forward(?:an)?)\b', body, re.IGNORECASE):
        return True

    return False


def is_update_command(text: Optional[str]) -> bool:
    """Mengecek apakah pesan merupakan perintah koreksi/update perihal pada sesi arsip aktif."""
    if not text:
        return False
    clean = text.strip()
    return bool(re.search(r'^(?:ubah|ganti|koreksi|update)?\s*(?:perihal|nomor|no\.?)\s*[:=]?', clean, re.IGNORECASE))


def is_archive_request(text: Optional[str]) -> bool:
    """
    Mengecek apakah pesan WhatsApp memuat kata kunci 'arsipkan'.
    Contoh: 'arsipkan', 'arsipkan surat masuk...', '/arsipkan', '!arsipkan'
    """
    if not text:
        return False
    return bool(re.search(r'(?:^|\s|[!/#])arsipkan\b', text, re.IGNORECASE))


def parse_archive_command(
    caption: str,
    sender_name: str = "",
    sender_phone: str = "",
    is_forwarded: bool = False,
    media_filename: Optional[str] = None,
) -> dict[str, Any]:
    """
    Mengekstraksi metadata surat dari caption pesan WhatsApp.
    - Jenis surat (Surat Masuk, Keluar, SK, Dokumen, Peraturan, dll.)
    - Nomor surat (opsional, auto-generate jika tidak ada)
    - Tanggal surat (opsional, default hari ini)
    - Pihak pengirim/penerima
    - Perihal
    Mendukung pesan terusan (forwarding) dan penentuan perihal dari nama file jika caption kosong.
    """
    text = (caption or "").strip()
    text_lower = text.lower()

    # 1. Deteksi Jenis Surat
    jenis = "Surat Masuk"  # Default
    if re.search(r'\b(surat\s+keluar|keluar)\b', text_lower):
        jenis = "Surat Keluar"
    elif re.search(r'\b(surat\s+keputusan|keputusan|\bsk\b)\b', text_lower):
        jenis = "Surat Keputusan"
    elif re.search(r'\b(peraturan|perwal|perda)\b', text_lower):
        jenis = "Peraturan"
    elif re.search(r'\b(paparan|materi)\b', text_lower):
        jenis = "Materi Paparan"
    elif re.search(r'\b(dokumen\s+lainnya)\b', text_lower):
        jenis = "Dokumen Lainnya"
    elif re.search(r'\b(dokumen)\b', text_lower):
        jenis = "Dokumen"
    elif re.search(r'\b(surat\s+masuk|masuk)\b', text_lower):
        jenis = "Surat Masuk"

    # 2. Deteksi Tanggal Surat
    tanggal_surat = date.today()
    m_tgl = re.search(
        r'(?:tanggal|tgl)\s*[:=]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[-\/]\d{1,2}[-\/]\d{4})',
        text,
        re.IGNORECASE,
    )
    if m_tgl:
        raw_tgl = m_tgl.group(1).replace("/", "-")
        try:
            parts = raw_tgl.split("-")
            if len(parts[0]) == 4:
                tanggal_surat = date(int(parts[0]), int(parts[1]), int(parts[2]))
            else:
                tanggal_surat = date(int(parts[2]), int(parts[1]), int(parts[0]))
        except Exception:
            tanggal_surat = date.today()

    # 3. Deteksi Nomor Surat
    now = datetime.now()
    m_no = re.search(
        r'(?:nomor\s+surat|nomor|no\.?)\s*[:=]?\s*([a-zA-Z0-9\/\.\-_]+)',
        text,
        re.IGNORECASE,
    )
    if m_no:
        nomor_surat = m_no.group(1).strip()
    else:
        nomor_surat = f"WA/{now.strftime('%Y%m%d')}/{now.strftime('%H%M%S')}"

    # 4. Deteksi Pihak (Pengirim / Penerima)
    m_pihak = re.search(
        r'(?:pengirim|penerima|pihak|dari|kepada)\s*[:=]?\s*([^\n,]+)',
        text,
        re.IGNORECASE,
    )
    clean_sender = sender_name.strip() if sender_name else (sender_phone.split("@")[0] if sender_phone else "Pengirim WA")
    if m_pihak:
        pihak = m_pihak.group(1).strip()
    else:
        if jenis == "Surat Keluar":
            pihak = "Penerima Dokumen"
        elif is_forwarded:
            pihak = f"{clean_sender} (Terusan)"
        else:
            pihak = clean_sender

    # 5. Deteksi Perihal
    m_perihal = re.search(
        r'(?:perihal|hal|tentang)\s*[:=]?\s*([^\n]+)',
        text,
        re.IGNORECASE,
    )
    if m_perihal:
        raw_p = m_perihal.group(1).strip()
        cleaned_p = re.split(
            r'\s+(?:nomor|no\.?|tanggal|tgl|dari|kepada|pihak)\s*[:=]?',
            raw_p,
            flags=re.IGNORECASE,
        )[0].strip()
        perihal = cleaned_p if cleaned_p else raw_p
    else:
        # Bersihkan teks caption dari keyword 'arsipkan' dan bagian terstruktur
        clean_text = re.sub(r'^[!/#]?arsipkan[:\s]*', '', text, flags=re.IGNORECASE)
        clean_text = re.sub(
            r'^(surat\s+masuk|surat\s+keluar|surat\s+keputusan|sk|dokumen|peraturan|materi\s+paparan)[\s:,]*',
            '',
            clean_text,
            flags=re.IGNORECASE,
        ).strip()
        if m_no:
            clean_text = clean_text.replace(m_no.group(0), "")
        if m_pihak:
            clean_text = clean_text.replace(m_pihak.group(0), "")
        if m_tgl:
            clean_text = clean_text.replace(m_tgl.group(0), "")

        clean_text = re.sub(r'[\s,;:_-]+$', '', clean_text).strip()

        if len(clean_text) >= 3:
            perihal = clean_text
        elif media_filename:
            # Ambil nama file tanpa ekstensi sebagai perihal
            stem = Path(media_filename).stem.replace("_", " ").replace("-", " ").strip()
            # Bersihkan prefix angka acak / timestamp GoWA
            cleaned_stem = re.sub(r'^\d{8,14}[\s_]*', '', stem)
            if len(cleaned_stem) >= 3 and not re.match(r'^(wa_media|wa|img|doc|media|file|image)', cleaned_stem, re.IGNORECASE):
                perihal = cleaned_stem.title()
            elif is_forwarded:
                perihal = f"Arsip Dokumen Terusan dari {clean_sender}"
            else:
                perihal = f"Arsip Dokumen dari {clean_sender}"
        elif is_forwarded:
            perihal = f"Arsip Dokumen Terusan dari {clean_sender}"
        else:
            perihal = f"Arsip Surat dari {clean_sender}"

    # 6. Keterangan
    waktu_str = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%d/%m/%Y %H:%M:%S")
    if is_forwarded:
        keterangan = f"Diarsipkan otomatis dari pesan terusan (forwarding) WhatsApp ({clean_sender} - {sender_phone}) pada {waktu_str} WIB"
    else:
        keterangan = f"Diarsipkan otomatis via WhatsApp ({clean_sender} - {sender_phone}) pada {waktu_str} WIB"

    return {
        "jenis_surat": jenis,
        "nomor_surat": nomor_surat,
        "tanggal_surat": tanggal_surat,
        "pihak": pihak,
        "perihal": perihal,
        "keterangan": keterangan,
    }


def payload_has_media(payload: dict[str, Any]) -> bool:
    """
    Mengecek apakah payload WhatsApp mengandung attachment media (foto, dokumen, dsb).
    """
    if not isinstance(payload, dict):
        return False

    media_keys = (
        "image", "document", "video", "audio", "file", "media",
        "images", "documents", "videos", "files", "attachments", "media_list",
        "file_path", "image_path", "media_path", "path",
        "url", "file_url", "image_url", "media_url",
    )
    for k in media_keys:
        val = payload.get(k)
        if val:
            if isinstance(val, (dict, list)):
                return True
            if isinstance(val, str) and val.strip() and val.strip() != "-":
                return True
    return False


def format_file_size(sb: int) -> str:
    """Format ukuran file dalam bytes ke string yang mudah dibaca."""
    if sb < 1024:
        return f"{sb} B"
    elif sb < 1024 * 1024:
        return f"{sb / 1024:.1f} KB"
    else:
        return f"{sb / (1024 * 1024):.1f} MB"


def upload_media_dict_to_gdrive(media: dict[str, Any], folder_id: str) -> dict[str, Any]:
    """Mengunggah satu media dict ke Google Drive dan mengembalikan metadata drive."""
    tmp_path = None
    drive_res = {}
    try:
        ext = Path(media["filename"]).suffix or ".jpg"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(media["content"])
            tmp_path = tmp.name

        drive_res = upload_file(
            local_path=tmp_path,
            filename=media["filename"],
            mime_type=media["mime_type"],
            folder_id=folder_id,
        ) or {}
    except Exception as e:
        logger.error(f"[WA Archive] Gagal upload media {media.get('filename')} ke Google Drive: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return drive_res


async def extract_media_items_from_payload(
    payload: dict[str, Any],
    device_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Mengambil semua file media (foto/dokumen) yang dikirimkan bersama pesan WhatsApp.
    Mendukung direct URL di payload, local file path, nested dict, list of files,
    dan GoWA REST download API.
    """
    dev_id = device_id or settings.WA_DEVICE_ID
    server_base = settings.wa_server_url
    storage_path = Path(settings.WA_STORAGE_PATH) if getattr(settings, "WA_STORAGE_PATH", None) else None
    media_dir = Path(settings.WA_MEDIA_DIR) if getattr(settings, "WA_MEDIA_DIR", None) else None

    # Kumpulkan pasangan candidate: (path_or_url, custom_filename, is_url)
    candidates: list[tuple[str, Optional[str], bool]] = []

    def _add_candidate(val: Any, custom_name: Optional[str] = None) -> None:
        if not val:
            return
        if isinstance(val, str):
            val_clean = val.strip()
            if not val_clean or val_clean == "-":
                return
            if val_clean.startswith("http://") or val_clean.startswith("https://"):
                candidates.append((val_clean, custom_name, True))
            else:
                candidates.append((val_clean, custom_name, False))
        elif isinstance(val, dict):
            c_name = val.get("filename") or val.get("file_name") or val.get("name") or custom_name
            for k in ("path", "file_path", "image_path", "media_path"):
                p_val = val.get(k)
                if p_val and isinstance(p_val, str) and p_val.strip() and p_val.strip() != "-":
                    candidates.append((p_val.strip(), c_name, False))
            for k in ("url", "file_url", "image_url", "media_url"):
                u_val = val.get(k)
                if u_val and isinstance(u_val, str) and u_val.strip():
                    candidates.append((u_val.strip(), c_name, True))
        elif isinstance(val, list):
            for item in val:
                _add_candidate(item, custom_name)

    # 1. Ekstraksi candidate dari direct keys
    for k in ("file_path", "image_path", "media_path", "path"):
        _add_candidate(payload.get(k))
    for k in ("url", "file_url", "image_url", "media_url"):
        _add_candidate(payload.get(k))

    # 2. Ekstraksi candidate dari nested single keys
    for media_key in ("image", "document", "video", "audio", "file", "media"):
        _add_candidate(payload.get(media_key))

    # 3. Ekstraksi candidate dari list keys
    for list_key in ("images", "documents", "videos", "files", "attachments", "media_list"):
        _add_candidate(payload.get(list_key))

    results: list[dict[str, Any]] = []
    seen_identifiers: set[str] = set()

    # Proses semua candidate
    for target, custom_name, is_url in candidates:
        if is_url:
            if target in seen_identifiers:
                continue
            seen_identifiers.add(target)
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(target)
                    if resp.status_code == 200 and resp.content:
                        filename = custom_name or Path(target.split("?")[0]).name or f"wa_media_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                        mime = resp.headers.get("content-type") or mimetypes.guess_type(filename)[0] or "image/jpeg"
                        results.append({
                            "content": resp.content,
                            "filename": filename,
                            "mime_type": mime,
                            "size_bytes": len(resp.content),
                        })
            except Exception as e:
                logger.error(f"[WA Archive] Gagal download dari URL {target}: {e}")
        else:
            # File lokal
            candidate_paths = [Path(target)]
            if storage_path:
                candidate_paths.append(storage_path / target.lstrip("/"))
                candidate_paths.append(storage_path.parent / target.lstrip("/"))
                candidate_paths.append(storage_path / "statics" / "media" / Path(target).name)
                candidate_paths.append(storage_path.parent / "statics" / "media" / Path(target).name)
            if media_dir:
                candidate_paths.append(media_dir / Path(target).name)
                candidate_paths.append(media_dir / target.lstrip("/"))
                candidate_paths.append(media_dir.parent / target.lstrip("/"))

            found_file = False
            for cp in candidate_paths:
                if cp.exists() and cp.is_file():
                    abs_key = str(cp.resolve())
                    if abs_key in seen_identifiers:
                        found_file = True
                        break
                    seen_identifiers.add(abs_key)
                    try:
                        content = cp.read_bytes()
                        mime, _ = mimetypes.guess_type(str(cp))
                        filename = custom_name or cp.name
                        results.append({
                            "content": content,
                            "filename": filename,
                            "mime_type": mime or "image/jpeg",
                            "size_bytes": len(content),
                        })
                        found_file = True
                        break
                    except Exception as e:
                        logger.error(f"[WA Archive] Gagal membaca file lokal {cp}: {e}")
            if found_file:
                continue

            # Jika file lokal tidak ditemukan, coba unduh via HTTP dari server GoWA jika target adalah path relatif
            if server_base and not target.startswith("http"):
                file_url = f"{server_base}/{target.lstrip('/')}"
                if file_url not in seen_identifiers:
                    seen_identifiers.add(file_url)
                    try:
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            resp = await client.get(file_url)
                            if resp.status_code == 200 and resp.content:
                                filename = custom_name or Path(target).name or f"wa_media_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                                mime = resp.headers.get("content-type") or mimetypes.guess_type(filename)[0] or "image/jpeg"
                                results.append({
                                    "content": resp.content,
                                    "filename": filename,
                                    "mime_type": mime,
                                    "size_bytes": len(resp.content),
                                })
                    except Exception as e:
                        logger.debug(f"[WA Archive] Gagal unduh dari URL fallback server GoWA {file_url}: {e}")

    # 4. Jika belum ada file yang berhasil dibaca, coba endpoint GoWA REST download
    if not results:
        msg_id = payload.get("id") or payload.get("message_id")
        sender_raw = payload.get("from") or payload.get("chat_id") or ""
        clean_phone = re.sub(r'[^0-9]', '', sender_raw.split('@')[0])

        if msg_id and clean_phone:
            download_api_url = f"{server_base}/message/{msg_id}/download"
            headers = {"X-Device-Id": dev_id}
            params = {"phone": clean_phone}

            try:
                logger.info(f"[WA Archive] Memanggil GoWA Download API: {download_api_url} (phone: {clean_phone})")
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(download_api_url, params=params, headers=headers)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        res_data = res_json.get("results") or {}
                        file_path = res_data.get("file_path") or res_json.get("file_path")

                        if file_path:
                            candidates_gowa = [Path(file_path)]
                            if storage_path:
                                candidates_gowa.append(storage_path / file_path.lstrip("/"))
                            if media_dir:
                                candidates_gowa.append(media_dir / Path(file_path).name)

                            loaded = False
                            for cp in candidates_gowa:
                                if cp.exists() and cp.is_file():
                                    content = cp.read_bytes()
                                    mime, _ = mimetypes.guess_type(str(cp))
                                    results.append({
                                        "content": content,
                                        "filename": cp.name,
                                        "mime_type": mime or "image/jpeg",
                                        "size_bytes": len(content),
                                    })
                                    loaded = True
                                    break

                            if not loaded:
                                file_url = f"{server_base}/{file_path.lstrip('/')}"
                                logger.info(f"[WA Archive] Mengunduh file dari GoWA server: {file_url}")
                                f_resp = await client.get(file_url)
                                if f_resp.status_code == 200 and f_resp.content:
                                    fname = Path(file_path).name
                                    mime = f_resp.headers.get("content-type") or mimetypes.guess_type(fname)[0] or "image/jpeg"
                                    results.append({
                                        "content": f_resp.content,
                                        "filename": fname,
                                        "mime_type": mime,
                                        "size_bytes": len(f_resp.content),
                                    })
            except Exception as e:
                logger.error(f"[WA Archive] Error memanggil download API GoWA: {e}")

    # 5. Jika masih belum ada dan ada replied_to_id, coba unduh media dari pesan yang dikutip
    if not results and payload.get("replied_to_id"):
        replied_id = payload.get("replied_to_id")
        sender_raw = payload.get("from") or payload.get("chat_id") or ""
        replied_media = await extract_media_from_replied_message(replied_id, sender_phone=sender_raw, device_id=dev_id)
        if replied_media:
            results.extend(replied_media)

    return results


async def extract_media_from_replied_message(
    replied_msg_id: str,
    sender_phone: str,
    device_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Mengambil media dari pesan yang di-reply/dikutip melalui GoWA download API atau unarchived cache.
    """
    if not replied_msg_id:
        return []

    clean_phone = re.sub(r'[^0-9]', '', sender_phone.split('@')[0]) if sender_phone else ""

    # 1. Cek recent unarchived media cache terlebih dahulu
    cached_items, _ = pop_recent_unarchived_media(clean_phone, msg_id=replied_msg_id)
    if cached_items:
        logger.info(f"[WA Archive] Ditemukan {len(cached_items)} file dari cache unarchived untuk replied ID {replied_msg_id}")
        return cached_items

    # 2. Panggil GoWA download API
    dev_id = device_id or settings.WA_DEVICE_ID
    server_base = settings.wa_server_url
    storage_path = Path(settings.WA_STORAGE_PATH) if getattr(settings, "WA_STORAGE_PATH", None) else None
    media_dir = Path(settings.WA_MEDIA_DIR) if getattr(settings, "WA_MEDIA_DIR", None) else None

    download_api_url = f"{server_base}/message/{replied_msg_id}/download"
    headers = {"X-Device-Id": dev_id}
    params = {"phone": clean_phone} if clean_phone else {}

    try:
        logger.info(f"[WA Archive] Memanggil download API untuk replied message {replied_msg_id} (phone: {clean_phone})")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(download_api_url, params=params, headers=headers)
            if resp.status_code == 200:
                res_json = resp.json()
                res_data = res_json.get("results") or {}
                file_path = res_data.get("file_path") or res_json.get("file_path")
                custom_name = res_data.get("filename")

                if file_path:
                    candidate_paths = [Path(file_path)]
                    if storage_path:
                        candidate_paths.append(storage_path / file_path.lstrip("/"))
                        candidate_paths.append(storage_path.parent / file_path.lstrip("/"))
                        candidate_paths.append(storage_path / "statics" / "media" / Path(file_path).name)
                        candidate_paths.append(storage_path.parent / "statics" / "media" / Path(file_path).name)
                    if media_dir:
                        candidate_paths.append(media_dir / Path(file_path).name)
                        candidate_paths.append(media_dir / file_path.lstrip("/"))

                    for cp in candidate_paths:
                        if cp.exists() and cp.is_file():
                            content = cp.read_bytes()
                            mime, _ = mimetypes.guess_type(str(cp))
                            fname = custom_name or cp.name
                            return [{
                                "content": content,
                                "filename": fname,
                                "mime_type": mime or "image/jpeg",
                                "size_bytes": len(content),
                            }]

                    # Coba unduh via HTTP dari server GoWA
                    file_url = f"{server_base}/{file_path.lstrip('/')}"
                    f_resp = await client.get(file_url)
                    if f_resp.status_code == 200 and f_resp.content:
                        fname = custom_name or Path(file_path).name
                        mime = f_resp.headers.get("content-type") or mimetypes.guess_type(fname)[0] or "image/jpeg"
                        return [{
                            "content": f_resp.content,
                            "filename": fname,
                            "mime_type": mime,
                            "size_bytes": len(f_resp.content),
                        }]
    except Exception as e:
        logger.error(f"[WA Archive] Gagal download replied media dari GoWA ({replied_msg_id}): {e}")

    return []


def update_recent_archive_metadata(
    surat_id: int,
    new_caption: str,
    sender_phone: str = "",
    session: Optional[Session] = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """
    Memperbarui perihal/nomor/pihak/jenis arsip surat yang baru saja dibuat (misal dari forwarding),
    ketika user mengirimkan keterangan detail atau koreksi perihal.
    """
    clean_sender = sender_phone.split("@")[0] if sender_phone else "Pengirim WA"

    meta = parse_archive_command(new_caption, sender_name=clean_sender, sender_phone=sender_phone)

    if session is None:
        from app.database import engine
        db_context = Session(engine)
        should_close = True
    else:
        db_context = session
        should_close = False

    try:
        actor_user = user
        if not actor_user:
            actor_user = get_user_by_whatsapp_phone(sender_phone, session=db_context)
            if not actor_user and clean_sender:
                actor_user = get_user_by_whatsapp_phone(clean_sender, session=db_context)

        if not actor_user:
            return {
                "status": "unauthorized",
                "reply": (
                    f"⛔ *AKSES DITOLAK*\n\n"
                    f"Nomor WhatsApp Anda belum terdaftar dalam Daftar Pengguna SIMETRI."
                ),
            }

        surat = db_context.get(Surat, surat_id)
        if not surat:
            return {"status": "error", "message": f"Surat ID {surat_id} tidak ditemukan"}

        # Update perihal jika terdeteksi
        if meta.get("perihal") and not meta["perihal"].startswith("Arsip Surat dari"):
            surat.perihal = meta["perihal"]

        # Update jenis surat jika bukan default atau user menyebut eksplisit
        raw_lower = new_caption.lower()
        if any(j.lower() in raw_lower for j in JENIS_SURAT if j != "Surat Masuk"):
            surat.jenis_surat = meta["jenis_surat"]

        # Update nomor surat jika bukan auto-generated WA/
        if not meta["nomor_surat"].startswith("WA/"):
            surat.nomor_surat = meta["nomor_surat"]

        # Update pihak jika user menyebut eksplisit
        if meta.get("pihak") and meta["pihak"] != clean_sender:
            surat.pihak = meta["pihak"]

        surat.updated_at = datetime.now()
        db_context.add(surat)
        db_context.commit()
        db_context.refresh(surat)

        log_activity(
            db=db_context,
            action="UPDATE",
            entity="surat",
            entity_id=surat.id,
            description=f"Pembaruan metadata arsip surat {surat.nomor_surat} via WhatsApp ({sender_phone}): {surat.perihal}",
            user=actor_user,
        )

        all_att = db_context.exec(
            select(AttachmentSurat).where(AttachmentSurat.surat_id == surat.id)
        ).all()
        att_count = len(all_att)

        tgl_display = surat.tanggal_surat.strftime("%d/%m/%Y")
        label_p = label_pihak(surat.jenis_surat)
        petugas_info = f"👤 *Petugas:* {actor_user.name}\n" if actor_user and actor_user.name else ""

        reply_text = (
            f"✏️ *DATA ARSIP BERHASIL DIPERBARUI*\n\n"
            f"📂 *Jenis Surat:* {surat.jenis_surat}\n"
            f"📄 *Nomor Surat:* {surat.nomor_surat}\n"
            f"📅 *Tanggal Surat:* {tgl_display}\n"
            f"👤 *{label_p}:* {surat.pihak}\n"
            f"📝 *Perihal:* {surat.perihal}\n"
            f"{petugas_info}"
            f"📎 *Lampiran:* {att_count} file tersimpan di Google Drive\n\n"
            f"_Data arsip berhasil disesuaikan di SIMETRI._"
        )

        return {
            "status": "success",
            "surat_id": surat.id,
            "reply": reply_text,
        }
    except Exception as e:
        logger.error(f"[WA Archive] Gagal update metadata surat ID {surat_id}: {e}")
        db_context.rollback()
        raise
    finally:
        if should_close:
            db_context.close()


async def download_whatsapp_media(
    payload: dict[str, Any],
    device_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Mengambil file media pertama yang dikirimkan bersama pesan WhatsApp.
    (Backward compatibility wrapper).
    """
    items = await extract_media_items_from_payload(payload, device_id=device_id)
    return items[0] if items else None


async def process_whatsapp_archive(
    payload: dict[str, Any],
    device_id: Optional[str] = None,
    session: Optional[Session] = None,
    is_forwarded: bool = False,
    override_meta: Optional[dict[str, Any]] = None,
    custom_media_items: Optional[list[dict[str, Any]]] = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """
    Alur utama pemrosesan arsip via WhatsApp:
    1. Ekstraksi media dari payload, replied message, atau unarchived cache.
    2. Parsing caption & metadata surat (mendukung pesan forwarding).
    3. Jika media belum ada: simpan perintah pending dan beri panduan.
    4. Simpan record Surat ke database.
    5. Daftarkan active archive session untuk nomor pengirim ini.
    6. Upload media ke Google Drive (folder tahunan) dan simpan AttachmentSurat.
    7. Buat pesan respon konfirmasi WhatsApp.
    """
    caption = payload.get("body") or payload.get("caption") or ""
    sender_name = payload.get("from_name") or payload.get("sender_display_name") or ""
    sender_phone = payload.get("from") or payload.get("chat_id") or ""
    clean_phone = re.sub(r'[^0-9]', '', sender_phone.split('@')[0]) if sender_phone else ""

    # 0. Verifikasi otorisasi pengirim: hanya nomor yang terdaftar di Daftar Pengguna (tabel users)
    actor_user = user
    if not actor_user:
        actor_user = get_user_by_whatsapp_phone(sender_phone, session=session)
        if not actor_user and clean_phone:
            actor_user = get_user_by_whatsapp_phone(clean_phone, session=session)

    if not actor_user:
        logger.warning(
            f"[WA Archive] Otorisasi arsip DITOLAK: nomor {sender_phone} ({clean_phone}) tidak terdaftar di Daftar Pengguna."
        )
        return {
            "status": "unauthorized",
            "reply": (
                f"⛔ *AKSES PENGARSIPAN DITOLAK*\n\n"
                f"Mohon maaf, nomor WhatsApp Anda (*{clean_phone or sender_phone}*) belum terdaftar dalam Daftar Pengguna SIMETRI.\n\n"
                f"Hanya pengguna yang terdaftar di Daftar Pengguna SIMETRI yang dapat melakukan perintah arsipkan surat/dokumen.\n"
                f"Silakan hubungi Administrator SIMETRI Bappeda Kota Tegal untuk mendaftarkan nomor WhatsApp Anda.\n\n"
                f"_SIMETRI — Bappeda Kota Tegal_"
            ),
        }

    effective_sender_name = actor_user.name or sender_name

    # 1. Ambil file media (custom items, dari payload, dari replied message, atau dari unarchived cache)
    if custom_media_items:
        media_items = custom_media_items
    else:
        media_items = await extract_media_items_from_payload(payload, device_id=device_id)
        if not media_items and clean_phone:
            # Cek apakah ada unarchived media yang baru dikirim dalam 3 menit terakhir
            unarchived_items, unarchived_caption = pop_recent_unarchived_media(clean_phone)
            if unarchived_items:
                logger.info(f"[WA Archive] Menggunakan {len(unarchived_items)} unarchived media sebelumnya untuk {clean_phone}")
                media_items = unarchived_items
                if not caption and unarchived_caption:
                    caption = unarchived_caption

    # 2. Parse metadata surat
    first_filename = media_items[0]["filename"] if media_items else None
    if override_meta:
        meta = override_meta
    else:
        meta = parse_archive_command(
            caption,
            sender_name=effective_sender_name,
            sender_phone=sender_phone,
            is_forwarded=is_forwarded,
            media_filename=first_filename,
        )

    greeting = actor_user.name if actor_user.name else (sender_name or "Bapak/Ibu")

    if not media_items:
        # User mengirim perintah 'arsipkan' namun belum ada file terlampir
        # Daftarkan sebagai pending archive command agar file yang dikirim/diteruskan berikutnya langsung tersambung
        if clean_phone:
            register_pending_archive_command(clean_phone, meta, caption)

        reply_no_media = (
            f"📥 *PERINTAH ARSIP DITERIMA*\n\n"
            f"Halo *{greeting}*,\n"
            f"Perintah arsip *{meta['perihal']}* ({meta['jenis_surat']}) telah kami catat.\n\n"
            f"👉 Mohon *kirim atau teruskan (forward) foto/dokumen surat* sekarang untuk disimpan ke dalam arsip ini (berlaku 2 menit).\n\n"
            f"_SIMETRI — Bappeda Kota Tegal_"
        )
        return {
            "status": "pending_media",
            "reply": reply_no_media,
        }

    # Buka session database
    if session is None:
        from app.database import engine
        db_context = Session(engine)
        should_close = True
    else:
        db_context = session
        should_close = False

    try:
        # Tentukan user pencatat arsip (milik user yang terverifikasi)
        creator_id = actor_user.id

        surat = Surat(
            jenis_surat=meta["jenis_surat"],
            nomor_surat=meta["nomor_surat"],
            tanggal_surat=meta["tanggal_surat"],
            pihak=meta["pihak"],
            perihal=meta["perihal"],
            keterangan=meta["keterangan"],
            created_by_id=creator_id,
            created_at=datetime.now(),
        )
        db_context.add(surat)
        db_context.commit()
        db_context.refresh(surat)

        # Daftarkan sesi aktif agar pesan lampiran berikutnya langsung ditautkan ke surat ini
        if clean_phone:
            register_active_archive(clean_phone, surat.id)

        # Dapatkan folder tujuan di Google Drive
        parent_folder = settings.GDRIVE_PARENT_FOLDER_ID or None
        arsip_folder_id = get_or_create_folder(
            settings.GDRIVE_ARSIP_FOLDER_NAME, parent_id=parent_folder
        )
        tahun_str = str(meta["tanggal_surat"].year)
        tahun_folder_id = get_or_create_folder(tahun_str, parent_id=arsip_folder_id)

        # Upload dan catat setiap lampiran (dengan deduplikasi per surat)
        uploaded_attachments: list[dict[str, Any]] = []
        existing_filenames = {
            a.filename for a in db_context.exec(
                select(AttachmentSurat).where(AttachmentSurat.surat_id == surat.id)
            ).all()
        }
        for media in media_items:
            fname = media["filename"]
            if fname in existing_filenames:
                logger.info(f"[WA Archive] File {fname} sudah terlampir di Surat ID {surat.id}, melewati duplikasi.")
                continue

            drive_res = upload_media_dict_to_gdrive(media, tahun_folder_id)
            drive_file_id = drive_res.get("id", "")
            drive_link = drive_res.get("webViewLink", "")

            attachment = AttachmentSurat(
                surat_id=surat.id,
                drive_file_id=drive_file_id,
                drive_link=drive_link,
                filename=fname,
                mime_type=media["mime_type"],
                size_bytes=media["size_bytes"],
                uploaded_by_id=creator_id,
                uploaded_at=datetime.now(),
            )
            db_context.add(attachment)
            existing_filenames.add(fname)
            uploaded_attachments.append({
                "filename": fname,
                "size_bytes": media["size_bytes"],
                "drive_link": drive_link,
            })

        db_context.commit()

        origin_desc = "terusan (forwarding) WhatsApp" if is_forwarded else "WhatsApp"
        log_activity(
            db=db_context,
            action="CREATE",
            entity="surat",
            entity_id=surat.id,
            description=f"Arsip surat {surat.nomor_surat} ({len(media_items)} lampiran) otomatis via {origin_desc} ({sender_phone})",
            user=actor_user,
        )

        logger.info(
            f"[WA Archive] Berhasil mengarsipkan surat ID {surat.id} ({surat.nomor_surat}) dengan {len(media_items)} file dari WA {sender_phone} oleh {actor_user.name if actor_user else 'System'}"
        )

        saved_id = surat.id
        saved_jenis = surat.jenis_surat
        saved_nomor = surat.nomor_surat
        saved_pihak = surat.pihak
        saved_perihal = surat.perihal

    except Exception as e:
        logger.error(f"[WA Archive] Gagal menyimpan surat ke database: {e}")
        db_context.rollback()
        raise
    finally:
        if should_close:
            db_context.close()

    # Siapkan pesan respon konfirmasi WhatsApp
    tgl_display = meta["tanggal_surat"].strftime("%d/%m/%Y")
    label_p = label_pihak(saved_jenis)

    if len(uploaded_attachments) == 1:
        att = uploaded_attachments[0]
        size_str = format_file_size(att["size_bytes"])
        link_info = f"\n🔗 *Link Dokumen (Google Drive):*\n{att['drive_link']}" if att['drive_link'] else ""
        lampiran_section = f"📎 *Lampiran:* {att['filename']} ({size_str}){link_info}"
    else:
        lampiran_lines = []
        for idx, att in enumerate(uploaded_attachments, 1):
            size_str = format_file_size(att["size_bytes"])
            link_part = f"\n   🔗 {att['drive_link']}" if att['drive_link'] else ""
            lampiran_lines.append(f"{idx}. {att['filename']} ({size_str}){link_part}")
        lampiran_section = f"📎 *Lampiran ({len(uploaded_attachments)} file):*\n" + "\n".join(lampiran_lines)

    header_title = "✅ *ARSIP SURAT (DARI FORWARDING) BERHASIL DISIMPAN*" if is_forwarded else "✅ *ARSIP SURAT BERHASIL DISIMPAN*"
    petugas_line = f"👤 *Petugas Pengarsip:* {actor_user.name}\n" if actor_user and actor_user.name else ""
    tips_section = (
        "\n\n💡 *Tips:*\n"
        "- Dokumen otomatis diarsipkan dari pesan yang diteruskan (forward).\n"
        "- Untuk melengkapi nomor/perihal, cukup balas pesan ini:\n"
        "  👉 *ubah perihal: [Perihal Baru]*\n"
        "- Anda juga dapat meneruskan dokumen tambahan dalam 2 menit ini untuk digabungkan."
        if is_forwarded
        else "\n\n_Dokumen telah tercatat di SIMETRI Arsip Surat Bappeda Kota Tegal._"
    )

    success_reply = (
        f"{header_title}\n\n"
        f"📂 *Jenis Surat:* {saved_jenis}\n"
        f"📄 *Nomor Surat:* {saved_nomor}\n"
        f"📅 *Tanggal Surat:* {tgl_display}\n"
        f"👤 *{label_p}:* {saved_pihak}\n"
        f"📝 *Perihal:* {saved_perihal}\n"
        f"{petugas_line}"
        f"{lampiran_section}"
        f"{tips_section}"
    )

    return {
        "status": "success",
        "surat_id": saved_id,
        "reply": success_reply,
        "attachments_count": len(uploaded_attachments),
    }


async def process_whatsapp_forwarded_archive(
    payload: dict[str, Any],
    device_id: Optional[str] = None,
    session: Optional[Session] = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """
    Memproses arsip otomatis khusus untuk pesan yang diteruskan (forwarded) di WhatsApp.
    Mengekstrak file/foto dan mengarsipkannya secara langsung.
    """
    sender_phone = payload.get("from") or payload.get("chat_id") or ""
    clean_phone = re.sub(r'[^0-9]', '', sender_phone.split('@')[0]) if sender_phone else ""

    # 1. Cek apakah ada sesi arsip aktif (multi-file / kelanjutan)
    active_surat_id = get_active_archive(clean_phone, session=session) if clean_phone else None
    if active_surat_id:
        logger.info(f"[WA Archive] Meneruskan media forwarded ke sesi aktif Surat ID {active_surat_id}")
        return await append_whatsapp_archive_media(
            surat_id=active_surat_id,
            payload=payload,
            sender_phone=sender_phone,
            device_id=device_id,
            session=session,
            user=user,
        )

    # 2. Proses sebagai arsip baru dari pesan forwarding
    return await process_whatsapp_archive(
        payload=payload,
        device_id=device_id,
        session=session,
        is_forwarded=True,
        user=user,
    )


async def append_whatsapp_archive_media(
    surat_id: int,
    payload: dict[str, Any],
    sender_phone: str = "",
    device_id: Optional[str] = None,
    session: Optional[Session] = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """
    Menambahkan lampiran media ke Surat yang baru saja dibuat (untuk multi-file WhatsApp).
    """
    media_items = await extract_media_items_from_payload(payload, device_id=device_id)
    if not media_items:
        return {
            "status": "no_media",
            "surat_id": surat_id,
            "reply": "",
        }

    clean_phone = re.sub(r'[^0-9]', '', sender_phone.split('@')[0]) if sender_phone else ""

    if session is None:
        from app.database import engine
        db_context = Session(engine)
        should_close = True
    else:
        db_context = session
        should_close = False

    try:
        surat = db_context.get(Surat, surat_id)
        if not surat:
            logger.warning(f"[WA Archive] Surat ID {surat_id} tidak ditemukan untuk append lampiran")
            return {
                "status": "error",
                "message": f"Surat ID {surat_id} tidak ditemukan",
            }

        actor_user = user
        if not actor_user:
            actor_user = get_user_by_whatsapp_phone(sender_phone, session=db_context)
            if not actor_user and clean_phone:
                actor_user = get_user_by_whatsapp_phone(clean_phone, session=db_context)

        if not actor_user:
            logger.warning(
                f"[WA Archive] Append lampiran DITOLAK: nomor {sender_phone} ({clean_phone}) tidak terdaftar di Daftar Pengguna."
            )
            return {
                "status": "unauthorized",
                "reply": (
                    f"⛔ *AKSES DITOLAK*\n\n"
                    f"Nomor WhatsApp Anda belum terdaftar dalam Daftar Pengguna SIMETRI."
                ),
            }

        creator_id = actor_user.id

        # Dapatkan folder tujuan di Google Drive
        parent_folder = settings.GDRIVE_PARENT_FOLDER_ID or None
        arsip_folder_id = get_or_create_folder(
            settings.GDRIVE_ARSIP_FOLDER_NAME, parent_id=parent_folder
        )
        tahun_str = str(surat.tanggal_surat.year)
        tahun_folder_id = get_or_create_folder(tahun_str, parent_id=arsip_folder_id)

        added_attachments: list[dict[str, Any]] = []
        existing_filenames = {
            a.filename for a in db_context.exec(
                select(AttachmentSurat).where(AttachmentSurat.surat_id == surat.id)
            ).all()
        }
        for media in media_items:
            fname = media["filename"]
            if fname in existing_filenames:
                logger.info(f"[WA Archive] File {fname} sudah terlampir di Surat ID {surat.id}, melewati duplikasi.")
                continue

            drive_res = upload_media_dict_to_gdrive(media, tahun_folder_id)
            drive_file_id = drive_res.get("id", "")
            drive_link = drive_res.get("webViewLink", "")

            attachment = AttachmentSurat(
                surat_id=surat.id,
                drive_file_id=drive_file_id,
                drive_link=drive_link,
                filename=fname,
                mime_type=media["mime_type"],
                size_bytes=media["size_bytes"],
                uploaded_by_id=creator_id,
                uploaded_at=datetime.now(),
            )
            db_context.add(attachment)
            existing_filenames.add(fname)
            added_attachments.append({
                "filename": fname,
                "size_bytes": media["size_bytes"],
                "drive_link": drive_link,
            })

        # Hitung total lampiran sekarang
        all_att = db_context.exec(
            select(AttachmentSurat).where(AttachmentSurat.surat_id == surat.id)
        ).all()
        total_count = len(all_att)

        if not added_attachments:
            logger.info(f"[WA Archive] Tidak ada file baru yang perlu ditambahkan ke Surat ID {surat.id} (semua file sudah terdaftar).")
            return {
                "status": "already_attached",
                "surat_id": surat_id,
                "reply": "",
                "added_count": 0,
                "total_count": total_count,
            }

        surat.updated_at = datetime.now()
        db_context.add(surat)
        db_context.commit()

        log_activity(
            db=db_context,
            action="UPDATE",
            entity="surat",
            entity_id=surat.id,
            description=f"Menambahkan {len(media_items)} lampiran ke arsip surat {surat.nomor_surat} via WhatsApp ({sender_phone})",
            user=actor_user,
        )

        logger.info(
            f"[WA Archive] Berhasil menambahkan {len(media_items)} lampiran ke Surat ID {surat.id} ({surat.nomor_surat}) dari {sender_phone}. Total: {total_count}"
        )

        # Perbarui timestamp sesi aktif pengirim
        if clean_phone:
            register_active_archive(clean_phone, surat.id)

        nomor_surat = surat.nomor_surat
        jenis_surat = surat.jenis_surat
        perihal = surat.perihal

    except Exception as e:
        logger.error(f"[WA Archive] Gagal menambahkan lampiran ke surat ID {surat_id}: {e}")
        db_context.rollback()
        raise
    finally:
        if should_close:
            db_context.close()

    # Buat respon WhatsApp
    petugas_line = f"👤 *Petugas:* {actor_user.name}\n" if actor_user and actor_user.name else ""
    if len(added_attachments) == 1:
        att = added_attachments[0]
        size_str = format_file_size(att["size_bytes"])
        link_info = f"\n🔗 *Link Dokumen (Google Drive):*\n{att['drive_link']}" if att['drive_link'] else ""
        lampiran_info = f"📎 *Lampiran Tambahan:* {att['filename']} ({size_str}){link_info}"
    else:
        lampiran_lines = []
        for idx, att in enumerate(added_attachments, 1):
            size_str = format_file_size(att["size_bytes"])
            link_part = f"\n   🔗 {att['drive_link']}" if att['drive_link'] else ""
            lampiran_lines.append(f"{idx}. {att['filename']} ({size_str}){link_part}")
        lampiran_info = f"📎 *Lampiran Tambahan ({len(added_attachments)} file):*\n" + "\n".join(lampiran_lines)

    append_reply = (
        f"📎 *LAMPIRAN BERHASIL DITAMBAHKAN*\n\n"
        f"📂 *Jenis Surat:* {jenis_surat}\n"
        f"📄 *Nomor Surat:* {nomor_surat}\n"
        f"📝 *Perihal:* {perihal}\n"
        f"{petugas_line}"
        f"{lampiran_info}\n\n"
        f"_Total lampiran tersimpan saat ini: {total_count} file._"
    )

    return {
        "status": "success",
        "surat_id": surat_id,
        "reply": append_reply,
        "added_count": len(added_attachments),
        "total_count": total_count,
    }

