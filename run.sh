#!/bin/bash
# Script menjalankan SIMETRI Bappeda Kota Tegal

set -e

# Masuk ke direktori script
cd "$(dirname "$0")"

# Aktifkan virtual environment jika ada
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Pastikan tabel tersedia sebelum seeding pada database baru
python3 -c 'from app.database import init_db; init_db()'
python3 seed.py

# Jalankan server FastAPI dengan Uvicorn
PORT=${PORT:-$(python3 -c 'from app.config import get_settings; print(get_settings().PORT)')}
FORWARDED_ALLOW_IPS=${FORWARDED_ALLOW_IPS:-$(python3 -c 'from app.config import get_settings; print(get_settings().FORWARDED_ALLOW_IPS)')}
echo "Menjalankan SIMETRI pada http://127.0.0.1:$PORT ..."
exec uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --proxy-headers --forwarded-allow-ips="$FORWARDED_ALLOW_IPS" --reload
