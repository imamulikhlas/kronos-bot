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
rem Python 3.12/3.11 diutamakan: pendukung VGA AMD/Intel (DirectML) belum ada untuk Python 3.13
set PYEXE=python
py -3.12 -c "" >nul 2>nul && set PYEXE=py -3.12
if "%PYEXE%"=="python" py -3.11 -c "" >nul 2>nul && set PYEXE=py -3.11
if not exist .venv %PYEXE% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || (echo. & echo Gagal memasang library. Cek internet lalu klik MULAI lagi. & pause & exit /b 1)
python setup_kronos.py || (echo. & echo Gagal mengunduh Kronos. Cek internet lalu klik MULAI lagi. & pause & exit /b 1)
if not exist .env copy .env.example .env >nul
copy /y requirements.txt .venv\req_installed.txt >nul
echo ok> .venv\setup_ok
echo Persiapan selesai.

:run
call .venv\Scripts\activate.bat
fc /b requirements.txt .venv\req_installed.txt >nul 2>nul || (echo Memperbarui library untuk versi baru... & pip install -r requirements.txt && copy /y requirements.txt .venv\req_installed.txt >nul)
if exist .venv\gpu_redo (del .venv\gpu_redo & del .venv\gpu_checked_v3 >nul 2>nul)
if not exist .venv\gpu_checked_v3 (
  echo.
  echo Memeriksa kartu grafis VGA untuk AI, sekali saja...
  python setup_gpu.py
  echo ok> .venv\gpu_checked_v3
)
pip show MetaTrader5 >nul 2>nul || pip install MetaTrader5 >nul 2>nul || echo Library MetaTrader 5 tidak terpasang. Forex tetap bisa lewat data Yahoo Finance.
echo.
echo ==========================================================
echo   Panel robot terbuka di browser: http://localhost:8501
echo   Biarkan jendela ini terbuka selama memakai panel.
echo ==========================================================
python server.py
pause
exit /b 0
