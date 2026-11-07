"""Ramalan Kronos -> sinyal angka yang bisa diputuskan oleh strategi."""
import logging
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import KRONOS_DIR

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


class KronosForecaster:
    """Membungkus KronosPredictor. Menghasilkan beberapa skenario (path) sekaligus."""

    def __init__(self, mcfg: dict):
        if not (KRONOS_DIR / "model").exists():
            raise SystemExit(f"Folder Kronos tidak ditemukan di {KRONOS_DIR}. Jalankan setup dulu.")
        sys.path.insert(0, str(KRONOS_DIR))
        from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

        device = mcfg.get("device", "auto")
        device = None if device in (None, "auto") else device
        t0 = time.time()
        log.info("Memuat model %s (pertama kali akan mengunduh dari Hugging Face)...", mcfg["name"])
        tokenizer = KronosTokenizer.from_pretrained(mcfg["tokenizer"])
        model = Kronos.from_pretrained(mcfg["name"])
        tokenizer.eval()
        model.eval()
        self.predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
        log.info("Model siap di %s (%.1f detik)", self.predictor.device, time.time() - t0)
        self.cfg = mcfg

    def paths(self, hist: pd.DataFrame, y_ts: pd.Series) -> np.ndarray:
        """Return array (n_paths, pred_len, 4) berisi open/high/low/close tiap skenario."""
        n = int(self.cfg.get("n_paths", 10))
        pred_len = len(y_ts)
        x = hist[COLS].reset_index(drop=True)
        xt = hist["timestamps"].reset_index(drop=True)
        yt = pd.Series(y_ts).reset_index(drop=True)
        outs = self.predictor.predict_batch(
            df_list=[x] * n, x_timestamp_list=[xt] * n, y_timestamp_list=[yt] * n,
            pred_len=pred_len, T=float(self.cfg.get("temperature", 1.0)),
            top_p=float(self.cfg.get("top_p", 0.9)), sample_count=1, verbose=False,
        )
        return np.stack([o[["open", "high", "low", "close"]].to_numpy(dtype=float) for o in outs])


class DummyForecaster:
    """Ramalan acak (random walk) untuk uji coba alur bot TANPA model. Bukan untuk trading."""

    def __init__(self, mcfg: dict, seed: int | None = None):
        self.cfg = mcfg
        self.rng = np.random.default_rng(seed)
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


def make_forecaster(cfg: dict, dummy: bool = False):
    return DummyForecaster(cfg["model"]) if dummy else KronosForecaster(cfg["model"])


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
    exp_ret = float(rets.mean() * 100)
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
    )
