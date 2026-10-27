"""
Model Audit Log — rekam jejak aktivitas pengguna.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, DateTime
from sqlmodel import SQLModel, Field


class AuditLog(SQLModel, table=True):
    """Rekam jejak setiap aktivitas penting pengguna."""

    __tablename__ = "audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True)
    user_email: str = Field(default="", index=True)
    user_name: str = Field(default="")
    user_bidang: str = Field(default="")
    action: str = Field(index=True)  # "LOGIN","CREATE","UPDATE","DELETE","UPLOAD"
    entity: str = Field(index=True)  # "kejadian","dokumen","surat","agenda","lampiran","auth","user"
    entity_id: str = Field(default="", index=True)
    description: str = Field(default="")
    ip_address: str = Field(default="")
    user_agent: str = Field(default="")
    details: str = Field(default="")  # JSON snapshot
    created_at: datetime = Field(sa_column=Column(DateTime, default=datetime.now, index=True))
