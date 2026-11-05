@echo off
title Robot Trading Kronos
cd /d "%~dp0"
set PYTHONUTF8=1
if exist .venv\setup_ok goto run

echo ==========================================================
echo   Persiapan pertama kali (5-15 menit, hanya sekali)
echo ==========================================================
where python >nul 2>nul || (echo. & echo Python belum terpasang. & echo Install Python 3.11 dari https://www.python.org/downloads/ & echo dan CENTANG "Add python.exe to PATH" saat instalasi. Lalu klik MULAI lagi. & pause & exit /b 1)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" || (echo Versi Python terlalu lama. Install Python 3.11 dari python.org. & pause & exit /b 1)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || (echo. & echo Gagal memasang library. Cek internet lalu klik MULAI lagi. & pause & exit /b 1)
python setup_kronos.py || (echo. & echo Gagal mengunduh Kronos. Cek internet lalu klik MULAI lagi. & pause & exit /b 1)
if not exist .env copy .env.example .env >nul
echo ok> .venv\setup_ok
echo Persiapan selesai.

:run
call .venv\Scripts\activate.bat
echo.
echo ==========================================================
echo   Panel Kontrol terbuka di browser: http://localhost:8501
echo   Biarkan jendela ini terbuka selama memakai panel.
echo ==========================================================
streamlit run app.py --server.headless false --browser.gatherUsageStats false
pause
