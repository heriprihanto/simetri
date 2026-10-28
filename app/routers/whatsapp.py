"""
Router WhatsApp Webhook — Receiver, Logger & Auto-Reply
Mengimplementasikan fungsi webhook WhatsApp persis seperti whatsappwebhook.php.
"""

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sqlmodel import Session
from app.database import engine
from app.services.wa_search_service import is_search_request, search_whatsapp
from app.services.wa_agenda_service import is_agenda_request, handle_whatsapp_agenda

from app.config import get_settings
from app.services.wa_archive_service import (
    append_whatsapp_archive_media,
    extract_media_items_from_payload,
    get_active_archive,
    get_sender_lock,
    get_user_by_whatsapp_phone,
    is_archive_request,
    is_forwarded_message,
    is_update_command,
    normalize_phone_number,
    payload_has_media,
    pop_pending_archive_command,
    process_whatsapp_archive,
    process_whatsapp_forwarded_archive,
    register_unarchived_media,
    update_recent_archive_metadata,
)
from app.services.wa_kejadian_service import (
    append_whatsapp_kejadian_media,
    get_active_kejadian,
    is_kejadian_request,
    process_whatsapp_kejadian,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

# Direktori root proyek tempat file log disimpan (sesuai whatsappwebhook.php)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_FILE = BASE_DIR / "webhook.log"
MSG_LOG_FILE = BASE_DIR / "message.log"

# Pelacak pesan untuk mencegah duplikasi (idempotensi webhook)
PROCESSED_MESSAGE_IDS: dict[str, float] = {}
IN_FLIGHT_MESSAGES: set[str] = set()


def check_and_mark_message(msg_id: Optional[str]) -> bool:
    """
    Mengecek apakah message ID ini sedang atau sudah selesai diproses.
    Mengembalikan True jika pesan ini duplikat (harus diabaikan).
    """
    if not msg_id:
        return False
    now = time.time()
    # Bersihkan entri lama (> 10 menit)
    expired = [k for k, t in PROCESSED_MESSAGE_IDS.items() if now - t > 600]
    for k in expired:
        PROCESSED_MESSAGE_IDS.pop(k, None)

    if msg_id in IN_FLIGHT_MESSAGES or msg_id in PROCESSED_MESSAGE_IDS:
        return True
    IN_FLIGHT_MESSAGES.add(msg_id)
    return False


def complete_message(msg_id: Optional[str]) -> None:
    """Menandai bahwa message ID telah selesai diproses."""
    if msg_id:
        IN_FLIGHT_MESSAGES.discard(msg_id)
        PROCESSED_MESSAGE_IDS[msg_id] = time.time()


def append_to_file(file_path: Path, content: str) -> None:
    """Helper untuk menulis log ke file dengan thread safety."""
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"[WhatsApp Webhook] Gagal menulis ke {file_path}: {e}")


async def send_whatsapp_message(
    phone: str,
    message: str,
    device_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Kirim pesan WhatsApp menggunakan HTTP POST ke WhatsApp Gateway API.
    Sesuai fungsi sendWhatsAppMessage pada whatsappwebhook.php.
    """
    api_url = settings.WA_API_URL
    dev_id = device_id or settings.WA_DEVICE_ID
    post_data = {
        "phone": phone,
        "message": message,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Device-Id": dev_id,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            resp = await client.post(api_url, json=post_data, headers=headers)
            http_code = resp.status_code
            resp_text = resp.text
            success = 200 <= http_code < 300
            return {
                "success": success,
                "http_code": http_code,
                "response": resp_text,
                "error": "",
            }
    except Exception as e:
        logger.error(f"[WhatsApp Webhook] Gagal mengirim pesan ke {phone}: {e}")
        return {
            "success": False,
            "http_code": 0,
            "response": "",
            "error": str(e),
        }


@router.get("")
async def get_webhook_status():
    """Health check endpoint sederhana (GET /api/whatsapp)."""
    return JSONResponse(
        content={
            "status": "ok",
            "message": "WhatsApp Webhook endpoint is active and ready to receive POST requests.",
        },
        status_code=200,
    )


@router.post("")
async def receive_webhook(request: Request):
    """
    Menerima raw JSON payload dari WhatsApp Gateway, mencatat log, dan melakukan auto-reply.
    """
    # 1. Ambil raw payload
    raw_body = await request.body()
    if not raw_body or not raw_body.strip():
        return JSONResponse(
            content={
                "status": "error",
                "message": "Empty request body.",
            },
            status_code=400,
        )

    # 2. Decode JSON
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Invalid JSON payload: {str(e)}",
            },
            status_code=400,
        )

    # 3. Ekstraksi metadata log
    # Set timezone Asia/Jakarta
    now_jkt = datetime.now(ZoneInfo("Asia/Jakarta"))
    timestamp = now_jkt.strftime("%Y-%m-%d %H:%M:%S")

    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "UNKNOWN")
    )
    event_type = data.get("event") or "unknown_event"
    device_id = data.get("device_id") or "-"

    payload = data.get("payload") or {}
    message_body = payload.get("body") or payload.get("caption") or payload.get("text") or "-"
    sender = payload.get("from") or payload.get("sender_display_name") or "-"

    # Format JSON pretty print persis seperti PHP
    formatted_payload = json.dumps(data, indent=4, ensure_ascii=False)

    # 4. Pencatatan log (webhook.log)
    log_entry = (
        "====================================================\n"
        f"[{timestamp}] [IP: {client_ip}] Event: {event_type}\n"
        f"Device ID : {device_id}\n"
        f"From      : {sender}\n"
        f"Message   : {message_body}\n"
        f"Payload:\n{formatted_payload}\n\n"
    )
    append_to_file(LOG_FILE, log_entry)

    # Khusus event 'message', catat juga ke message.log
    if event_type == "message":
        msg_log_entry = (
            "----------------------------------------------------\n"
            f"[{timestamp}] [FROM: {sender}] [DEVICE: {device_id}]\n"
            f"Pesan: {message_body}\n"
            f"Payload: {formatted_payload}\n\n"
        )
        append_to_file(MSG_LOG_FILE, msg_log_entry)

    # 5. Proses Event & Auto-Reply
    reply_result = None
    archive_result = None
    kejadian_result = None
    search_result = None
    agenda_result = None

    if event_type == "message":
        is_from_me = payload.get("is_from_me", False)

        # Abaikan jika pesan berasal dari diri sendiri (is_from_me = true) untuk mencegah looping
        if not is_from_me:
            msg_id = payload.get("id") or payload.get("message_id")
            if msg_id and check_and_mark_message(msg_id):
                logger.info(f"[WhatsApp Webhook] Pesan ID {msg_id} sudah/sedang diproses, mengabaikan duplikasi retry.")
                return JSONResponse(
                    content={
                        "status": "ignored",
                        "message": "Duplicate message ID (already processed)",
                        "message_id": msg_id,
                    },
                    status_code=200,
                )

            sender_phone = payload.get("from") or payload.get("chat_id") or ""
            sender_name = payload.get("from_name") or payload.get("sender_display_name") or ""

            if sender_phone:
                clean_phone = normalize_phone_number(sender_phone)
                sender_lock = get_sender_lock(clean_phone) if clean_phone else None

                async def _handle_sender_message():
                    nonlocal reply_result, archive_result, kejadian_result, search_result, agenda_result
                    registered_user = get_user_by_whatsapp_phone(sender_phone)
                    greeting_name = (
                        registered_user.name
                        if registered_user and registered_user.name
                        else (sender_name if sender_name else "Bapak/Ibu")
                    )
                    # Helper untuk mengirim dan mencatat log auto-reply
                    async def _send_and_log_reply(tag: str, text: str, extra_info: str = ""):
                        nonlocal reply_result
                        if not text:
                            return
                        reply_result = await send_whatsapp_message(
                            sender_phone, text, device_id=device_id
                        )
                        status_log = "SUCCESS" if reply_result["success"] else "FAILED"
                        log_msg = (
                            f"[{timestamp}] [AUTO-REPLY - {tag} - {status_log}] To: {sender_phone} | HTTP: {reply_result['http_code']}\n"
                        )
                        if extra_info:
                            log_msg += f"{extra_info}\n"
                        if reply_result.get("error"):
                            log_msg += f"cURL Error: {reply_result['error']}\n"
                        if reply_result.get("response"):
                            log_msg += f"Gateway Response: {reply_result['response']}\n"
                        log_msg += "----------------------------------------------------\n\n"
                        append_to_file(LOG_FILE, log_msg)
                        append_to_file(MSG_LOG_FILE, log_msg)

                    # Search takes priority over recording, forwarding, and active media sessions.
                    if is_search_request(message_body):
                        chat = str(payload.get("chat_id") or sender_phone)
                        if "@g.us" in chat or "@g.us" in str(sender_phone) or payload.get("is_group"):
                            search_result = {"status": "ignored_group"}
                            return
                        if not registered_user:
                            search_result = {
                                "status": "unauthorized",
                                "reply": "Akses pencarian ditolak. Nomor WhatsApp Anda belum terdaftar atau tidak aktif di Daftar Pengguna SIMETRI. Hubungi Administrator.",
                            }
                        else:
                            try:
                                with Session(engine) as session:
                                    search_result = search_whatsapp(message_body, registered_user, session)
                            except Exception:
                                logger.exception("[WhatsApp Webhook] Pencarian gagal")
                                search_result = {"status": "error", "reply": "Pencarian belum dapat diproses. Silakan coba lagi beberapa saat."}
                        await _send_and_log_reply("PENCARIAN", search_result.get("reply", ""))
                        return

                    # Agenda query (simetri-agenda)
                    if is_agenda_request(message_body):
                        chat = str(payload.get("chat_id") or sender_phone)
                        if "@g.us" in chat or "@g.us" in str(sender_phone) or payload.get("is_group"):
                            agenda_result = {"status": "ignored_group"}
                            return
                        if not registered_user:
                            display_phone = clean_phone or sender_phone
                            target_name = sender_name or "Bapak/Ibu"
                            logger.warning(
                                f"[WhatsApp Webhook] Percobaan cek agenda ditolak: Nomor {sender_phone} ({target_name}) belum terdaftar di Daftar Pengguna."
                            )
                            agenda_result = {
                                "status": "unauthorized",
                                "reply": (
                                    f"Halo *{target_name}*,\n\n"
                                    f"⚠️ *AKSES AGENDA DITOLAK*\n\n"
                                    f"Nomor WhatsApp Anda (*{display_phone}*) *belum terdaftar* di Daftar Pengguna aplikasi SIMETRI Bappeda Kota Tegal.\n\n"
                                    f"🔒 Sesuai kebijakan keamanan, hanya nomor WhatsApp yang telah didaftarkan dan aktif di *Daftar Pengguna* yang berhak menanyakan agenda kegiatan.\n\n"
                                    f"Silakan hubungi Administrator untuk mendaftarkan nomor WhatsApp Anda ke dalam sistem.\n\n"
                                    f"_SIMETRI — Bappeda Kota Tegal_"
                                ),
                            }
                        else:
                            try:
                                with Session(engine) as session:
                                    agenda_result = handle_whatsapp_agenda(
                                        message_body, registered_user, session, now_jkt=now_jkt
                                    )
                            except Exception:
                                logger.exception("[WhatsApp Webhook] Query agenda gagal")
                                agenda_result = {
                                    "status": "error",
                                    "reply": "Informasi agenda belum dapat diproses saat ini. Silakan coba lagi beberapa saat.",
                                }
                        await _send_and_log_reply("AGENDA", agenda_result.get("reply", ""))
                        return

                    has_media = payload_has_media(payload)
                    is_archive = is_archive_request(message_body)
                    is_kejadian = is_kejadian_request(message_body)
                    is_forwarded = is_forwarded_message(payload, message_body)
                    active_surat_id = get_active_archive(clean_phone) if clean_phone else None
                    active_kejadian_id = get_active_kejadian(clean_phone) if clean_phone else None
                    pending_cmd = pop_pending_archive_command(clean_phone) if clean_phone else None

                    # KASUS 0: Perintah Pencatatan Kronologi Kejadian ("simetri [nama_dokumen] [uraian]...")
                    if is_kejadian:
                        display_phone = clean_phone or sender_phone
                        target_name = (registered_user.name if registered_user else sender_name) or "Bapak/Ibu"
                        if not registered_user:
                            logger.warning(
                                f"[WhatsApp Webhook] Percobaan pencatatan kejadian ditolak: Nomor {sender_phone} ({target_name}) belum terdaftar di Daftar Pengguna."
                            )
                            reply_unauthorized = (
                                f"Halo *{target_name}*,\n\n"
                                f"⚠️ *AKSES PENCATATAN KEJADIAN DITOLAK*\n\n"
                                f"Nomor WhatsApp Anda (*{display_phone}*) *belum terdaftar* di Daftar Pengguna aplikasi SIMETRI Bappeda Kota Tegal.\n\n"
                                f"🔒 Sesuai kebijakan keamanan, hanya nomor WhatsApp yang telah didaftarkan dan aktif di *Daftar Pengguna* yang berhak mencatat kejadian ke dalam sistem SIMETRI.\n\n"
                                f"Silakan hubungi Administrator untuk mendaftarkan nomor WhatsApp Anda ke dalam sistem.\n\n"
                                f"_SIMETRI — Bappeda Kota Tegal_"
                            )
                            kejadian_result = {
                                "status": "unauthorized",
                                "message": f"Nomor {display_phone} tidak terdaftar di Daftar Pengguna SIMETRI",
                            }
                            await _send_and_log_reply(
                                "KEJADIAN-UNAUTHORIZED",
                                reply_unauthorized,
                                f"Akses ditolak: Nomor {display_phone} tidak terdaftar di Daftar Pengguna",
                            )
                            return

                        logger.info(
                            f"[WhatsApp Webhook] Memproses pencatatan kejadian dari {sender_phone} ({greeting_name}): {message_body}"
                        )
                        kejadian_result = await process_whatsapp_kejadian(
                            payload,
                            device_id=device_id,
                            user=registered_user,
                        )
                        reply_text = kejadian_result.get("reply", "")
                        extra = f"Status Kejadian: {kejadian_result.get('status')}"
                        if kejadian_result.get("kejadian_id"):
                            extra += f" | Kejadian ID: {kejadian_result['kejadian_id']} | Dokumen ID: {kejadian_result.get('dokumen_id')}"
                        await _send_and_log_reply("KRONOLOGI", reply_text, extra)
                        return

                    # CEK OTORISASI ARSIP: Hanya nomor yang terdaftar di Daftar Pengguna yang boleh mengarsipkan
                    is_archive_action = (
                        is_archive
                        or (active_surat_id and is_update_command(message_body))
                        or has_media
                        or is_forwarded
                    )

                    if is_archive_action and not registered_user:
                        display_phone = clean_phone or sender_phone
                        target_name = sender_name or "Bapak/Ibu"
                        logger.warning(
                            f"[WhatsApp Webhook] Percobaan pengarsipan ditolak: Nomor {sender_phone} ({target_name}) belum terdaftar di Daftar Pengguna."
                        )
                        reply_unauthorized = (
                            f"Halo *{target_name}*,\n\n"
                            f"⚠️ *AKSES PENGARSIPAN DITOLAK*\n\n"
                            f"Nomor WhatsApp Anda (*{display_phone}*) *belum terdaftar* di Daftar Pengguna aplikasi SIMETRI Bappeda Kota Tegal.\n\n"
                            f"🔒 Sesuai kebijakan keamanan, hanya nomor WhatsApp yang telah didaftarkan dan aktif di *Daftar Pengguna* yang berhak melakukan perintah pengarsipan surat.\n\n"
                            f"Silakan hubungi Administrator untuk mendaftarkan nomor WhatsApp Anda ke dalam sistem.\n\n"
                            f"_SIMETRI — Bappeda Kota Tegal_"
                        )
                        archive_result = {
                            "status": "unauthorized",
                            "message": f"Nomor {display_phone} tidak terdaftar di Daftar Pengguna SIMETRI",
                        }
                        await _send_and_log_reply(
                            "UNAUTHORIZED",
                            reply_unauthorized,
                            f"Akses ditolak: Nomor {display_phone} tidak terdaftar di Daftar Pengguna",
                        )
                        return

                    # KASUS 1: Perintah Arsip Eksplisit ("arsipkan ...")
                    if is_archive:
                        if active_surat_id and not has_media and not payload.get("replied_to_id"):
                            # Pengguna memperbarui perihal pada arsip yang baru saja dibuat
                            logger.info(f"[WhatsApp Webhook] Memperbarui perihal Surat ID {active_surat_id} dari {sender_phone} ({greeting_name}): {message_body}")
                            archive_result = update_recent_archive_metadata(
                                surat_id=active_surat_id,
                                new_caption=message_body,
                                sender_phone=sender_phone,
                                user=registered_user,
                            )
                        else:
                            logger.info(f"[WhatsApp Webhook] Memproses permintaan arsip baru dari {sender_phone} ({greeting_name}): {message_body}")
                            archive_result = await process_whatsapp_archive(
                                payload,
                                device_id=device_id,
                                is_forwarded=is_forwarded,
                                user=registered_user,
                            )

                        reply_text = archive_result.get("reply", "")
                        extra = f"Status Arsip: {archive_result.get('status')}"
                        if archive_result.get("surat_id"):
                            extra += f" | Surat ID: {archive_result['surat_id']}"
                        await _send_and_log_reply("ARSIP", reply_text, extra)

                    # KASUS 2: Pesan merupakan koreksi perihal ("ubah perihal: ...", "perihal: ...") pada sesi aktif
                    elif active_surat_id and is_update_command(message_body):
                        logger.info(f"[WhatsApp Webhook] Update perihal Surat ID {active_surat_id} dari {sender_phone} ({greeting_name}): {message_body}")
                        archive_result = update_recent_archive_metadata(
                            surat_id=active_surat_id,
                            new_caption=message_body,
                            sender_phone=sender_phone,
                            user=registered_user,
                        )
                        reply_text = archive_result.get("reply", "")
                        await _send_and_log_reply("ARSIP-UPDATE", reply_text, f"Surat ID: {active_surat_id}")

                    # KASUS 3: Pesan membawa Media (Foto/Dokumen)
                    elif has_media:
                        # Sub-kasus 3-0: Ada sesi kronologi kejadian aktif -> langsung tautkan ke Kejadian!
                        if active_kejadian_id:
                            logger.info(
                                f"[WhatsApp Webhook] Menambahkan lampiran lanjutan ke Kejadian ID {active_kejadian_id} dari {sender_phone} ({greeting_name})"
                            )
                            kejadian_result = await append_whatsapp_kejadian_media(
                                kejadian_id=active_kejadian_id,
                                payload=payload,
                                sender_phone=sender_phone,
                                device_id=device_id,
                                user=registered_user,
                            )
                            reply_text = kejadian_result.get("reply", "")
                            extra = f"Status Kejadian: {kejadian_result.get('status')} | Kejadian ID: {active_kejadian_id}"
                            await _send_and_log_reply("KRONOLOGI-APPEND", reply_text, extra)

                        # Sub-kasus 3A: Ada sesi arsip aktif (multi-file / kelanjutan)
                        elif active_surat_id:
                            logger.info(
                                f"[WhatsApp Webhook] Menambahkan lampiran lanjutan ke Surat ID {active_surat_id} dari {sender_phone} ({greeting_name})"
                            )
                            archive_result = await append_whatsapp_archive_media(
                                surat_id=active_surat_id,
                                payload=payload,
                                sender_phone=sender_phone,
                                device_id=device_id,
                                user=registered_user,
                            )
                            reply_text = archive_result.get("reply", "")
                            extra = f"Status Arsip: {archive_result.get('status')} | Surat ID: {archive_result.get('surat_id')}"
                            await _send_and_log_reply("ARSIP-APPEND", reply_text, extra)

                        # Sub-kasus 3B: Ada perintah arsip pending yang menunggu media
                        elif pending_cmd:
                            logger.info(
                                f"[WhatsApp Webhook] Menautkan media ke perintah arsip pending '{pending_cmd.get('raw_body')}' untuk {sender_phone} ({greeting_name})"
                            )
                            archive_result = await process_whatsapp_archive(
                                payload,
                                device_id=device_id,
                                override_meta=pending_cmd.get("meta"),
                                is_forwarded=is_forwarded,
                                user=registered_user,
                            )
                            reply_text = archive_result.get("reply", "")
                            extra = f"Status Arsip: {archive_result.get('status')} | Surat ID: {archive_result.get('surat_id')}"
                            await _send_and_log_reply("ARSIP-PENDING-MATCH", reply_text, extra)

                        # Sub-kasus 3C: Pesan merupakan TERUSAN (FORWARDING) membawa media -> langsung arsipkan!
                        elif is_forwarded:
                            logger.info(
                                f"[WhatsApp Webhook] Memproses arsip otomatis dari pesan terusan (forwarding) dari {sender_phone} ({greeting_name})"
                            )
                            archive_result = await process_whatsapp_forwarded_archive(
                                payload,
                                device_id=device_id,
                                user=registered_user,
                            )
                            reply_text = archive_result.get("reply", "")
                            extra = f"Status Arsip: {archive_result.get('status')} | Surat ID: {archive_result.get('surat_id')}"
                            await _send_and_log_reply("ARSIP-FORWARD", reply_text, extra)

                        # Sub-kasus 3D: Media reguler tanpa kata 'arsipkan' dan bukan terusan
                        else:
                            # Simpan media sementara di cache agar jika dalam 3 menit user mengirim 'arsipkan...', langsung ditautkan
                            items = await extract_media_items_from_payload(payload, device_id=device_id)
                            if items:
                                register_unarchived_media(clean_phone, items, msg_id=msg_id, caption=message_body)

                            reply_text = (
                                f"Halo *{greeting_name}*,\n\n"
                                f"File foto/dokumen Anda telah kami terima.\n"
                                f"Untuk mengarsipkan ke sistem SIMETRI, silakan balas dengan keterangan contoh:\n"
                                f"👉 *arsipkan Surat Masuk perihal Undangan Rapat*\n\n"
                                f"💡 *Tips:* Anda juga dapat langsung meneruskan (forward) pesan dari chat lain untuk pengarsipan otomatis.\n\n"
                                f"_SIMETRI — Bappeda Kota Tegal_"
                            )
                            await _send_and_log_reply("PANDUAN-MEDIA", reply_text)

                    # KASUS 4: Pesan Teks Terusan tanpa media
                    elif is_forwarded:
                        logger.info(f"[WhatsApp Webhook] Pesan teks terusan diterima dari {sender_phone} ({greeting_name}): {message_body}")
                        reply_text = (
                            f"Halo *{greeting_name}*,\n\n"
                            f"Pesan teks terusan Anda telah diterima.\n"
                            f"Untuk mengarsipkan pesan ini ke SIMETRI, silakan balas dengan:\n"
                            f"👉 *arsipkan [perihal surat]*\n\n"
                            f"_SIMETRI — Bappeda Kota Tegal_"
                        )
                        await _send_and_log_reply("TEXT-FORWARD", reply_text)

                    # KASUS 5: Pesan teks biasa
                    else:
                        reply_text = (
                            f"Halo {greeting_name}, Jangan chat saya yah, saya BOT silahkan chat admin:\n\n BOT SIMLABA"
                        )
                        await _send_and_log_reply("BOT-DEFAULT", reply_text)

                try:
                    if sender_lock:
                        async with sender_lock:
                            await _handle_sender_message()
                    else:
                        await _handle_sender_message()
                finally:
                    complete_message(msg_id)

    # 6. Respon sukses ke pengirim webhook
    response_output: dict[str, Any] = {
        "status": "success",
        "message": "Webhook received and logged successfully",
        "event": event_type,
        "timestamp": timestamp,
    }

    if search_result is not None:
        response_output["search"] = {
            key: search_result[key] for key in ("status", "arsip_count", "kejadian_count") if key in search_result
        }

    if agenda_result is not None:
        response_output["agenda"] = {
            key: agenda_result[key] for key in ("status", "count", "target_date") if key in agenda_result
        }

    if archive_result is not None:
        response_output["archive"] = {
            "status": archive_result.get("status"),
            "surat_id": archive_result.get("surat_id"),
        }

    if kejadian_result is not None:
        response_output["kejadian"] = {
            "status": kejadian_result.get("status"),
            "kejadian_id": kejadian_result.get("kejadian_id"),
            "dokumen_id": kejadian_result.get("dokumen_id"),
        }

    if reply_result is not None:
        response_output["auto_reply"] = {
            "sent": reply_result["success"],
            "http_code": reply_result["http_code"],
        }

    return JSONResponse(content=response_output, status_code=200)


@router.api_route("", methods=["PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def method_not_allowed():
    """Mengembalikan 405 Method Not Allowed untuk HTTP method selain GET dan POST."""
    return JSONResponse(
        content={
            "status": "error",
            "message": "Method Not Allowed. Only POST is accepted.",
        },
        status_code=405,
    )
