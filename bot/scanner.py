"""
Scanner pasar: cari pair yang sedang bergerak dan punya peluang paling bagus di SELURUH pasar,
bukan hanya watchlist.

Dua tahap:
  1. Saring teknikal cepat untuk semua pair (tanpa AI): tren, momentum yang dinormalkan volatilitas,
     kerapian gerak (efficiency ratio), breakout, lonjakan volume, RSI, dan biaya dibanding gerakan.
  2. Kandidat teratas diramal Kronos (dibatch, cepat dengan GPU): peluang skenario searah,
     perkiraan gerakan setelah biaya, dan rapor akurasi bila ada.

Skor 0-100 hanya untuk mengurutkan. Peluang yang ditampilkan adalah porsi skenario AI,
bukan jaminan. Rapor akurasi dari Backtest menunjukkan seberapa bisa dipercaya untuk pair itu.
"""
import math

import numpy as np
import pandas as pd

from .indicators import ema, rsi

TF_SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}

FX_UNIVERSE = [
    # mayor
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    # silang
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD", "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF", "CHFJPY",
    # logam
    "XAUUSD", "XAGUSD",
]
FX_MAJORS = FX_UNIVERSE[:7] + ["XAUUSD"]
STABLES = {"USDC", "FDUSD", "TUSD", "DAI", "BUSD", "USDP", "USDE", "PYUSD", "EUR", "TRY", "BIDR", "IDRT", "AEUR", "XUSD", "USD1"}


# ===================================================================== universe
def crypto_universe(data, quote="USDT", top=60, min_quote_vol=200_000):
    """Pair kripto teramai (volume 24 jam). Return list dict {symbol, quote_volume, change_pct}."""
    tick = data.tickers()
    rows = []
    for sym, t in tick.items():
        if not sym.endswith("/" + quote):
            continue
        base = sym.split("/")[0]
        if base in STABLES or base.endswith(("UP", "DOWN", "BULL", "BEAR")):
            continue
        qv = t.get("quote_volume") or 0
        if qv < min_quote_vol:
            continue
        rows.append({"symbol": sym, "quote_volume": float(qv), "change_pct": t.get("change_pct")})
    rows.sort(key=lambda r: r["quote_volume"], reverse=True)
    return rows[:top]


def forex_universe(data, size="all"):
    names = FX_MAJORS if size == "majors" else FX_UNIVERSE
    if getattr(data, "source", "") == "mt5":
        from .forex import clean
        broker = {clean(s)[:6]: s for s in data.pairs()}
        return [{"symbol": broker[n]} for n in names if n in broker]
    return [{"symbol": n} for n in names]


# ===================================================================== tahap 1: teknikal
def _sig(x):
    return 0.5 + 0.5 * math.tanh(x)


def technical(df: pd.DataFrame, tf: str, fee_pct: float, venue: str, horizon: int = 12) -> dict | None:
    if df is None or len(df) < 120:
        return None
    c, h, lo, v = (df[k].to_numpy(float) for k in ("close", "high", "low", "volume"))
    n = len(c)
    per_day = max(1, 86400 // TF_SEC.get(tf, 3600))
    d1, d7 = min(per_day, n - 1), min(per_day * 7, n - 1)
    ret_1d = (c[-1] / c[-1 - d1] - 1) * 100
    ret_7d = (c[-1] / c[-1 - d7] - 1) * 100
    tr = np.maximum(h[1:], c[:-1]) - np.minimum(lo[1:], c[:-1])
    atr_pct = float(pd.Series(tr).rolling(14).mean().iloc[-1] / c[-1] * 100)
    if not atr_pct or math.isnan(atr_pct):
        return None
    cs = pd.Series(c)
    e50, e200 = ema(cs, 50), ema(cs, min(200, n - 1))
    slope = (e50.iloc[-1] / e50.iloc[-11] - 1) * 100 if n > 11 else 0.0
    trend = 1 if (c[-1] > e50.iloc[-1] > e200.iloc[-1] and slope > 0) else \
        -1 if (c[-1] < e50.iloc[-1] < e200.iloc[-1] and slope < 0) else 0
    r = float(rsi(cs).iloc[-1])
    k = min(48, n - 1)
    path = np.abs(np.diff(c[-k - 1:])).sum()
    er = float(abs(c[-1] - c[-k - 1]) / path) if path else 0.0
    move_dir = 1 if c[-1] > c[-k - 1] else -1
    hi50, lo50 = h[-50:].max(), lo[-50:].min()
    brk_up = c[-1] >= hi50 * (1 - 0.15 * atr_pct / 100)
    brk_dn = c[-1] <= lo50 * (1 + 0.15 * atr_pct / 100)
    vol_ratio = None
    if v[-d7:].sum() > 0 and d7 > d1:
        prior = v[-d7:-d1].mean()
        vol_ratio = float(v[-d1:].mean() / prior) if prior > 0 else None
    z7 = ret_7d / (atr_pct * math.sqrt(max(1, d7)))
    move_h = atr_pct * math.sqrt(horizon)          # gerak wajar dalam horizon ramalan
    cost_ratio = 2 * fee_pct / move_h if move_h else 9.0

    def side_score(sgn):
        trend_s = 1.0 if trend == sgn else (0.45 if trend == 0 and slope * sgn > 0 else 0.0 if trend == -sgn else 0.25)
        mom = _sig(z7 * sgn * 1.5)
        er_s = er if move_dir == sgn else 0.0
        rsi_ok = (1.0 if r < 68 else 0.35) if sgn > 0 else (1.0 if r > 32 else 0.35)
        brk = 1.0 if (brk_up if sgn > 0 else brk_dn) else 0.0
        parts = [(0.30, trend_s), (0.25, mom), (0.15, er_s), (0.10, rsi_ok), (0.10, brk)]
        if vol_ratio is not None:
            vs = max(0.0, min(1.0, (vol_ratio - 1) / 1.5)) if move_dir == sgn else 0.0
            parts.append((0.10, vs))
        sc = sum(w * x for w, x in parts) / sum(w for w, _ in parts)
        if cost_ratio > 0.5:
            sc *= 0.6
        return float(sc)

    long_s = side_score(1)
    short_s = side_score(-1) if venue == "forex" else 0.0
    side = "long" if long_s >= short_s else "short"
    best = max(long_s, short_s)
    sgn = 1 if side == "long" else -1
    tags = []
    if trend == sgn:
        tags.append("Strong trend" if er > 0.35 else "Trend")
    if (brk_up if sgn > 0 else brk_dn):
        tags.append("Breakout" if sgn > 0 else "Breakdown")
    if vol_ratio and vol_ratio >= 1.5 and move_dir == sgn:
        tags.append(f"Volume ×{vol_ratio:.1f}")
    if (sgn > 0 and r >= 70) or (sgn < 0 and r <= 30):
        tags.append("Overextended")
    if er < 0.15:
        tags.append("Choppy")
    if cost_ratio > 0.5:
        tags.append("Costly vs move")
    return {
        "price": float(c[-1]), "ret_1d": float(ret_1d), "ret_7d": float(ret_7d), "atr_pct": atr_pct,
        "day_move_pct": float(atr_pct * math.sqrt(per_day)), "trend": trend, "rsi": r, "er": er,
        "vol_ratio": vol_ratio, "cost_ratio": float(cost_ratio), "long": long_s, "short": short_s,
        "side": side, "tech": best, "tags": tags,
        "spark": [float(x) for x in c[-min(n, per_day * 3):]][-72:],
    }


# ===================================================================== tahap 2: gabung AI
def combine(row: dict, sig, fee_pct: float, acc: dict | None, venue: str) -> dict:
    """Tambahkan hasil AI ke baris teknikal dan hitung skor akhir."""
    t = row["tech_detail"]
    if sig is None:
        row.update(score=round(t["tech"] * 100), ai=None)
        return row
    h = max(1, sig.horizon)
    move_h = max(1e-9, t["atr_pct"] * math.sqrt(h))
    best = None
    for side in (("long", "short") if venue == "forex" else ("long",)):
        sgn = 1 if side == "long" else -1
        p = sig.prob_up if sgn > 0 else sig.prob_down
        exp = sig.exp_ret_pct * sgn
        net = exp - 2 * fee_pct
        edge = max(0.0, min(1.0, 0.5 + net / (2 * move_h)))
        tech = t["long"] if sgn > 0 else t["short"]
        sc = 0.45 * p + 0.30 * tech + 0.25 * edge
        if best is None or sc > best[0]:
            best = (sc, side, p, exp, net)
    sc, side, p, exp, net = best
    flags = []
    if acc and acc.get("n", 0) >= 30 and acc.get("hit") is not None and acc["hit"] < 0.5:
        sc *= 0.8
        flags.append("AI often wrong here")
    if net <= 0:
        flags.append("Move too small after costs")
    row.update(score=round(sc * 100), side=side, ai={
        "prob": p, "exp_ret_pct": sig.exp_ret_pct, "gain_pct": exp, "net_pct": net, "horizon": h,
        "upside_pct": sig.upside_pct, "downside_pct": sig.downside_pct,
        "prob_up": sig.prob_up, "prob_down": sig.prob_down, "direction": sig.direction,
    }, accuracy=(acc or {}).get("hit"), acc_n=(acc or {}).get("n", 0), flags=flags)
    return row
