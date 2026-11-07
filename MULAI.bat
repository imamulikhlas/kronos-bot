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
copy /y requirements.txt .venv\req_installed.txt >nul
echo ok> .venv\setup_ok
echo Persiapan selesai.

:run
call .venv\Scripts\activate.bat
fc /b requirements.txt .venv\req_installed.txt >nul 2>nul || (echo Memperbarui library untuk versi baru... & pip install -r requirements.txt && copy /y requirements.txt .venv\req_installed.txt >nul)
if not exist .venv\gpu_checked call :gpu
pip show MetaTrader5 >nul 2>nul || pip install MetaTrader5 >nul 2>nul || echo (Library MetaTrader 5 tidak terpasang. Forex tetap bisa lewat data Yahoo Finance.)
echo.
echo ==========================================================
echo   Panel robot terbuka di browser: http://localhost:8501
echo   Biarkan jendela ini terbuka selama memakai panel.
echo ==========================================================
python server.py
pause
exit /b 0

:gpu
rem Kartu grafis NVIDIA? Pasang PyTorch versi CUDA supaya ramalan & backtest bisa memakai GPU.
echo ok> .venv\gpu_checked
where nvidia-smi >nul 2>nul || exit /b 0
python -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>nul && exit /b 0
set CUDA_TAG=cu126
nvidia-smi --query-gpu=name --format=csv,noheader | findstr /r /c:"RTX 50" >nul && set CUDA_TAG=cu128
echo.
echo Kartu grafis NVIDIA terdeteksi. Memasang PyTorch versi GPU, sekali saja, sekitar 2-3 GB...
pip uninstall -y torch >nul 2>nul
pip install torch --index-url https://download.pytorch.org/whl/%CUDA_TAG% && exit /b 0
echo Versi GPU gagal dipasang. Memakai versi CPU, robot tetap jalan.
pip install torch
exit /b 0
