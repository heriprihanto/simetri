"""
Konfigurasi terpusat Jinja2Templates untuk SIMETRI.
Menyediakan instance templates singleton dengan globals root_path dan url_path terdaftar.
"""

from fastapi.templating import Jinja2Templates
from app.config import get_settings

settings = get_settings()

def deployment_context(request):
    """Prefix juga tersedia pada fragment HTMX yang tidak mewarisi base.html."""
    return {
        "root_path": request.scope.get("root_path", settings.ROOT_PATH),
        "format_rupiah": format_rupiah,
    }


def format_rupiah(val):
    if val is None or val == "":
        return "Rp 0"
    try:
        n = int(round(float(val)))
        return f"Rp {n:,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return "Rp 0"


templates = Jinja2Templates(directory="app/templates", context_processors=[deployment_context])
templates.env.globals["root_path"] = settings.ROOT_PATH.rstrip("/")
templates.env.globals["url_path"] = settings.url_path
templates.env.filters["rupiah"] = format_rupiah
templates.env.filters["format_rupiah"] = format_rupiah
templates.env.globals["format_rupiah"] = format_rupiah
templates.env.globals["rupiah"] = format_rupiah
