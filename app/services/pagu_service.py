"""
Service untuk Modul Penyusunan Pagu:
- Agregasi matriks pagu (OPD x Kategori Belanja)
- Manajemen CRUD rincian anggaran
- Generator fake data rincian anggaran
"""

import random
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlmodel import Session, col, desc, select

from app.models.pagu import KategoriBelanja, RincianAnggaran
from app.models.user import TaOpd


def get_all_jenis_kategori(db: Session) -> List[str]:
    """Mengambil daftar jenis kategori belanja unik."""
    stmt = (
        select(KategoriBelanja.jenis)
        .where(KategoriBelanja.jenis != None)  # noqa: E711
        .distinct()
        .order_by(KategoriBelanja.jenis)
    )
    results = db.exec(stmt).all()
    return [j for j in results if j]


def get_pagu_matrix(
    db: Session,
    jenis_filter: Optional[str] = None,
    q_opd: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Menyusun matriks data pagu:
    - Baris: Perangkat Daerah (ta_opd, is_pd=1, aktif=1)
    - Kolom: Kategori Belanja (kategori_belanja.kategori)
    - Cell: Nilai total anggaran dari rincian_anggaran
    """
    # 1. Ambil Perangkat Daerah
    opd_stmt = select(TaOpd).where(TaOpd.is_pd == 1, TaOpd.aktif == 1)
    if q_opd:
        keyword = f"%{q_opd.strip().lower()}%"
        opd_stmt = opd_stmt.where(
            func.lower(TaOpd.nama_pd).like(keyword) | func.lower(TaOpd.kode).like(keyword)
        )
    opd_list = db.exec(opd_stmt.order_by(TaOpd.kode)).all()

    # 2. Ambil Kategori Belanja
    kat_stmt = select(KategoriBelanja)
    if jenis_filter and jenis_filter != "ALL":
        kat_stmt = kat_stmt.where(KategoriBelanja.jenis == jenis_filter)
    kat_list = db.exec(kat_stmt.order_by(KategoriBelanja.nomor, KategoriBelanja.id)).all()

    # 3. Agregasi rincian anggaran per (id_pd, id_kategori)
    agg_stmt = (
        select(
            RincianAnggaran.id_pd,
            RincianAnggaran.id_kategori,
            func.sum(RincianAnggaran.anggaran).label("total_anggaran"),
            func.count(RincianAnggaran.id).label("item_count"),
        )
        .group_by(RincianAnggaran.id_pd, RincianAnggaran.id_kategori)
    )
    agg_rows = db.exec(agg_stmt).all()

    matrix: Dict[int, Dict[int, Dict[str, Any]]] = {}
    pd_totals: Dict[int, Decimal] = {}
    pd_counts: Dict[int, int] = {}
    kat_totals: Dict[int, Decimal] = {}
    kat_counts: Dict[int, int] = {}
    grand_total = Decimal(0)
    grand_count = 0

    for row in agg_rows:
        id_pd = row[0]
        id_kat = row[1]
        total = Decimal(row[2] or 0)
        cnt = int(row[3] or 0)

        if id_pd not in matrix:
            matrix[id_pd] = {}
        matrix[id_pd][id_kat] = {"total": total, "count": cnt}

        pd_totals[id_pd] = pd_totals.get(id_pd, Decimal(0)) + total
        pd_counts[id_pd] = pd_counts.get(id_pd, 0) + cnt

        kat_totals[id_kat] = kat_totals.get(id_kat, Decimal(0)) + total
        kat_counts[id_kat] = kat_counts.get(id_kat, 0) + cnt

        grand_total += total
        grand_count += cnt

    # Total jumlah seluruh rincian anggaran di database (tanpa filter kolom)
    total_all_records = db.exec(select(func.count(RincianAnggaran.id))).one() or 0
    total_all_anggaran = db.exec(select(func.sum(RincianAnggaran.anggaran))).one() or Decimal(0)

    return {
        "opd_list": opd_list,
        "kategori_list": kat_list,
        "matrix": matrix,
        "pd_totals": pd_totals,
        "pd_counts": pd_counts,
        "kat_totals": kat_totals,
        "kat_counts": kat_counts,
        "grand_total": grand_total,
        "grand_count": grand_count,
        "total_all_records": total_all_records,
        "total_all_anggaran": Decimal(total_all_anggaran),
        "all_jenis": get_all_jenis_kategori(db),
        "current_jenis": jenis_filter or "ALL",
        "q_opd": q_opd or "",
    }


def get_rincian_anggaran_list(
    db: Session,
    id_pd: Optional[int] = None,
    id_kategori: Optional[int] = None,
    q: Optional[str] = None,
    page: int = 1,
    per_page: int = 15,
) -> Tuple[List[RincianAnggaran], int, int]:
    """Mengambil daftar rincian anggaran dengan filter dan pagination."""
    stmt = select(RincianAnggaran)

    if id_pd:
        stmt = stmt.where(RincianAnggaran.id_pd == id_pd)
    if id_kategori:
        stmt = stmt.where(RincianAnggaran.id_kategori == id_kategori)
    if q:
        kwd = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(RincianAnggaran.uraian).like(kwd)
            | func.lower(RincianAnggaran.uraian_belanja).like(kwd)
            | func.lower(RincianAnggaran.tags).like(kwd)
        )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_items = db.exec(count_stmt).one() or 0

    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    offset = (page - 1) * per_page
    stmt = (
        stmt.order_by(desc(RincianAnggaran.id))
        .offset(offset)
        .limit(per_page)
    )
    items = db.exec(stmt).all()
    return items, total_items, total_pages


def get_opd_pagu_summary(db: Session, id_pd: int) -> Dict[str, Any]:
    """Mengambil ringkasan pagu untuk satu Perangkat Daerah."""
    stmt = (
        select(
            func.sum(RincianAnggaran.anggaran).label("total_anggaran"),
            func.count(RincianAnggaran.id).label("total_items"),
            func.count(func.distinct(RincianAnggaran.id_kategori)).label("kategori_count"),
        )
        .where(RincianAnggaran.id_pd == id_pd)
    )
    row = db.exec(stmt).one()
    return {
        "total_anggaran": Decimal(row[0] or 0),
        "total_items": int(row[1] or 0),
        "kategori_count": int(row[2] or 0),
    }


# --------------------------------------------------------------------------
# FAKE DATA GENERATOR
# --------------------------------------------------------------------------

CONTOH_URAIAN_BY_JENIS = {
    "BELANJA PEGAWAI": [
        ("Penyediaan Gaji dan Tunjangan ASN", "Gaji Pokok PNS dan Tunjangan Keluarga Jan - Des"),
        ("Tambahan Penghasilan Pegawai (TPP)", "TPP Berdasarkan Beban Kerja dan Prestasi Kerja ASN"),
        ("Penyediaan Gaji dan Tunjangan PPPK", "Gaji Pokok dan Tunjangan PPPK Formasi Terakhir"),
        ("Insentif Pemungutan Pajak dan Retribusi Daerah", "Insentif Petugas Pemungut Pajak Daerah"),
        ("Penyediaan Tunjangan Profesi Guru", "Tunjangan Sertifikasi / TPG Guru Terakreditasi"),
    ],
    "DANA TRANSFER": [
        ("Pengelolaan Dana BOS Reguler", "Penyediaan Operasional Sekolah dan Bahan Ajar Siswa"),
        ("Bantuan Operasional Kesehatan (BOK)", "Operasional Pelayanan Kesehatan Dasar di Puskesmas"),
        ("Pemanfaatan DBHCHT untuk Pelayanan Publik", "Pengadaan Alat Kesehatan & Pembinaan Buruh Pabrik Rokok"),
        ("Penyelenggaraan DAK Fisik Bidang Infrastruktur", "Rehabilitasi Saluran Drainase dan Jalan Lingkungan"),
        ("Fasilitasi Kegiatan TMMD", "Karya Bakti TNI Manunggal Membangun Desa / Kelurahan"),
    ],
    "HARUS DIAKOMODIR KELURAHAN": [
        ("Fasilitasi Operasional Lembaga Kemasyarakatan Kelurahan", "Bantuan Operasional RT, RW, dan LPMK"),
        ("Jaminan Keselamatan Kerja Pengurus RT/RW", "Iuran BPJS Ketenagakerjaan (JKK & JKM) Pengurus RT/RW"),
        ("Pencegahan dan Penurunan Stunting Terintegrasi", "Penyelenggaraan Rembug Stunting dan Pemberian PMT Balita"),
        ("Strategi Komunikasi Perubahan Perilaku (Strakom)", "Penyuluhan Pola Hidup Sehat dan Sosialisasi Gizi"),
    ],
    "PRIORITAS DAN TUPOKSI": [
        ("Pembangunan & Pemeliharaan Sarana Prasarana Prioritas", "Peningkatan Mutu Jalan Kota & Fasilitas Penunjang"),
        ("Pengembangan Sistem Informasi dan Digitalisasi Daerah", "Pengembangan Aplikasi Layanan Publik Kota Tegal"),
        ("Percepatan Pengentasan Kemiskinan Ekstrem", "Bantuan Pemberdayaan Usaha Ekonomi Produktif"),
        ("Peningkatan Mutu Pelayanan Publik Daerah", "Penyediaan Fasilitas Ramah Disabilitas dan Anak"),
    ],
    "LAIN - LAIN": [
        ("Pengadaan Jasa Kebersihan dan Keamanan Kantor", "Biaya Outsourcing Tenaga Pengamanan dan Cleaning Service"),
        ("Fasilitasi Penyelenggaraan Musrenbang Daerah", "Penyelenggaraan Musrenbang RKPD Tingkat Kota dan Kecamatan"),
        ("Penyediaan Kebutuhan Langganan Daya dan Jasa", "Biaya Listrik, Air, dan Jaringan Internet Perkantoran"),
        ("Bantuan Keuangan kepada Partai Politik", "Bantuan Keuangan Parpol Peraih Kursi DPRD"),
        ("Penyediaan Biaya Perjalanan Dinas Koordinasi", "SPPD Koordinasi Teknis ke Provinsi dan Kementerian"),
    ],
}

TAGS_OPTIONS = [
    "#PaguIndikatif2027",
    "#PrioritasDaerah",
    "#MandatorySpending",
    "#DinasPendidikan",
    "#DinasKesehatan",
    "#InfrastrukturKota",
    "#DAU",
    "#DAK",
    "#DBHCHT",
    "#KelurahanMaju",
    "#Stunting",
    "#SPPD",
    "#Operasional",
]


def generate_fake_rincian_anggaran(
    db: Session,
    total_target: int = 150,
    clear_existing: bool = False,
) -> int:
    """
    Membuat fake data realistis untuk rincian_anggaran:
    - Menghubungkan ke Perangkat Daerah aktif di ta_opd (is_pd=1)
    - Menghubungkan ke kategori_belanja
    - Mengisi uraian, uraian belanja, anggaran (Rupiah), dan tags
    """
    if clear_existing:
        all_existing = db.exec(select(RincianAnggaran)).all()
        for item in all_existing:
            db.delete(item)
        db.commit()

    opds = db.exec(select(TaOpd).where(TaOpd.is_pd == 1, TaOpd.aktif == 1)).all()
    if not opds:
        return 0

    kategoris = db.exec(select(KategoriBelanja)).all()
    if not kategoris:
        return 0

    kat_by_jenis: Dict[str, List[KategoriBelanja]] = {}
    for k in kategoris:
        j = k.jenis or "LAIN - LAIN"
        if j not in kat_by_jenis:
            kat_by_jenis[j] = []
        kat_by_jenis[j].append(k)

    created_count = 0
    records: List[RincianAnggaran] = []

    for _ in range(total_target):
        opd = random.choice(opds)
        
        # Pilih jenis dan template uraian yang sesuai
        jenis = random.choice(list(CONTOH_URAIAN_BY_JENIS.keys()))
        uraian_pair = random.choice(CONTOH_URAIAN_BY_JENIS[jenis])
        
        # Ambil kategori yang sesuai dengan jenis, atau fallback ke sembarang kategori
        possible_kats = kat_by_jenis.get(jenis, kategoris)
        kategori = random.choice(possible_kats)

        # Generate nominal realistis (misal: Rp 15.000.000 s/d Rp 5.000.000.000 dalam kelipatan jutaan)
        tier = random.random()
        if tier < 0.4:
            nominal = random.randint(15, 200) * 1_000_000
        elif tier < 0.8:
            nominal = random.randint(250, 1500) * 1_000_000
        else:
            nominal = random.randint(2000, 8500) * 1_000_000

        tags_picked = " ".join(random.sample(TAGS_OPTIONS, k=random.randint(1, 3)))

        rec = RincianAnggaran(
            id_pd=opd.id_sub_pd,
            id_kategori=kategori.id,
            uraian=f"{uraian_pair[0]} - {opd.nama_pd_singkat or opd.nama_pd}",
            uraian_belanja=uraian_pair[1],
            anggaran=Decimal(nominal),
            tags=tags_picked,
        )
        records.append(rec)
        created_count += 1

    db.add_all(records)
    db.commit()
    return created_count

