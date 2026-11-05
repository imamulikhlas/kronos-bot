#!/usr/bin/env bash
# Robot Trading Kronos — untuk macOS / Linux. Klik dua kali (macOS) atau jalankan: bash mulai.command
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
if [ ! -f .venv/setup_ok ]; then
  echo "=== Persiapan pertama kali (5-15 menit, hanya sekali) ==="
  PY=$(command -v python3.11 || command -v python3.12 || command -v python3)
  if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
    echo "Butuh Python 3.10 atau lebih baru. Install dari https://www.python.org/downloads/"; read -r; exit 1
  fi
  [ -d .venv ] || "$PY" -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt || { echo "Gagal memasang library. Cek internet lalu jalankan lagi."; read -r; exit 1; }
  python setup_kronos.py || { echo "Gagal mengunduh Kronos. Cek internet lalu jalankan lagi."; read -r; exit 1; }
  [ -f .env ] || cp .env.example .env
  echo ok > .venv/setup_ok
fi
source .venv/bin/activate
echo "Panel Kontrol terbuka di browser: http://localhost:8501  (biarkan jendela ini terbuka)"
streamlit run app.py --server.headless false --browser.gatherUsageStats false
