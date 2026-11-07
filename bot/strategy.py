"""Aturan keputusan. Dipakai SAMA PERSIS oleh robot (simulasi/live) dan uji strategi.

Kripto (spot)  : hanya LONG (beli lalu jual).
Forex          : LONG (buy) dan SHORT (sell) jika diizinkan.
Setelan kripto ada di config 'strategy', setelan forex di 'strategy_forex'.
"""
from .forecast import Signal

COMMON = {
    "trend_filter": True, "trend_period": 200, "rsi_max": 75, "min_rr": 1.2,
    "sl_mode": "persen", "sl_atr_mult": 2.0, "tp_atr_mult": 4.0,
    "trailing_on": True, "trail_activate_pct": 1.5, "trail_pct": 1.0,
    "max_hold_candles": 24, "exit_prob_up_below": 0.35, "cooldown_candles": 2,
    "min_accuracy": 0.55,        # akurasi arah minimal agar boleh trading (0 = abaikan)
    "min_accuracy_n": 30,        # jumlah ramalan minimal sebelum akurasi dinilai
    "require_proof": False,      # True = jangan trading sebelum akurasinya terbukti
    "allow_short": False,
}
VENUE_DEFAULTS = {
    "crypto": {"fee_pct": 0.1, "min_expected_return_pct": 0.8, "min_prob_up": 0.65,
               "stop_loss_pct": 2.0, "take_profit_pct": 4.0},
    "forex": {"fee_pct": 0.02, "min_expected_return_pct": 0.1, "min_prob_up": 0.65,
              "stop_loss_pct": 0.4, "take_profit_pct": 0.8, "sl_mode": "atr",
              "trail_activate_pct": 0.3, "trail_pct": 0.2, "allow_short": True},
}
DEFAULTS = {**COMMON, **VENUE_DEFAULTS["crypto"]}   # kompatibel dengan kode lama


def venue_of(symbol: str) -> str:
    return "crypto" if "/" in str(symbol) else "forex"


def strat(cfg: dict, venue: str) -> dict:
    key = "strategy" if venue == "crypto" else "strategy_forex"
    s = {**COMMON, **VENUE_DEFAULTS[venue], **(cfg.get(key) or {})}
    if venue == "crypto":
        s["allow_short"] = False   # spot tidak bisa short
    return s


def opt(s: dict, key):
    return s.get(key, DEFAULTS.get(key))


def sgn(side: str) -> int:
    return -1 if side == "short" else 1


# ===================================================================== masuk
def _accuracy_gate(sig: Signal, s: dict) -> str:
    need = float(s.get("min_accuracy") or 0)
    n_min = int(s.get("min_accuracy_n") or 0)
    if need <= 0:
        return ""
    if sig.acc_n >= n_min and sig.accuracy is not None:
        if sig.accuracy < need:
            return f"ramalan di pasar ini baru tepat {sig.accuracy:.0%} (butuh {need:.0%})"
        return ""
    if s.get("require_proof"):
        return f"akurasi belum terbukti ({sig.acc_n}/{n_min} ramalan dinilai)"
    return ""


def _check_long(sig: Signal, s: dict) -> str:
    if sig.exp_ret_pct < s["min_expected_return_pct"]:
        return f"ramalan {sig.exp_ret_pct:+.2f}% belum cukup (butuh +{s['min_expected_return_pct']}%)"
    if sig.prob_up < s["min_prob_up"]:
        return f"peluang naik {sig.prob_up:.0%} (butuh {s['min_prob_up']:.0%})"
    if s["trend_filter"] and not sig.trend_up:
        return "tren besar belum naik"
    if sig.rsi > s["rsi_max"]:
        return f"harga sudah naik terlalu cepat (RSI {sig.rsi:.0f})"
    if sig.rr < s["min_rr"]:
        return f"untung:rugi {sig.rr:.1f} (butuh {s['min_rr']})"
    return ""


def _check_short(sig: Signal, s: dict) -> str:
    if -sig.exp_ret_pct < s["min_expected_return_pct"]:
        return f"ramalan {sig.exp_ret_pct:+.2f}% belum cukup turun (butuh −{s['min_expected_return_pct']}%)"
    if sig.prob_down < s["min_prob_up"]:
        return f"peluang turun {sig.prob_down:.0%} (butuh {s['min_prob_up']:.0%})"
    if s["trend_filter"] and not sig.trend_down:
        return "tren besar belum turun"
    if sig.rsi < 100 - s["rsi_max"]:
        return f"harga sudah turun terlalu cepat (RSI {sig.rsi:.0f})"
    if sig.rr_short < s["min_rr"]:
        return f"untung:rugi {sig.rr_short:.1f} (butuh {s['min_rr']})"
    return ""


def entry_side(sig: Signal, s: dict) -> tuple[str | None, str]:
    """Mengembalikan ('long' | 'short' | None, alasan)."""
    gate = _accuracy_gate(sig, s)
    if gate:
        return None, gate
    why_long = _check_long(sig, s)
    if not why_long:
        return "long", (f"ramalan {sig.exp_ret_pct:+.2f}%, peluang naik {sig.prob_up:.0%}, "
                        f"untung:rugi {sig.rr:.1f}")
    if s.get("allow_short"):
        why_short = _check_short(sig, s)
        if not why_short:
            return "short", (f"ramalan {sig.exp_ret_pct:+.2f}%, peluang turun {sig.prob_down:.0%}, "
                             f"untung:rugi {sig.rr_short:.1f}")
        if sig.exp_ret_pct < 0:
            return None, why_short
    return None, why_long


def entry_decision(sig: Signal, s: dict) -> tuple[bool, str]:
    """Kompatibel lama: True jika boleh membuka posisi (sisi mana pun)."""
    side, why = entry_side(sig, s)
    return side is not None, why


def side_score(sig: Signal, s: dict) -> float:
    best = sig.exp_ret_pct * sig.prob_up
    if s.get("allow_short"):
        best = max(best, -sig.exp_ret_pct * sig.prob_down)
    return best


# ===================================================================== keluar
def exit_levels(entry: float, side: str, sig: Signal | None, s: dict) -> tuple[float, float]:
    """Harga stop-loss dan take-profit saat membuka posisi."""
    if s.get("sl_mode") == "atr" and sig is not None and sig.atr_pct > 0:
        sl_pct, tp_pct = sig.atr_pct * s["sl_atr_mult"], sig.atr_pct * s["tp_atr_mult"]
    else:
        sl_pct, tp_pct = s["stop_loss_pct"], s["take_profit_pct"]
    k = sgn(side)
    return entry * (1 - k * sl_pct / 100), entry * (1 + k * tp_pct / 100)


def trail(entry: float, best: float, sl: float, side: str, s: dict) -> float:
    """Geser stop-loss mengikuti harga terbaik (mengunci untung). best = puncak (long) / lembah (short)."""
    if not s.get("trailing_on"):
        return sl
    act, gap = s["trail_activate_pct"] / 100, s["trail_pct"] / 100
    if side == "short":
        if best <= entry * (1 - act):
            return min(sl, best * (1 + gap))
        return sl
    if best >= entry * (1 + act):
        return max(sl, best * (1 - gap))
    return sl


def price_exit(entry: float, sl: float, tp: float, side: str, o: float, h: float, l: float) -> tuple[float | None, str]:
    """Cek SL/TP terhadap harga candle (o,h,l). Untuk robot live: o=h=l=harga sekarang.
    Jika SL dan TP tersentuh di candle yang sama, dianggap SL dulu (pesimis)."""
    if side == "short":
        label = "trailing stop" if sl < entry else "stop-loss"
        if o >= sl:
            return o, label
        if h >= sl:
            return sl, label
        if o <= tp:
            return o, "take-profit"
        if l <= tp:
            return tp, "take-profit"
        return None, ""
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


def signal_exit(held: int, sig: Signal | None, side: str, s: dict) -> tuple[bool, str]:
    """Keluar karena waktu atau ramalan baru berbalik (dicek tiap candle tutup)."""
    if held >= s["max_hold_candles"]:
        return True, f"sudah {held} candle"
    if sig is None:
        return False, ""
    if side == "short":
        if sig.prob_down < s["exit_prob_up_below"] and sig.exp_ret_pct > 0:
            return True, f"ramalan berbalik naik (peluang turun {sig.prob_down:.0%})"
    elif sig.prob_up < s["exit_prob_up_below"] and sig.exp_ret_pct < 0:
        return True, f"ramalan berbalik turun (peluang naik {sig.prob_up:.0%})"
    return False, ""
