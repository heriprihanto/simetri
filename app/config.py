"""
Konfigurasi aplikasi SIMETRI.
Menggunakan pydantic-settings untuk memuat dari file .env.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Server
    PORT: int = 8000
    SERVER_URL: str = "http://localhost:8000"
    SECRET_KEY: str = "simetri_bappeda_kota_tegal_super_secret_key_2026"

    # Database PostgreSQL
    DB_HOST: str = "192.168.50.75"
    DB_PORT: int = 5432
    DB_USER: str = "monevrkpd"
    DB_PASSWORD: str = "heriprihanto140286"
    DB_NAME: str = "simetri"
    DB_SSLMODE: str = "disable"

    # Google OAuth 2.0
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/oauthcallback"

    # Google Service Account (untuk Drive upload)
    GOOGLE_SERVICE_ACCOUNT_FILE: str = "./secrets/service_account.json"
    GDRIVE_PARENT_FOLDER_ID: str = ""

    # Google Drive folder names
    GDRIVE_ARSIP_FOLDER_NAME: str = "ARSIP_SURAT_BAPPEDA"
    GDRIVE_GALERI_FOLDER_NAME: str = "GALERI_KEGIATAN_BAPPEDA"

    # WhatsApp Gateway API & Storage
    WA_API_URL: str = "http://localhost:3000/send/message"
    WA_DEVICE_ID: str = "Simetri"
    WA_STORAGE_PATH: str = "/home/herry/1_Project/go-whatsapp-web-multidevice/src"
    WA_MEDIA_DIR: str = ""

    @model_validator(mode="after")
    def set_default_wa_paths(self):
        if not self.WA_MEDIA_DIR and self.WA_STORAGE_PATH:
            self.WA_MEDIA_DIR = f"{self.WA_STORAGE_PATH.rstrip('/')}/statics/media"
        return self

    @property
    def wa_server_url(self) -> str:
        url = self.WA_API_URL
        if "/send" in url:
            return url.split("/send")[0]
        return url.rstrip("/")

    # Initial Admin
    INITIAL_ADMIN_EMAIL: str = "perencanaan.bappedategalkota@gmail.com"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
