"""
Model Kejadian (Kronologi) dan LampiranKejadian.
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import Text, Column, DateTime
from sqlmodel import SQLModel, Field, Relationship


class LampiranKejadian(SQLModel, table=True):
    """File lampiran kejadian: dokumen, foto, atau link eksternal."""

    __tablename__ = "lampiran_kejadians"

    id: Optional[int] = Field(default=None, primary_key=True)
    kejadian_id: int = Field(foreign_key="kejadians.id", index=True)
    tipe_lampiran: str = Field(default="file_gdrive")  # "file_gdrive", "foto", "link_eksternal"
    judul: str = Field(default="")
    file_name: str = Field(default="")
    mime_type: str = Field(default="")
    file_size: int = Field(default=0)
    g_drive_file_id: str = Field(default="")
    g_drive_web_view_link: str = Field(default="")
    g_drive_download_link: str = Field(default="")
    external_url: str = Field(default="")
    created_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))

    @property
    def is_file(self) -> bool:
        return self.tipe_lampiran in ("file_gdrive", "foto")

    @property
    def is_link(self) -> bool:
        return self.tipe_lampiran == "link_eksternal"

    @property
    def display_url(self) -> str:
        if self.is_link:
            return self.external_url
        return self.g_drive_web_view_link

    @property
    def size_display(self) -> str:
        if not self.file_size:
            return ""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"


class Kejadian(SQLModel, table=True):
    """Kronologi kejadian dalam proses perencanaan pembangunan."""

    __tablename__ = "kejadians"

    id: Optional[int] = Field(default=None, primary_key=True)
    dokumen_id: int = Field(foreign_key="dokumen_perencanaans.id", index=True)
    tanggal_kejadian: datetime = Field(sa_column=Column(DateTime, index=True))
    waktu_mulai: str = Field(default="")
    waktu_selesai: str = Field(default="")
    lokasi: str = Field(default="")
    jenis_kejadian: str = Field(index=True)
    judul_kejadian: str
    uraian_kronologi: str = Field(default="", sa_type=Text)
    pihak_pengusul: str = Field(default="", sa_type=Text)
    hasil_pembahasan: str = Field(default="", sa_type=Text)
    dasar_dokumen_keputusan: str = Field(default="", sa_type=Text)
    bidang_pj: str = Field(default="", index=True)
    perubahan_indikator_target: str = Field(default="", sa_type=Text)
    perubahan_pagu: str = Field(default="", sa_type=Text)
    program_kegiatan_terkait: str = Field(default="", sa_type=Text)
    created_by_id: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))
    updated_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))

    # Relationships
    lampiran: List[LampiranKejadian] = Relationship()

    @property
    def rentang_waktu(self) -> str:
        if not self.waktu_mulai:
            return "Sehari penuh"
        if self.waktu_selesai:
            return f"{self.waktu_mulai} – {self.waktu_selesai}"
        return self.waktu_mulai

    @property
    def tanggal_format(self) -> str:
        return self.tanggal_kejadian.strftime("%d %B %Y")
