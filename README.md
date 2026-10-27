# SIMETRI

**Sistem Informasi Memori dan Riwayat Perencanaan Pembangunan Daerah**  
Badan Perencanaan Pembangunan Daerah (Bappeda) Kota Tegal

---

## 📌 Tentang Aplikasi

SIMETRI dirancang sebagai sistem memori institusional (*institutional memory*) untuk mencatat seluruh proses, kronologi peristiwa, dasar pertimbangan, dan dokumen pendukung dalam penyusunan dokumen perencanaan pembangunan daerah di Kota Tegal (RPJPD, RPJMD, RKPD, Renstra, Renja).

Aplikasi ini menggabungkan dan memodernisasi fungsionalitas dari dua sistem:
1. **SIMETRI-OLD** (Go/Gin/React) → Data model kronologi peristiwa 5W1H, struktur hierarki Google Drive, dan role-based access.
2. **AGENDASURAT** (PHP/SQLite) → Modul arsip surat dan dokumen kedinasan, kalender agenda kegiatan, dan integrasi Google Drive.

---

## 🚀 Fitur & Menu Utama

### 1. ⏱️ Kronologi Kejadian (`/kronologi`)
- **Pencatatan Kronologis (5W + 1H)**: Tanggal, waktu, lokasi, jenis kejadian, judul, uraian peristiwa, pihak pengusul/peserta, hasil pembahasan, dan dasar dokumen/keputusan.
- **Dampak Perubahan Perencanaan**: Catatan perubahan pagu anggaran, indikator kinerja, dan target sasaran.
- **Tampilan Timeline Interaktif**: Timeline vertikal modern dengan badge kategori, filter per dokumen, pencarian dinamis (htmx), dan paginasi.
- **Lampiran Google Drive**: Terintegrasi langsung dengan Google Drive melalui Service Account.

### 2. 📁 Manajemen Dokumen Perencanaan (`/dokumen`)
- Pengelolaan master dokumen perencanaan tingkat Kota (RPJPD, RPJMD, RKPD) maupun tingkat Perangkat Daerah (Renstra, Renja).
- Filter cakupan kota dan OPD.

### 3. 📨 Arsip Surat (`/arsip`)
- Pengarsipan 7 jenis naskah kedinasan: Surat Masuk, Surat Keluar, Surat Keputusan, Peraturan, Dokumen, Materi Paparan, dan Dokumen Lainnya.
- Pencarian cerdas, filter jenis surat, badge warna dinamis, dan upload lampiran berkas PDF/dokumen ke Google Drive.
- Statistik ringkas total arsip, surat masuk, dan surat keluar.

### 4. 📅 Agenda Kegiatan (`/agenda`)
- Tampilan kalender bulanan interaktif dengan navigasi bulan dan indikator agenda.
- Kategorisasi agenda: Rapat, Undangan, Kunjungan, dan Lainnya.
- Penautan agenda ke arsip surat/undangan terkait.
- Dokumentasi foto kegiatan ke Google Drive.

### 5. 🛡️ Administrasi Sistem (Admin Only)
- **Manajemen Pengguna (`/admin/users`)**: Whitelist akun Google OAuth, pengaturan peran (*admin*, *user_bidang*, *user_opd*), penugasan bidang/OPD, dan aktivasi akun.
- **Audit Trail (`/admin/audit`)**: Perekaman seluruh aktivitas sistem (Login, Create, Update, Delete, Upload) lengkap dengan timestamp, IP address, dan detail perubahan.

---

## 🛠️ Teknologi yang Digunakan

- **Backend**: Python 3.14, FastAPI, SQLModel, SQLAlchemy 2.0, Pydantic v2
- **Frontend**: Server-Side Rendering (Jinja2), htmx 2.0, TailwindCSS, Lucide Icons
- **Database**: PostgreSQL (`simetri` di `192.168.50.75`)
- **Autentikasi**: Google OAuth 2.0 dengan JWT Session Cookie
- **Penyimpanan Berkas**: Google Drive API v3 (Google Service Account)

---

## ⚙️ Cara Menjalankan Aplikasi

### 1. Prasyarat
- Python 3.10+
- PostgreSQL database aktif
- Kredensial Google OAuth & Service Account di direktori `secrets/`

### 2. Instalasi Dependensi
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Inisialisasi & Seeding Data Awal
```bash
python3 seed.py
```

### 4. Menjalankan Server
```bash
./run.sh
# Atau langsung melalui uvicorn:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Aplikasi dapat diakses di browser melalui: **`http://localhost:8000`**

---

## 🔒 Hak Akses (Role-Based Access Control)

| Role | Cakupan Akses |
|---|---|
| **admin** | Akses penuh ke seluruh menu, kelola pengguna whitelist, audit log, kelola seluruh dokumen dan OPD. |
| **user_bidang** | Staf/pejabat Bidang Bappeda Kota Tegal. Mengelola dokumen tingkat kota, mencatat kronologi, arsip surat, dan agenda. |
| **user_opd** | Perencana Perangkat Daerah. Mencatat kejadian dan melihat dokumen perencanaan OPD masing-masing serta dokumen kota. |

### Pencarian melalui WhatsApp

Gunakan webhook yang sudah ada: `POST /api/whatsapp`. Atur URL callback WhatsApp
Gateway ke `<SERVER_URL>/api/whatsapp`; balasan dikirim melalui `WA_API_URL` dan
`WA_DEVICE_ID` yang dikonfigurasi di `.env`. Gunakan `SERVER_URL` yang dapat diakses
pengguna agar tautan hasil pencarian mengarah ke aplikasi yang benar.

Daftarkan nomor WhatsApp pada kolom nomor HP di **Manajemen Pengguna** dan pastikan
penggunanya aktif. Nomor `08…`, `628…`, dan `+628…` dinormalisasi sebelum dicocokkan
secara penuh. Nomor tidak terdaftar atau pengguna nonaktif ditolak.

Kirim pesan pribadi ke nomor bot:

```text
simetri-cari "rapat RKPD"
```

Kata kunci tanpa tanda kutip juga diterima. Pencarian tidak membedakan huruf besar
atau kecil, dengan batas 200 karakter. Balasan memuat maksimal lima hasil terbaru
untuk masing-masing kategori arsip surat dan kronologi, beserta tautan aplikasi
(yang tetap memerlukan login). Pesan grup diabaikan untuk perintah pencarian.

Arsip dicari dari nomor surat, pihak, perihal, dan keterangan. Kronologi dicari dari
judul, uraian, pengusul, hasil pembahasan, dasar keputusan, dan nama dokumen.
Kronologi dibatasi pada dokumen aktif sesuai peran: admin melihat semua, pengguna
bidang melihat tingkat kota, dan pengguna OPD hanya melihat OPD sendiri. Pengguna
OPD tanpa OPD terpilih tidak menerima hasil kronologi. Arsip mengikuti akses arsip
aplikasi yang tersedia bagi semua pengguna aktif.

Contoh payload gateway:

```json
{
  "event": "message",
  "device_id": "Simetri",
  "payload": {
    "id": "pesan-unik-001",
    "from": "6281234567890@s.whatsapp.net",
    "body": "simetri-cari \"rapat RKPD\"",
    "is_from_me": false
  }
}
```

Jalankan verifikasi lokal (database SQLite sementara dan gateway tiruan):

```bash
venv/bin/python -m unittest discover -s tests -v
```
