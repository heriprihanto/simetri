# Deployment SIMETRI

Target: `https://monevrkpd.tegalkota.go.id/simetri`.

## Hasil pemeriksaan lokal

- Routing, login, CSS/JS, form HTMX, upload biasa, redirect dan logout memakai `/simetri`.
- Mendukung proxy yang menghapus maupun mempertahankan prefix. Jangan daftarkan router dua kali dan jangan tambahkan `--root-path` di perintah Uvicorn.
- Endpoint `/auth/dev-login` dihapus. Upload/hapus lampiran dan halaman dokumen memerlukan login.
- Cakupan kronologi diperiksa pada daftar, detail, edit, simpan, hapus dan lampirannya. Pengguna OPD tanpa penugasan tidak menerima seluruh data ketika daftar dokumennya kosong.
- OAuth memakai state bertanda tangan dengan masa berlaku 10 menit dan cookie Secure/HttpOnly; email Google harus terverifikasi.
- Konfigurasi HTTPS menolak kunci sesi bawaan/lemah, cookie tidak aman, dan callback di luar URL aplikasi.
- URL database mengenkode karakter khusus pada password serta menerapkan `DB_SSLMODE` dan timeout koneksi.
- Startup membuat tabel sebelum seeding, mendengarkan loopback, dan tidak memakai auto-reload.
- Kalender menangani bulan di luar rentang tanpa error 500.

Pengujian memakai SQLite sementara dan OAuth/gateway tiruan. Koneksi PostgreSQL server, konfigurasi Google Console, hak akses Drive, WhatsApp, Gemini, sertifikat dan virtual host publik tetap harus diverifikasi dari server deployment. Pemeriksaan ini bukan audit keamanan menyeluruh.

## Persiapan server

1. Pasang Python 3.10+ dan PostgreSQL. Letakkan aplikasi, misalnya di `/opt/simetri`, dengan user layanan `simetri`.
2. Buat virtual environment dan pasang dependensi:

   ```bash
   cd /opt/simetri
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   venv/bin/pip check
   ```

3. Salin `.env.example` menjadi `.env`, isi password database, kredensial Google dan kunci sesi acak. Jika memakai `.env` lokal yang telah diperbaiki, pertahankan kunci sesi yang sama pada seluruh proses server. `.env` tidak disertakan dalam Git.
4. Pastikan database `simetri` tersedia, user database dapat membuat tabel, dan koneksi PostgreSQL diizinkan dari server aplikasi. Isi `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, dan `DB_SSLMODE` sesuai server.
5. Tempatkan service account di `secrets/service_account.json`, isi `GDRIVE_PARENT_FOLDER_ID`, dan beri service account hak tulis pada folder Drive/Shared Drive yang digunakan. Pastikan kebijakan akun mengizinkan upload, terutama bila service account tidak mempunyai kuota penyimpanan pribadi.
6. Di Google Cloud Console, daftarkan **Authorized redirect URI** persis:

   ```text
   https://monevrkpd.tegalkota.go.id/simetri/oauthcallback
   ```

   Pastikan `GOOGLE_CLIENT_ID` dan `GOOGLE_CLIENT_SECRET` berasal dari client tersebut. Isi `INITIAL_ADMIN_EMAIL` dengan akun Google admin yang benar sebelum startup pertama.
7. Isi `WA_API_URL`, `WA_DEVICE_ID`, dan path media sesuai lokasi gateway server. Default path komputer pengembang harus diganti. Jika gateway satu mesin, callback dapat memakai `http://127.0.0.1:8987/api/whatsapp`. Jika melalui domain publik, izinkan hanya IP gateway pada blok webhook di konfigurasi proxy. Webhook menerima identitas pengirim dari gateway sehingga harus dibatasi aksesnya.
8. Jika chatbot digunakan, isi `GEMINI_API_KEY` dan verifikasi ketersediaan `GEMINI_MODEL` pada akun Google AI yang digunakan.
9. Batasi akses `.env` dan service account (`chmod 600`); user layanan harus dapat membacanya dan menulis direktori `uploads/` serta log webhook di root aplikasi. Web server harus mem-proxy ke Uvicorn, bukan melayani direktori proyek sebagai document root.

## Menjalankan layanan

Jalankan pemeriksaan lokal:

```bash
venv/bin/python -m unittest discover -s tests -v
bash -n run.sh
```

`./run.sh` membuat tabel yang belum ada dan mengisi master/admin awal secara idempoten. Pada database existing, `create_all` **tidak mengubah kolom tabel lama**: cadangkan database dan cocokkan skema dengan model sebelum upgrade. Jangan jalankan seed pada database yang belum ditentukan dengan benar.

Sesuaikan user dan path pada `deploy/simetri.service`, lalu pasang unit di server:

```bash
sudo cp deploy/simetri.service /etc/systemd/system/simetri.service
sudo systemctl daemon-reload
sudo systemctl enable --now simetri
sudo systemctl status simetri
```

Pilih salah satu snippet `nginx-simetri.conf` atau `apache-simetri.conf` sesuai web server. Gabungkan ke virtual host HTTPS yang sudah ada; sesuaikan port jika bukan 8987. Validasi dengan `nginx -t` atau `apachectl configtest` sebelum reload server.

`FORWARDED_ALLOW_IPS=127.0.0.1` sesuai proxy pada mesin yang sama. Jika proxy berada di mesin terpisah, sesuaikan bind Uvicorn dan IP proxy tepercaya, serta batasi akses backend melalui firewall.

## Verifikasi setelah pemasangan

- `/simetri` mengarah ke `/simetri/`, kemudian kronologi/login; tidak ada redirect ke localhost atau prefix ganda.
- `/simetri/login`, `/simetri/static/css/app.css`, dan `/simetri/static/js/app.js` merespons 200.
- `/simetri/auth/dev-login` merespons 404; halaman dokumen dan API lampiran menolak pengguna tanpa sesi.
- Login Google dengan akun whitelist berhasil; akun tidak terdaftar/nonaktif ditolak. Logout menghapus cookie sesi.
- Buka kronologi, arsip, agenda, dokumen, chatbot, pengguna, dan audit; uji simpan data serta upload/download lampiran.
- Uji callback WhatsApp dari gateway yang diizinkan dan pastikan sumber lain ditolak proxy.
- Periksa `journalctl -u simetri` jika startup atau request gagal. Pastikan TLS valid dan tidak ada mixed content.

Kunci sesi default pada `.env` lokal sudah diganti saat pemeriksaan; sesi lama memerlukan login ulang. Jangan menyalin kunci pengembang ke deployment lain: buat kunci khusus server bila konfigurasi dibuat ulang.
