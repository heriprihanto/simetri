"""
Koneksi database PostgreSQL menggunakan SQLModel + SQLAlchemy.
"""

from sqlmodel import SQLModel, Session, create_engine
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)


def init_db():
    """Buat semua tabel yang belum ada di database."""
    # Import semua model agar SQLModel mengenali metadata-nya
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency FastAPI untuk mendapatkan database session."""
    with Session(engine) as session:
        yield session


get_db = get_session
