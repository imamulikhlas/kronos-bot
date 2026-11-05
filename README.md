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
1. Menu **⚙️ Pengaturan Robot**: pilih koin, modal per posisi, maksimal posisi, stop-loss, take-profit, lalu **Simpan**.
2. Menu **🏠 Beranda**: klik **▶️ Nyalakan Robot**.

Robot mulai di mode **Simulasi** (uang virtual, harga asli). Pertama kali menyala, robot mengunduh model AI, jadi tunggu beberapa menit.

**Langkah 4 — Pakai uang sungguhan (setelah simulasi meyakinkan)**
Menu **🔑 Akun & Mode** → isi API key Tokocrypto → **Tes koneksi akun** → pilih **Live** → ketik konfirmasi.

## Isi Panel Kontrol

| Menu | Fungsi |
|---|---|
| 🏠 Beranda | Nyalakan/matikan robot, lihat saldo & untung/rugi, posisi terbuka + tombol **Jual**, tombol **Jual semua**, **Jeda beli baru**, keputusan terakhir robot |
| ⚙️ Pengaturan Robot | Koin, timeframe, modal per posisi, **maksimal posisi terbuka**, batas rugi harian, stop-loss, take-profit, seberapa yakin sebelum membeli, ukuran model AI |
| 🔑 Akun & Mode | API key, tes koneksi, pindah Simulasi ↔ Live, reset simulasi |
| 📊 Riwayat & Grafik | Grafik aset, semua trade, grafik ramalan AI |
| 🧪 Uji Strategi | Coba pengaturan Anda di data masa lalu sebelum dipakai |

## Penting

- **Robot tetap berjalan walau tab browser ditutup.** Untuk menghentikannya, buka panel lalu klik **⏹️ Matikan Robot**.
- **Komputer harus menyala dan tidak tidur (sleep).** Stop-loss dijalankan oleh robot. Jika komputer mati, posisi terbuka tidak terlindungi. Atur Windows: Settings → Power → Sleep: *Never*.
- Saat membuat API key di Tokocrypto, aktifkan **baca + spot trading** saja. **Jangan aktifkan withdraw.**
- Jangan trading manual di koin yang sama saat robot menyala.
- Robot hanya membeli lalu menjual (spot). Tidak ada margin atau leverage.
- Ini alat eksperimen dan bisa rugi. Mulai dari Simulasi, lalu Live dengan modal kecil.

## Jika ada masalah

- **Panel tidak terbuka:** buka browser lalu ketik `http://localhost:8501`.
- **Robot mati sendiri:** Beranda akan menampilkan pesan error-nya. Penyebab umum: internet putus, pair salah, atau API key ditolak.
- **Ingin mengulang persiapan dari awal:** hapus folder `.venv`, lalu klik MULAI lagi.
- Log lengkap ada di folder `logs/`.
