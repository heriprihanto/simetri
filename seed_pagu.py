"""
Script Seeder Fake Data Rincian Anggaran untuk Modul Penyusunan Pagu SIMETRI.
Usage:
    python3 seed_pagu.py [--total 100] [--clear]
"""

import sys
import argparse
from sqlmodel import Session
from app.database import engine
from app.services.pagu_service import generate_fake_rincian_anggaran, get_pagu_matrix

def main():
    parser = argparse.ArgumentParser(description="Seed fake data rincian anggaran")
    parser.add_argument("--total", type=int, default=120, help="Jumlah fake records yang dibuat")
    parser.add_argument("--clear", action="store_true", help="Hapus data rincian anggaran yang sudah ada terlebih dahulu")
    args = parser.parse_args()

    print(f"Menyiapkan pembuatan {args.total} fake data rincian anggaran...")
    with Session(engine) as session:
        count = generate_fake_rincian_anggaran(session, total_target=args.total, clear_existing=args.clear)
        matrix = get_pagu_matrix(session)
        print(f"✓ Berhasil menambahkan {count} data rincian anggaran!")
        print(f"  - Total Data di DB: {matrix['total_all_records']}")
        print(f"  - Grand Total Pagu: Rp {int(matrix['grand_total']):,.0f}".replace(",", "."))

if __name__ == "__main__":
    main()

