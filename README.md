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
3. **Pilih market:** Crypto atau Forex. Pindah kapan saja lewat tombol di atas.
4. Di halaman **Overview**, tekan **Start**. Mulai dari mode **Simulation** dulu.

## Crypto dan Forex terpisah

Tiap market punya robot sendiri: tombol Start/Stop, mode Simulation/Live, saldo virtual, setelan, posisi, dan riwayat masing-masing. Robot crypto bisa jalan sementara robot forex mati, atau dua-duanya jalan bareng.

| | Crypto | Forex |
|---|---|---|
| Broker | Tokocrypto (spot) | MetaTrader 5 (atau data Yahoo untuk simulasi) |
| Arah | Hanya Buy | Buy dan Sell |
| Ukuran posisi | USDT tetap per posisi | Lot dihitung dari risiko % per posisi |
| Jam pasar | 24 jam | Senin 04.00 – Sabtu 04.00 WIB |
| Stop-loss/target | Dijaga robot | Juga dipasang di server broker |

## Isi panel (per market)

| Menu | Buat apa |
|---|---|
| Overview | Start/Stop robot, equity, untung-rugi, posisi terbuka (tombol Close), sinyal terakhir, ringkasan "How this bot trades", rapor akurasi, aktivitas |
| Markets | Pantau banyak pair sekaligus: harga, grafik kecil, ramalan AI, akurasi. Tombol **Auto** memilih pair mana yang di-trade robot. Centang **Compare** untuk membandingkan performa (%), volatilitas, drawdown, dan korelasi |
| Chart | Grafik live satu pair plus ramalan AI ke depan dan keputusan yang bakal diambil robot |
| Backtest | Uji setelan di data lama, plus cari setelan terbaik yang dinilai di periode yang belum pernah dilihat. Setelan bisa dipakai dengan 1 klik |
| Settings | Mode Simulation/Live, timeframe, ukuran posisi & risiko, aturan masuk (Careful/Balanced/Active), aturan keluar, filter akurasi, model AI |

**Account** (pojok kanan atas) untuk API key Tokocrypto dan koneksi MetaTrader 5. Tombol bulan untuk tema terang/gelap.

## Forex lewat MetaTrader 5 (Windows)

1. Bikin akun di broker forex yang pakai **MetaTrader 5**. Mulai dari **akun demo gratis** dulu.
2. Install aplikasi MT5 dari broker itu, login, lalu nyalain tombol **Algo Trading** sampai hijau.
3. Di panel, buka **Account → MetaTrader 5**. Centang "Use MetaTrader 5 for Forex", simpan, lalu klik **Test connection**.
4. Pastikan nama simbol di panel sama dengan di Market Watch MT5. Beberapa broker pakai akhiran, misalnya `EURUSDm`. Ketik saja nama itu di kolom "Add pair" di halaman Forex → Markets.

Tanpa MT5 (misalnya di Mac), forex tetap bisa dianalisa, diuji, dan disimulasikan pakai data Yahoo Finance. Data Yahoo untuk timeframe 15 dan 30 menit cuma sekitar 60 hari ke belakang.

Untuk forex, stop-loss dan target juga dipasang **di server broker**, jadi tetap aktif walau komputer mati. Trailing stop tetap butuh robot menyala.

## Soal akurasi

Robot mencatat **seberapa sering arah ramalannya benar** untuk tiap pasar, dari dua sumber: uji strategi, dan ramalan robot yang waktunya sudah lewat. Hasilnya tampil di kartu **Accuracy** di Overview dan di tiap kartu Markets.

Default-nya, robot tidak membuka posisi di pasar yang akurasinya di bawah 55% setelah 30 ramalan dinilai. Batas ini bisa diubah di **Settings → Accuracy filter**, termasuk opsi "wajib terbukti dulu".

Cara tercepat mengisi rapor: jalankan **Backtest** untuk tiap pair yang kamu pilih.

Ramalan tetap bisa salah. Akurasi 55–60% di arah harga itu sudah termasuk bagus. Yang menentukan untung atau rugi adalah gabungan akurasi, stop-loss/target, dan biaya.

## Penting

- **Robot tetap jalan walau tab browser ditutup.** Matikan lewat tombol Stop di Overview market masing-masing.
- **Komputer harus nyala dan tidak sleep.** Di Windows: Settings → Power → Sleep: *Never*.
- API key Tokocrypto: aktifkan izin **baca + spot trading** saja, **jangan izin withdraw**.
- Jangan trading manual di pasar yang sama saat robot menyala.
- Setelah update ini, saldo simulasi dihitung terpisah per market (mulai lagi dari saldo awal). Untuk live, kunci pengaman di `.env` sekarang `LIVE_CRYPTO` dan `LIVE_FOREX` (diatur otomatis dari Settings).
- Kunci & password tersimpan di file `.env` di komputer kamu dan tidak pernah ikut ke GitHub.

## Kalau ada masalah

- **Panel nggak kebuka:** ketik `http://localhost:8501` di browser.
- **Robot mati sendiri:** pesan error-nya muncul di Overview. Penyebab umum: internet putus, nama simbol salah, API key ditolak, atau MT5 belum login.
- **MT5 nggak nyambung:** pastikan aplikasi MT5 terbuka, sudah login, dan Algo Trading hijau. Kalau terminalnya lebih dari satu, isi lokasi `terminal64.exe` di halaman Account.
- **Mau ulang persiapan dari awal:** hapus folder `.venv`, lalu klik MULAI lagi.
- Log lengkap ada di folder `logs/`.
