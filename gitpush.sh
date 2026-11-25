#!/bin/bash

set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 \"nama commit\""
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

#echo "🔨 Menjalankan build frontend..."
#npm --prefix FrontEnd run build

git add .
git commit -m "$*"
git push origin main

echo "✓ Commit dan push berhasil!"
