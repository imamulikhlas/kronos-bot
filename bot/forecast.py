"""Ramalan Kronos -> sinyal angka yang bisa diputuskan oleh strategi."""
import logging
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import KRONOS_DIR, ROOT

log = logging.getLogger("forecast")
COLS = ["open", "high", "low", "close", "volume", "amount"]


@dataclass
class Signal:
    time: str                 # waktu candle terakhir (WIB)
    symbol: str
    last_close: float
    exp_ret_pct: float        # rata-rata perubahan close di akhir horizon (%)
    median_ret_pct: float
    prob_up: float            # porsi skenario yang berakhir di atas harga + biaya
    pred_high: float          # median harga tertinggi yang diramal
    pred_low: float           # median harga terendah yang diramal
    path: list = field(default_factory=list)      # median jalur close ke depan
    path_lo: list = field(default_factory=list)   # skenario buruk (persentil 10)
    path_hi: list = field(default_factory=list)   # skenario baik (persentil 90)
    trend_up: bool = True     # harga di atas EMA tren dan EMA menanjak
    rsi: float = 50.0
    atr_pct: float = 0.0      # volatilitas rata-rata per candle (%)
    upside_pct: float = 0.0   # potensi naik (median harga tertinggi)
    downside_pct: float = 0.0  # potensi turun (median harga terendah)
    rr: float = 0.0           # potensi naik : potensi turun (untuk buy)
    score: float = 0.0        # kekuatan sinyal naik = ekspektasi x peluang naik
    prob_down: float = 0.0    # porsi skenario yang berakhir di bawah harga - biaya
    trend_down: bool = False
    rr_short: float = 0.0     # potensi turun : potensi naik (untuk sell)
    horizon: int = 0          # jumlah candle yang diramal
    prob_up_raw: float = 0.5  # porsi skenario yang berakhir di atas harga sekarang (tanpa biaya)
    accuracy: float | None = None  # akurasi arah ramalan di pasar ini (0..1)
    acc_n: int = 0            # jumlah ramalan yang sudah dinilai

    @property
    def direction(self) -> str:
        thr = max(0.02, 0.3 * self.atr_pct)
        if self.exp_ret_pct > thr and self.prob_up >= 0.55:
            return "NAIK"
        if self.exp_ret_pct < -thr and self.prob_down >= 0.55:
            return "TURUN"
        return "SAMPING"

    def summary(self) -> str:
        acc = f"akurasi {self.accuracy:.0%}/{self.acc_n}" if self.accuracy is not None else "akurasi -"
        return (f"{self.symbol} {self.last_close:,.6g} | {self.direction} {self.exp_ret_pct:+.2f}% "
                f"| naik {self.prob_up:.0%} turun {self.prob_down:.0%} | R:R {self.rr:.1f}/{self.rr_short:.1f} "
                f"| RSI {self.rsi:.0f} | {acc}")


def os_gpus() -> list[str]:
    """Nama kartu grafis menurut sistem operasi (terlepas dari PyTorch)."""
    import platform
    import shutil
    import subprocess
    names = []
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                                 capture_output=True, text=True, timeout=15).stdout
            names = [x.strip() for x in out.splitlines() if x.strip()]
        elif platform.system() == "Linux" and shutil.which("lspci"):
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10).stdout
            names = [ln.split(": ", 1)[-1] for ln in out.splitlines() if " VGA " in ln or "3D controller" in ln]
    except Exception:  # noqa: BLE001
        pass
    return [n for n in names if not any(k in n for k in ("Basic Display", "Remote Display", "Virtual", "VMware"))]


def gpu_vendor(name: str) -> str:
    n = (name or "").lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "quadro" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n or "advanced micro" in n:
        return "amd"
    if "intel" in n or " arc" in n or "iris" in n:
        return "intel"
    if "apple" in n:
        return "apple"
    return "other"


def _dml():
    try:
        import torch_directml  # noqa: F401
        return torch_directml if torch_directml.device_count() > 0 else None
    except Exception:  # noqa: BLE001
        return None


def system_info() -> dict:
    """GPU yang bisa dipakai PyTorch: NVIDIA/AMD (CUDA/ROCm), Intel (XPU), Apple (Metal),
    atau GPU apa saja di Windows lewat DirectML."""
    import os
    import platform
    info = {"torch": None, "gpu": None, "vram_gb": None, "backend": None, "best": "cpu",
            "cpu": platform.processor() or platform.machine(), "threads": os.cpu_count() or 1,
            "os": platform.system(), "os_gpus": os_gpus()}
    try:
        import torch
        info["torch"] = torch.__version__
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            rocm = bool(getattr(torch.version, "hip", None))
            info.update(gpu=p.name, vram_gb=round(p.total_memory / 1024 ** 3, 1), best="cuda",
                        backend="ROCm" if rocm else "CUDA")
        elif hasattr(torch, "xpu") and torch.xpu.is_available():
            info.update(gpu=torch.xpu.get_device_name(0), best="xpu", backend="Intel XPU")
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            info.update(gpu="Apple GPU", best="mps", backend="Metal")
        else:
            dml = _dml()
            if dml is not None:
                info.update(gpu=dml.device_name(0), best="dml", backend="DirectML")
    except Exception as e:  # noqa: BLE001
        info["error"] = str(e)
    real = [g for g in info["os_gpus"] if gpu_vendor(g) != "apple" or info["best"] == "cpu"]
    info["gpu_unused"] = bool(real) and info["best"] == "cpu"
    info["gpu_unused_name"] = real[0] if info["gpu_unused"] else None
    try:
        import json
        f = ROOT / ".venv" / "gpu_setup.json"
        info["setup"] = json.loads(f.read_text()) if f.exists() else None
    except Exception:  # noqa: BLE001
        info["setup"] = None
    if info["best"] != "cpu":
        try:
            import torch  # noqa: F401
            dev = resolve_device("gpu")
            if dev == "cpu":
                info.update(best="cpu", gpu_broken=info["gpu"], gpu=None, backend=None, gpu_unused=True,
                            gpu_unused_name=info["gpu"])
        except Exception:  # noqa: BLE001
            pass
    return info


_ok_cache: dict = {}


def _works(dev) -> bool:
    """Tes kecil: apakah device ini bisa menjalankan operasi yang dipakai model."""
    key = str(dev)
    if key in _ok_cache:
        return _ok_cache[key]
    try:
        import torch
        x = torch.randn(8, 16, 32, device=dev)
        y = torch.nn.functional.layer_norm(x @ torch.randn(32, 32, device=dev), (32,))
        p = torch.softmax(y.mean(dim=1), dim=-1)
        torch.multinomial(p, 1).sum().item()
        ok = True
    except Exception as e:  # noqa: BLE001
        log.warning("GPU %s tidak bisa dipakai: %s", key, str(e).splitlines()[0][:200])
        ok = False
    _ok_cache[key] = ok
    return ok


def gpu_candidates() -> list:
    """Semua device GPU yang terpasang di PyTorch, dari yang biasanya paling cepat."""
    import torch
    out = []
    if torch.cuda.is_available():
        out.append("cuda:0")
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        out.append("xpu")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        out.append("mps")
    dml = _dml()
    if dml is not None:
        out.append(dml.device(0))
    return out


def resolve_device(pref: str | None):
    """'auto' | 'gpu' | 'cpu' -> device PyTorch terbaik yang benar-benar jalan."""
    pref = (pref or "auto").lower()
    if pref == "cpu":
        return "cpu"
    cands = gpu_candidates()
    if pref not in ("auto", "gpu"):
        for dev in cands:
            if str(dev) == pref and _works(dev):
                return dev
    for dev in cands:
        if _works(dev):
            return dev
    if pref == "gpu":
        log.warning("GPU diminta tetapi tidak ada yang bisa dipakai PyTorch, memakai CPU.")
    return "cpu"


def device_kind(device) -> str:
    d = str(device)
    return "cuda" if d.startswith("cuda") else "xpu" if d.startswith("xpu") else \
        "mps" if d == "mps" else "dml" if d.startswith("privateuseone") else "cpu"


def default_batch(device) -> int:
    """Berapa titik waktu diramal sekaligus (x n_paths skenario)."""
    kind = device_kind(device)
    if kind == "cuda":
        try:
            import torch
            vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
        except Exception:  # noqa: BLE001
            vram = 4
        return 64 if vram >= 16 else 32 if vram >= 8 else 16
    return {"xpu": 16, "mps": 8, "dml": 8}.get(kind, 2)


def ensemble_lookbacks(lookback: int, on: bool) -> list[int]:
    """Ensemble: skenario dibagi ke beberapa panjang riwayat supaya ramalan tidak bergantung pada satu jendela."""
    if not on:
        return [lookback]
    out = [lookback, int(lookback * 0.75), int(lookback * 0.5)]
    return [x for x in dict.fromkeys(max(64, x) for x in out)]


class KronosForecaster:
    """Membungkus KronosPredictor. Menghasilkan beberapa skenario (path) sekaligus."""

    def __init__(self, mcfg: dict, device: str | None = None):
        if not (KRONOS_DIR / "model").exists():
            raise SystemExit(f"Folder Kronos tidak ditemukan di {KRONOS_DIR}. Jalankan setup dulu.")
        sys.path.insert(0, str(KRONOS_DIR))
        import torch
        from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

        self.device = resolve_device(device or mcfg.get("device", "auto"))
        self.kind = device_kind(self.device)
        t0 = time.time()
        log.info("Memuat model %s (pertama kali akan mengunduh dari Hugging Face)...", mcfg["name"])
        self._tok = KronosTokenizer.from_pretrained(mcfg["tokenizer"])
        self._model = Kronos.from_pretrained(mcfg["name"])
        self._tok.eval()
        self._model.eval()
        self._ctx = 2048 if "mini" in mcfg["name"] else 512
        self._Pred = KronosPredictor
        self.predictor = KronosPredictor(self._model, self._tok, device=self.device, max_context=self._ctx)
        if self.kind == "cuda":
            name = f"GPU {torch.cuda.get_device_name(0)}"
        elif self.kind == "xpu":
            name = f"GPU {torch.xpu.get_device_name(0)}"
        elif self.kind == "mps":
            name = "GPU Apple (Metal)"
        elif self.kind == "dml":
            name = f"GPU {_dml().device_name(0)} (DirectML)"
        else:
            name = f"CPU ({torch.get_num_threads()} thread)"
        self.device_name = name
        log.info("Model siap di %s (%.1f detik)", name, time.time() - t0)
        self.cfg = mcfg

    def _to_cpu(self, err):
        """GPU gagal (operasi tidak didukung / memori habis): lanjut di CPU, tidak berhenti."""
        import torch
        log.warning("GPU gagal (%s). Pindah ke CPU.", str(err).splitlines()[0][:200])
        self.device, self.kind = "cpu", "cpu"
        self.device_name = f"CPU ({torch.get_num_threads()} thread, GPU gagal)"
        self.predictor = self._Pred(self._model.cpu(), self._tok.cpu(), device="cpu", max_context=self._ctx)

    def _run(self, dfs, xts, yts):
        import torch
        ctx = torch.no_grad() if self.kind == "dml" else torch.inference_mode()
        with ctx:
            return self.predictor.predict_batch(
                df_list=dfs, x_timestamp_list=xts, y_timestamp_list=yts,
                pred_len=len(yts[0]), T=float(self.cfg.get("temperature", 1.0)),
                top_p=float(self.cfg.get("top_p", 0.9)), sample_count=1, verbose=False,
            )

    def paths_many(self, items: list) -> list:
        """items: [(hist, y_ts), ...]. Return list array (n_paths, pred_len, 4) per item."""
        n = int(self.cfg.get("n_paths", 10))
        lbs = ensemble_lookbacks(min(len(h) for h, _ in items), bool(self.cfg.get("ensemble")))
        per = n if len(lbs) == 1 else max(4, -(-n // len(lbs)))
        result = [[] for _ in items]
        for lb in lbs:
            dfs, xts, yts = [], [], []
            for hist, y_ts in items:
                h = hist.tail(lb).reset_index(drop=True)
                dfs += [h[COLS]] * per
                xts += [h["timestamps"]] * per
                yts += [pd.Series(y_ts).reset_index(drop=True)] * per
            try:
                outs = self._run(dfs, xts, yts)
            except Exception as e:  # noqa: BLE001
                if self.kind == "cpu":
                    raise
                self._to_cpu(e)
                outs = self._run(dfs, xts, yts)
            arr = np.stack([o[["open", "high", "low", "close"]].to_numpy(dtype=float) for o in outs])
            for i in range(len(items)):
                result[i].append(arr[i * per:(i + 1) * per])
        return [np.concatenate(r, axis=0) for r in result]

    def paths(self, hist: pd.DataFrame, y_ts: pd.Series) -> np.ndarray:
        """Return array (n_paths, pred_len, 4) berisi open/high/low/close tiap skenario."""
        return self.paths_many([(hist, y_ts)])[0]


class DummyForecaster:
    """Ramalan acak (random walk) untuk uji coba alur bot TANPA model. Bukan untuk trading."""

    def __init__(self, mcfg: dict, seed: int | None = None, device: str | None = None):
        self.cfg = mcfg
        self.rng = np.random.default_rng(seed)
        self.device = "cpu"
        self.device_name = "CPU (ramalan acak)"
        log.warning("MODE DUMMY: ramalan acak, hanya untuk menguji alur program.")

    def paths(self, hist: pd.DataFrame, y_ts: pd.Series) -> np.ndarray:
        n, h = int(self.cfg.get("n_paths", 10)), len(y_ts)
        rets = np.log(hist["close"]).diff().dropna().tail(200)
        vol = float(rets.std() or 0.01)
        last = float(hist["close"].iloc[-1])
        steps = self.rng.normal(0, vol, size=(n, h))
        close = last * np.exp(np.cumsum(steps, axis=1))
        openp = np.concatenate([np.full((n, 1), last), close[:, :-1]], axis=1)
        wig = np.abs(self.rng.normal(0, vol / 2, size=(n, h)))
        high = np.maximum(openp, close) * (1 + wig)
        low = np.minimum(openp, close) * (1 - wig)
        return np.stack([openp, high, low, close], axis=2)

    def paths_many(self, items: list) -> list:
        return [self.paths(h, y) for h, y in items]


def make_forecaster(cfg: dict, dummy: bool = False, device: str | None = None):
    return DummyForecaster(cfg["model"]) if dummy else KronosForecaster(cfg["model"], device)


def build_signal(symbol: str, hist: pd.DataFrame, paths: np.ndarray, fee_pct: float,
                 trend_period: int = 200) -> Signal:
    from .indicators import snapshot
    last = float(hist["close"].iloc[-1])
    final = paths[:, -1, 3]
    rets = final / last - 1
    hurdle = 2 * fee_pct / 100  # harus bergerak melebihi biaya buka + tutup
    hi = float(np.median(paths[:, :, 1].max(axis=1)))
    lo = float(np.median(paths[:, :, 2].min(axis=1)))
    up = max(0.0, (hi / last - 1) * 100)
    down = max(0.0, (1 - lo / last) * 100)
    srt = np.sort(rets)
    cut = len(srt) // 10 if len(srt) >= 10 else 0
    exp_ret = float(srt[cut:len(srt) - cut].mean() * 100)   # rata-rata terpangkas: tahan skenario ekstrem
    snap = snapshot(hist, trend_period)
    closes = paths[:, :, 3]
    return Signal(
        time=str(hist["timestamps"].iloc[-1]), symbol=symbol, last_close=last,
        exp_ret_pct=exp_ret, median_ret_pct=float(np.median(rets) * 100),
        prob_up=float((rets > hurdle).mean()), prob_down=float((rets < -hurdle).mean()),
        pred_high=hi, pred_low=lo,
        path=[float(v) for v in np.median(closes, axis=0)],
        path_lo=[float(v) for v in np.percentile(closes, 10, axis=0)],
        path_hi=[float(v) for v in np.percentile(closes, 90, axis=0)],
        trend_up=snap["trend_up"], trend_down=snap["trend_down"], rsi=snap["rsi"], atr_pct=snap["atr_pct"],
        upside_pct=up, downside_pct=down, rr=up / max(down, 1e-6), rr_short=down / max(up, 1e-6),
        score=exp_ret * float((rets > hurdle).mean()), horizon=int(paths.shape[1]),
        prob_up_raw=float((rets > 0).mean() + 0.5 * (rets == 0).mean()),
    )
