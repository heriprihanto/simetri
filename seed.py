"""
Database Seeder SIMETRI
Mengisi data awal master jenis kejadian, master bidang, dan admin default jika belum ada.
"""

from sqlmodel import Session, select
from app.database import engine
from app.models.master import MasterJenisKejadian, MasterBidang
from app.models.user import User
from app.config import get_settings

settings = get_settings()

MASTER_BIDANG_DATA = [
    {"kode": "SEKRETARIAT", "nama": "Sekretariat", "deskripsi": "Sekretariat Bappeda Kota Tegal"},
    {"kode": "PPEP", "nama": "Bidang PPEP", "deskripsi": "Perencanaan, Pengendalian dan Evaluasi Pembangunan"},
    {"kode": "PPM", "nama": "Bidang PPM", "deskripsi": "Pemerintahan dan Pembangunan Manusia"},
    {"kode": "INFRA_WIL", "nama": "Bidang Infrastruktur & Kewilayahan", "deskripsi": "Infrastruktur dan Kewilayahan"},
    {"kode": "EKONOMI_SDA", "nama": "Bidang Perekonomian & SDA", "deskripsi": "Perekonomian dan Sumber Daya Alam"},
]

MASTER_JENIS_KEJADIAN_DATA = [
    {"nama": "Forum Konsultasi Publik", "kategori": "Konsultasi Publik", "warna_badge": "blue", "urutan": 1},
    {"nama": "Musrenbang", "kategori": "Musrenbang", "warna_badge": "purple", "urutan": 2},
    {"nama": "Forum Perangkat Daerah", "kategori": "Forum PD", "warna_badge": "indigo", "urutan": 3},
    {"nama": "Desk Bappeda", "kategori": "Desk", "warna_badge": "cyan", "urutan": 4},
    {"nama": "Rapat TAPD", "kategori": "Rapat", "warna_badge": "amber", "urutan": 5},
    {"nama": "Rakor Teknis Pembangunan Antar OPD dan OPD-Lintas Sektoral", "kategori": "Rakor", "warna_badge": "teal", "urutan": 6},
    {"nama": "Rapat / Konsultasi DPRD", "kategori": "DPRD", "warna_badge": "orange", "urutan": 7},
    {"nama": "Pokir (Pokok Pikiran DPRD)", "kategori": "DPRD", "warna_badge": "rose", "urutan": 8},
    {"nama": "Asistensi", "kategori": "Asistensi", "warna_badge": "emerald", "urutan": 9},
    {"nama": "Verifikasi", "kategori": "Verifikasi", "warna_badge": "lime", "urutan": 10},
    {"nama": "Evaluasi", "kategori": "Evaluasi", "warna_badge": "yellow", "urutan": 11},
    {"nama": "Perubahan Indikator / Target", "kategori": "Perubahan", "warna_badge": "red", "urutan": 12},
    {"nama": "Perubahan Pagu", "kategori": "Perubahan", "warna_badge": "red", "urutan": 13},
    {"nama": "Perubahan Program/Kegiatan/Subkegiatan", "kategori": "Perubahan", "warna_badge": "red", "urutan": 14},
    {"nama": "Arahan Pimpinan", "kategori": "Pimpinan", "warna_badge": "violet", "urutan": 15},
    {"nama": "Surat Masuk/Keluar / Nota Dinas", "kategori": "Surat", "warna_badge": "sky", "urutan": 16},
    {"nama": "Surat Usulan", "kategori": "Surat", "warna_badge": "sky", "urutan": 17},
    {"nama": "Surat Tanggapan / Balasan", "kategori": "Surat", "warna_badge": "sky", "urutan": 18},
    {"nama": "Hasil Evaluasi Provinsi/Kemendagri", "kategori": "Evaluasi", "warna_badge": "amber", "urutan": 19},
    {"nama": "Penetapan Dokumen", "kategori": "Penetapan", "warna_badge": "green", "urutan": 20},
    {"nama": "Kejadian Penting Lainnya", "kategori": "Lainnya", "warna_badge": "gray", "urutan": 21},
]


def seed():
    with Session(engine) as session:
        # 1. Seed Master Bidang
        print("Checking Master Bidang...")
        for item in MASTER_BIDANG_DATA:
            existing = session.exec(
                select(MasterBidang).where(MasterBidang.kode == item["kode"])
            ).first()
            if not existing:
                session.add(MasterBidang(**item))
                print(f"  + Added Bidang: {item['nama']}")
        session.commit()

        # 2. Seed Master Jenis Kejadian
        print("Checking Master Jenis Kejadian...")
        for item in MASTER_JENIS_KEJADIAN_DATA:
            existing = session.exec(
                select(MasterJenisKejadian).where(MasterJenisKejadian.nama == item["nama"])
            ).first()
            if not existing:
                session.add(MasterJenisKejadian(**item))
                print(f"  + Added Jenis Kejadian: {item['nama']}")
        session.commit()

        # 3. Seed Default Admin User
        admin_email = settings.INITIAL_ADMIN_EMAIL
        if admin_email:
            existing_admin = session.exec(
                select(User).where(User.email == admin_email)
            ).first()
            if not existing_admin:
                admin_user = User(
                    email=admin_email,
                    name="Admin Perencanaan Bappeda",
                    role="admin",
                    bidang="SEKRETARIAT",
                    is_active=True,
                )
                session.add(admin_user)
                session.commit()
                print(f"  + Added Admin User: {admin_email}")
            else:
                print(f"  * Admin User already exists: {admin_email}")

        print("Seeding completed successfully!")


if __name__ == "__main__":
    seed()
