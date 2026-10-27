"""
Model Master Data: Jenis Kejadian dan Bidang Bappeda.
"""

from typing import Optional
from sqlmodel import SQLModel, Field


class MasterJenisKejadian(SQLModel, table=True):
    """Master data jenis-jenis kejadian perencanaan."""

    __tablename__ = "master_jenis_kejadians"

    id: Optional[int] = Field(default=None, primary_key=True)
    nama: str = Field(unique=True, index=True)
    kategori: str = Field(default="")
    warna_badge: str = Field(default="")
    urutan: int = Field(default=0)


class MasterBidang(SQLModel, table=True):
    """Master data bidang-bidang di Bappeda Kota Tegal."""

    __tablename__ = "master_bidangs"

    id: Optional[int] = Field(default=None, primary_key=True)
    kode: str = Field(unique=True, index=True)
    nama: str
    deskripsi: str = Field(default="")
