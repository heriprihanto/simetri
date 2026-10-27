"""
Model User dan TaOpd (master OPD existing).
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, DateTime
from sqlmodel import SQLModel, Field, Relationship


class TaOpd(SQLModel, table=True):
    """Master OPD dari tabel ta_opd yang sudah ada di database."""

    __tablename__ = "ta_opd"
    __table_args__ = {"extend_existing": True}

    id_sub_pd: int = Field(primary_key=True)
    id_pd: Optional[int] = Field(default=None)
    kode: str = Field(default="")
    nama_pd: str = Field(default="")
    nip_kepala: str = Field(default="")
    nama_kepala: str = Field(default="")
    is_pd: int = Field(default=0)
    bidangurusan: str = Field(default="")
    nama_pd_singkat: str = Field(default="")
    jabatan_kepala: str = Field(default="")
    alamat: str = Field(default="")
    telp: str = Field(default="")
    email: str = Field(default="")
    aktif: int = Field(default=1)


class User(SQLModel, table=True):
    """Pengguna aplikasi SIMETRI (whitelist oleh admin)."""

    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str = Field(default="")
    avatar: str = Field(default="")
    role: str = Field(default="user_bidang")  # "admin", "user_bidang", "user_opd"
    bidang: str = Field(default="")  # Kode bidang di Bappeda
    no_hp: str = Field(default="")  # Nomor WhatsApp / HP pengguna
    opd_id: Optional[int] = Field(
        default=None, foreign_key="ta_opd.id_sub_pd", index=True
    )
    is_active: bool = Field(default=True)
    created_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))
    updated_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now))

    # Relationships
    opd: Optional[TaOpd] = Relationship()

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_user_bidang(self) -> bool:
        return self.role == "user_bidang"

    @property
    def is_user_opd(self) -> bool:
        return self.role == "user_opd"

    @property
    def display_name(self) -> str:
        return self.name or self.email

    @property
    def initial(self) -> str:
        return (self.name or self.email)[0].upper()
