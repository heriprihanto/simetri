# SIMETRI

**Sistem Informasi Memori dan Riwayat Perencanaan Pembangunan Daerah**
Badan Perencanaan Pembangunan Daerah (Bappeda) Kota Tegal

> Konsep: *Institutional memory / jejak proses perencanaan pembangunan.*
> Beberapa tahun kemudian Bappeda tetap bisa menjawab:
> "Mengapa program ini muncul?", "Kapan target indikator berubah?",
> "Siapa yang mengusulkan?", "Apa hasil pembahasannya?",
> "Dokumen apa yang menjadi dasar keputusan?"

---

## Tech Stack

| Layer       | Teknologi                                                       |
|-------------|-----------------------------------------------------------------|
| **Backend** | Python 3.11+, FastAPI, SQLModel, SQLAlchemy, Uvicorn            |
| **Frontend**| Jinja2 (server-side rendered), htmx 2.x, TailwindCSS (CDN/CLI) |
| **Database**| PostgreSQL (host: `192.168.50.75`, db: `simetri`)               |
| **Auth**    | Google OAuth 2.0 (via `authlib`)                                |
| **Storage** | Google Drive API v3 (via service account)                       |
| **Port**    | `8000` (Uvicorn default)                                        |

---

## Menu Utama

```
┌──────────────────────────────────────────────────────────────┐
│  SIMETRI  │  Kronologi Kejadian  │  Arsip  │  Agenda  │ 👤  │
└──────────────────────────────────────────────────────────────┘
```

### 1. Kronologi Kejadian (dari SIMETRI-OLD)
Timeline besar proses perencanaan pembangunan Kota Tegal.
- Entri kejadian terkait dokumen perencanaan (RPJPD, RPJMD, RKPD, Renstra, Renja)
- Tampilan timeline vertikal (terbaru di atas)
- Filter per dokumen perencanaan, jenis kejadian, tanggal, bidang PJ
- Detail kejadian: 5W1H (judul, uraian kronologi, pihak pengusul, hasil pembahasan, dasar dokumen keputusan)
- Lampiran: upload file ke Google Drive + link eksternal
- Manajemen dokumen perencanaan (tingkat kota & tingkat OPD)

### 2. Arsip (dari AGENDASURAT)
Arsip surat dan dokumen kedinasan.
- Jenis: Surat Masuk, Surat Keluar, Surat Keputusan, Peraturan, Dokumen, Materi Paparan, Dokumen Lainnya
- Data: nomor surat, tanggal, pengirim/penerima, perihal, keterangan
- Attachment file (upload ke Google Drive)
- Pencarian & filter, paginasi
- Ekstraksi otomatis surat via Gemini API (opsional nanti)

### 3. Agenda (dari AGENDASURAT)
Kalender kegiatan Bappeda.
- Kategori: Rapat, Undangan, Kunjungan, Lainnya
- Tampilan kalender bulanan + daftar
- Tautan ke surat terkait
- Upload foto dokumentasi kegiatan ke Google Drive
- Sinkronisasi ke Google Calendar (opsional)

---

## Struktur Proyek

```
SIMETRI/
├── .env                          # Environment variables
├── .gitignore
├── PLAN.md                       # Dokumen ini
├── requirements.txt              # Python dependencies
├── secrets/                      # Google OAuth & Service Account keys
│   ├── web_app.json
│   ├── service_account.json
│   └── desktop_app.json
│
├── app/                          # Kode aplikasi utama
│   ├── __init__.py
│   ├── main.py                   # FastAPI app, router mounting, startup
│   ├── config.py                 # Settings via pydantic-settings
│   ├── database.py               # SQLAlchemy engine, session, init
│   │
│   ├── models/                   # SQLModel models
│   │   ├── __init__.py
│   │   ├── user.py               # User, TaOpd
│   │   ├── dokumen.py            # DokumenPerencanaan
│   │   ├── kejadian.py           # Kejadian, LampiranKejadian
│   │   ├── surat.py              # Surat, Attachment (arsip)
│   │   ├── agenda.py             # Agenda, Foto
│   │   ├── master.py             # MasterJenisKejadian, MasterBidang
│   │   └── audit.py              # AuditLog
│   │
│   ├── routers/                  # FastAPI routers (mengembalikan HTML)
│   │   ├── __init__.py
│   │   ├── auth.py               # Google OAuth login/callback/logout
│   │   ├── kronologi.py          # Kronologi kejadian & timeline
│   │   ├── dokumen.py            # CRUD dokumen perencanaan
│   │   ├── arsip.py              # CRUD arsip surat
│   │   ├── agenda.py             # CRUD agenda kegiatan
│   │   ├── lampiran.py           # Upload file/foto ke Google Drive
│   │   ├── users.py              # Manajemen pengguna (admin only)
│   │   └── audit.py              # Audit trail (admin only)
│   │
│   ├── services/                 # Business logic & external APIs
│   │   ├── __init__.py
│   │   ├── auth_service.py       # Google OAuth flow, JWT
│   │   ├── gdrive_service.py     # Google Drive upload/folder/delete
│   │   ├── calendar_service.py   # Google Calendar sync (opsional)
│   │   └── audit_service.py      # Logging audit trail
│   │
│   ├── middleware/                # FastAPI middleware
│   │   ├── __init__.py
│   │   └── auth.py               # Session/JWT auth, role check
│   │
│   ├── templates/                # Jinja2 HTML templates
│   │   ├── base.html             # Layout utama (navbar, footer, tema)
│   │   ├── login.html            # Halaman login Google OAuth
│   │   ├── kronologi/
│   │   │   ├── index.html        # Timeline view + filter
│   │   │   ├── form.html         # Form entri/edit kejadian (htmx modal)
│   │   │   ├── detail.html       # Detail kejadian (htmx partial)
│   │   │   └── dokumen.html      # Manajemen dokumen perencanaan
│   │   ├── arsip/
│   │   │   ├── index.html        # Daftar arsip surat + filter
│   │   │   └── form.html         # Form entri/edit surat
│   │   ├── agenda/
│   │   │   ├── index.html        # Kalender bulanan + daftar
│   │   │   └── form.html         # Form entri/edit agenda
│   │   ├── admin/
│   │   │   ├── users.html        # Manajemen pengguna
│   │   │   └── audit.html        # Audit trail
│   │   └── partials/             # htmx partial fragments
│   │       ├── timeline_list.html
│   │       ├── surat_table.html
│   │       ├── agenda_list.html
│   │       ├── toast.html
│   │       └── modal.html
│   │
│   └── static/                   # Static assets
│       ├── css/
│       │   └── app.css           # TailwindCSS output + custom styles
│       ├── js/
│       │   └── app.js            # Minimal JS (tema, htmx config)
│       └── img/
│
├── tailwind.config.js            # TailwindCSS configuration
├── package.json                  # Node deps (tailwindcss CLI only)
└── seed.py                       # Database seeder script
```

---

## Data Models (SQLModel)

### Tabel Existing (Read-Only)

```python
class TaOpd(SQLModel, table=True):
    """Master OPD dari tabel ta_opd yang sudah ada di database."""
    __tablename__ = "ta_opd"
    id_sub_pd: int = Field(primary_key=True)
    id_pd: int | None
    kode: str
    nama_pd: str
    nip_kepala: str
    nama_kepala: str
    is_pd: int
    bidangurusan: str
    nama_pd_singkat: str
    jabatan_kepala: str
    alamat: str
    telp: str
    email: str
    aktif: int
```

### Tabel Baru

```python
class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str = ""
    avatar: str = ""
    role: str = "user_bidang"       # "admin", "user_bidang", "user_opd"
    bidang: str = ""                # Bidang di Bappeda
    opd_id: int | None = None      # FK ke ta_opd.id_sub_pd (untuk user_opd)
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

class DokumenPerencanaan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    nama: str                       # "RPJMD Kota Tegal 2025-2030"
    jenis: str                      # "RPJPD","RPJMD","RKPD","Renstra","Renja"
    tahun_awal: int
    tahun_akhir: int
    tahun_rencana: int
    opd_id: int | None = None       # null = tingkat kota, id = tingkat OPD
    status: str = "dalam proses"    # "dalam proses", "selesai"
    is_active: bool = True
    deskripsi: str = ""
    created_by_id: int
    created_at: datetime
    updated_at: datetime

class Kejadian(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    dokumen_id: int                 # FK ke DokumenPerencanaan
    tanggal_kejadian: datetime
    waktu_mulai: str = ""
    waktu_selesai: str = ""
    lokasi: str = ""
    jenis_kejadian: str
    judul_kejadian: str
    uraian_kronologi: str = ""
    pihak_pengusul: str = ""
    hasil_pembahasan: str = ""
    dasar_dokumen_keputusan: str = ""
    bidang_pj: str = ""
    perubahan_indikator_target: str = ""
    perubahan_pagu: str = ""
    program_kegiatan_terkait: str = ""
    created_by_id: int
    created_at: datetime
    updated_at: datetime

class LampiranKejadian(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kejadian_id: int
    tipe_lampiran: str              # "file_gdrive", "foto", "link_eksternal"
    judul: str = ""
    file_name: str = ""
    mime_type: str = ""
    file_size: int = 0
    gdrive_file_id: str = ""
    gdrive_web_view_link: str = ""
    gdrive_download_link: str = ""
    external_url: str = ""
    created_at: datetime

class Surat(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    jenis_surat: str                # "Surat Masuk","Surat Keluar","SK", dll
    nomor_surat: str
    tanggal_surat: date
    pihak: str                      # pengirim/penerima/penerbit
    perihal: str
    keterangan: str = ""
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime | None

class AttachmentSurat(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    surat_id: int
    drive_file_id: str
    drive_link: str
    filename: str
    mime_type: str = ""
    size_bytes: int = 0
    uploaded_by_id: int | None
    uploaded_at: datetime

class Agenda(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    judul: str
    kategori: str = "Rapat"         # "Rapat","Undangan","Kunjungan","Lainnya"
    tanggal: date
    jam_mulai: str = ""
    jam_selesai: str = ""
    tempat: str = ""
    keterangan: str = ""
    surat_id: int | None = None     # FK ke Surat (opsional)
    drive_folder_id: str = ""
    calendar_event_id: str = ""
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime | None

class Foto(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    agenda_id: int
    drive_file_id: str
    drive_link: str
    filename: str
    mime_type: str = ""
    size_bytes: int = 0
    uploaded_by_id: int | None
    uploaded_at: datetime

class MasterJenisKejadian(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    nama: str = Field(unique=True)
    kategori: str = ""
    warna_badge: str = ""
    urutan: int = 0

class MasterBidang(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kode: str = Field(unique=True)
    nama: str
    deskripsi: str = ""

class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None
    user_email: str = ""
    user_name: str = ""
    action: str                     # "LOGIN","CREATE","UPDATE","DELETE","UPLOAD"
    entity: str                     # "kejadian","dokumen","surat","agenda","lampiran"
    entity_id: str = ""
    description: str = ""
    ip_address: str = ""
    user_agent: str = ""
    details: str = ""               # JSON snapshot
    created_at: datetime
```

---

## Alur Autentikasi

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│  /login     │───▶│ Google OAuth  │───▶│ /oauthcallback│
│  (tombol)   │    │  consent     │    │  verifikasi   │
└─────────────┘    └──────────────┘    │  email ada di │
                                       │  tabel users? │
                                       └───────┬───────┘
                                          Ya   │   Tidak
                                       ┌──────┘   │
                                       ▼           ▼
                                 Set session    403 Ditolak
                                 cookie JWT     (bukan whitelist)
                                       │
                                       ▼
                                  Redirect ke
                                  halaman utama
```

- **Whitelist**: Admin membuat user account terlebih dahulu, user baru bisa login
- **Session**: JWT disimpan di HTTP-only cookie, diverifikasi per-request
- **Role**: `admin`, `user_bidang`, `user_opd`

---

## Hak Akses per Role

| Fitur                                  | Admin | User Bidang | User OPD |
|----------------------------------------|:-----:|:-----------:|:--------:|
| Kronologi → Dokumen Tingkat Kota       | ✅    | ✅          | ❌       |
| Kronologi → Dokumen Tingkat OPD Sendiri| ✅    | ❌          | ✅       |
| Kronologi → Semua Dokumen OPD          | ✅    | ❌          | ❌       |
| Arsip Surat                            | ✅    | ✅          | ✅       |
| Agenda Kegiatan                        | ✅    | ✅          | ✅       |
| Manajemen Pengguna                     | ✅    | ❌          | ❌       |
| Manajemen Dokumen Perencanaan          | ✅    | ❌          | ❌*      |
| Audit Trail                           | ✅    | ❌          | ❌       |

> *User OPD bisa membuat dokumen perencanaan tingkat OPD mereka sendiri.

---

## Google Drive – Struktur Folder

```
TIMELINE_RENBANG_KOTA_TEGAL/              (Parent Folder ID dari .env)
├── [Nama Dokumen Perencanaan]/
│   ├── [Jenis Kejadian]/
│   │   └── [YYYY-MM-DD]/
│   │       └── file_upload_1.pdf
│   │       └── foto_kegiatan.jpg
│
ARSIP_SURAT_BAPPEDA/                      (Folder baru untuk arsip)
├── [YYYY]/
│   ├── [MM]/
│   │   └── [DD]/
│   │       └── surat_masuk_001.pdf
│
GALERI_KEGIATAN_BAPPEDA/                  (Folder baru untuk agenda)
├── [judul-kegiatan-yyyy-mm-dd]/
│   └── foto_1.jpg
```

---

## Konfigurasi (.env)

```env
# Server
PORT=8000
SERVER_URL=http://localhost:8000
SECRET_KEY=your_secret_key_here

# Database PostgreSQL
DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=simetri
DB_SSLMODE=disable

# Google OAuth 2.0
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/oauthcallback

# Google Service Account (untuk Drive upload)
GOOGLE_SERVICE_ACCOUNT_FILE=./secrets/service_account.json
GDRIVE_PARENT_FOLDER_ID=your_gdrive_folder_id

# Initial Admin
INITIAL_ADMIN_EMAIL=admin@example.com
```

---

## Python Dependencies (requirements.txt)

```
fastapi>=0.115
uvicorn[standard]>=0.30
sqlmodel>=0.0.22
sqlalchemy>=2.0
psycopg2-binary>=2.9
pydantic-settings>=2.0
python-dotenv>=1.0
authlib>=1.3
httpx>=0.27
itsdangerous>=2.2
python-multipart>=0.0.12
jinja2>=3.1
google-api-python-client>=2.130
google-auth>=2.30
pyjwt>=2.9
```

---

## Tahapan Pengembangan

### Fase 1: Foundation (Core Backend) — ✅ SELESAI
1. ✅ Buat PLAN.md
2. ✅ Setup project structure & virtual environment
3. ✅ Konfigurasi `.env` & `config.py` (pydantic-settings)
4. ✅ Database connection (`database.py`) & SQLModel models (12 tabel lengkap terhubung PostgreSQL)
5. ✅ Auto-migration & seeder (`seed.py`)
6. ✅ Base template Jinja2 (`base.html`) + TailwindCSS
7. ✅ Middleware auth (session cookie/JWT, role check)

### Fase 2: Autentikasi — ✅ SELESAI
8. ✅ Google OAuth flow (login, callback, logout)
9. ✅ Halaman login modern dengan branding Bappeda Kota Tegal
10. ✅ Session management (JWT cookie)
11. ✅ User whitelist & role checking (admin, user_bidang, user_opd)

### Fase 3: Kronologi Kejadian — ✅ SELESAI
12. ✅ CRUD Dokumen Perencanaan (Tingkat Kota & OPD)
13. ✅ Timeline view (htmx partial swap & paginasi)
14. ✅ Form entri & edit kejadian (htmx modal 5W1H)
15. ✅ Detail kejadian (htmx partial view & uploader lampiran)
16. ✅ Filter & pencarian dinamis (htmx swap)
17. ✅ Upload lampiran ke Google Drive (service account)

### Fase 4: Arsip Surat — ✅ SELESAI
18. ✅ CRUD arsip surat kedinasan
19. ✅ Daftar surat + filter/pencarian + paginasi
20. ✅ Form entri surat
21. ✅ Upload attachment ke Google Drive
22. ✅ Badge jenis surat dengan warna

### Fase 5: Agenda Kegiatan — ✅ SELESAI
23. ✅ CRUD agenda kegiatan
24. ✅ Tampilan kalender bulanan interaktif & daftar rincian agenda
25. ✅ Form agenda + tautan ke arsip surat
26. ✅ Upload foto dokumentasi ke Google Drive
27. ✅ Kategori agenda (Rapat, Undangan, Kunjungan, Lainnya)

### Fase 6: Admin & Polish — ✅ SELESAI
28. ✅ Manajemen pengguna (CRUD whitelist Google OAuth & penugasan OPD)
29. ✅ Audit trail (perekaman seluruh aksi & log aktivitas)
30. ✅ Dark mode / tema toggle dengan penyimpanan localStorage
31. ✅ Responsive design mobile & desktop
32. ✅ Polish UI, glassmorphism, animasi fade/slide, dan micro-interactions

---

## Seed Data

### Master Bidang Bappeda
| Kode          | Nama                                |
|---------------|-------------------------------------|
| SEKRETARIAT   | Sekretariat                         |
| PPEP          | Bidang PPEP                         |
| PPM           | Bidang PPM                          |
| INFRA_WIL     | Bidang Infrastruktur & Kewilayahan  |
| EKONOMI_SDA   | Bidang Perekonomian & SDA           |

### Master Jenis Kejadian
1. Forum Konsultasi Publik
2. Musrenbang
3. Forum Perangkat Daerah
4. Desk Bappeda
5. Rapat TAPD
6. Rakor Teknis Pembangunan Antar OPD dan OPD-Lintas Sektoral
7. Rapat / Konsultasi DPRD
8. Pokir (Pokok Pikiran DPRD)
9. Asistensi
10. Verifikasi
11. Evaluasi
12. Perubahan Indikator / Target
13. Perubahan Pagu
14. Perubahan Program/Kegiatan/Subkegiatan
15. Arahan Pimpinan
16. Surat Masuk/Keluar / Nota Dinas
17. Surat Usulan
18. Surat Tanggapan / Balasan
19. Hasil Evaluasi Provinsi/Kemendagri
20. Penetapan Dokumen
21. Kejadian Penting Lainnya

### Jenis Arsip Surat
- Surat Masuk, Surat Keluar, Surat Keputusan, Peraturan, Dokumen, Materi Paparan, Dokumen Lainnya

### Kategori Agenda
- Rapat, Undangan, Kunjungan, Lainnya

---

## Catatan Desain UI

- **Dark mode** dengan toggle, mengikuti preferensi sistem sebagai default
- **Warna utama**: Indigo/Violet gradient (konsisten dengan AGENDASURAT)
- **Glassmorphism**: Navbar transparan dengan backdrop-blur
- **Timeline**: Vertikal, terbaru di atas, badge warna per jenis kejadian
- **Kalender**: Grid bulanan dengan dot indicator per kegiatan
- **Responsive**: Mobile-first, adaptif untuk tablet/desktop
- **htmx patterns**: Modal form, inline edit, swap search results, toast notifications
- **Animasi**: Fade-in timeline cards, slide-in modals, pulse loading states

---

## Referensi Proyek

| Sumber                   | Diambil                                                    |
|--------------------------|------------------------------------------------------------|
| SIMETRI-OLD (Go/Gin)    | Data model kronologi, role/auth, Google Drive hierarchy     |
| AGENDASURAT (PHP Native) | Modul arsip surat, agenda kegiatan, Google Drive/Calendar   |


Form Catat Kejadian Baru
tanggal dan waktu otomatis waktu sekarang
Pilihan Bidang otomatis
Isian hanya textarea Uraian Kronologi Peristiwa * saja, pakai rich text editor 
hapus :
Pihak Pengusul / Peserta Rapat (Who)
Dasar Dokumen / Surat Keputusan (Why)
Hasil Pembahasan / Kesepakatan
Dampak Perubahan Perencanaan (Opsional)
Perubahan Indikator / Target

Hapus Lokasi Pelaksanaan, Waktu Selesai.
Waktu pakai datetime saja

Buat API /api/whatsapp
untuk Whatsapp webhook persis seperti 

Buat Whatsapp webhook untuk mengarsipkan surat masuk, keluar, dokumen.
Arsip Surat selain entri dari Web App, bisa juga melalui WhatsApp
jik pesan masuk dengan keyword arsipkan, lampirkan foto, maka akan otomatis masuk ke arsip surat.

### WhatsApp Webhook Access Control (Selesai)
- Hanya nomor WhatsApp yang terdaftar dan aktif di **Daftar Pengguna** (`users.no_hp` dengan `is_active == True`) yang dapat menjalankan perintah pengarsipan surat (`arsipkan ...`, forwarding media/pesan, append media, atau update metadata perihal).
- Nomor tidak terdaftar otomatis ditolak dengan balasan WhatsApp informatif (Akses Ditolak) dan tidak dicatat ke database/Google Drive.
- Arsip yang dibuat otomatis diatribusikan ke user yang bersangkutan (`created_by_id`, `uploaded_by_id`, dan audit log).

Sekarang buat Whatsapp Webhook untuk menyimpan Kronologi Kejadian
Hanya menerima dari nomor yang terdaftar di Daftar Pengguna
keyword pesan : simetri nama_dokumen_perencanaan uraian_kronologi_kejadian
Lampiran file bisa disertakan

pada Dokumen Perencanaan tambahkan alias nama_dokumen_perencanaan untuk bisa dipakai di pesan Whatsapp 

### Dokumen Perencanaan — Manajemen CRUD Lengkap (Selesai)
- **Edit Dokumen**: Pengguna dapat mengubah nama, alias WhatsApp, jenis dokumen, rentang tahun, status pengerjaan, cakupan OPD, dan deskripsi dokumen perencanaan melalui tombol **Edit** pada setiap kartu dokumen.
- **Hapus Dokumen**: Pengguna dapat menghapus dokumen melalui tombol **Hapus** dengan dialog konfirmasi aman yang menampilkan jumlah catatan kronologi kejadian terkait (beserta lampirannya yang ikut dibersihkan).
- **Penghitungan Otomatis Kejadian**: Setiap kartu dokumen menampilkan lencana (*badge*) jumlah kronologi kejadian yang tercatat.
- **Audit Logging**: Setiap aksi pembuatan, pembaruan, dan penghapusan dokumen perencanaan dicatat ke sistem audit log SIMETRI.

### Agenda Kegiatan — Tempat/Ruangan & Bidang (Selesai)
- **Tempat / Ruangan Kombinasi**: Input tempat pada form Agenda Kegiatan menggunakan HTML5 `<datalist>` dengan opsi standar:
  - `R. Rapat Lt. 1 Bapperida`
  - `R. Rapat Lt. 2 Bapperida`
  - `R. Rapat Kecil Lt. 2 Bapperida`
  Serta tombol pilihan cepat (*preset chips*) 1-klik, dan tetap dapat diketik bebas secara manual jika tempat kegiatan berada di luar opsi tersebut.
- **Field Bidang**: Ditambahkan kolom `bidang` pada model [Agenda](file:///home/herry/1_Project/2026/SIMETRI/app/models/agenda.py) dan database PostgreSQL, dropdown pilihan bidang dari [MasterBidang](file:///home/herry/1_Project/2026/SIMETRI/app/models/master.py), serta lencana (*badge*) bidang pada daftar rincian agenda.

Buat Whatsapp Webhook untuk pencarian arsip dan kronologi kejadian 
contoh pesan : simetri-cari "Kata / kalimat kunci pencarian"
Hanya menerima dari nomor yang terdaftar di Daftar Pengguna


Aplikasi ini akan dideploy di server https://monevrkpd.tegalkota.go.id/simetri dengan reverse proxy.

### Panduan Konfigurasi Reverse Proxy (Nginx)

#### 1. Konfigurasi Nginx Server Block
Tambahkan blok `location /simetri` pada konfigurasi Nginx di server `monevrkpd.tegalkota.go.id`:

```nginx
# Konfigurasi Reverse Proxy untuk SIMETRI pada monevrkpd.tegalkota.go.id
location /simetri {
    # Catatan: Tanpa trailing slash agar FastAPI menerima path utuh
    proxy_pass http://127.0.0.1:8987;
    
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /simetri;
    proxy_set_header X-Forwarded-Host $host;

    # Pengaturan timeout & buffering untuk upload lampiran dokumen / foto
    client_max_body_size 50M;
    proxy_connect_timeout 90s;
    proxy_send_timeout 90s;
    proxy_read_timeout 90s;

    # Mendukung WebSocket / HTTP streaming jika diperlukan
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

> **Penting**: Gunakan `proxy_pass http://127.0.0.1:8987;` (tanpa slash di akhir URL target), sehingga Uvicorn/FastAPI dapat mencocokkan `root_path="/simetri"` dengan path request browser.

---

#### 2. Konfigurasi File `.env` di Server Production

```env
# Server
PORT=8987
SERVER_URL=https://monevrkpd.tegalkota.go.id/simetri
ROOT_PATH=/simetri
COOKIE_SECURE=True
SECRET_KEY=ganti_dengan_secret_key_acak_dan_kuat_2026

# Database PostgreSQL
DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=monevrkpd
DB_PASSWORD=password_db_anda
DB_NAME=simetri
DB_SSLMODE=disable

# Google OAuth 2.0
# Daftarkan Redirect URI ini di Google Cloud Console -> APIs & Services -> Credentials
GOOGLE_CLIENT_ID=client_id_google_anda.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=client_secret_google_anda
GOOGLE_REDIRECT_URI=https://monevrkpd.tegalkota.go.id/simetri/oauthcallback

# Google Service Account (Drive Upload)
GOOGLE_SERVICE_ACCOUNT_FILE=./secrets/service_account.json
GDRIVE_PARENT_FOLDER_ID=id_parent_folder_drive_anda

# WhatsApp Webhook & API
WA_API_URL=http://localhost:3000/send/message
WA_DEVICE_ID=Simetri
WA_STORAGE_PATH=/path/ke/go-whatsapp-web-multidevice/src
```

---

#### 3. Penyesuaian Arsitektural yang Telah Diterapkan di SIMETRI
1. **FastAPI `root_path` & `ProxyHeadersMiddleware`**:
   - `app = FastAPI(..., root_path=settings.ROOT_PATH)`
   - `ProxyHeadersMiddleware` aktif untuk mempercayai header `X-Forwarded-Proto: https`, `X-Forwarded-Prefix: /simetri`, dan `X-Forwarded-For`.
2. **Jinja2 Template Prefixing**:
   - Variable `root_path` dan fungsi `url_path` diinjeksikan ke template global Jinja2.
   - Semua aset statis (`css/app.css`, `js/app.js`), form action, dan navigasi anchor telah diprefix dengan `{{ root_path }}`.
3. **HTMX Subpath Interceptor (`base.html`)**:
   - Dilengkapi interceptor otomatis pada event `htmx:configRequest`. Setiap request AJAX HTMX (`hx-get`, `hx-post`, `hx-delete`) otomatis diberi prefix `SIMETRI_ROOT_PATH` jika aplikasi berada di subpath.
4. **JWT Session Cookie**:
   - `cookie_path` diset universal (`/`) dan `secure` mengikuti setting `COOKIE_SECURE` (True untuk HTTPS).
5. **Backend Redirects**:
   - Seluruh `RedirectResponse` (login, logout, auth Google, dokumen, agenda, user) menggunakan `settings.url_path(...)` agar browser diarahkan ke URL reverse proxy yang tepat.