"""Mengunduh kode Kronos dari GitHub ke folder ./Kronos (tanpa perlu git).
Dikunci ke versi yang sudah diperiksa agar bot tidak rusak jika repo berubah."""
import io
import shutil
import urllib.request
import zipfile
from pathlib import Path

COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
URL = f"https://github.com/shiyu-coder/Kronos/archive/{COMMIT}.zip"
DEST = Path(__file__).resolve().parent / "Kronos"

if (DEST / "model" / "kronos.py").exists():
    print(f"Kronos sudah ada di {DEST}")
else:
    print(f"Mengunduh Kronos ({COMMIT[:7]})...")
    data = urllib.request.urlopen(URL, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = z.namelist()[0].split("/")[0]
        tmp = DEST.parent / "_kronos_tmp"
        z.extractall(tmp)
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.move(str(tmp / root), str(DEST))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Selesai: {DEST}")
