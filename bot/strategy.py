"""Aturan keputusan. Dipakai SAMA PERSIS oleh bot live/paper dan backtest.

Strategi hanya LONG (spot): beli lalu jual. Tidak ada short/leverage.
"""
from .forecast import Signal


def entry_decision(sig: Signal, s: dict) -> tuple[bool, str]:
    """Apakah sinyal cukup kuat untuk membeli?"""
    if sig.exp_ret_pct < s["min_expected_return_pct"]:
        return False, f"ekspektasi {sig.exp_ret_pct:+.2f}% < {s['min_expected_return_pct']}%"
    if sig.prob_up < s["min_prob_up"]:
        return False, f"peluang naik {sig.prob_up:.0%} < {s['min_prob_up']:.0%}"
    return True, f"ekspektasi {sig.exp_ret_pct:+.2f}%, peluang naik {sig.prob_up:.0%}"


def price_exit(entry: float, o: float, h: float, l: float, s: dict) -> tuple[float | None, str]:
    """Cek stop-loss / take-profit terhadap harga candle (o,h,l).
    Untuk bot live, isi o=h=l=harga sekarang. Jika SL dan TP tersentuh di candle yang sama,
    dianggap SL dulu (asumsi pesimis)."""
    sl = entry * (1 - s["stop_loss_pct"] / 100)
    tp = entry * (1 + s["take_profit_pct"] / 100)
    if o <= sl:
        return o, "stop-loss"
    if l <= sl:
        return sl, "stop-loss"
    if o >= tp:
        return o, "take-profit"
    if h >= tp:
        return tp, "take-profit"
    return None, ""


def signal_exit(held_candles: int, sig: Signal | None, s: dict) -> tuple[bool, str]:
    """Cek keluar berdasarkan waktu atau ramalan baru (dicek tiap candle tutup)."""
    if held_candles >= s["max_hold_candles"]:
        return True, f"batas waktu {held_candles} candle"
    if sig is not None and sig.prob_up < s["exit_prob_up_below"] and sig.exp_ret_pct < 0:
        return True, f"model berbalik (peluang naik {sig.prob_up:.0%}, ekspektasi {sig.exp_ret_pct:+.2f}%)"
    return False, ""
