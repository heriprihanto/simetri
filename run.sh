#!/bin/bash
# Script menjalankan SIMETRI Bappeda Kota Tegal

set -e

# Masuk ke direktori script
cd "$(dirname "$0")"

# Aktifkan virtual environment jika ada
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Pastikan tabel & data master terisi
python3 seed.py

# Jalankan server FastAPI dengan Uvicorn
PORT=${PORT:-8987}
echo "Menjalankan SIMETRI pada http://localhost:$PORT ..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*' --reload
