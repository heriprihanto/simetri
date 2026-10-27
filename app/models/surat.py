"""
Model Surat (Arsip) dan AttachmentSurat.
"""

from datetime import date, datetime
from typing import Optional, List
from sqlalchemy import Column, DateTime
from sqlmodel import SQLModel, Field, Relationship


class AttachmentSurat(SQLModel, table=True):
    """File lampiran surat di Google Drive."""

    __tablename__ = "attachment_surat"

    id: Optional[int] = Field(default=None, primary_key=True)
    surat_id: int = Field(foreign_key="surat.id", index=True)
    drive_file_id: str
    drive_link: str
    filename: str
    mime_type: str = Field(default="")
    size_bytes: int = Field(default=0)
    uploaded_by_id: Optional[int] = Field(default=None, foreign_key="users.id")
    uploaded_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))

    @property
    def size_display(self) -> str:
        """Ukuran file dalam format yang mudah dibaca."""
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        else:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"


class Surat(SQLModel, table=True):
    """Arsip surat dan dokumen kedinasan."""

    __tablename__ = "surat"

    id: Optional[int] = Field(default=None, primary_key=True)
    jenis_surat: str = Field(index=True)
    nomor_surat: str
    tanggal_surat: date = Field(index=True)
    pihak: str  # pengirim/penerima/penerbit
    perihal: str
    keterangan: str = Field(default="")
    created_by_id: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))
    updated_at: Optional[datetime] = Field(sa_column=Column(DateTime, default=None))

    # Relationships
    attachments: List[AttachmentSurat] = Relationship()


# Jenis surat yang diizinkan
JENIS_SURAT = [
    "Surat Masuk",
    "Surat Keluar",
    "Surat Keputusan",
    "Peraturan",
    "Dokumen",
    "Materi Paparan",
    "Dokumen Lainnya",
]

# Warna badge per jenis surat
WARNA_JENIS_SURAT = {
    "Surat Masuk": {
        "bg": "bg-emerald-50 dark:bg-emerald-500/15",
        "text": "text-emerald-700 dark:text-emerald-300",
        "border": "border-emerald-200 dark:border-emerald-500/30",
        "dot": "bg-emerald-500",
    },
    "Surat Keluar": {
        "bg": "bg-amber-50 dark:bg-amber-500/15",
        "text": "text-amber-700 dark:text-amber-300",
        "border": "border-amber-200 dark:border-amber-500/30",
        "dot": "bg-amber-500",
    },
    "Surat Keputusan": {
        "bg": "bg-violet-50 dark:bg-violet-500/15",
        "text": "text-violet-700 dark:text-violet-300",
        "border": "border-violet-200 dark:border-violet-500/30",
        "dot": "bg-violet-500",
    },
    "Peraturan": {
        "bg": "bg-rose-50 dark:bg-rose-500/15",
        "text": "text-rose-700 dark:text-rose-300",
        "border": "border-rose-200 dark:border-rose-500/30",
        "dot": "bg-rose-500",
    },
    "Dokumen": {
        "bg": "bg-sky-50 dark:bg-sky-500/15",
        "text": "text-sky-700 dark:text-sky-300",
        "border": "border-sky-200 dark:border-sky-500/30",
        "dot": "bg-sky-500",
    },
    "Materi Paparan": {
        "bg": "bg-fuchsia-50 dark:bg-fuchsia-500/15",
        "text": "text-fuchsia-700 dark:text-fuchsia-300",
        "border": "border-fuchsia-200 dark:border-fuchsia-500/30",
        "dot": "bg-fuchsia-500",
    },
    "Dokumen Lainnya": {
        "bg": "bg-slate-100 dark:bg-slate-700",
        "text": "text-slate-700 dark:text-slate-200",
        "border": "border-slate-200 dark:border-slate-600",
        "dot": "bg-slate-400",
    },
}


def label_pihak(jenis: str) -> str:
    """Label kolom 'pihak' menyesuaikan jenis surat."""
    if jenis == "Surat Masuk":
        return "Pengirim"
    if jenis == "Surat Keluar":
        return "Penerima"
    return "Penerbit / Sumber"
