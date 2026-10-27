"""
Service Google Drive — upload file via Service Account.
"""

import logging
from typing import Optional
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Cache instance service
_drive_service = None
_folder_cache: dict[str, str] = {}


def get_drive_service():
    """Inisialisasi atau kembalikan Drive API service singleton."""
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    sa_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    if not sa_file or not Path(sa_file).exists():
        logger.warning("[GDrive] File service account tidak ditemukan: %s", sa_file)
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            sa_file,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        _drive_service = build("drive", "v3", credentials=creds)
        logger.info("[GDrive] Berhasil terhubung ke Google Drive API")
        return _drive_service
    except Exception as e:
        logger.error("[GDrive] Gagal inisialisasi: %s", e)
        return None


def get_or_create_folder(
    folder_name: str, parent_id: Optional[str] = None
) -> Optional[str]:
    """Cari atau buat folder di Google Drive, dengan cache."""
    service = get_drive_service()
    if not service:
        return None

    cache_key = f"{parent_id or 'root'}:{folder_name}"
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]

    # Cari folder yang sudah ada
    escaped = folder_name.replace("'", "\\'")
    parent = parent_id or "root"
    query = (
        f"mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{escaped}' "
        f"and trashed = false "
        f"and '{parent}' in parents"
    )

    try:
        result = (
            service.files()
            .list(
                q=query,
                fields="files(id)",
                pageSize=1,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        if result.get("files"):
            folder_id = result["files"][0]["id"]
            _folder_cache[cache_key] = folder_id
            return folder_id
    except Exception as e:
        logger.error("[GDrive] Gagal mencari folder '%s': %s", folder_name, e)

    # Buat folder baru
    try:
        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        folder = (
            service.files()
            .create(
                body=metadata,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )

        folder_id = folder["id"]
        _folder_cache[cache_key] = folder_id
        logger.info("[GDrive] Dibuat folder '%s' (ID: %s)", folder_name, folder_id)
        return folder_id
    except Exception as e:
        logger.error("[GDrive] Gagal membuat folder '%s': %s", folder_name, e)
        return None


def upload_file(
    local_path: str,
    filename: str,
    mime_type: str,
    folder_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Upload file ke Google Drive.
    Return: {"id": ..., "webViewLink": ..., "webContentLink": ...}
    """
    service = get_drive_service()
    if not service:
        return None

    try:
        metadata = {"name": filename}
        if folder_id:
            metadata["parents"] = [folder_id]

        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)

        file_result = (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id,webViewLink,webContentLink",
                supportsAllDrives=True,
            )
            .execute()
        )

        # Set akses publik agar bisa dilihat tanpa login
        try:
            service.permissions().create(
                fileId=file_result["id"],
                body={"role": "reader", "type": "anyone"},
                supportsAllDrives=True,
            ).execute()
        except Exception:
            pass  # Opsional, upload tetap berhasil

        file_id = file_result.get("id", "")
        return {
            "id": file_id,
            "webViewLink": file_result.get(
                "webViewLink",
                f"https://drive.google.com/file/d/{file_id}/view",
            ),
            "webContentLink": file_result.get(
                "webContentLink",
                f"https://drive.google.com/uc?export=download&id={file_id}",
            ),
        }
    except Exception as e:
        logger.error("[GDrive] Gagal upload '%s': %s", filename, e)
        return None


def upload_with_hierarchy(
    local_path: str,
    filename: str,
    mime_type: str,
    *folder_segments: str,
) -> Optional[dict]:
    """
    Upload file ke Google Drive dengan hirarki folder otomatis.
    Contoh: upload_with_hierarchy(path, name, mime, "RKPD 2027", "Musrenbang", "2026-02-20")
    """
    parent_id = settings.GDRIVE_PARENT_FOLDER_ID

    for segment in folder_segments:
        segment = segment.strip()
        if not segment:
            continue
        folder_id = get_or_create_folder(segment, parent_id)
        if folder_id:
            parent_id = folder_id
        else:
            break

    return upload_file(local_path, filename, mime_type, parent_id)


def get_folder_for_kejadian(tahun: int, bidang_pj: str, dokumen_nama: str) -> Optional[str]:
    """Dapatkan atau buat folder terstruktur untuk lampiran kejadian."""
    parent_id = settings.GDRIVE_PARENT_FOLDER_ID or None
    root_folder = get_or_create_folder("SIMETRI_KRONOLOGI", parent_id=parent_id)
    tahun_folder = get_or_create_folder(str(tahun), parent_id=root_folder)
    dokumen_folder = get_or_create_folder(dokumen_nama[:40], parent_id=tahun_folder)
    return dokumen_folder


def delete_file(file_id: str) -> bool:
    """Hapus file dari Google Drive."""
    service = get_drive_service()
    if not service or not file_id:
        return False

    try:
        service.files().delete(
            fileId=file_id, supportsAllDrives=True
        ).execute()
        return True
    except Exception as e:
        logger.error("[GDrive] Gagal hapus file '%s': %s", file_id, e)
        return False
