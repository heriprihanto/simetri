# PRODUCT REQUIREMENTS DOCUMENT (PRD)
# PRIORA — Sistem Pendukung Keputusan Prioritas Pembangunan dan Alokasi Anggaran Pemerintah Kota Tegal

**Versi:** 1.0 (draft untuk validasi pemangku kepentingan)  
**Tanggal:** 20 November 2026  
**Status:** Rancangan, belum merupakan kebijakan resmi Pemerintah Kota Tegal  
**Target implementasi:** Aplikasi internal Bappeda/BPKAD/OPD; pengembangan bertahap melalui Codex IDE

## 1. Ringkasan eksekutif
PRIORA adalah sistem pendukung keputusan (decision support system/DSS) yang menghubungkan prioritas pembangunan, ruang fiskal, kebutuhan OPD, program, kegiatan, subkegiatan, dan paket kebutuhan untuk menghasilkan **rekomendasi pagu indikatif yang transparan dan dapat diaudit**. Sistem menerapkan top-down (arah kebijakan dan batas fiskal), bottom-up (usulan dan biaya terverifikasi), serta rekonsiliasi iteratif. AI membantu analisis dokumen, penjelasan dan forecasting; perhitungan pagu dan kepatuhan dilakukan oleh aturan dan optimasi deterministik. Semua keputusan resmi tetap berada pada pejabat/lembaga berwenang.

### 1.1 Masalah
- Pembagian pagu sering dimulai dari angka historis OPD tanpa keterkaitan eksplisit dengan outcome dan urgensi.
- Data RKPD/Renja, indikator, realisasi dan kebutuhan biaya tersebar; kualitas dan definisinya tidak seragam.
- Sulit membandingkan skenario fiskal, konsekuensi pengurangan anggaran, dan alasan penyesuaian pagu.
- Jejak keputusan serta versi pagu dari usulan sampai pembahasan belum selalu terstruktur.

### 1.2 Tujuan produk
1. Menyediakan matriks keterkaitan prioritas → indikator → intervensi → program → kegiatan → subkegiatan → OPD.
2. Mengonsolidasikan kebutuhan dan kewajiban fiskal tanpa melanggar earmarking dan aturan belanja.
3. Menilai usulan menggunakan kriteria terukur, sumber bukti dan bobot terversi.
4. Menghasilkan simulasi alokasi yang feasible serta penjelasan trade-off.
5. Mencatat review manusia, revisi, persetujuan, dan audit trail yang tidak dapat dihapus melalui UI.
6. Mengukur selisih antara rekomendasi, keputusan final, dan capaian outcome berikutnya.

### 1.3 Bukan tujuan (non-goals)
- Bukan pengganti SIPD-RI, sistem akuntansi daerah, pengesahan APBD, atau keputusan TAPD/DPRD.
- Tidak mengirim perubahan langsung ke SIPD-RI pada MVP.
- Tidak menjadikan jawaban LLM sebagai sumber kebenaran angka, skor, batas fiskal, atau dasar hukum.
- Tidak melakukan auto-approval, auto-reallocation, atau pemrosesan data pribadi publik tanpa dasar.

## 2. Prinsip dan asumsi
- Data → masalah → objective → alternatif intervensi → estimasi biaya → KPI → evaluasi.
- Kewajiban hukum/kontraktual dan pembatasan sumber dana adalah **hard constraints**, bukan sekadar skor.
- Skor prioritas **tidak sama** dengan persentase pagu.
- Satu intervensi dapat terkait beberapa prioritas; kontribusi dan manfaat tidak boleh dihitung ganda.
- Perubahan bobot, aturan, data, dan model harus memiliki versi serta dapat direproduksi.
- Sistem harus bisa digunakan **tanpa AI** untuk alur inti.
- Tahun anggaran, tahap (rancangan awal/rancangan/rancangan akhir/perubahan), versi dokumen dan status harus eksplisit.
- Nilai pagu Rp1 triliun dan ~90 OPD adalah ilustrasi kebutuhan, bukan fakta anggaran resmi.
- Pemetaan nomenklatur harus mengikuti referensi yang berlaku pada tahun anggaran; kode dapat berubah.

## 3. Pengguna, peran, dan kewenangan
| Role | Akses utama |
|---|---|
| Super Admin | konfigurasi teknis, pengguna, role, tidak berhak menyetujui pagu atas nama TAPD |
| Admin Perencanaan Bappeda | tahun/tahap, prioritas, matriks keterkaitan, kriteria, verifikasi perencanaan |
| Admin Fiskal BPKAD | proyeksi fiskal, sumber dana, batasan, validasi fiscal envelope |
| Operator OPD | usulan subkegiatan/paket, volume, biaya, evidence; hanya OPD sendiri |
| Verifikator Bappeda | review substansi, baseline, outcome, bukti, mapping |
| Verifikator Fiskal | review standar biaya, sumber dana, kewajiban, pagu |
| Analis/TAPD | membuat/membandingkan simulasi, merekomendasikan pembahasan |
| Approver berwenang | persetujuan versi sesuai tahapan dan delegasi kewenangan |
| Auditor/Inspektorat (read-only) | melihat seluruh jejak, asumsi, hasil dan ekspor |

**Aturan:** pengguna tidak boleh memverifikasi atau menyetujui usulannya sendiri apabila kebijakan pemisahan tugas berlaku; pembatasan OPD ditegakkan pada backend, bukan hanya frontend.

## 4. Model proses bisnis end-to-end
1. **Buka siklus:** Bappeda membuat `fiscal_year` dan `planning_stage`, menyalin referensi yang valid, menetapkan jadwal dan status.
2. **Konsolidasi:** impor referensi OPD, program, kegiatan, subkegiatan, RPJMD/RKPD, indikator, historis pagu/realisasi, SPM dan data sektoral; simpan provenance dan hasil validasi.
3. **Rumusan prioritas:** Bappeda mencatat masalah, baseline, target, urgensi, indikator, sumber bukti dan hubungan ke program/intervensi; AI hanya memberi saran dengan kutipan sumber.
4. **Ruang fiskal:** BPKAD menetapkan kapasitas, dana terikat, komitmen, batas per sumber dana dan alokasi minimum yang sah. Pemeriksaan infeasibility wajib.
5. **Usulan OPD:** operator memasukkan usulan pada tingkat subkegiatan/paket, target output, lokasi, penerima manfaat, volume, harga satuan, rincian biaya, kewajiban, dependensi dan evidence.
6. **Validasi berlapis:** pemeriksaan format, nomenklatur, duplikasi, kelengkapan, kelayakan, dasar biaya, kesesuaian prioritas dan sumber dana; dikembalikan jika belum layak.
7. **Skoring:** jalankan konfigurasi kriteria/bobot versi aktif terhadap usulan layak; tampilkan nilai setiap kriteria, alasan, evidence dan confidence data. Override hanya dengan alasan.
8. **Simulasi:** pilih snapshot data, batas fiskal, skenario dan versi kebijakan; jalankan solver; tampilkan feasible/infeasible, kebutuhan, alokasi, gap, indikator dan trade-off.
9. **Rekonsiliasi:** agregasikan subkegiatan → kegiatan → program → OPD, bandingkan pagu indikatif awal, jalankan revisi dan simulasi ulang sampai disepakati.
10. **Pembahasan dan persetujuan:** TAPD mencatat keputusan; versi dikunci, ditandatangani/disetujui melalui mekanisme resmi yang berlaku; ekspor rekap dan log perubahan.
11. **Evaluasi:** bandingkan rencana, alokasi final, realisasi, output dan outcome; jadikan input siklus berikutnya.

### 4.1 Status workflow
`DRAFT → SUBMITTED → ADMIN_REVIEW → VERIFIED → SCORED → SIMULATED → UNDER_DISCUSSION → APPROVED_STAGE → LOCKED`; cabang `RETURNED`, `REJECTED`, `CANCELLED`. Setiap transisi memiliki actor, timestamp, komentar, versi, dan authorization check. `LOCKED` tidak diedit langsung: revisi harus membuat versi/tahap baru.

### 4.2 Aturan bisnis kritis
- Tidak ada nilai negatif; semua uang disimpan sebagai `NUMERIC(20,2)` atau integer rupiah, bukan float.
- Jumlah alokasi per sumber dana ≤ kapasitas tersedia pada sumber tersebut.
- Belanja wajib/terikat dipenuhi sesuai aturan dan klasifikasi terverifikasi; jika tidak mungkin, solver mengembalikan `INFEASIBLE` dan diagnosis.
- Paket indivisible menggunakan variabel biner; paket divisible memakai batas minimum dan maksimum; dependensi paket dan multi-year commitment didukung.
- Nomenklatur/indikator referensi bersifat versioned; jangan melakukan cascade delete historis.
- Dokumen dan evidence harus memiliki metadata sumber, hash, pembuat, tanggal, dan klasifikasi akses.
- Hasil AI tidak boleh memodifikasi database inti tanpa konfirmasi pengguna dan validasi server.

## 5. Kebutuhan fungsional (FR)
| ID | Prioritas | Kebutuhan | Acceptance criteria ringkas |
|---|---|---|---|
| FR-001 | P0 | Login, RBAC dan OPD scope | user OPD A tidak dapat membaca/mengubah usulan OPD B via API |
| FR-002 | P0 | Siklus tahun/tahap/versi | satu snapshot dapat dibekukan dan direproduksi |
| FR-003 | P0 | Master OPD, nomenklatur, indikator, sumber dana | impor tervalidasi, error per baris, versi referensi |
| FR-004 | P0 | Prioritas dan objective | masalah, baseline, target, KPI, evidence wajib sebelum verifikasi |
| FR-005 | P0 | Mapping prioritas–intervensi–program | many-to-many, kontribusi terukur, cegah duplikasi outcome |
| FR-006 | P0 | Fiscal envelope | jumlah, earmark, minimum, commitment, pemeriksaan feasible |
| FR-007 | P0 | Usulan OPD | CRUD, detail biaya, target, lokasi, bukti, status |
| FR-008 | P0 | Review/verifikasi | checklist, komentar, return, audit transisi |
| FR-009 | P0 | Skoring deterministik | hasil sama untuk input dan versi aturan sama |
| FR-010 | P0 | Simulasi alokasi | tidak melanggar batas fiskal, mendukung infeasible |
| FR-011 | P0 | Agregasi hierarkis | jumlah subkegiatan = kegiatan = program = OPD (sesuai mapping unik) |
| FR-012 | P0 | Perbandingan skenario | kebutuhan vs alokasi, gap, alasan, ekspor |
| FR-013 | P0 | Approval dan lock | hanya approver berwenang, revisi versi baru |
| FR-014 | P0 | Audit log | immutable dari UI, before/after, actor, timestamp, reason |
| FR-015 | P1 | AI analisis dokumen | rekomendasi ber-citation, sumber terbatas, fallback manual |
| FR-016 | P1 | Forecast kebutuhan | model, training window, metrik backtest, asumsi, interval |
| FR-017 | P1 | Dashboard KPI | filter tahun, tahap, OPD, prioritas, sumber dana |
| FR-018 | P1 | Ekspor Excel/PDF | sama dengan angka snapshot, mencantumkan versi |
| FR-019 | P1 | Integrasi impor/ekspor SIPD-RI | adapter berbasis file/API resmi, tanpa scraping yang tidak diizinkan |
| FR-020 | P2 | Analisis dampak spasial | peta lokasi intervensi, jika data spasial tersedia |

## 6. Dataset dan struktur data konseptual
Tabel inti (nama awal; finalisasi pada desain ERD):
- `users`, `roles`, `user_roles`, `user_opd_scopes`.
- `fiscal_years`, `planning_stages`, `planning_versions`, `snapshots`.
- `opds`, `programs`, `activities`, `subactivities`, `nomenclature_versions`.
- `priorities`, `development_issues`, `objectives`, `indicators`, `indicator_observations`, `priority_links`.
- `funding_sources`, `fiscal_envelopes`, `fund_restrictions`, `mandatory_obligations`, `commitments`.
- `proposals`, `proposal_packages`, `proposal_cost_items`, `proposal_outputs`, `proposal_evidence`, `proposal_dependencies`.
- `criteria`, `criteria_sets`, `criterion_weights`, `proposal_scores`, `score_explanations`, `score_overrides`.
- `scenario_sets`, `scenarios`, `scenario_constraints`, `scenario_runs`, `scenario_allocations`, `solver_diagnostics`.
- `reviews`, `approvals`, `workflow_events`, `audit_events`, `attachments`, `data_import_jobs`, `source_provenance`.
- `forecast_models`, `forecast_runs`, `forecast_results`, `ai_analysis_runs`, `ai_citations`.

**Relasi:** satu OPD memiliki banyak proposal; proposal mengacu tepat satu subkegiatan dan tahap/versi; subkegiatan → kegiatan → program; prioritas ke proposal/program menggunakan tabel penghubung; skenario menggunakan snapshot immutable; setiap run menyimpan input hash, konfigurasi, versi solver, hasil dan status.

**Tipe kunci:** UUID untuk entitas transaksi; kode referensi eksternal disimpan string; `year` integer; uang NUMERIC; timestamps `TIMESTAMPTZ` UTC; seluruh tabel utama memiliki `created_at`, `updated_at`, `created_by`, `version`.

**Sumber data:** gunakan data historis Renja, realisasi triwulanan/bulanan, evaluasi RKPD, LRA dan referensi nomenklatur yang sudah tersedia di lingkungan pemerintah kota, melalui proses staging dan pemetaan; jangan mengasumsikan nama tabel internal sama dengan sistem sumber.

## 7. Algoritma
### 7.1 Skoring MCDA
Untuk kriteria `j` dan proposal `i`, `score_i = 100 × Σ(weight_j × rating_ij / max_rating_j)` dengan `Σ weight_j = 1`. Rating 1–5, sumber nilai, rubric dan evaluator harus tersimpan. Contoh bobot awal: kontribusi prioritas 30%, urgensi 25%, efektivitas 20%, efisiensi 15%, kesiapan 10%. **Bobot adalah placeholder yang harus disahkan**, bukan regulasi. Kewajiban belanja tetap hard constraint.

### 7.2 Optimasi
Untuk paket yang bisa dipilih penuh/tidak: `x_i ∈ {0,1}`; untuk paket bertahap: `0 ≤ x_i ≤ 1` dengan minimum implementable. Maksimalkan nilai manfaat tertimbang `Σ utility_i × x_i` dengan batas:
- `Σ cost_(i,f) × x_i ≤ envelope_f` untuk setiap sumber dana `f`.
- Kewajiban minimum, pembatasan sumber dana, prioritas yang diwajibkan, dependensi, mutual exclusivity, kapasitas pelaksanaan dan plafon yang disahkan.
- Jangan gunakan skor MCDA mentah sebagai proksi outcome lintas sektor tanpa kalibrasi. Mulai dengan utility relatif dalam kelompok sebanding; simpan asumsi.
- Jika infeasible: tampilkan daftar constraint konflik dan gap; **jangan** mengeluarkan alokasi palsu.
- Untuk fractional: hitung dampak/biaya sesuai kurva atau minimum viable package; jangan asumsikan linear jika tidak didukung data.
- Gunakan OR-Tools CP-SAT untuk keputusan integer dan model linear/MIP yang sesuai untuk variabel kontinu.

### 7.3 Forecasting
Baseline sederhana (moving average, tren) dibanding model regresi/time-series. Backtest rolling origin; metrik MAE/MAPE atau sMAPE sesuai karakter data; tampilkan ketidakpastian dan faktor eksternal. Jika data tidak memadai, tampilkan `INSUFFICIENT_DATA`, bukan prediksi buatan.

### 7.4 AI/RAG
Ingest dokumen resmi yang diizinkan; chunk + metadata (judul, halaman, tahun, versi); retrieval hanya dari koleksi yang disetujui; keluaran JSON tervalidasi (`claim`, `source`, `page`, `confidence`, `assumptions`); manusia mengonfirmasi mapping. Angka keuangan hanya berasal dari query database terverifikasi, bukan hasil generatif.

## 8. Modul UI
1. Dashboard eksekutif: ringkasan fiskal, usulan, prioritas, gap, status review.
2. Tahun/Tahap dan konfigurasi referensi.
3. Prioritas pembangunan: isu, indikator, target, mapping.
4. Fiskal: sumber dana, earmark, kewajiban, commitment.
5. Portal OPD: formulir usulan dan rincian biaya, evidence.
6. Verifikasi: inbox, checklist, komentar, history.
7. Skoring: rubric, bobot, skor dan penjelasan.
8. Simulasi: parameter, jalankan solver, status, diagnosis, perbandingan.
9. Rekap bertingkat: OPD → program → kegiatan → subkegiatan; drill-down.
10. Pembahasan, approval, snapshot dan ekspor.
11. Audit, data quality dan monitoring model.

## 9. API awal (prefix `/api/v1`)
- `POST /auth/login`, `GET /auth/me`.
- `GET/POST /planning-cycles`, `POST /planning-cycles/{id}/snapshot`.
- `GET/POST /priorities`, `GET/POST /objectives`, `POST /priority-links`.
- `GET/POST /fiscal-envelopes`, `POST /fiscal-envelopes/{id}/validate`.
- `GET/POST /proposals`, `GET/PATCH /proposals/{id}`, `POST /proposals/{id}/submit`.
- `POST /proposals/{id}/review`, `GET /proposals/{id}/history`.
- `POST /score-runs`, `GET /score-runs/{id}`.
- `POST /scenarios`, `POST /scenarios/{id}/run`, `GET /scenario-runs/{id}`.
- `GET /scenario-runs/{id}/allocations`, `GET /scenarios/compare`.
- `POST /planning-versions/{id}/approve`, `POST /planning-versions/{id}/lock`.
- `GET /reports/allocation-hierarchy`, `GET /audit-events`.
- `POST /imports`, `GET /imports/{id}`.
- `POST /ai/priority-analysis` (P1), `POST /forecasts` (P1).

**API conventions:** OpenAPI; pagination/filter/sort; error `{code,message,details,request_id}`; idempotency key pada operasi run/approval; `409` untuk konflik versi; permission per endpoint; validasi payload ketat; audit correlation ID.

## 10. Non-functional requirements
- **Security:** TLS, bcrypt/Argon2 password hash, JWT berumur pendek, refresh token aman, RBAC + OPD scope, rate limit, sanitasi unggahan, pembatasan akses evidence, secrets via environment, no secrets in git.
- **Privacy:** minimisasi data pribadi; jangan mengirim dokumen rahasia ke provider AI eksternal tanpa persetujuan dan kebijakan pengelolaan data.
- **Integrity:** transaksi database untuk perubahan pagu, optimistic locking, immutable snapshot, checksum input-output, audit log append-only.
- **Performance target awal (uji beban):** 100 pengguna bersamaan, halaman list p95 < 2 detik pada data uji representatif; simulasi 5.000 paket selesai < 120 detik pada server benchmark yang ditentukan. Angka target harus dikalibrasi saat pilot.
- **Availability:** backup harian dan uji restore; target RPO 24 jam/RTO 8 jam untuk pilot, revisi berdasarkan SLA pemerintah kota.
- **Observability:** structured logs, request ID, job metrics, solver duration, error rate, AI token/cost.
- **Accessibility:** antarmuka Bahasa Indonesia, validasi form jelas, keyboard navigation.
- **Deployment:** Ubuntu Server + Nginx reverse proxy + Supervisor/systemd + virtualenv; PostgreSQL terpisah; Docker opsional bukan wajib.

## 11. Acceptance test end-to-end
- **AT-01:** OPD membuat usulan dan tidak dapat mengakses usulan OPD lain (termasuk dengan memodifikasi URL/API).
- **AT-02:** Proposal tanpa baseline/evidence yang diwajibkan gagal verifikasi dengan alasan spesifik.
- **AT-03:** Dua run skor dengan snapshot dan versi kriteria identik menghasilkan skor identik.
- **AT-04:** Solver tidak pernah melampaui envelope per sumber dana.
- **AT-05:** Kewajiban minimum yang melebihi ruang fiskal menghasilkan `INFEASIBLE` dan gap, bukan angka alokasi.
- **AT-06:** Paket indivisible tidak pernah didanai sebagian.
- **AT-07:** Total pagu hierarki konsisten dan tidak menggandakan proposal multi-prioritas.
- **AT-08:** Revisi setelah lock membuat versi baru; versi lama tetap bisa diaudit.
- **AT-09:** Override skor/alokasi membutuhkan alasan, aktor, dan rekam before/after.
- **AT-10:** Ekspor pagu sama persis dengan snapshot yang disetujui.
- **AT-11:** AI tanpa evidence tidak boleh menghasilkan rekomendasi yang ditandai terverifikasi.
- **AT-12:** Sistem inti tetap berfungsi saat layanan AI mati.

## 12. Rencana implementasi Codex (incremental)
### Sprint 0 — Fondasi
Struktur monorepo, konfigurasi `.env.example`, FastAPI, SQLModel/Alembic, PostgreSQL, frontend ExtJS shell, CI pytest/lint, dokumentasi menjalankan lokal dan produksi. **Deliverable:** healthcheck, migrasi pertama, login dasar.
### Sprint 1 — Master dan siklus
Master OPD/nomenklatur, planning cycle/stage/version, role + OPD scope, import staging. **Deliverable:** referensi tervalidasi dan snapshot.
### Sprint 2 — Prioritas dan usulan
Prioritas, indikator, objective, mapping, usulan, rincian biaya, evidence, workflow. **Deliverable:** satu usulan berjalan dari draft ke verified.
### Sprint 3 — Fiskal dan skoring
Envelope per sumber dana, kewajiban, constraint, rubric/bobot terversi, deterministic scoring. **Deliverable:** laporan skor dapat diaudit.
### Sprint 4 — Simulasi
Solver OR-Tools, infeasibility diagnostics, scenario comparison, agregasi hierarki. **Deliverable:** rekomendasi alokasi feasible dan ekspor.
### Sprint 5 — Approval dan audit
Pembahasan, override, approval, locking, laporan dan audit trail. **Deliverable:** end-to-end pilot tanpa AI.
### Sprint 6 — AI/forecasting
RAG dengan citations, forecast dan backtest, penjelasan rekomendasi, observability. **Deliverable:** AI sebagai opsional enhancement.

**Definition of Done tiap sprint:** migrasi database reversible, unit/integration tests lulus, permission tests, OpenAPI diperbarui, sample seed, changelog, README, screenshot UI atau Playwright smoke test; tidak mengubah data produksi.

## 13. Struktur repositori yang disarankan
```text
priora/
  README.md
  PRD_PRIORA.md
  AGENTS.md
  .env.example
  backend/
    pyproject.toml
    alembic/
    app/
      main.py
      core/        # settings, auth, permissions, logging
      db/          # engine, sessions
      models/      # SQLModel entities
      schemas/     # request/response DTO
      api/v1/      # routers
      services/    # domain logic
      scoring/     # deterministic MCDA
      optimization/# OR-Tools + diagnostics
      forecasting/ # P1
      ai/          # P1, never directly writes allocations
      imports/
    tests/
  frontend/
    app/           # ExtJS Modern source
    resources/
    tests/
  docs/
    architecture.md
    business-rules.md
    api-contract.md
    data-dictionary.md
    decision-log.md
```

## 14. Instruksi awal untuk Codex IDE
> Baca `PRD_PRIORA.md` seluruhnya. Kerjakan **hanya Sprint 0** terlebih dahulu. Buat rencana file yang akan dibuat, asumsi, dan pertanyaan blocker. Gunakan FastAPI + SQLModel + PostgreSQL + Alembic dan frontend ExtJS Modern; jangan mengganti stack tanpa persetujuan. Terapkan modular monolith, strict typing, lint, pytest, dan migration. Jangan membuat data anggaran produksi atau angka hasil AI palsu. Buat `.env.example`, README instalasi Linux tanpa Docker, dan healthcheck. Setelah implementasi, jalankan pengujian dan laporkan hasil, daftar file berubah, perintah menjalankan, serta hal yang belum selesai. Jangan mulai Sprint 1 sebelum disetujui.

## 15. Pertanyaan kebijakan yang harus diputuskan sebelum Sprint 3–4
1. Apakah pagu OPD merupakan batas awal mengikat, batas lunak, atau hasil agregasi bottom-up? **Usulan:** batas awal lunak dengan rekonsiliasi, kecuali batas yang disahkan.
2. Bagaimana daftar belanja wajib/terikat dan basis hukumnya diverifikasi per tahun?
3. Apakah scoring lintas sektor diizinkan atau dipisah per kelompok layanan?
4. Siapa yang menyetujui rubric/bobot dan kapan versi dikunci?
5. Apa unit paket minimum yang dapat didanai, dan apakah paket boleh bertahap?
6. Bagaimana perlakuan hibah, bantuan keuangan, belanja tidak terduga dan sumber dana terikat dalam model?
7. Bagaimana hasil PRIORA ditransfer ke dokumen dan proses SIPD-RI secara resmi?
8. Apakah AI eksternal diizinkan memproses dokumen internal? Jika tidak, gunakan model lokal atau non-AI.

## 16. Referensi dan status validasi
- Basis konseptual: Onno W. Purbo, *AI untuk Perencanaan Anggaran* (2026), terutama bab tentang data training, objective, forecasting, simulasi alternatif dan governance. Buku **tidak** menetapkan algoritma khusus APBD Kota Tegal.
- Kerangka regulasi untuk **diverifikasi oleh tim hukum/perencanaan** sebelum produksi: UU 23/2014, PP 12/2019, Permendagri 86/2017, Permendagri 77/2020, ketentuan klasifikasi/kodefikasi/nomenklatur dan pedoman APBD tahun terkait, serta aturan mandatory spending dan SPM yang berlaku.
- Seluruh bobot, SLA, ukuran data, anggaran ilustratif dan pilihan stack dalam PRD ini adalah **usulan desain**, bukan kebijakan resmi.
