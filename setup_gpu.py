"""
Siapkan kartu grafis (VGA) untuk AI. Dijalankan otomatis oleh MULAI (sekali), atau ulang lewat panel.

Urutan yang dicoba, sesuai kartu grafis yang terdeteksi:
  NVIDIA            -> PyTorch CUDA
  Intel Arc / Core Ultra -> PyTorch XPU, kalau gagal DirectML
  Intel UHD / Iris  -> DirectML
  AMD Radeon        -> DirectML (Windows) / ROCm (Linux)
  kartu lain (Windows, DirectX 12) -> DirectML
  Mac M1-M4         -> Metal, tidak perlu dipasang apa-apa

Tiap pilihan dites dengan operasi yang dipakai model AI. Kalau tes gagal, dicoba pilihan berikutnya,
dan kalau semua gagal robot tetap memakai CPU. Hasilnya ditulis ke .venv/gpu_setup.json supaya panel
bisa menampilkan apa yang terjadi.
"""
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / ".venv" / "gpu_setup.json"
PY = sys.executable
TEST = r"""
import sys, torch
kind = sys.argv[1]
if kind == "dml":
    import torch_directml
    dev = torch_directml.device(0)
elif kind == "xpu":
    assert torch.xpu.is_available(), "torch.xpu tidak tersedia"
    dev = torch.device("xpu")
elif kind == "cuda":
    assert torch.cuda.is_available(), "torch.cuda tidak tersedia"
    dev = torch.device("cuda:0")
elif kind == "mps":
    dev = torch.device("mps")
x = torch.randn(64, 128, 256, device=dev)
w = torch.randn(256, 256, device=dev)
y = torch.nn.functional.layer_norm(x @ w, (256,))
q = y.view(64, 4, 128, 64)
a = torch.softmax(q @ q.transpose(-1, -2) / 8.0, dim=-1) @ q
p = torch.softmax(a.mean(dim=(1, 2)), dim=-1)
s = torch.multinomial(p, 1)
emb = torch.nn.Embedding(1024, 32).to(dev)
e = emb(s.clamp(max=1023))
print("OK", float(a.sum().cpu()), int(s.sum().cpu()), tuple(e.shape))
"""


def log(msg):
    print(msg, flush=True)


def gpus() -> list[str]:
    names = []
    try:
        if platform.system() == "Windows":
            for cmd in (["powershell", "-NoProfile", "-Command",
                         "(Get-CimInstance Win32_VideoController).Name"],
                        ["wmic", "path", "win32_VideoController", "get", "name"]):
                try:
                    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
                except Exception:  # noqa: BLE001
                    continue
                names = [x.strip() for x in out.splitlines() if x.strip() and x.strip().lower() != "name"]
                if names:
                    break
        elif platform.system() == "Linux":
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10).stdout
            names = [ln.split(": ", 1)[-1] for ln in out.splitlines() if " VGA " in ln or "3D controller" in ln]
        elif platform.system() == "Darwin":
            names = ["Apple GPU"] if platform.machine() == "arm64" else []
    except Exception:  # noqa: BLE001
        pass
    return [n for n in names if not any(k in n for k in ("Basic Display", "Remote Display", "Virtual", "VMware",
                                                          "Parsec", "Meta Virtual", "Citrix"))]


def vendor(n: str) -> str:
    n = n.lower()
    if any(k in n for k in ("nvidia", "geforce", "rtx", "quadro", "tesla")):
        return "nvidia"
    if any(k in n for k in ("amd", "radeon", "advanced micro")):
        return "amd"
    if "intel" in n or " arc" in n or n.startswith("arc"):
        return "intel"
    if "apple" in n:
        return "apple"
    return "other"


def pip(*args) -> bool:
    cmd = [PY, "-m", "pip", "install", "--disable-pip-version-check", *args]
    log("  > pip install " + " ".join(args))
    return subprocess.run(cmd).returncode == 0


def pip_uninstall(*pk):
    subprocess.run([PY, "-m", "pip", "uninstall", "-y", *pk], capture_output=True)


def test(kind: str) -> tuple[bool, str]:
    r = subprocess.run([PY, "-c", TEST, kind], capture_output=True, text=True, timeout=600)
    out = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0 and "OK" in r.stdout
    return ok, out.splitlines()[-1][:300] if out else ""


def torch_info():
    r = subprocess.run([PY, "-c", "import torch;print(torch.__version__)"], capture_output=True, text=True)
    return r.stdout.strip() or None


def plans(names: list[str]) -> list[tuple[str, str]]:
    """(jenis, cara pasang) dari yang terbaik."""
    pyver = sys.version_info[:2]
    sysname = platform.system()
    out = []
    vs = [vendor(n) for n in names]
    if sysname == "Darwin":
        return [("mps", "none")]
    if "nvidia" in vs:
        tag = "cu128" if any("RTX 50" in n.upper() for n in names) else "cu126"
        out.append(("cuda", tag))
    if "intel" in vs:
        if any(("arc" in n.lower()) or ("ultra" in n.lower()) for n in names):
            out.append(("xpu", "xpu"))
    if sysname == "Linux" and "amd" in vs:
        out.append(("cuda", "rocm6.3"))
    if sysname == "Windows" and names:
        if pyver <= (3, 12):
            out.append(("dml", "directml"))
        else:
            out.append(("dml", "py313"))
    return out


def main():
    t0 = time.time()
    names = gpus()
    res = {"time": time.strftime("%Y-%m-%d %H:%M"), "os": platform.system(), "python": platform.python_version(),
           "gpus": names, "tried": [], "chosen": "cpu", "ok": False, "message": ""}
    log(f"Kartu grafis terdeteksi: {', '.join(names) if names else 'tidak ada'}")
    todo = plans(names)
    if not todo:
        res["message"] = "Tidak ada kartu grafis yang bisa dipakai. Robot memakai CPU."
    for kind, how in todo:
        if kind == "mps":
            ok, out = test("mps")
            res["tried"].append({"kind": kind, "ok": ok, "detail": out})
            if ok:
                res.update(chosen="mps", ok=True, message="GPU Apple (Metal) siap dipakai.")
                break
            continue
        if how == "py313":
            res["tried"].append({"kind": kind, "ok": False,
                                 "detail": f"DirectML belum tersedia untuk Python {platform.python_version()}. "
                                           "Install Python 3.12 dari python.org, hapus folder .venv, lalu jalankan MULAI lagi."})
            continue
        # sudah jalan? (mis. dari pemasangan sebelumnya)
        ok, out = test(kind)
        if not ok:
            log(f"\nMenyiapkan {kind.upper()} untuk {', '.join(names)} (sekali saja, bisa beberapa menit)...")
            if kind == "dml":
                installed = pip("torch-directml")
            else:
                pip_uninstall("torch-directml", "torch")
                installed = pip("torch", "--index-url", f"https://download.pytorch.org/whl/{how}")
            ok, out = test(kind) if installed else (False, "pemasangan gagal (cek internet)")
        res["tried"].append({"kind": kind, "ok": ok, "detail": out})
        log(f"  tes {kind}: {'berhasil' if ok else 'gagal'} {'' if ok else out}")
        if ok:
            res.update(chosen=kind, ok=True, message=f"Kartu grafis siap dipakai lewat {kind.upper()}.")
            break
        if kind == "dml":
            pip_uninstall("torch-directml")
    if not res["ok"]:
        # pastikan PyTorch masih bisa jalan di CPU
        if subprocess.run([PY, "-c", "import torch; torch.randn(2,2)@torch.randn(2,2)"], capture_output=True).returncode:
            pip("--upgrade", "torch")
        if todo and not res["message"]:
            last = next((t["detail"] for t in reversed(res["tried"]) if t.get("detail")), "")
            res["message"] = "Kartu grafis belum bisa dipakai" + (f": {last}" if last else ".") + \
                (" " if last.endswith(".") else ". ") + "Robot tetap jalan dengan CPU."
    res["torch"] = torch_info()
    res["seconds"] = round(time.time() - t0)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    log(res["message"])


if __name__ == "__main__":
    main()
