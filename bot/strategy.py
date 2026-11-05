"""Aturan keputusan. Dipakai SAMA PERSIS oleh robot (paper/live) dan uji strategi.

Hanya LONG di spot: beli lalu jual. Tidak ada short/leverage.
Nilai default di sini dipakai jika config.yaml lama belum punya pengaturan baru.
"""
from .forecast import Signal

DEFAULTS = {
    "trend_filter": True,      # hanya beli saat tren naik
    "trend_period": 200,       # panjang EMA tren (candle)
    "rsi_max": 75,             # jangan beli saat RSI di atas ini (jenuh beli)
    "min_rr": 1.2,             # minimal rasio potensi naik : potensi turun
    "sl_mode": "persen",       # persen | atr
    "sl_atr_mult": 2.0,
    "tp_atr_mult": 4.0,
    "trailing_on": True,
    "trail_activate_pct": 1.5,  # trailing aktif setelah untung sekian %
    "trail_pct": 1.0,           # jarak trailing stop dari harga tertinggi
}


def opt(s: dict, key):
    return s.get(key, DEFAULTS[key])


def entry_decision(sig: Signal, s: dict) -> tuple[bool, str]:
    """Apakah sinyal cukup kuat untuk membeli? Mengembalikan (boleh, alasan)."""
    if sig.exp_ret_pct < s["min_expected_return_pct"]:
        return False, f"ramalan {sig.exp_ret_pct:+.2f}% < {s['min_expected_return_pct']}%"
    if sig.prob_up < s["min_prob_up"]:
        return False, f"peluang naik {sig.prob_up:.0%} < {s['min_prob_up']:.0%}"
    if opt(s, "trend_filter") and not sig.trend_up:
        return False, "tren sedang turun"
    if sig.rsi > opt(s, "rsi_max"):
        return False, f"jenuh beli (RSI {sig.rsi:.0f})"
    if sig.rr < opt(s, "min_rr"):
        return False, f"rasio untung:rugi {sig.rr:.1f} < {opt(s, 'min_rr')}"
    return True, f"ramalan {sig.exp_ret_pct:+.2f}%, peluang naik {sig.prob_up:.0%}, R:R {sig.rr:.1f}"


def exit_levels(entry: float, sig: Signal | None, s: dict) -> tuple[float, float]:
    """Harga stop-loss dan take-profit saat membeli."""
    if opt(s, "sl_mode") == "atr" and sig is not None and sig.atr_pct > 0:
        sl_pct = sig.atr_pct * opt(s, "sl_atr_mult")
        tp_pct = sig.atr_pct * opt(s, "tp_atr_mult")
    else:
        sl_pct, tp_pct = s["stop_loss_pct"], s["take_profit_pct"]
    return entry * (1 - sl_pct / 100), entry * (1 + tp_pct / 100)


def trail(entry: float, peak: float, sl: float, s: dict) -> float:
    """Naikkan stop-loss mengikuti harga tertinggi (mengunci untung)."""
    if opt(s, "trailing_on") and peak >= entry * (1 + opt(s, "trail_activate_pct") / 100):
        return max(sl, peak * (1 - opt(s, "trail_pct") / 100))
    return sl


def price_exit(entry: float, sl: float, tp: float, o: float, h: float, l: float) -> tuple[float | None, str]:
    """Cek stop-loss / take-profit terhadap harga candle. Untuk robot live, o=h=l=harga sekarang.
    Jika SL dan TP tersentuh di candle yang sama, dianggap SL dulu (asumsi pesimis)."""
    label = "trailing stop" if sl > entry else "stop-loss"
    if o <= sl:
        return o, label
    if l <= sl:
        return sl, label
    if o >= tp:
        return o, "take-profit"
    if h >= tp:
        return tp, "take-profit"
    return None, ""


def signal_exit(held_candles: int, sig: Signal | None, s: dict) -> tuple[bool, str]:
    """Keluar karena waktu atau ramalan baru berbalik (dicek tiap candle tutup)."""
    if held_candles >= s["max_hold_candles"]:
        return True, f"batas waktu {held_candles} candle"
    if sig is not None and sig.prob_up < s["exit_prob_up_below"] and sig.exp_ret_pct < 0:
        return True, f"ramalan berbalik turun (peluang naik {sig.prob_up:.0%})"
    return False, ""
