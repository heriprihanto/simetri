"""
Registrasi semua model SQLModel.
Import file ini agar SQLModel.metadata mengenal seluruh tabel.
"""

from app.models.user import User, TaOpd  # noqa: F401
from app.models.dokumen import DokumenPerencanaan  # noqa: F401
from app.models.kejadian import Kejadian, LampiranKejadian  # noqa: F401
from app.models.surat import Surat, AttachmentSurat  # noqa: F401
from app.models.agenda import Agenda, Foto  # noqa: F401
from app.models.master import MasterJenisKejadian, MasterBidang  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
