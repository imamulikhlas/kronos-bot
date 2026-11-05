# 🤖 Robot Trading Kronos (Tokocrypto)

Robot ini membeli dan menjual crypto **otomatis** di Tokocrypto berdasarkan ramalan AI Kronos.
Semua diatur dari **Panel Kontrol** di browser. Tidak perlu mengetik perintah apa pun.

## Cara memakai

**Langkah 1 — Install Python (sekali saja)**
Unduh Python 3.11 dari https://www.python.org/downloads/.
Saat instalasi di Windows, **centang "Add python.exe to PATH"**.

**Langkah 2 — Buka Panel Kontrol**
- Windows: klik dua kali **`MULAI.bat`**
- Mac: klik kanan **`mulai.command`** → Open

Pertama kali akan ada persiapan otomatis selama 5–15 menit. Setelah itu, Panel Kontrol langsung terbuka di browser. Biarkan jendela hitamnya tetap terbuka.

**Langkah 3 — Atur dan nyalakan**
1. Menu **Pengaturan**: pilih koin, modal per posisi, maksimal posisi, stop-loss, take-profit, lalu **Simpan**.
2. Menu **Beranda**: klik **Nyalakan robot**.

Robot mulai di mode **Simulasi** (uang virtual, harga asli). Pertama kali menyala, robot mengunduh model AI, jadi tunggu beberapa menit.

**Langkah 4 — Pakai uang sungguhan (setelah simulasi meyakinkan)**
Menu **Akun & mode** → isi API key Tokocrypto → **Tes koneksi akun** → pilih **Live** → ketik konfirmasi.

## Isi Panel Kontrol

| Menu | Fungsi |
|---|---|
| Beranda | Nyalakan/matikan robot, hitung mundur ke ramalan berikutnya, total aset & untung/rugi, posisi terbuka dengan batas jual + tombol **Jual** / **Jual semua**, **Jeda beli baru**, keputusan terakhir per koin, aktivitas |
| Analisa | Grafik candlestick live + **kerucut ramalan AI** (perkiraan tengah dan rentang 10–90%), EMA, RSI, volume; arah prediksi dengan peluang naik, potensi untung:rugi, tren; apa yang akan dilakukan robot; **Ramal sekarang** dan **Pindai banyak koin** |
| Pengaturan | Koin, timeframe, modal per posisi, **maksimal posisi terbuka**, batas rugi harian, stop-loss, take-profit, seberapa yakin sebelum membeli, filter tren, batas RSI, rasio untung:rugi, stop-loss otomatis (ATR), **trailing stop**, ukuran model AI |
| Akun & mode | API key, tes koneksi, pindah Simulasi ↔ Live, reset simulasi |
| Riwayat | Grafik aset, semua trade, grafik ramalan AI |
| Uji strategi | Coba pengaturan Anda di data masa lalu + **optimasi otomatis**: mencari setelan terbaik lalu mengujinya di periode yang belum dilihat; pakai hasilnya dengan satu klik |

## Cara robot memutuskan

Setiap candle tutup, robot meramal semua koin, lalu:
1. **Mengurus posisi yang ada dulu.** Jual jika kena stop-loss, take-profit, atau trailing stop, sudah terlalu lama dipegang, atau ramalan berbalik turun.
2. **Membeli mulai dari sinyal terkuat** (skor = perkiraan kenaikan × peluang naik). Robot hanya membeli jika semua syarat lolos:
   - ramalan naik cukup besar
   - peluang naik cukup tinggi
   - tren sedang naik
   - RSI belum jenuh beli
   - potensi untung cukup besar dibanding potensi rugi
   - slot posisi dan saldo masih ada
3. **Menjaga posisi tiap menit.** Saat harga naik, trailing stop ikut naik untuk mengunci untung.

## Penting

- **Robot tetap berjalan walau tab browser ditutup.** Untuk menghentikannya, buka panel lalu klik **Matikan robot**.
- **Komputer harus menyala dan tidak tidur (sleep).** Stop-loss dijalankan oleh robot. Jika komputer mati, posisi terbuka tidak terlindungi. Atur Windows: Settings → Power → Sleep: *Never*.
- Saat membuat API key di Tokocrypto, aktifkan **baca + spot trading** saja. **Jangan aktifkan withdraw.**
- Jangan trading manual di koin yang sama saat robot menyala.
- Robot hanya membeli lalu menjual (spot). Tidak ada margin atau leverage.
- Ini alat eksperimen dan bisa rugi. Mulai dari Simulasi, lalu Live dengan modal kecil.

## Jika ada masalah

- **Panel tidak terbuka:** buka browser lalu ketik `http://localhost:8501`. Panel hanya bisa dibuka dari komputer ini.
- **Robot mati sendiri:** Beranda akan menampilkan pesan error-nya. Penyebab umum: internet putus, pair salah, atau API key ditolak.
- **Ingin mengulang persiapan dari awal:** hapus folder `.venv`, lalu klik MULAI lagi.
- Log lengkap ada di folder `logs/`.
