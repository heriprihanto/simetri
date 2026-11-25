"""
Model SQLModel untuk Modul Penyusunan Pagu:
- KategoriBelanja (tabel kategori_belanja)
- RincianAnggaran (tabel rincian_anggaran)
"""

from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import TaOpd


class KategoriBelanja(SQLModel, table=True):
    """Kategori belanja dari tabel kategori_belanja."""

    __tablename__ = "kategori_belanja"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    nomor: Optional[int] = Field(default=None)
    jenis: Optional[str] = Field(default=None)
    kategori: Optional[str] = Field(default=None)
    ket: Optional[str] = Field(default=None)

    @property
    def label_kategori(self) -> str:
        """Kategori bersih tanpa newline."""
        if not self.kategori:
            return ""
        return " ".join(self.kategori.split())


class RincianAnggaran(SQLModel, table=True):
    """Rincian anggaran dari tabel rincian_anggaran."""

    __tablename__ = "rincian_anggaran"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    id_pd: Optional[int] = Field(
        default=None, foreign_key="ta_opd.id_sub_pd", index=True
    )
    id_kategori: Optional[int] = Field(
        default=None, foreign_key="kategori_belanja.id", index=True
    )
    uraian: Optional[str] = Field(default=None)
    uraian_belanja: Optional[str] = Field(default=None)
    anggaran: Optional[Decimal] = Field(default=Decimal(0))
    tags: Optional[str] = Field(default=None)

    # Relationships
    opd: Optional["TaOpd"] = Relationship()
    kategori_rel: Optional[KategoriBelanja] = Relationship()

    @property
    def formatted_anggaran(self) -> str:
        """Format nominal rupiah."""
        val = int(self.anggaran or 0)
        return f"Rp {val:,.0f}".replace(",", ".")

