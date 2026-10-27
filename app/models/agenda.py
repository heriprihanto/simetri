"""
Model Agenda (Kegiatan) dan Foto.
"""

from datetime import date, datetime
from typing import Optional, List
from sqlalchemy import Column, DateTime
from sqlmodel import SQLModel, Field, Relationship


class Foto(SQLModel, table=True):
    """Foto dokumentasi kegiatan di Google Drive."""

    __tablename__ = "foto"

    id: Optional[int] = Field(default=None, primary_key=True)
    agenda_id: int = Field(foreign_key="agenda.id", index=True)
    drive_file_id: str
    drive_link: str
    filename: str
    mime_type: str = Field(default="")
    size_bytes: int = Field(default=0)
    uploaded_by_id: Optional[int] = Field(default=None, foreign_key="users.id")
    uploaded_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))


class Agenda(SQLModel, table=True):
    """Agenda kegiatan: rapat, undangan, kunjungan, dll."""

    __tablename__ = "agenda"

    id: Optional[int] = Field(default=None, primary_key=True)
    judul: str
    kategori: str = Field(default="Rapat")  # "Rapat","Undangan","Kunjungan","Lainnya"
    tanggal: date = Field(index=True)
    jam_mulai: str = Field(default="")
    jam_selesai: str = Field(default="")
    tempat: str = Field(default="")
    bidang: str = Field(default="", index=True)
    keterangan: str = Field(default="")
    surat_id: Optional[int] = Field(default=None, foreign_key="surat.id", index=True)
    drive_folder_id: str = Field(default="")
    calendar_event_id: str = Field(default="")
    calendar_synced_at: Optional[datetime] = Field(sa_column=Column(DateTime, default=None))
    created_by_id: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))
    updated_at: Optional[datetime] = Field(sa_column=Column(DateTime, default=None))

    # Relationships
    foto_list: List[Foto] = Relationship()

    @property
    def rentang_jam(self) -> str:
        if not self.jam_mulai:
            return "Sehari penuh"
        if self.jam_selesai:
            return f"{self.jam_mulai} – {self.jam_selesai}"
        return self.jam_mulai


# Kategori agenda
KATEGORI_AGENDA = ["Rapat", "Undangan", "Kunjungan", "Lainnya"]

# Warna per kategori agenda
WARNA_KATEGORI_AGENDA = {
    "Rapat": {
        "bg": "bg-indigo-50 dark:bg-indigo-500/15",
        "text": "text-indigo-700 dark:text-indigo-300",
        "border": "border-indigo-200 dark:border-indigo-500/30",
        "dot": "bg-indigo-500",
        "grad": "from-indigo-500 to-violet-600",
    },
    "Undangan": {
        "bg": "bg-emerald-50 dark:bg-emerald-500/15",
        "text": "text-emerald-700 dark:text-emerald-300",
        "border": "border-emerald-200 dark:border-emerald-500/30",
        "dot": "bg-emerald-500",
        "grad": "from-emerald-500 to-teal-600",
    },
    "Kunjungan": {
        "bg": "bg-amber-50 dark:bg-amber-500/15",
        "text": "text-amber-700 dark:text-amber-300",
        "border": "border-amber-200 dark:border-amber-500/30",
        "dot": "bg-amber-500",
        "grad": "from-amber-500 to-orange-600",
    },
    "Lainnya": {
        "bg": "bg-slate-100 dark:bg-slate-700",
        "text": "text-slate-700 dark:text-slate-200",
        "border": "border-slate-200 dark:border-slate-600",
        "dot": "bg-slate-400",
        "grad": "from-slate-500 to-slate-600",
    },
}
