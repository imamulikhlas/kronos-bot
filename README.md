# kronos — robot trading kripto & forex

Robot ini meramal arah harga pakai AI **Kronos**, lalu buka dan tutup posisi sendiri.

- **Kripto** lewat Tokocrypto. Spot, jadi cuma bisa buy.
- **Forex & emas** lewat MetaTrader 5. Bisa buy dan sell.

Semuanya diatur dari panel di browser, tanpa ngetik perintah.

> Ini alat eksperimen dan bisa rugi. Mulai dari mode **simulasi** (uang virtual, harga asli),
> dan kalau mau live, pakai modal kecil yang siap hilang. Ini bukan nasihat keuangan.

## Cara pakai

1. **Install Python 3.11** dari https://www.python.org/downloads/. Di Windows, centang **"Add python.exe to PATH"**.
2. **Buka panel.**
   - Windows: klik dua kali **`MULAI.bat`**.
   - Mac: klik kanan **`mulai.command`** → Open.

   Pertama kali ada persiapan otomatis 5–15 menit. Setelah itu panel kebuka sendiri di `http://localhost:8501`. Jendela hitamnya jangan ditutup.
3. **Ikuti 3 langkah di beranda:**
   1. Pilih pasar.
   2. Uji dulu.
   3. Nyalain robot.

## Isi panel

| Menu | Buat apa |
|---|---|
| beranda | Saklar nyala/mati robot, total aset, cuan hari ini, posisi terbuka (stop-loss, target, tombol tutup), keputusan terakhir robot, **rapor akurasi**, aktivitas |
| analisa | Grafik live dan ramalan AI ke depan beserta batas atas-bawahnya, arah (naik/turun/datar), peluang naik vs turun, dan apa yang bakal dilakukan robot. Ada juga fitur bandingin banyak pasar sekaligus |
| riwayat | Semua trade yang sudah ditutup dan grafik aset |
| uji | Uji setelan di data lama, plus optimasi otomatis yang dinilai di periode yang belum pernah dilihat. Setelan terbaik bisa dipakai dengan 1 klik |
| setelan | Pasar, timeframe, modal, risiko forex per posisi, posisi maksimal, cara buka/tutup posisi (terpisah untuk kripto & forex), batas akurasi, ukuran model AI |
| akun | Simulasi atau live, API key Tokocrypto, koneksi MetaTrader 5 |

Tombol bulan di pojok kanan atas buat ganti tema terang/gelap.

## Forex lewat MetaTrader 5 (Windows)

1. Bikin akun di broker forex yang pakai **MetaTrader 5**. Mulai dari **akun demo gratis** dulu.
2. Install aplikasi MT5 dari broker itu, login, lalu nyalain tombol **Algo Trading** sampai hijau.
3. Di panel, buka **akun → MetaTrader 5**. Centang "pakai MT5 buat forex", simpan, lalu klik **cek koneksi**.
4. Pastikan nama simbol di panel sama dengan di Market Watch MT5. Beberapa broker pakai akhiran, misalnya `EURUSDm`. Ketik saja nama itu di kolom tambah pasar.

Tanpa MT5 (misalnya di Mac), forex tetap bisa dianalisa, diuji, dan disimulasikan pakai data Yahoo Finance. Data Yahoo untuk timeframe 15 dan 30 menit cuma sekitar 60 hari ke belakang.

Untuk forex, stop-loss dan target juga dipasang **di server broker**, jadi tetap aktif walau komputer mati. Trailing stop tetap butuh robot menyala.

## Soal akurasi

Robot mencatat **seberapa sering arah ramalannya benar** untuk tiap pasar, dari dua sumber: uji strategi, dan ramalan robot yang waktunya sudah lewat. Hasilnya tampil di **rapor akurasi** di beranda.

Default-nya, robot tidak membuka posisi di pasar yang akurasinya di bawah 55% setelah 30 ramalan dinilai. Batas ini bisa diubah di **setelan → akurasi**, termasuk opsi "wajib terbukti dulu".

Cara tercepat mengisi rapor: jalankan **uji** untuk tiap pasar yang kamu pilih.

Ramalan tetap bisa salah. Akurasi 55–60% di arah harga itu sudah termasuk bagus. Yang menentukan untung atau rugi adalah gabungan akurasi, stop-loss/target, dan biaya.

## Penting

- **Robot tetap jalan walau tab browser ditutup.** Matikan lewat saklar di beranda.
- **Komputer harus nyala dan tidak sleep.** Di Windows: Settings → Power → Sleep: *Never*.
- API key Tokocrypto: aktifkan izin **baca + spot trading** saja, **jangan izin withdraw**.
- Jangan trading manual di pasar yang sama saat robot menyala.
- Kunci & password tersimpan di file `.env` di komputer kamu dan tidak pernah ikut ke GitHub.

## Kalau ada masalah

- **Panel nggak kebuka:** ketik `http://localhost:8501` di browser.
- **Robot mati sendiri:** pesan error-nya muncul di beranda. Penyebab umum: internet putus, nama simbol salah, API key ditolak, atau MT5 belum login.
- **MT5 nggak nyambung:** pastikan aplikasi MT5 terbuka, sudah login, dan Algo Trading hijau. Kalau terminalnya lebih dari satu, isi lokasi `terminal64.exe` di halaman akun.
- **Mau ulang persiapan dari awal:** hapus folder `.venv`, lalu klik MULAI lagi.
- Log lengkap ada di folder `logs/`.
