"""
Konfigurasi aplikasi SIMETRI.
Menggunakan pydantic-settings untuk memuat dari file .env.
"""

from typing import Any, Optional
from functools import lru_cache
from urllib.parse import urlsplit
import secrets
from pydantic import model_validator
from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    # Server & Reverse Proxy
    PORT: int = 8000
    SERVER_URL: str = "http://localhost:8000"
    ROOT_PATH: str = ""  # Di server: "/simetri" jika diakses via reverse proxy
    COOKIE_SECURE: bool = False  # Di server: True (HTTPS)
    SECRET_KEY: str = ""
    FORWARDED_ALLOW_IPS: str = "127.0.0.1"

    def url_path(self, path: str, request: Any = None) -> str:
        """URL lokal berdasarkan prefix konfigurasi, bukan header dari klien."""
        root = self.ROOT_PATH
        if not path.startswith("/"):
            path = "/" + path
        if root and (path == root or path.startswith(root + "/") or path.startswith(root + "?")):
            return path
        return f"{root}{path}" if root else path

    # Database PostgreSQL
    DB_HOST: str = "192.168.50.75"
    DB_PORT: int = 5432
    DB_USER: str = "monevrkpd"
    DB_PASSWORD: str = ""
    DB_NAME: str = "simetri"
    DB_SSLMODE: str = "disable"

    # Google OAuth 2.0
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""

    # Google Service Account (untuk Drive upload)
    GOOGLE_SERVICE_ACCOUNT_FILE: str = "./secrets/service_account.json"
    GDRIVE_PARENT_FOLDER_ID: str = ""

    # Google Drive folder names
    GDRIVE_ARSIP_FOLDER_NAME: str = "ARSIP_SURAT_BAPPEDA"
    GDRIVE_GALERI_FOLDER_NAME: str = "GALERI_KEGIATAN_BAPPEDA"

    # Google Gemini AI (Chatbot)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"

    # WhatsApp Gateway API & Storage
    WA_API_URL: str = "http://localhost:3000/send/message"
    WA_DEVICE_ID: str = "Simetri"
    WA_STORAGE_PATH: str = "/home/herry/1_Project/go-whatsapp-web-multidevice/src"
    WA_MEDIA_DIR: str = ""

    @model_validator(mode="after")
    def set_default_wa_paths(self):
        public = urlsplit(self.SERVER_URL)
        if public.scheme not in ("http", "https") or not public.netloc or public.query or public.fragment:
            raise ValueError("SERVER_URL harus berupa URL HTTP(S) tanpa query/fragment")
        self.ROOT_PATH = self.ROOT_PATH.rstrip("/") or public.path.rstrip("/")
        if self.ROOT_PATH and (not self.ROOT_PATH.startswith("/") or self.ROOT_PATH.startswith("//") or any(c in self.ROOT_PATH for c in ('?', '#', '"', "'", '<', '>', '\\'))):
            raise ValueError("ROOT_PATH harus berupa path absolut, misalnya /simetri")
        if public.path.rstrip("/") and public.path.rstrip("/") != self.ROOT_PATH:
            raise ValueError("Path SERVER_URL harus sama dengan ROOT_PATH")
        self.SERVER_URL = f"{public.scheme}://{public.netloc}{self.ROOT_PATH}"
        if not self.GOOGLE_REDIRECT_URI:
            self.GOOGLE_REDIRECT_URI = self.SERVER_URL + "/oauthcallback"
        if public.scheme == "https":
            if len(self.SECRET_KEY) < 32 or self.SECRET_KEY == "simetri_bappeda_kota_tegal_super_secret_key_2026":
                raise ValueError("Deployment HTTPS memerlukan SECRET_KEY acak minimal 32 karakter")
            if not self.COOKIE_SECURE:
                raise ValueError("Deployment HTTPS memerlukan COOKIE_SECURE=true")
            if self.GOOGLE_REDIRECT_URI not in (self.SERVER_URL + "/oauthcallback", self.SERVER_URL + "/auth/google"):
                raise ValueError("GOOGLE_REDIRECT_URI harus mengarah ke callback pada SERVER_URL")
        elif not self.SECRET_KEY:
            self.SECRET_KEY = secrets.token_urlsafe(48)
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
        return URL.create(
            "postgresql+psycopg2", username=self.DB_USER, password=self.DB_PASSWORD,
            host=self.DB_HOST, port=self.DB_PORT, database=self.DB_NAME,
            query={"sslmode": self.DB_SSLMODE, "connect_timeout": "5"},
        ).render_as_string(hide_password=False)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
