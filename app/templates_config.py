"""
Konfigurasi terpusat Jinja2Templates untuk SIMETRI.
Menyediakan instance templates singleton dengan globals root_path dan url_path terdaftar.
"""

from fastapi.templating import Jinja2Templates
from app.config import get_settings

settings = get_settings()

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["root_path"] = settings.ROOT_PATH.rstrip("/")
templates.env.globals["url_path"] = settings.url_path
