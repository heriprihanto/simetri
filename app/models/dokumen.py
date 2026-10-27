"""
Model Dokumen Perencanaan.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Column, DateTime
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.user import User


class DokumenPerencanaan(SQLModel, table=True):
    """Dokumen perencanaan pembangunan daerah (tingkat kota maupun OPD)."""

    __tablename__ = "dokumen_perencanaans"

    id: Optional[int] = Field(default=None, primary_key=True)
    nama: str  # "RPJMD Kota Tegal 2025-2030"
    alias: str = Field(default="", index=True)  # Alias untuk keyword WhatsApp (contoh: "rkpd", "rpjmd")
    jenis: str  # "RPJPD","RPJMD","RKPD","Renstra","Renja","Perubahan RKPD"
    tahun_awal: int = Field(default=0)
    tahun_akhir: int = Field(default=0)
    tahun_rencana: int = Field(default=0)
    opd_id: Optional[int] = Field(
        default=None, foreign_key="ta_opd.id_sub_pd", index=True
    )  # null = tingkat kota
    status: str = Field(default="dalam proses")  # "dalam proses", "selesai"
    is_active: bool = Field(default=True)
    is_default: bool = Field(default=False)
    deskripsi: str = Field(default="")
    created_by_id: Optional[int] = Field(
        default=None, foreign_key="users.id"
    )
    created_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))
    updated_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))

    @property
    def is_tingkat_kota(self) -> bool:
        return self.opd_id is None

    @property
    def label_cakupan(self) -> str:
        return "Tingkat Kota" if self.is_tingkat_kota else "Tingkat OPD"

    @property
    def rentang_tahun(self) -> str:
        if self.tahun_awal == self.tahun_akhir:
            return str(self.tahun_awal)
        return f"{self.tahun_awal} – {self.tahun_akhir}"


# Daftar jenis dokumen perencanaan yang diizinkan
JENIS_DOKUMEN = [
    "RPJPD",
    "RPJMD",
    "RKPD",
    "Perubahan RKPD",
    "Renstra",
    "Renja",
]
