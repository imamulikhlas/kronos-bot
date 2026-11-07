"""
Backtest: robot trading pura-pura di data masa lalu (biasanya dijalankan dari panel, menu Backtest).

    python backtest.py BTC/USDT --candles 1000
    python backtest.py EURUSD XAUUSD --candles 1500 --optimize --device gpu
    python backtest.py BTC/USDT --dummy                     # uji alur cepat dengan ramalan acak

Kejujuran hasil:
- Model hanya melihat data SEBELUM tiap titik keputusan. Order dieksekusi di harga open candle berikutnya.
- Kalau stop-loss dan take-profit tersentuh di candle yang sama, dianggap kena stop-loss (pesimis).
- Biaya (fee/spread) dan slippage dihitung tiap buka dan tutup posisi.
- Periode dibagi beberapa segmen. Setelan dinilai dari KONSISTENSI di semua segmen, bukan hanya total.
- Walk-forward: untuk tiap segmen, setelan dipilih HANYA dari segmen sebelumnya lalu diuji di segmen itu.
  Hasil walk-forward adalah perkiraan paling jujur kalau kamu memakai optimasi ini sungguhan.
- Monte Carlo: urutan trade diacak ribuan kali untuk melihat rentang hasil yang masuk akal.

Ramalan disimpan ke cache, jadi menguji ulang dengan setelan berbeda berjalan instan.
Dengan GPU (NVIDIA CUDA atau Apple Metal), banyak titik waktu diramal sekaligus sehingga jauh lebih cepat.
"""
import argparse
import hashlib
import itertools
import json
import math
import time

import numpy as np
import pandas as pd

from bot.config import load_config, path_in_root, setup_logging, venue_cfg
from bot.forecast import Signal, build_signal, default_batch, make_forecaster
from bot.forex import base_quote, contract_size, round_down
from bot.strategy import entry_side, exit_levels, price_exit, sgn, signal_exit, strat, trail, venue_of

OUT = path_in_root("data/backtest/x").parent
TF_SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def safe(symbol):
    return symbol.replace("/", "")


class Progress:
    """Satu baris progres yang dibaca panel: 'Progres 42% | ...'."""

    def __init__(self, log, n_sym):
        self.log, self.n, self.k = log, n_sym, 0

    def __call__(self, frac, text):
        pct = (self.k + max(0.0, min(1.0, frac))) / self.n * 100
        self.log.info("Progres %.0f%% | %s", pct, text)


# ============================================================ data & ramalan
def load_candles(cfg, symbol, tf, n, csv):
    if csv:
        df = pd.read_csv(csv)
        df["timestamps"] = pd.to_datetime(df["timestamps"])
        if "ts" not in df:
            df["ts"] = (df["timestamps"] - pd.Timestamp("1970-01-01 07:00")) // pd.Timedelta(milliseconds=1)
        for c in ("volume", "amount"):
            if c not in df:
                df[c] = 0.0
        return df.reset_index(drop=True), None
    from bot.venues import Markets
    data = Markets(cfg).data(venue_of(symbol))
    df = data.history(symbol, tf, n)
    df.to_csv(OUT / f"candles_{safe(symbol)}_{tf}.csv", index=False)
    return df, data


def cache_path(symbol, tf, cfg, s, dummy):
    m = cfg["model"]
    key = {k: m.get(k) for k in ["name", "lookback", "pred_len", "n_paths", "temperature", "top_p", "ensemble"]}
    key |= {"fee": s["fee_pct"], "trend": s["trend_period"], "dummy": dummy, "v": 5}
    h = hashlib.md5(json.dumps(key, sort_keys=True).encode()).hexdigest()[:8]
    return OUT / f"cache_{safe(symbol)}_{tf}_{h}.json"


def compute_signals(df, symbol, cfg, s, forecaster, start, every, future, cache_file, log, prog, batch):
    m = cfg["model"]
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    lookback, pred_len = int(m["lookback"]), int(m["pred_len"])
    todo = [t for t in range(start, len(df))
            if (t - start) % every == 0 and str(int(df["ts"].iloc[t - 1])) not in cache]
    stats = {"points": len(todo), "cached": 0, "seconds": 0.0, "batch": batch}
    log.info("%s: %d titik perlu diramal, %d sudah ada di cache. Perangkat: %s, %d titik sekaligus.",
             symbol, len(todo), len(cache), forecaster.device_name, batch)
    t0 = time.time()
    done = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        items = []
        for t in chunk:
            hist = df.iloc[t - lookback:t].reset_index(drop=True)
            items.append((hist, future(hist["timestamps"].iloc[-1], pred_len)))
        for (hist, _), paths in zip(items, forecaster.paths_many(items)):
            sig = build_signal(symbol, hist, paths, s["fee_pct"], int(s["trend_period"]))
            cache[str(int(hist["ts"].iloc[-1]))] = sig.__dict__
        done += len(chunk)
        el = time.time() - t0
        rate = done / el if el else 0
        left = (len(todo) - done) / rate / 60 if rate else 0
        prog(0.85 * done / len(todo), f"{symbol}: meramal {done}/{len(todo)} | {rate:.2f} titik/detik | sisa ~{left:.1f} menit")
        cache_file.write_text(json.dumps(cache))
    stats["seconds"] = round(time.time() - t0, 1)
    stats["sec_per_point"] = round(stats["seconds"] / len(todo), 3) if todo else None
    known = set(Signal.__dataclass_fields__)
    return {int(k): Signal(**{a: b for a, b in v.items() if a in known}) for k, v in cache.items()}, stats


# ============================================================ simulasi
def q2usd(symbol, price):
    b, q = base_quote(symbol)
    if q == "USD":
        return 1.0
    if b == "USD":
        return 1.0 / price
    return 1.0   # silang (mis. EURGBP): perkiraan


def simulate(df, signals, cfg, symbol, s, start, end):
    """Satu kali jalan robot di candle [start, end). Keputusan saat candle t-1 tutup, eksekusi di open candle t."""
    venue = venue_of(symbol)
    r, p, fx = cfg["risk"], cfg["paper"], cfg.get("forex") or {}
    fee, slip = s["fee_pct"] / 100, p["slippage_pct"] / 100
    cash = start_cash = float(p["starting_balance"])
    O, H, L, C, TS = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "ts"))
    times = df["timestamps"].to_numpy()
    pos, trades, eq, cooldown_until, skipped, in_mkt = None, [], [], -1, 0, 0

    def pos_value(px):
        if pos is None:
            return 0.0
        if venue == "crypto":
            return pos["units"] * px
        return pos["units"] * (px - pos["entry"]) * sgn(pos["side"]) * q2usd(symbol, px)

    def close(t, px, why):
        nonlocal cash, pos
        k = sgn(pos["side"])
        if venue == "crypto":
            px = px * (1 - slip)
            proceeds = pos["units"] * px * (1 - fee)
            cash += proceeds
            pnl = proceeds - pos["cost"]
            pct = pnl / pos["cost"] * 100
        else:
            px = px * (1 - k * (fee / 2 + slip))
            pnl = pos["units"] * (px - pos["entry"]) * k * q2usd(symbol, px)
            cash += pnl
            pct = (px / pos["entry"] - 1) * 100 * k
        trades.append({"side": pos["side"], "entry_time": times[pos["i"]], "entry_price": pos["entry"],
                       "exit_time": times[t], "exit_price": px, "cost": pos["cost"], "pnl": pnl, "pnl_pct": pct,
                       "held": t - pos["i"] + 1, "exit_reason": why})
        pos = None

    for t in range(start, end):
        o, h, lo, c = O[t], H[t], L[t], C[t]
        sig = signals.get(int(TS[t - 1]))
        if pos is not None:
            hit, why = signal_exit(t - pos["i"], sig, pos["side"], s)
            if hit:
                close(t, o, why)
                cooldown_until = t + int(s["cooldown_candles"])
        if pos is None and sig is not None and t >= cooldown_until and t < end - 1:
            side, _ = entry_side(sig, s)
            if side:
                k = sgn(side)
                if venue == "crypto":
                    cost = min(float(r["order_size_quote"]), float(r["max_order_size_quote"]), cash)
                    px = o * (1 + slip)
                    if cost > 0:
                        sl, tp = exit_levels(px, side, sig, s)
                        cash -= cost
                        pos = {"i": t, "side": side, "entry": px, "units": cost * (1 - fee) / px, "cost": cost,
                               "sl": sl, "tp": tp, "best": px}
                else:
                    px = o * (1 + k * (fee / 2 + slip))
                    sl, tp = exit_levels(px, side, sig, s)
                    lot = contract_size(symbol)
                    units = cash * float(fx.get("risk_pct", 1.0)) / 100 / max(abs(px - sl) * q2usd(symbol, px), 1e-12)
                    units = round_down(min(units, float(fx.get("max_lots", 1.0)) * lot), 0.01 * lot)
                    if units > 0:
                        margin = units * px * q2usd(symbol, px) / max(1.0, float(fx.get("leverage", 100)))
                        pos = {"i": t, "side": side, "entry": px, "units": units, "cost": margin,
                               "sl": sl, "tp": tp, "best": px}
                    else:
                        skipped += 1
        if pos is not None:
            in_mkt += 1
            px, why = price_exit(pos["entry"], pos["sl"], pos["tp"], pos["side"],
                                 o if t > pos["i"] else pos["entry"], h, lo)
            if px is not None:
                close(t, px, why)
                cooldown_until = t + int(s["cooldown_candles"])
            else:
                pos["best"] = min(pos["best"], lo) if pos["side"] == "short" else max(pos["best"], h)
                pos["sl"] = trail(pos["entry"], pos["best"], pos["sl"], pos["side"], s)
        eq.append(cash + pos_value(c))

    if pos is not None:
        close(end - 1, C[end - 1], "akhir periode")
        eq[-1] = cash
    curve = pd.DataFrame({"timestamps": times[start:end], "close": C[start:end], "equity": eq})
    return pd.DataFrame(trades), curve, start_cash, {"skipped": skipped, "exposure": in_mkt / max(1, end - start)}


def metrics(trades, curve, start_cash, tf="1h", venue="crypto", extra=None):
    eqv = curve["equity"].to_numpy(float)
    n = len(trades)
    rets = np.diff(eqv) / eqv[:-1] if len(eqv) > 1 else np.array([0.0])
    per_year = (365 if venue == "crypto" else 260) * 86400 / TF_SEC.get(tf, 3600)
    sd = float(rets.std())
    down = rets[rets < 0]
    out = {
        "return_pct": float((eqv[-1] / start_cash - 1) * 100),
        "buyhold_pct": float((curve["close"].iloc[-1] / curve["close"].iloc[0] - 1) * 100),
        "max_dd_pct": float(((eqv / np.maximum.accumulate(eqv)) - 1).min() * 100),
        "trades": n,
        "win_pct": float((trades["pnl"] > 0).mean() * 100) if n else 0.0,
        "avg_trade_pct": float(trades["pnl_pct"].mean()) if n else 0.0,
        "longs": int((trades["side"] == "long").sum()) if n else 0,
        "shorts": int((trades["side"] == "short").sum()) if n else 0,
        "sharpe": float(rets.mean() / sd * math.sqrt(per_year)) if sd > 0 else 0.0,
        "sortino": float(rets.mean() / down.std() * math.sqrt(per_year)) if len(down) > 1 and down.std() > 0 else 0.0,
    }
    if n:
        gains, losses = trades.loc[trades["pnl"] > 0, "pnl"].sum(), -trades.loc[trades["pnl"] < 0, "pnl"].sum()
        out["profit_factor"] = float(gains / losses) if losses > 0 else (99.0 if gains > 0 else 0.0)
        out["avg_win_pct"] = float(trades.loc[trades["pnl"] > 0, "pnl_pct"].mean()) if (trades["pnl"] > 0).any() else 0.0
        out["avg_loss_pct"] = float(trades.loc[trades["pnl"] <= 0, "pnl_pct"].mean()) if (trades["pnl"] <= 0).any() else 0.0
        out["expectancy"] = float(trades["pnl"].mean())
        streak = best = 0
        for v in trades["pnl"]:
            streak = streak + 1 if v <= 0 else 0
            best = max(best, streak)
        out["max_losing_streak"] = best
        out["avg_held"] = float(trades["held"].mean())
    else:
        out.update(profit_factor=0.0, avg_win_pct=0.0, avg_loss_pct=0.0, expectancy=0.0, max_losing_streak=0, avg_held=0.0)
    if extra:
        out["exposure_pct"] = round(extra["exposure"] * 100, 1)
        out["skipped"] = extra["skipped"]
    return out


def monte_carlo(trades, start_cash, runs=3000, seed=7):
    """Acak urutan & pilihan trade (bootstrap) untuk melihat rentang hasil yang wajar."""
    if len(trades) < 3:
        return None
    rng = np.random.default_rng(seed)
    pnl = trades["pnl"].to_numpy(float)
    picks = rng.integers(0, len(pnl), size=(runs, len(pnl)))
    paths = start_cash + np.cumsum(pnl[picks], axis=1)
    final = (paths[:, -1] / start_cash - 1) * 100
    dd = ((paths / np.maximum.accumulate(np.concatenate([np.full((runs, 1), start_cash), paths], axis=1))[:, 1:]) - 1).min(axis=1) * 100
    return {"p5": float(np.percentile(final, 5)), "p50": float(np.percentile(final, 50)),
            "p95": float(np.percentile(final, 95)), "prob_loss": float((final < 0).mean()),
            "dd_p95": float(np.percentile(dd, 5)), "runs": runs}


# ============================================================ kualitas ramalan
def binom_p(hits, n):
    """Peluang dapat >= hits benar dari n kalau sebenarnya cuma lempar koin (uji satu sisi)."""
    if n == 0:
        return 1.0
    logs = [math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) - n * math.log(2) for k in range(hits, n + 1)]
    mx = max(logs)
    return float(min(1.0, math.exp(mx) * sum(math.exp(v - mx) for v in logs)))


def forecast_quality(df, signals, pred_len, start):
    """Seberapa bagus ramalan AI, terlepas dari strategi: arah, peluang (kalibrasi), dan besar gerakan."""
    idx = {int(ts): i for i, ts in enumerate(df["ts"])}
    close = df["close"].to_numpy(float)
    rows = []
    for ts, sig in signals.items():
        i = idx.get(ts)
        if i is None or i + 1 < start or i + pred_len >= len(df):
            continue
        actual = (close[i + pred_len] / sig.last_close - 1) * 100
        if actual == 0:
            continue
        p = getattr(sig, "prob_up_raw", None)
        if p is None or p == 0.5 and sig.prob_up + sig.prob_down > 0:
            p = sig.prob_up + (1 - sig.prob_up - sig.prob_down) / 2
        rows.append((sig.exp_ret_pct, actual, p, sig.direction))
    n = len(rows)
    if not n:
        return {"n": 0, "hits": 0, "hit": None}
    exp = np.array([r[0] for r in rows])
    act = np.array([r[1] for r in rows])
    pu = np.clip(np.array([r[2] for r in rows]), 0, 1)
    dirs = np.array([r[3] for r in rows])
    up = (act > 0).astype(float)
    hit_mask = np.sign(exp) == np.sign(act)
    hits = int(hit_mask.sum())
    conf = dirs != "SAMPING"
    conf_hits = int(((dirs == "NAIK") & (act > 0)).sum() + ((dirs == "TURUN") & (act < 0)).sum())
    brier = float(np.mean((pu - up) ** 2))
    base = float(np.mean((up.mean() - up) ** 2)) or 0.25
    mae = float(np.mean(np.abs(exp - act)))
    mae_naive = float(np.mean(np.abs(act)))
    calib = []
    for lo, hi in [(0, .3), (.3, .45), (.45, .55), (.55, .7), (.7, 1.01)]:
        m = (pu >= lo) & (pu < hi)
        if m.sum():
            calib.append({"from": lo, "to": min(hi, 1), "n": int(m.sum()), "pred": float(pu[m].mean()),
                          "actual": float(up[m].mean())})
    return {"n": n, "hits": hits, "hit": hits / n, "p_value": binom_p(hits, n),
            "conf_n": int(conf.sum()), "conf_hits": conf_hits,
            "conf_hit": conf_hits / int(conf.sum()) if conf.sum() else None,
            "conf_p_value": binom_p(conf_hits, int(conf.sum())) if conf.sum() else None,
            "brier": brier, "brier_skill": 1 - brier / base,
            "mae": mae, "mae_naive": mae_naive, "mae_skill": 1 - mae / mae_naive if mae_naive else 0.0,
            "up_rate": float(up.mean()), "calibration": calib}


# ============================================================ optimasi (walk-forward)
GRIDS = {
    "crypto": {
        "min_expected_return_pct": [0.3, 0.6, 1.0, 1.5],
        "min_prob_up": [0.55, 0.65, 0.75],
        "stops": [("persen", 1.5, 3.0), ("persen", 2.0, 4.0), ("persen", 3.0, 6.0),
                  ("atr", 1.5, 3.0), ("atr", 2.0, 4.0), ("atr", 3.0, 6.0)],
        "trailing": [None, (1.0, 0.8), (2.0, 1.5)],
        "trend_filter": [True, False],
        "allow_short": [False],
    },
    "forex": {
        "min_expected_return_pct": [0.05, 0.1, 0.2, 0.3],
        "min_prob_up": [0.55, 0.65, 0.75],
        "stops": [("persen", 0.3, 0.6), ("persen", 0.5, 1.0), ("persen", 1.0, 2.0),
                  ("atr", 1.5, 3.0), ("atr", 2.0, 4.0), ("atr", 3.0, 6.0)],
        "trailing": [None, (0.2, 0.15), (0.4, 0.3)],
        "trend_filter": [True, False],
        "allow_short": [True, False],
    },
}
PARAM_KEYS = ["min_expected_return_pct", "min_prob_up", "sl_mode", "stop_loss_pct", "take_profit_pct",
              "sl_atr_mult", "tp_atr_mult", "trailing_on", "trail_activate_pct", "trail_pct", "trend_filter",
              "allow_short"]


def apply_params(base: dict, combo: dict) -> dict:
    s = dict(base)
    s["min_expected_return_pct"] = combo["min_expected_return_pct"]
    s["min_prob_up"] = combo["min_prob_up"]
    mode, a, b = combo["stops"]
    s["sl_mode"] = mode
    if mode == "atr":
        s["sl_atr_mult"], s["tp_atr_mult"] = a, b
    else:
        s["stop_loss_pct"], s["take_profit_pct"] = a, b
    s["trailing_on"] = combo["trailing"] is not None
    if combo["trailing"] is not None:
        s["trail_activate_pct"], s["trail_pct"] = combo["trailing"]
    s["trend_filter"] = combo["trend_filter"]
    s["allow_short"] = combo["allow_short"]
    s["min_accuracy"] = 0    # akurasi dinilai terpisah
    return s


def make_segments(start, end, folds):
    edges = np.linspace(start, end, folds + 1).astype(int)
    return [(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:])]


def seg_eval(df, signals, cfg, symbol, s, segs, tf):
    v = venue_of(symbol)
    out = []
    for a, b in segs:
        tr, cv, sc, ex = simulate(df, signals, cfg, symbol, s, a, b)
        m = metrics(tr, cv, sc, tf, v, ex)
        out.append({"return_pct": m["return_pct"], "trades": m["trades"], "max_dd_pct": m["max_dd_pct"],
                    "win_pct": m["win_pct"]})
    return out


def robust_score(segs, upto=None, min_trades=None):
    """Rata-rata hasil per segmen, dikurangi ketidakstabilan dan drawdown terburuk."""
    sg = segs[:upto] if upto else segs
    trades = sum(x["trades"] for x in sg)
    if trades < (min_trades if min_trades is not None else max(4, len(sg))):
        return -1e9
    r = np.array([x["return_pct"] for x in sg])
    dd = max(abs(x["max_dd_pct"]) for x in sg)
    return float(r.mean() - 0.5 * r.std() - 0.25 * dd)


def compound(rets):
    return float((np.prod([1 + r / 100 for r in rets]) - 1) * 100)


def grade(quality, full_m, segs, mc, wf_total=None):
    """Nilai akhir A-D dengan alasan yang bisa dibaca."""
    cons = float(np.mean([x["return_pct"] > 0 for x in segs])) if segs else 0.0
    checks = []
    acc_ok = bool(quality.get("hit") and quality["hit"] > 0.5 and (quality.get("p_value") or 1) < 0.01)
    checks.append({"ok": acc_ok, "key": "edge",
                   "text": (f"Arah ramalan benar {quality['hit']:.0%} dari {quality['n']}, " +
                            ("terbukti lebih baik dari lempar koin." if acc_ok else
                             ("ada tanda lebih baik dari lempar koin, tapi belum cukup kuat." if quality.get("hit", 0) > 0.5 and (quality.get("p_value") or 1) < 0.05
                              else "belum terbukti lebih baik dari lempar koin.")))
                   if quality.get("n") else "Belum ada ramalan untuk dinilai."})
    if wf_total is not None:
        checks.append({"ok": wf_total > 0, "key": "walkforward",
                       "text": f"Uji walk-forward (setelan dipilih tanpa melihat masa depan): {wf_total:+.2f}%."})
    else:
        checks.append({"ok": full_m["return_pct"] > 0, "key": "return",
                       "text": f"Hasil di periode uji: {full_m['return_pct']:+.2f}%."})
    checks.append({"ok": cons >= 0.6, "key": "consistency",
                   "text": f"Untung di {sum(x['return_pct'] > 0 for x in segs)} dari {len(segs)} segmen waktu."})
    checks.append({"ok": full_m["trades"] >= 15, "key": "sample",
                   "text": f"{full_m['trades']} trade" + (" (cukup untuk dinilai)." if full_m["trades"] >= 15 else ", terlalu sedikit untuk yakin.")})
    checks.append({"ok": full_m.get("profit_factor", 0) >= 1.2, "key": "pf",
                   "text": f"Profit factor {full_m.get('profit_factor', 0):.2f} (untung kotor dibagi rugi kotor, bagus di atas 1,2)."})
    if mc:
        checks.append({"ok": mc["prob_loss"] <= 0.35, "key": "montecarlo",
                       "text": f"Monte Carlo: peluang rugi {mc['prob_loss']:.0%}, rentang hasil {mc['p5']:+.1f}% s/d {mc['p95']:+.1f}%."})
    pts = sum(c["ok"] for c in checks)
    letter = "A" if pts >= len(checks) - 0 else "B" if pts >= len(checks) - 2 else "C" if pts >= len(checks) - 4 else "D"
    # syarat mutlak: tanpa bukti keunggulan AI atau tanpa hasil positif yang jujur, maksimal C
    # syarat mutlak untuk A/B: keunggulan AI terbukti, hasil positif yang jujur, dan trade cukup banyak
    if letter in ("A", "B") and not (checks[0]["ok"] and checks[1]["ok"] and full_m["trades"] >= 15):
        letter = "C"
    label = {"A": "Ready to try live", "B": "Promising", "C": "Weak", "D": "Avoid"}[letter]
    notes = []
    if full_m.get("skipped"):
        notes.append(f"{full_m['skipped']} sinyal dilewati karena saldo terlalu kecil untuk 0,01 lot dengan risiko per "
                     "trade sekarang. Naikkan saldo atau risiko, atau pakai stop-loss yang lebih dekat.")
    if full_m["trades"] == 0:
        notes.append("Tidak ada posisi dibuka. Syarat masuk mungkin terlalu ketat untuk pair ini.")
    return {"letter": letter, "label": label, "points": pts, "of": len(checks), "consistency": cons,
            "checks": checks, "notes": notes}


def optimize(df, signals, cfg, symbol, base, segs, quality, log, prog, tf, tag=""):
    venue = venue_of(symbol)
    grid = GRIDS[venue]
    combos = [dict(zip(grid, v)) for v in itertools.product(*grid.values())]
    log.info("%s: mencari setelan terbaik, %d kombinasi x %d segmen...", symbol, len(combos), len(segs))
    rows = []
    t0 = time.time()
    for i, cb in enumerate(combos, 1):
        s = apply_params(base, cb)
        sg = seg_eval(df, signals, cfg, symbol, s, segs, tf)
        rows.append({"params": {k: s[k] for k in PARAM_KEYS}, "segments": sg, "score": robust_score(sg), "_s": s})
        if i % 24 == 0 or i == len(combos):
            el = time.time() - t0
            prog(0.85 + 0.13 * i / len(combos),
                 f"{symbol}: optimasi {i}/{len(combos)} | sisa ~{el / i * (len(combos) - i) / 60:.1f} menit")

    # walk-forward: pilih dari segmen 0..k-1, uji di segmen k
    wf = []
    for k in range(1, len(segs)):
        cand = max(rows, key=lambda r: robust_score(r["segments"], upto=k, min_trades=max(2, k)))
        if robust_score(cand["segments"], upto=k, min_trades=max(2, k)) <= -1e9:
            wf.append({"segment": k, "return_pct": 0.0, "trades": 0, "note": "tidak ada setelan layak, robot diam"})
            continue
        x = cand["segments"][k]
        wf.append({"segment": k, "return_pct": x["return_pct"], "trades": x["trades"],
                   "params": cand["params"]})
    wf_total = compound([w["return_pct"] for w in wf]) if wf else None

    valid = sorted([r for r in rows if r["score"] > -1e9], key=lambda r: r["score"], reverse=True)
    top = valid[:10]
    a, b = segs[0][0], segs[-1][1]
    for r in top:
        tr, cv, sc, ex = simulate(df, signals, cfg, symbol, r.pop("_s"), a, b)
        r["full"] = metrics(tr, cv, sc, tf, venue, ex)
        r["consistency"] = float(np.mean([x["return_pct"] > 0 for x in r["segments"]]))
        r["montecarlo"] = monte_carlo(tr, sc)
    for r in rows:
        r.pop("_s", None)
    cur_s = dict(base, min_accuracy=0)
    cur_sg = seg_eval(df, signals, cfg, symbol, cur_s, segs, tf)
    tr, cv, sc, ex = simulate(df, signals, cfg, symbol, cur_s, a, b)
    cur_full = metrics(tr, cv, sc, tf, venue, ex)
    current = {"params": {k: cur_s.get(k) for k in PARAM_KEYS}, "segments": cur_sg, "full": cur_full,
               "consistency": float(np.mean([x["return_pct"] > 0 for x in cur_sg])), "montecarlo": monte_carlo(tr, sc),
               "score": robust_score(cur_sg)}
    best_grade = grade(quality, top[0]["full"], top[0]["segments"], top[0]["montecarlo"], wf_total) if top else None
    res = {"version": 2, "symbol": symbol, "venue": venue, "tf": tf, "created": (pd.Timestamp.utcnow() + pd.Timedelta(hours=7)).strftime("%Y-%m-%d %H:%M"),
           "combos": len(combos), "valid": len(valid),
           "segments": [{"from": str(df["timestamps"].iloc[x])[:16], "to": str(df["timestamps"].iloc[y - 1])[:16]}
                        for x, y in segs],
           "current": current, "candidates": top, "walk_forward": {"steps": wf, "total_pct": wf_total},
           "grade": best_grade}
    (OUT / f"{safe(symbol)}_{tf}{tag}_optimasi.json").write_text(json.dumps(res, indent=1, default=str))
    log.info("Setelan sekarang   : %+.2f%% | untung di %d/%d segmen", cur_full["return_pct"],
             sum(x["return_pct"] > 0 for x in cur_sg), len(cur_sg))
    for j, r in enumerate(top[:5], 1):
        log.info("Kandidat #%d        : %+.2f%% | untung di %d/%d segmen | %d trade", j, r["full"]["return_pct"],
                 sum(x["return_pct"] > 0 for x in r["segments"]), len(segs), r["full"]["trades"])
    if wf_total is not None:
        log.info("Walk-forward       : %+.2f%% (perkiraan paling jujur)", wf_total)
    return res


# ============================================================ laporan
def report(symbol, tf, trades, curve, start_bal, quality, log, tag, extra, segs_cur, mc, info):
    venue = venue_of(symbol)
    m = metrics(trades, curve, start_bal, tf, venue, extra)
    g = grade(quality, m, segs_cur, mc)
    lines = [
        f"Backtest {symbol} {tf} | {curve['timestamps'].iloc[0]} s/d {curve['timestamps'].iloc[-1]}",
        f"  Arah ramalan benar   : {quality['hit'] or 0:.1%} dari {quality['n']} (p={quality.get('p_value', 1):.3f})",
        f"  Jumlah trade         : {m['trades']} (buy {m['longs']}, sell {m['shorts']}) | menang {m['win_pct']:.0f}%",
        f"  Hasil robot          : {m['return_pct']:+.2f}% (saldo {start_bal:.2f} -> {curve['equity'].iloc[-1]:.2f})",
        f"  Beli & tahan         : {m['buyhold_pct']:+.2f}%",
        f"  Penurunan terdalam   : {m['max_dd_pct']:.2f}% | profit factor {m['profit_factor']:.2f} | Sharpe {m['sharpe']:.2f}",
        f"  Nilai                : {g['letter']} ({g['label']})",
    ]
    if extra["skipped"]:
        lines.append(f"  Dilewati             : {extra['skipped']} sinyal (modal terlalu kecil untuk 0,01 lot)")
    for ln in lines:
        log.info(ln)
    base = OUT / f"{safe(symbol)}_{tf}{tag}"
    trades.to_csv(f"{base}_trades.csv", index=False)
    curve.to_csv(f"{base}_equity.csv", index=False)
    meta = {"version": 2, "symbol": symbol, "venue": venue, "tf": tf, "metrics": m,
            "accuracy": {"hits": quality["hits"], "n": quality["n"], "hit": quality["hit"],
                         "err": quality.get("mae")},
            "quality": quality, "segments": segs_cur, "montecarlo": mc, "grade": g, **info}
    (OUT / f"{safe(symbol)}_{tf}{tag}_meta.json").write_text(json.dumps(meta, default=str))
    (OUT / f"{safe(symbol)}_{tf}{tag}_ringkasan.txt").write_text("\n".join(lines), encoding="utf-8")


def run_symbol(symbol, full, args, log, prog, forecaster_box):
    venue = venue_of(symbol)
    cfg = venue_cfg(full, venue)
    tf = args.tf or cfg["timeframe"]
    cfg["timeframe"] = tf
    s = strat(cfg, venue)
    lookback, pred_len = int(cfg["model"]["lookback"]), int(cfg["model"]["pred_len"])

    prog(0.01, f"{symbol}: mengambil data {tf}")
    extra = 0
    end = None
    if args.end:
        end = pd.Timestamp(args.end)
        if end.hour == 0 and end.minute == 0:
            end = end + pd.Timedelta(hours=23, minutes=59)
        now = pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(hours=7)
        extra = max(0, int((now - end).total_seconds() // TF_SEC.get(tf, 3600)) + 5)
    df, data = load_candles(cfg, symbol, tf, args.candles + lookback + pred_len + extra, args.csv)
    if end is not None:
        df = df[df["timestamps"] <= end].reset_index(drop=True)
        log.info("%s: periode diuji berakhir %s (%d candle tersedia sebelum tanggal itu).", symbol, end, len(df))
    if len(df) < lookback + 60:
        raise SystemExit(f"Data {symbol} terlalu sedikit ({len(df)} candle). Untuk forex 15/30 menit, Yahoo hanya "
                         "menyediakan sekitar 60 hari; kurangi jumlah candle atau pakai timeframe lebih besar.")
    if data is not None:
        future = lambda last, n: data.future_ts(last, tf, n)  # noqa: E731
    else:
        step = pd.Timedelta(milliseconds=int(df["ts"].diff().median()))
        future = lambda last, n: pd.Series([last + step * (i + 1) for i in range(n)])  # noqa: E731
    start = max(lookback, len(df) - args.candles)

    if forecaster_box.get("obj") is None:
        prog(0.02, "memuat model AI")
        forecaster_box["obj"] = make_forecaster(full, dummy=args.dummy, device=args.device)
    fc = forecaster_box["obj"]
    batch = args.batch or default_batch(fc.device)
    cfile = cache_path(symbol, tf, cfg, s, args.dummy)
    signals, speed = compute_signals(df, symbol, cfg, s, fc, start, args.every, future, cfile, log, prog, batch)
    speed.update(device=fc.device, device_name=fc.device_name)

    run_s = dict(s, min_accuracy=0)
    end = len(df)
    trades, curve, bal, extra = simulate(df, signals, cfg, symbol, run_s, start, end)
    quality = forecast_quality(df, signals, pred_len, start)
    folds = args.folds or int(min(6, max(3, (end - start) // 120)))
    segs = make_segments(start, end, folds)
    segs_cur = seg_eval(df, signals, cfg, symbol, run_s, segs, tf)
    mc = monte_carlo(trades, bal)
    tag = ("_" + args.end.replace("-", "")[:8] if args.end else "") + ("_dummy" if args.dummy else "")
    info = {"end": args.end,"speed": speed, "candles": end - start, "every": args.every, "folds": folds,
            "model": {k: full["model"].get(k) for k in ("name", "n_paths", "pred_len", "lookback")},
            "period": [str(df["timestamps"].iloc[start])[:16], str(df["timestamps"].iloc[-1])[:16]]}
    report(symbol, tf, trades, curve, bal, quality, log, tag, extra, segs_cur, mc, info)
    if not args.dummy and quality["n"] and not args.end:
        from bot.store import Store
        Store(path_in_root(cfg["db_path"]), cfg["mode"], venue).set_backtest_accuracy(
            symbol, tf, pred_len, quality["hits"], quality["n"])
    if args.optimize:
        optimize(df, signals, cfg, symbol, s, segs, quality, log, prog, tf, tag)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--tf", default=None)
    ap.add_argument("--candles", type=int, default=1000, help="jumlah candle yang diuji")
    ap.add_argument("--every", type=int, default=1, help="meramal tiap N candle (lebih besar = lebih cepat)")
    ap.add_argument("--csv", default=None, help="file CSV sendiri (kolom timestamps,open,high,low,close,volume)")
    ap.add_argument("--optimize", "--optimasi", dest="optimize", action="store_true", help="cari setelan terbaik")
    ap.add_argument("--device", default=None, help="auto | gpu | cpu")
    ap.add_argument("--batch", type=int, default=0, help="titik waktu yang diramal sekaligus (0 = otomatis)")
    ap.add_argument("--folds", type=int, default=0, help="jumlah segmen waktu (0 = otomatis)")
    ap.add_argument("--end", default=None, help="uji periode yang berakhir di tanggal ini (YYYY-MM-DD), bukan sekarang")
    ap.add_argument("--dummy", action="store_true")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    full = load_config(args.config)
    log = setup_logging("backtest")
    symbols = args.symbols or [full["crypto"]["symbols"][0]]
    prog = Progress(log, len(symbols))
    box = {}
    failed = []
    for k, sym in enumerate(symbols):
        prog.k = k
        try:
            run_symbol(sym, full, args, log, prog, box)
        except (SystemExit, Exception) as e:  # noqa: BLE001
            if len(symbols) == 1:
                raise
            log.error("%s dilewati: %s", sym, e)
            failed.append(sym)
    prog.k = len(symbols) - 1
    prog(1.0, "selesai")
    if failed and len(failed) == len(symbols):
        raise SystemExit("Semua pair gagal diuji.")
    log.info("SELESAI")


if __name__ == "__main__":
    main()
