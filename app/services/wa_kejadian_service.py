"""
Service WhatsApp Kejadian — Pencatatan Kronologi Kejadian Perencanaan via WhatsApp.
Menerima pesan berformat:
    simetri <nama_atau_alias_dokumen> <uraian_kronologi_kejadian>
Beserta lampiran file/foto (jika ada), mengunggah ke Google Drive,
dan mencatat ke tabel kejadians serta lampiran_kejadians di database SIMETRI.
Mendukung penyatuan otomatis file dari pesan terusan (forwarding) dan multi-file.
"""

import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, desc, select

from app.config import get_settings
from app.models.dokumen import DokumenPerencanaan
from app.models.kejadian import Kejadian, LampiranKejadian
from app.models.master import MasterBidang, MasterJenisKejadian
from app.models.surat import AttachmentSurat, Surat
from app.models.user import TaOpd, User
from app.services.audit_service import log_activity
from app.services.gdrive_service import get_folder_for_kejadian
from app.services.wa_archive_service import (
    ACTIVE_ARCHIVE_SESSIONS,
    extract_media_items_from_payload,
    format_file_size,
    get_user_by_whatsapp_phone,
    normalize_phone_number,
    pop_recent_unarchived_media,
    upload_media_dict_to_gdrive,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Sesi aktif pencatatan kronologi kejadian per nomor pengirim (window 2 menit)
ACTIVE_KEJADIAN_SESSIONS: dict[str, dict[str, Any]] = {}
KEJADIAN_SESSION_EXPIRY_SECONDS = 120


def register_active_kejadian(
    clean_phone: str,
    kejadian_id: int,
    dokumen_id: int,
    judul: str = "",
) -> None:
    """Mencatat sesi kronologi kejadian aktif per nomor pengirim."""
    if not clean_phone:
        return
    now = time.time()
    ACTIVE_KEJADIAN_SESSIONS[clean_phone] = {
        "kejadian_id": kejadian_id,
        "dokumen_id": dokumen_id,
        "judul": judul,
        "created_at": now,
        "last_activity": now,
    }


def get_active_kejadian(clean_phone: str, session: Optional[Session] = None) -> Optional[int]:
    """
    Mengambil ID Kejadian yang masih aktif dalam window waktu KEJADIAN_SESSION_EXPIRY_SECONDS.
    Jika ada media baru dikirim oleh nomor yang sama dalam window waktu,
    media tersebut akan otomatis ditautkan ke Kejadian ini.
    """
    if not clean_phone:
        return None

    now = time.time()
    sess_data = ACTIVE_KEJADIAN_SESSIONS.get(clean_phone)
    if sess_data:
        if now - sess_data.get("last_activity", 0) <= KEJADIAN_SESSION_EXPIRY_SECONDS:
            sess_data["last_activity"] = now
            return sess_data["kejadian_id"]
        else:
            ACTIVE_KEJADIAN_SESSIONS.pop(clean_phone, None)

    return None


def is_recent_datetime(dt: Optional[datetime], max_age_seconds: int = 120) -> bool:
    """Mengecek apakah datetime berada dalam rentang waktu max_age_seconds secara aman (naive vs aware)."""
    if not dt:
        return False
    if dt.tzinfo is not None:
        now = datetime.now(dt.tzinfo)
    else:
        now = datetime.now()
    diff = (now - dt).total_seconds()
    return -5 <= diff <= max_age_seconds


def find_recent_auto_forward_surat(
    clean_phone: str,
    session: Session,
    max_age_seconds: int = 120,
) -> Optional[Surat]:
    """
    Mencari record Surat yang baru saja dibuat otomatis dari pesan terusan (forwarding)
    oleh nomor pengirim yang sama dalam batas waktu max_age_seconds.
    Digunakan saat user memforward file terlebih dahulu, lalu mengirim pesan teks 'simetri...'.
    """
    if not clean_phone:
        return None

    # 1. Cek sesi arsip aktif
    sess_archive = ACTIVE_ARCHIVE_SESSIONS.get(clean_phone)
    if sess_archive and sess_archive.get("surat_id"):
        surat_from_sess = session.get(Surat, sess_archive["surat_id"])
        if surat_from_sess and is_recent_datetime(surat_from_sess.created_at, max_age_seconds):
            ket = (surat_from_sess.keterangan or "").lower()
            perihal = (surat_from_sess.perihal or "").lower()
            if "terusan (forwarding)" in ket or "arsip dokumen terusan" in perihal or "arsip surat dari" in perihal:
                return surat_from_sess

    # 2. Cek query database (ambil 5 teratas lalu validasi timestamp secara aman)
    query = (
        select(Surat)
        .where(Surat.keterangan.like(f"%{clean_phone}%"))
        .where(
            (Surat.keterangan.like("%terusan (forwarding)%"))
            | (Surat.perihal.like("Arsip Dokumen Terusan%"))
            | (Surat.perihal.like("Arsip Surat dari%"))
        )
        .order_by(desc(Surat.id))
        .limit(5)
    )
    candidates = session.exec(query).all()
    for s in candidates:
        if is_recent_datetime(s.created_at, max_age_seconds):
            return s

    return None


def migrate_surat_attachments_to_kejadian(
    surat: Surat,
    kejadian: Kejadian,
    session: Session,
) -> list[dict[str, Any]]:
    """
    Memindahkan seluruh file lampiran dari Surat terusan otomatis sementara ke Kejadian,
    kemudian menghapus record Surat sementara tersebut agar tidak ganda di arsip.
    """
    attachments = session.exec(
        select(AttachmentSurat).where(AttachmentSurat.surat_id == surat.id)
    ).all()

    migrated: list[dict[str, Any]] = []
    for att in attachments:
        mime = att.mime_type or "application/octet-stream"
        tipe = "foto" if mime.startswith("image/") else "file_gdrive"
        lampiran = LampiranKejadian(
            kejadian_id=kejadian.id,
            tipe_lampiran=tipe,
            judul=att.filename,
            file_name=att.filename,
            mime_type=mime,
            file_size=att.size_bytes or 0,
            g_drive_file_id=att.drive_file_id or "",
            g_drive_web_view_link=att.drive_link or "",
            g_drive_download_link=att.drive_link or "",
            created_at=datetime.now(),
        )
        session.add(lampiran)
        session.delete(att)
        migrated.append({
            "filename": att.filename,
            "size_bytes": att.size_bytes or 0,
            "drive_link": att.drive_link or "",
        })

    # Hapus surat arsip sementara
    surat_id = surat.id
    session.delete(surat)
    session.commit()

    logger.info(
        f"[WA Kejadian] Berhasil memindahkan {len(migrated)} lampiran dari Surat ID {surat_id} ke Kejadian ID {kejadian.id}"
    )
    return migrated


def is_kejadian_request(text: Optional[str]) -> bool:
    """
    Mengecek apakah pesan WhatsApp memuat kata kunci perintah kejadian:
    dimulai dengan kata 'simetri' (contoh: 'simetri rkpd rapat...', '!simetri rpjmd...').
    """
    if not text:
        return False
    clean = text.strip()
    return bool(re.match(r'^[!/#]?simetri\b', clean, re.IGNORECASE))


def parse_kejadian_text(text: str, session: Session) -> dict[str, Any]:
    """
    Mem-parsing teks pesan WhatsApp dengan format:
        simetri <nama_atau_alias_dokumen> <uraian_kronologi_kejadian>
    Mencari DokumenPerencanaan yang cocok berdasarkan alias, nama, atau jenis dokumen.
    """
    # Bersihkan prefix 'simetri'
    clean_text = re.sub(r'^[!/#]?simetri[:\s]*', '', text.strip(), flags=re.IGNORECASE).strip()

    # Ambil semua dokumen perencanaan aktif
    docs = session.exec(
        select(DokumenPerencanaan).where(DokumenPerencanaan.is_active == True)
    ).all()

    matched_doc: Optional[DokumenPerencanaan] = None
    uraian_text: str = clean_text

    # Prioritas pencocokan:
    # 1. Dokumen dengan alias yang cocok persis di awal kata
    # Urutkan alias terpanjang dulu untuk menghindari substring conflict
    docs_with_alias = [d for d in docs if d.alias and d.alias.strip()]
    docs_with_alias.sort(key=lambda d: len(d.alias), reverse=True)

    for d in docs_with_alias:
        pattern = rf'^{re.escape(d.alias)}(?:[:\s,.-]+|$)(.*)'
        m = re.match(pattern, clean_text, re.IGNORECASE | re.DOTALL)
        if m:
            matched_doc = d
            uraian_text = m.group(1).strip()
            break

    # 2. Jika belum cocok, cari berdasarkan nama lengkap dokumen
    if not matched_doc:
        docs_by_name = sorted(docs, key=lambda d: len(d.nama), reverse=True)
        for d in docs_by_name:
            pattern = rf'^{re.escape(d.nama)}(?:[:\s,.-]+|$)(.*)'
            m = re.match(pattern, clean_text, re.IGNORECASE | re.DOTALL)
            if m:
                matched_doc = d
                uraian_text = m.group(1).strip()
                break

    # 3. Jika belum cocok, coba jenis dokumen (misal user ketik 'simetri rkpd ...' padahal alias kosong)
    if not matched_doc:
        docs_by_jenis = sorted(docs, key=lambda d: len(d.jenis), reverse=True)
        for d in docs_by_jenis:
            pattern = rf'^{re.escape(d.jenis)}(?:[:\s,.-]+|$)(.*)'
            m = re.match(pattern, clean_text, re.IGNORECASE | re.DOTALL)
            if m:
                matched_doc = d
                uraian_text = m.group(1).strip()
                break

    return {
        "dokumen": matched_doc,
        "uraian": uraian_text,
        "clean_text": clean_text,
        "available_docs": docs,
    }


def detect_jenis_kejadian(uraian: str, session: Optional[Session] = None) -> str:
    """
    Mendeteksi MasterJenisKejadian yang relevan dari teks uraian secara otomatis.
    Jika tidak terdeteksi, default ke 'Kejadian Penting Lainnya'.
    """
    raw = uraian.lower()
    if "tapd" in raw:
        return "Rapat TAPD"
    if "musrenbang" in raw:
        return "Musrenbang"
    if "konsultasi publik" in raw or "fkp" in raw:
        return "Forum Konsultasi Publik"
    if "forum perangkat daerah" in raw or "fpd" in raw:
        return "Forum Perangkat Daerah"
    if "desk" in raw:
        return "Desk Bappeda"
    if "dprd" in raw or "pokir" in raw:
        return "Pokir (Pokok Pikiran DPRD)"
    if "asistensi" in raw:
        return "Asistensi"
    if "verifikasi" in raw:
        return "Verifikasi"
    if "evaluasi" in raw:
        return "Evaluasi"
    if "pagu" in raw:
        return "Perubahan Pagu"
    if "indikator" in raw or "target" in raw:
        return "Perubahan Indikator / Target"
    if "arahan pimpinan" in raw or "walikota" in raw or "sekda" in raw:
        return "Arahan Pimpinan"
    if "surat" in raw or "nota dinas" in raw:
        return "Surat Masuk/Keluar / Nota Dinas"
    if "rakor" in raw or "rapat" in raw:
        return "Rakor Teknis Pembangunan Antar OPD dan OPD-Lintas Sektoral"

    return "Kejadian Penting Lainnya"


def uraian_has_content(uraian: str) -> bool:
    """Mengecek apakah uraian memiliki teks bermakna (bukan hanya simbol atau spasi)."""
    clean = re.sub(r'[\s\-_:;,.]', '', uraian)
    return len(clean) >= 3


async def process_whatsapp_kejadian(
    payload: dict[str, Any],
    device_id: Optional[str] = None,
    session: Optional[Session] = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """
    Memproses perintah pencatatan Kronologi Kejadian dari pesan WhatsApp.
    Format:
        simetri <nama_atau_alias_dokumen> <uraian_kronologi_kejadian>
    Mendukung lampiran foto/dokumen yang disertakan bersama pesan atau
    diteruskan secara bersamaan (forwarding split).
    """
    caption = payload.get("body") or payload.get("caption") or payload.get("text") or ""
    sender_name = payload.get("from_name") or payload.get("sender_display_name") or ""
    sender_phone = payload.get("from") or payload.get("chat_id") or ""
    clean_phone = normalize_phone_number(sender_phone)

    if session is None:
        from app.database import engine
        db_context = Session(engine)
        should_close = True
    else:
        db_context = session
        should_close = False

    try:
        # 1. Verifikasi otorisasi: hanya nomor yang terdaftar di Daftar Pengguna (tabel users)
        actor_user = user
        if not actor_user:
            actor_user = get_user_by_whatsapp_phone(sender_phone, session=db_context)
            if not actor_user and clean_phone:
                actor_user = get_user_by_whatsapp_phone(clean_phone, session=db_context)

        display_phone = clean_phone or sender_phone
        target_name = (actor_user.name if actor_user else sender_name) or "Bapak/Ibu"

        if not actor_user:
            logger.warning(
                f"[WA Kejadian] Akses DITOLAK: Nomor {sender_phone} ({target_name}) belum terdaftar di Daftar Pengguna."
            )
            return {
                "status": "unauthorized",
                "reply": (
                    f"Halo *{target_name}*,\n\n"
                    f"⚠️ *AKSES PENCATATAN KEJADIAN DITOLAK*\n\n"
                    f"Nomor WhatsApp Anda (*{display_phone}*) *belum terdaftar* di Daftar Pengguna aplikasi SIMETRI Bappeda Kota Tegal.\n\n"
                    f"🔒 Sesuai kebijakan keamanan, hanya nomor WhatsApp yang terdaftar dan aktif di *Daftar Pengguna* yang berhak mencatat kejadian ke dalam sistem SIMETRI.\n\n"
                    f"Silakan hubungi Administrator SIMETRI Bappeda Kota Tegal untuk mendaftarkan nomor Anda.\n\n"
                    f"_SIMETRI — Bappeda Kota Tegal_"
                ),
            }

        # 2. Parsing perintah teks
        parsed = parse_kejadian_text(caption, session=db_context)
        doc = parsed.get("dokumen")
        uraian = parsed.get("uraian", "").strip()

        # Kasus A: Dokumen perencanaan tidak ditemukan
        if not doc:
            available_docs = parsed.get("available_docs", [])
            list_lines = []
            for d in available_docs[:8]:
                alias_tag = f"*{d.alias}*" if d.alias else f"_{d.nama}_"
                list_lines.append(f"• {alias_tag} ➜ {d.nama}")

            list_str = "\n".join(list_lines) if list_lines else "• _Belum ada dokumen perencanaan aktif_"

            reply_not_found = (
                f"Halo *{target_name}*,\n\n"
                f"⚠️ *DOKUMEN PERENCANAAN TIDAK DITEMUKAN*\n\n"
                f"Sistem tidak mengenali alias dokumen pada perintah Anda:\n"
                f"👉 _{caption}_\n\n"
                f"📌 *Format yang benar:*\n"
                f"👉 *simetri [alias_dokumen] [uraian kronologi kejadian]*\n\n"
                f"📋 *Daftar Dokumen / Alias yang Tersedia:*\n"
                f"{list_str}\n\n"
                f"💡 *Contoh:*\n"
                f"*simetri rkpd Rapat koordinasi pembahasan indikator makro bersama BPS*\n"
                f"_(Lampiran foto/dokumen dapat disertakan bersama pesan)_\n\n"
                f"_SIMETRI — Bappeda Kota Tegal_"
            )
            return {
                "status": "unknown_document",
                "reply": reply_not_found,
            }

        # Kasus B: Uraian kejadian kosong
        if not uraian_has_content(uraian):
            alias_example = doc.alias or doc.nama
            reply_empty = (
                f"Halo *{target_name}*,\n\n"
                f"⚠️ *URAIAN KEJADIAN BELUM DIISI*\n\n"
                f"Anda telah memilih dokumen *{doc.nama}*, namun uraian kejadian masih kosong.\n\n"
                f"📌 *Silakan kirim kembali dengan format:*\n"
                f"👉 *simetri {alias_example} [Uraian kronologi kejadian]*\n\n"
                f"💡 *Contoh:*\n"
                f"*simetri {alias_example} Rapat pembahasan rancangan awal bersama OPD terkait*\n\n"
                f"_SIMETRI — Bappeda Kota Tegal_"
            )
            return {
                "status": "empty_uraian",
                "reply": reply_empty,
            }

        # 3. Ekstraksi judul & jenis kejadian
        first_line = uraian.split("\n")[0].strip()
        first_line = re.sub(r'^[•\-\*#]+\s*', '', first_line)
        judul = first_line[:120].strip() if first_line else f"Kejadian {doc.nama}"

        jenis_kejadian = detect_jenis_kejadian(uraian, session=db_context)

        # Tentukan bidang penanggung jawab
        now_jkt = datetime.now(ZoneInfo("Asia/Jakarta"))
        waktu_str = now_jkt.strftime("%d/%m/%Y %H:%M")
        jam_str = now_jkt.strftime("%H:%M")

        bidang_pj = ""
        if actor_user.is_user_opd and actor_user.opd_id:
            opd_rec = db_context.get(TaOpd, actor_user.opd_id)
            bidang_pj = opd_rec.nama_pd if opd_rec else "OPD"
        elif actor_user.bidang:
            mb = db_context.exec(
                select(MasterBidang).where(
                    (MasterBidang.kode == actor_user.bidang) | (MasterBidang.nama == actor_user.bidang)
                )
            ).first()
            bidang_pj = mb.nama if mb else actor_user.bidang
        else:
            bidang_pj = "Bappeda Kota Tegal"

        # 4. Simpan record Kejadian
        kejadian = Kejadian(
            dokumen_id=doc.id,
            tanggal_kejadian=datetime.now(),
            waktu_mulai=jam_str,
            waktu_selesai="",
            lokasi="",
            jenis_kejadian=jenis_kejadian,
            judul_kejadian=judul,
            uraian_kronologi=uraian,
            pihak_pengusul="",
            hasil_pembahasan="",
            dasar_dokumen_keputusan="",
            bidang_pj=bidang_pj,
            created_by_id=actor_user.id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db_context.add(kejadian)
        db_context.commit()
        db_context.refresh(kejadian)

        # 5. Proses lampiran media
        # Cek media langsung di payload
        media_items = await extract_media_items_from_payload(payload, device_id=device_id)
        uploaded_attachments: list[dict[str, Any]] = []
        is_migrated_from_forward = False

        # Jika tidak ada media di payload, cek unarchived media di memory
        if not media_items and clean_phone:
            unarchived_items, _ = pop_recent_unarchived_media(clean_phone)
            if unarchived_items:
                media_items = unarchived_items

        # Jika masih tidak ada media, cek apakah baru saja ada surat auto-forwarding yang dibuat
        # untuk pengirim ini dalam 2 menit terakhir (kasus forwarding file + teks terpisah)
        if not media_items and clean_phone:
            recent_forward_surat = find_recent_auto_forward_surat(clean_phone, db_context, max_age_seconds=120)
            if recent_forward_surat:
                logger.info(
                    f"[WA Kejadian] Ditemukan Surat terusan otomatis ID {recent_forward_surat.id} "
                    f"untuk {clean_phone}. Memindahkan lampiran ke Kejadian ID {kejadian.id}..."
                )
                migrated = migrate_surat_attachments_to_kejadian(
                    surat=recent_forward_surat,
                    kejadian=kejadian,
                    session=db_context,
                )
                uploaded_attachments.extend(migrated)
                is_migrated_from_forward = True
                ACTIVE_ARCHIVE_SESSIONS.pop(clean_phone, None)

        # Jika ada media items baru yang belum diunggah, unggah ke Google Drive
        if media_items:
            try:
                folder_id = get_folder_for_kejadian(
                    tahun=kejadian.tanggal_kejadian.year,
                    bidang_pj=kejadian.bidang_pj or "LAINNYA",
                    dokumen_nama=doc.nama,
                )
                for media in media_items:
                    fname = media["filename"]
                    mime = media.get("mime_type") or "application/octet-stream"
                    tipe = "foto" if mime.startswith("image/") else "file_gdrive"

                    drive_res = upload_media_dict_to_gdrive(media, folder_id) if folder_id else {}
                    g_drive_id = drive_res.get("id", "")
                    g_view = drive_res.get("webViewLink", "")
                    g_download = drive_res.get("webContentLink", "")

                    lampiran = LampiranKejadian(
                        kejadian_id=kejadian.id,
                        tipe_lampiran=tipe,
                        judul=fname,
                        file_name=fname,
                        mime_type=mime,
                        file_size=media["size_bytes"],
                        g_drive_file_id=g_drive_id,
                        g_drive_web_view_link=g_view,
                        g_drive_download_link=g_download,
                        created_at=datetime.now(),
                    )
                    db_context.add(lampiran)
                    uploaded_attachments.append({
                        "filename": fname,
                        "size_bytes": media["size_bytes"],
                        "drive_link": g_view,
                    })

                db_context.commit()
            except Exception as ex:
                logger.error(f"[WA Kejadian] Gagal memproses lampiran kejadian ID {kejadian.id}: {ex}")

        # Catat sesi kejadian aktif agar lampiran lanjutan langsung ditautkan
        if clean_phone:
            register_active_kejadian(clean_phone, kejadian.id, doc.id, kejadian.judul_kejadian)

        # 6. Audit log aktivitas
        log_activity(
            db=db_context,
            action="CREATE",
            entity="kejadian",
            entity_id=kejadian.id,
            description=(
                f"Catat kronologi kejadian via WhatsApp oleh {actor_user.name} ({display_phone}): "
                f"'{kejadian.judul_kejadian}' pada {doc.nama}"
            ),
            user=actor_user,
        )

        logger.info(
            f"[WA Kejadian] Berhasil mencatat kejadian ID {kejadian.id} pada '{doc.nama}' oleh {actor_user.name} ({display_phone})"
        )

        # 7. Susun pesan konfirmasi balasan WhatsApp
        if len(uploaded_attachments) == 1:
            att = uploaded_attachments[0]
            size_str = format_file_size(att["size_bytes"])
            link_str = f"\n🔗 *Link Drive:* {att['drive_link']}" if att["drive_link"] else ""
            lampiran_info = f"\n📎 *Lampiran:* {att['filename']} ({size_str}){link_str}"
        elif len(uploaded_attachments) > 1:
            lines = []
            for idx, att in enumerate(uploaded_attachments, 1):
                size_str = format_file_size(att["size_bytes"])
                link_str = f" - 🔗 {att['drive_link']}" if att["drive_link"] else ""
                lines.append(f"  {idx}. {att['filename']} ({size_str}){link_str}")
            lampiran_info = f"\n📎 *Lampiran ({len(uploaded_attachments)} file):*\n" + "\n".join(lines)
        else:
            lampiran_info = ""

        forward_note = (
            "\n💡 _File lampiran dari pesan terusan WhatsApp telah otomatis disatukan ke dalam kronologi kejadian ini._"
            if is_migrated_from_forward
            else ""
        )

        ringkasan_uraian = uraian if len(uraian) <= 300 else uraian[:297] + "..."

        success_reply = (
            f"✅ *KRONOLOGI KEJADIAN BERHASIL DICATAT*\n\n"
            f"📁 *Dokumen Perencanaan:*\n"
            f"*{doc.nama}*\n\n"
            f"📅 *Waktu:* {waktu_str} WIB\n"
            f"🏷️ *Jenis:* {kejadian.jenis_kejadian}\n"
            f"👤 *Pencatat:* {actor_user.name} ({bidang_pj})\n"
            f"📌 *Judul:* {kejadian.judul_kejadian}\n\n"
            f"📝 *Uraian Kejadian:*\n"
            f"{ringkasan_uraian}\n"
            f"{lampiran_info}{forward_note}\n\n"
            f"_Data kronologi telah tersimpan di sistem SIMETRI._"
        )

        return {
            "status": "success",
            "kejadian_id": kejadian.id,
            "dokumen_id": doc.id,
            "reply": success_reply,
            "attachments_count": len(uploaded_attachments),
        }

    except Exception as e:
        logger.error(f"[WA Kejadian] Error saat memproses kejadian via WhatsApp: {e}")
        db_context.rollback()
        raise
    finally:
        if should_close:
            db_context.close()


async def append_whatsapp_kejadian_media(
    kejadian_id: int,
    payload: dict[str, Any],
    sender_phone: str = "",
    device_id: Optional[str] = None,
    session: Optional[Session] = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """
    Menambahkan lampiran media ke Kejadian yang baru saja dicatat
    (mendukung multi-file atau pengiriman file sesaat setelah teks kejadian).
    """
    media_items = await extract_media_items_from_payload(payload, device_id=device_id)
    if not media_items:
        return {
            "status": "no_media",
            "kejadian_id": kejadian_id,
            "reply": "",
        }

    clean_phone = normalize_phone_number(sender_phone)

    if session is None:
        from app.database import engine
        db_context = Session(engine)
        should_close = True
    else:
        db_context = session
        should_close = False

    try:
        kejadian = db_context.get(Kejadian, kejadian_id)
        if not kejadian:
            logger.warning(f"[WA Kejadian] Kejadian ID {kejadian_id} tidak ditemukan untuk append lampiran")
            return {
                "status": "error",
                "message": f"Kejadian ID {kejadian_id} tidak ditemukan",
            }

        doc = db_context.get(DokumenPerencanaan, kejadian.dokumen_id)
        doc_nama = doc.nama if doc else "Dokumen Perencanaan"

        # Folder Google Drive
        folder_id = get_folder_for_kejadian(
            tahun=kejadian.tanggal_kejadian.year,
            bidang_pj=kejadian.bidang_pj or "LAINNYA",
            dokumen_nama=doc_nama,
        )

        uploaded_attachments: list[dict[str, Any]] = []
        for media in media_items:
            fname = media["filename"]
            mime = media.get("mime_type") or "application/octet-stream"
            tipe = "foto" if mime.startswith("image/") else "file_gdrive"

            drive_res = upload_media_dict_to_gdrive(media, folder_id) if folder_id else {}
            g_drive_id = drive_res.get("id", "")
            g_view = drive_res.get("webViewLink", "")
            g_download = drive_res.get("webContentLink", "")

            lampiran = LampiranKejadian(
                kejadian_id=kejadian.id,
                tipe_lampiran=tipe,
                judul=fname,
                file_name=fname,
                mime_type=mime,
                file_size=media["size_bytes"],
                g_drive_file_id=g_drive_id,
                g_drive_web_view_link=g_view,
                g_drive_download_link=g_download,
                created_at=datetime.now(),
            )
            db_context.add(lampiran)
            uploaded_attachments.append({
                "filename": fname,
                "size_bytes": media["size_bytes"],
                "drive_link": g_view,
            })

        db_context.commit()

        # Perbarui timestamp aktivitas sesi kejadian
        if clean_phone and clean_phone in ACTIVE_KEJADIAN_SESSIONS:
            ACTIVE_KEJADIAN_SESSIONS[clean_phone]["last_activity"] = time.time()

        actor_name = user.name if user else "Pengguna"
        log_activity(
            db=db_context,
            action="UPDATE",
            entity="kejadian",
            entity_id=kejadian.id,
            description=f"Menambahkan {len(uploaded_attachments)} lampiran lanjutan ke Kejadian '{kejadian.judul_kejadian}' via WhatsApp",
            user=user,
        )

        logger.info(
            f"[WA Kejadian] Berhasil menambahkan {len(uploaded_attachments)} lampiran ke Kejadian ID {kejadian.id}"
        )

        if len(uploaded_attachments) == 1:
            att = uploaded_attachments[0]
            size_str = format_file_size(att["size_bytes"])
            link_str = f"\n🔗 *Link Drive:* {att['drive_link']}" if att["drive_link"] else ""
            lampiran_info = f"📎 *Lampiran:* {att['filename']} ({size_str}){link_str}"
        else:
            lines = []
            for idx, att in enumerate(uploaded_attachments, 1):
                size_str = format_file_size(att["size_bytes"])
                link_str = f" - 🔗 {att['drive_link']}" if att["drive_link"] else ""
                lines.append(f"  {idx}. {att['filename']} ({size_str}){link_str}")
            lampiran_info = f"📎 *Lampiran ({len(uploaded_attachments)} file):*\n" + "\n".join(lines)

        reply_text = (
            f"✅ *LAMPIRAN KRONOLOGI BERHASIL DITAMBAHKAN*\n\n"
            f"📁 *Dokumen Perencanaan:*\n"
            f"*{doc_nama}*\n\n"
            f"📌 *Judul Kejadian:*\n"
            f"{kejadian.judul_kejadian}\n\n"
            f"{lampiran_info}\n\n"
            f"_Lampiran telah berhasil ditautkan ke kronologi kejadian di SIMETRI._"
        )

        return {
            "status": "success",
            "kejadian_id": kejadian.id,
            "dokumen_id": kejadian.dokumen_id,
            "reply": reply_text,
            "attachments_count": len(uploaded_attachments),
        }

    except Exception as e:
        logger.error(f"[WA Kejadian] Gagal menambahkan lampiran ke Kejadian ID {kejadian_id}: {e}")
        db_context.rollback()
        return {
            "status": "error",
            "message": str(e),
        }
    finally:
        if should_close:
            db_context.close()
