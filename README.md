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

## Scanner: cari peluang di seluruh pasar

Menu **Scanner** memeriksa seluruh pasar, bukan cuma watchlist:
- **Crypto:** 30, 60, atau 100 koin USDT teramai (volume 24 jam). Stablecoin dan token leverage dilewati.
- **Forex:** 28 pair mayor dan silang, plus emas (XAU) dan perak (XAG).

Caranya dua tahap:
1. Semua pair dinilai secara teknikal: tren, momentum dibanding volatilitas, kerapian gerak, breakout, lonjakan volume (crypto), RSI, dan apakah gerakannya cukup besar dibanding biaya. Untuk forex, arah Buy dan Sell dinilai terpisah.
2. Kandidat teratas dicek AI Kronos. Hasilnya peluang skenario searah, perkiraan gerak harga, dan potensi untung setelah biaya.

Hasilnya skor 0–100, tiga pilihan teratas, dan tabel lengkap. Dari situ kamu bisa langsung **+ Watch**, nyalakan **Auto**, buka **Chart**, atau **Backtest** pair itu. Ringkasan Top opportunities juga muncul di Overview.

Skor hanya untuk mengurutkan, bukan jaminan untung. Sebelum pair diserahkan ke robot, jalankan Backtest dan pilih yang dapat nilai A atau B.

## Backtest lab: seberapa akurat, setelan mana yang terbaik

Buka **Backtest** di market yang kamu pilih, centang beberapa pair sekaligus, lalu tekan **Run backtest**. Tiap hasil dapat nilai **A sampai D**:

| Nilai | Artinya |
|---|---|
| A | Semua pemeriksaan lolos. Layak dicoba live dengan modal kecil |
| B | Ada harapan. Lanjutkan di Simulation dulu |
| C | Lemah, bisa jadi kebetulan. Jangan dipakai live |
| D | Hindari |

Nilai A atau B hanya mungkin kalau dua syarat ini lolos: arah ramalan AI **terbukti lebih baik dari lempar koin** (uji statistik), dan hasil **walk-forward** positif.

Yang dicek di backtest:
- **AI accuracy:** persentase arah benar, akurasi sinyal kuat, kalibrasi peluang (kalau AI bilang 70% naik, apakah memang naik sekitar 70%), dan error besar gerakan dibanding menebak "tidak bergerak".
- **Per segmen waktu:** periode dibagi beberapa bagian. Setelan yang bagus untung di sebagian besar bagian, bukan cuma sekali beruntung.
- **Walk-forward:** setelan dipilih hanya dari data sebelumnya, lalu diuji di data sesudahnya. Ini perkiraan paling jujur.
- **Monte Carlo:** urutan trade diacak ribuan kali untuk melihat rentang hasil dan peluang rugi.
- Eksekusi dibuat realistis: order di harga open candle berikutnya, fee/spread dan slippage dihitung, dan kalau stop-loss serta target tersentuh di candle yang sama, dianggap kena stop-loss.

Tab **Best settings** mengurutkan setelan dari yang paling konsisten. Tombol **Apply** langsung memakainya untuk robot market itu.

### Pakai GPU (VGA)

- **NVIDIA (Windows):** `MULAI.bat` otomatis memasang PyTorch versi GPU kalau kartu NVIDIA terdeteksi (sekali saja, sekitar 2–3 GB). Kalau gagal, hapus file `.venv\gpu_checked` lalu jalankan MULAI lagi.
- **Mac Apple Silicon (M1/M2/M3/M4):** GPU Metal dipakai otomatis.
- Pilih **Compute → GPU** di Backtest, atau **Settings → AI model & compute** untuk robot. Dengan GPU, banyak titik waktu diramal sekaligus, biasanya 10–30× lebih cepat. Itu cukup untuk model **Accurate** dan 30–50 skenario ramalan.
- GPU AMD dan Intel belum didukung, jadi robot tetap memakai CPU.

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
