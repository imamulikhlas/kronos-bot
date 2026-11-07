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
if not exist .venv\gpu_checked_v2 call :gpu
rem Pakai kartu grafis untuk AI: NVIDIA (CUDA), Intel Arc (XPU), AMD (DirectML). Sekali saja.
echo ok> .venv\gpu_checked_v2
python -c "import torch,sys; ok=torch.cuda.is_available() or (hasattr(torch,'xpu') and torch.xpu.is_available()); sys.exit(0 if ok else 1)" >nul 2>nul && exit /b 0
python -c "import torch_directml,sys; sys.exit(0 if torch_directml.device_count() else 1)" >nul 2>nul && exit /b 0
powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController).Name" > .venv\gpus.txt 2>nul
findstr /i "NVIDIA GeForce RTX Quadro" .venv\gpus.txt >nul && goto gpu_nvidia
findstr /i "Arc" .venv\gpus.txt >nul && goto gpu_intel
findstr /i "AMD Radeon" .venv\gpus.txt >nul && goto gpu_amd
exit /b 0

:gpu_nvidia
set CUDA_TAG=cu126
findstr /i /c:"RTX 50" .venv\gpus.txt >nul && set CUDA_TAG=cu128
echo.
echo Kartu grafis NVIDIA terdeteksi. Memasang PyTorch versi GPU, sekali saja, sekitar 2-3 GB...
pip uninstall -y torch >nul 2>nul
pip install torch --index-url https://download.pytorch.org/whl/%CUDA_TAG% && exit /b 0
goto gpu_fail

:gpu_intel
echo.
echo Kartu grafis Intel Arc terdeteksi. Memasang PyTorch versi Intel GPU, sekali saja...
pip uninstall -y torch >nul 2>nul
pip install torch --index-url https://download.pytorch.org/whl/xpu && exit /b 0
goto gpu_fail

:gpu_amd
echo.
echo Kartu grafis AMD terdeteksi. Memasang DirectML supaya AI bisa memakai GPU, sekali saja...
pip install torch-directml && exit /b 0
goto gpu_fail

:gpu_fail
echo Pendukung GPU gagal dipasang. Memakai CPU, robot tetap jalan.
pip install --upgrade torch
exit /b 0