"""
Uji strategi di data masa lalu (biasanya dijalankan dari Panel Kontrol, menu Uji Strategi).

    python backtest.py BTC/USDT --candles 500
    python backtest.py BTC/USDT --candles 800 --optimasi     # cari setelan terbaik otomatis
    python backtest.py BTC/USDT --dummy                      # uji alur cepat dengan ramalan acak

Model hanya melihat data SEBELUM tiap titik keputusan (walk-forward), jadi tidak "mengintip" masa depan.
Ramalan disimpan ke cache, sehingga mengubah setelan jual/beli lalu menguji ulang berjalan instan.

Optimasi: setelan dicari di 70% data awal (periode LATIH), lalu dinilai di 30% data akhir
(periode UJI) yang tidak dipakai saat mencari. Hasil periode UJI adalah gambaran yang lebih jujur.
"""
import argparse
import hashlib
import itertools
import json
import time

import numpy as np
import pandas as pd

from bot.config import load_config, path_in_root, setup_logging
from bot.forecast import Signal, build_signal, make_forecaster
from bot.market import fetch_history, future_timestamps, make_exchange, tf_ms
from bot.strategy import entry_decision, exit_levels, opt, price_exit, signal_exit, trail

OUT = path_in_root("data/backtest/x").parent


# ============================================================ data & ramalan
def load_candles(cfg, symbol, tf, n, csv):
    if csv:
        df = pd.read_csv(csv)
        df["timestamps"] = pd.to_datetime(df["timestamps"])
        if "ts" not in df:
            df["ts"] = (df["timestamps"] - pd.Timestamp("1970-01-01 07:00")) // pd.Timedelta(milliseconds=1)
        if "amount" not in df:
            df["amount"] = df["close"] * df["volume"]
        return df.reset_index(drop=True), None
    ex = make_exchange(cfg)
    df = fetch_history(ex, symbol, tf, n)
    df.to_csv(OUT / f"candles_{symbol.replace('/', '')}_{tf}.csv", index=False)
    return df, ex


def cache_path(symbol, tf, cfg, dummy):
    m = cfg["model"]
    key = {k: m.get(k) for k in ["name", "lookback", "pred_len", "n_paths", "temperature", "top_p"]}
    key |= {"fee": cfg["strategy"]["fee_pct"], "trend": opt(cfg["strategy"], "trend_period"), "dummy": dummy, "v": 2}
    h = hashlib.md5(json.dumps(key, sort_keys=True).encode()).hexdigest()[:8]
    return OUT / f"cache_{symbol.replace('/', '')}_{tf}_{h}.json"


def compute_signals(df, symbol, cfg, forecaster, start, every, step_ms, cache_file, log):
    m, s = cfg["model"], cfg["strategy"]
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    lookback, pred_len = int(m["lookback"]), int(m["pred_len"])
    todo = [t for t in range(start, len(df))
            if (t - start) % every == 0 and str(int(df["ts"].iloc[t - 1])) not in cache]
    if todo:
        log.info("Meramal %d titik (sisanya dari cache %d)...", len(todo), len(cache))
    t0 = time.time()
    for i, t in enumerate(todo, 1):
        hist = df.iloc[t - lookback:t].reset_index(drop=True)
        y_ts = future_timestamps(hist["timestamps"].iloc[-1], step_ms, pred_len)
        sig = build_signal(symbol, hist, forecaster.paths(hist, y_ts), s["fee_pct"], int(opt(s, "trend_period")))
        cache[str(int(hist["ts"].iloc[-1]))] = sig.__dict__
        if i % 10 == 0 or i == len(todo):
            el = time.time() - t0
            log.info("  Progres %d/%d (%.0f%%) | sisa ~%.1f menit", i, len(todo), i / len(todo) * 100,
                     el / i * (len(todo) - i) / 60)
            cache_file.write_text(json.dumps(cache))
    return {int(k): Signal(**v) for k, v in cache.items()}


# ============================================================ simulasi
def simulate(df, signals, cfg, s, start, end, every):
    r, p = cfg["risk"], cfg["paper"]
    fee, slip = s["fee_pct"] / 100, p["slippage_pct"] / 100
    size = min(float(r["order_size_quote"]), float(r["max_order_size_quote"]))
    cash = start_cash = float(p["starting_balance"])
    O, H, L, C, TS = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "ts"))
    times = df["timestamps"].to_numpy()
    pos, trades, eq, cooldown_until = None, [], [], -1

    def sell(t, px, why):
        nonlocal cash, pos
        px = px * (1 - slip)
        proceeds = pos["amount"] * px * (1 - fee)
        cash += proceeds
        trades.append({"entry_time": times[pos["i"]], "entry_price": pos["entry"], "exit_time": times[t],
                       "exit_price": px, "cost": size, "pnl": proceeds - size,
                       "pnl_pct": (proceeds / size - 1) * 100, "held": t - pos["i"], "exit_reason": why})
        pos = None

    for t in range(start, end):
        o, h, l, c = O[t], H[t], L[t], C[t]
        new_sig = signals.get(int(TS[t - 1])) if (t - start) % every == 0 else None
        # keputusan dibuat saat candle t-1 tutup, dieksekusi di harga open candle t
        if pos is not None:
            hit, why = signal_exit(t - pos["i"], new_sig, s)
            if hit:
                sell(t, o, why)
                cooldown_until = t + int(s["cooldown_candles"])
        if pos is None and new_sig is not None and t >= cooldown_until and cash >= size:
            ok, _ = entry_decision(new_sig, s)
            if ok:
                px = o * (1 + slip)
                sl, tp = exit_levels(px, new_sig, s)
                cash -= size
                pos = {"i": t, "entry": px, "amount": size * (1 - fee) / px, "sl": sl, "tp": tp, "peak": px}
        # stop-loss / take-profit / trailing di dalam candle t
        if pos is not None:
            px, why = price_exit(pos["entry"], pos["sl"], pos["tp"], o if t > pos["i"] else pos["entry"], h, l)
            if px is not None:
                sell(t, px, why)
                cooldown_until = t + int(s["cooldown_candles"])
            else:
                pos["peak"] = max(pos["peak"], h)
                pos["sl"] = trail(pos["entry"], pos["peak"], pos["sl"], s)
        eq.append(cash + (pos["amount"] * c if pos else 0.0))

    if pos is not None:
        sell(end - 1, C[end - 1], "akhir periode")
        eq[-1] = cash
    curve = pd.DataFrame({"timestamps": times[start:end], "close": C[start:end], "equity": eq})
    return pd.DataFrame(trades), curve, start_cash


def metrics(trades, curve, start_cash):
    eq = curve["equity"]
    n = len(trades)
    return {
        "return_pct": float((eq.iloc[-1] / start_cash - 1) * 100),
        "buyhold_pct": float((curve["close"].iloc[-1] / curve["close"].iloc[0] - 1) * 100),
        "max_dd_pct": float(((eq / eq.cummax()) - 1).min() * 100),
        "trades": n,
        "win_pct": float((trades["pnl"] > 0).mean() * 100) if n else 0.0,
        "avg_trade_pct": float(trades["pnl_pct"].mean()) if n else 0.0,
    }


def forecast_accuracy(df, signals, pred_len):
    """Seberapa sering arah ramalan benar (terlepas dari strategi)."""
    idx = {int(ts): i for i, ts in enumerate(df["ts"])}
    hits, n, errs = 0, 0, []
    for ts, sig in signals.items():
        i = idx.get(ts)
        if i is None or i + pred_len >= len(df):
            continue
        actual = (df["close"].iloc[i + pred_len] / sig.last_close - 1) * 100
        hits += (actual > 0) == (sig.exp_ret_pct > 0)
        errs.append(abs(actual - sig.exp_ret_pct))
        n += 1
    return (hits / n if n else float("nan")), (float(np.mean(errs)) if errs else float("nan")), n


# ============================================================ optimasi
GRID = {
    "min_expected_return_pct": [0.3, 0.6, 1.0, 1.5],
    "min_prob_up": [0.55, 0.65, 0.75],
    "stops": [("persen", 1.5, 3.0), ("persen", 2.0, 4.0), ("persen", 3.0, 6.0),
              ("atr", 1.5, 3.0), ("atr", 2.0, 4.0), ("atr", 3.0, 6.0)],
    "trailing": [None, (1.0, 0.8), (2.0, 1.5)],
    "trend_filter": [True, False],
}


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
    if combo["trailing"] is None:
        s["trailing_on"] = False
    else:
        s["trailing_on"] = True
        s["trail_activate_pct"], s["trail_pct"] = combo["trailing"]
    s["trend_filter"] = combo["trend_filter"]
    return s


def optimize(df, signals, cfg, start, every, log, symbol, tf, tag=""):
    split = start + int((len(df) - start) * 0.7)
    base = {**{k: opt(cfg["strategy"], k) for k in
               ("trend_filter", "trend_period", "rsi_max", "min_rr", "sl_mode", "sl_atr_mult", "tp_atr_mult",
                "trailing_on", "trail_activate_pct", "trail_pct")}, **cfg["strategy"]}
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]
    log.info("Optimasi: mencoba %d kombinasi setelan...", len(combos))

    def run(s, a, b):
        tr, cv, sc = simulate(df, signals, cfg, s, a, b, every)
        return metrics(tr, cv, sc)

    rows = []
    for i, cb in enumerate(combos, 1):
        s = apply_params(base, cb)
        m = run(s, start, split)
        rows.append({"params": s, "latih": m,
                     "nilai": m["return_pct"] - 0.5 * abs(m["max_dd_pct"]) if m["trades"] >= 3 else -1e9})
        if i % 50 == 0:
            log.info("  Progres optimasi %d/%d (%.0f%%)", i, len(combos), i / len(combos) * 100)
    rows.sort(key=lambda x: x["nilai"], reverse=True)
    top = [r for r in rows if r["nilai"] > -1e9][:10]
    for r in top:
        r["uji"] = run(r["params"], split, len(df))
    current = {"params": base, "latih": run(base, start, split), "uji": run(base, split, len(df))}
    res = {
        "symbol": symbol, "tf": tf, "dibuat": time.strftime("%Y-%m-%d %H:%M"),
        "periode_latih": [str(df["timestamps"].iloc[start]), str(df["timestamps"].iloc[split - 1])],
        "periode_uji": [str(df["timestamps"].iloc[split]), str(df["timestamps"].iloc[-1])],
        "setelan_sekarang": current, "terbaik": top,
    }
    path = OUT / f"{symbol.replace('/', '')}_{tf}{tag}_optimasi.json"
    path.write_text(json.dumps(res, indent=1, default=str))
    log.info("Setelan sekarang  : latih %+.2f%% | uji %+.2f%%", current["latih"]["return_pct"],
             current["uji"]["return_pct"])
    for j, r in enumerate(top[:5], 1):
        log.info("Kandidat #%d       : latih %+.2f%% | uji %+.2f%% (%d trade)", j, r["latih"]["return_pct"],
                 r["uji"]["return_pct"], r["uji"]["trades"])
    log.info("Hasil optimasi disimpan: %s", path)


# ============================================================ laporan
def report(symbol, tf, trades, curve, start_bal, acc, log, tag):
    m = metrics(trades, curve, start_bal)
    lines = [
        f"Uji {symbol} {tf} | {curve['timestamps'].iloc[0]} s/d {curve['timestamps'].iloc[-1]}",
        f"  Akurasi arah ramalan : {acc[0]:.1%} dari {acc[2]} ramalan (rata-rata meleset {acc[1]:.2f} poin %)",
        f"  Jumlah trade         : {m['trades']}  | menang {m['win_pct']:.0f}%",
        f"  Hasil robot          : {m['return_pct']:+.2f}%  (saldo {start_bal:.2f} -> {curve['equity'].iloc[-1]:.2f})",
        f"  Beli & tahan saja    : {m['buyhold_pct']:+.2f}%   (pembanding)",
        f"  Penurunan terdalam   : {m['max_dd_pct']:.2f}%",
    ]
    if m["trades"]:
        lines.append(f"  Rata-rata per trade  : {m['avg_trade_pct']:+.2f}% | lama {trades['held'].mean():.1f} candle")
        reasons = trades["exit_reason"].str.replace(r"\s*[\d(].*$", "", regex=True).value_counts()
        lines.append("  Alasan jual          : " + ", ".join(f"{k} {v}" for k, v in reasons.items()))
    for ln in lines:
        log.info(ln)
    base = OUT / f"{symbol.replace('/', '')}_{tf}{tag}"
    trades.to_csv(f"{base}_trades.csv", index=False)
    curve.to_csv(f"{base}_equity.csv", index=False)
    (OUT / f"{symbol.replace('/', '')}_{tf}{tag}_ringkasan.txt").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default=None)
    ap.add_argument("--tf", default=None)
    ap.add_argument("--candles", type=int, default=500, help="jumlah candle yang diuji")
    ap.add_argument("--every", type=int, default=1, help="meramal tiap N candle (lebih besar = lebih cepat)")
    ap.add_argument("--csv", default=None, help="pakai file CSV sendiri (kolom timestamps,open,high,low,close,volume)")
    ap.add_argument("--optimasi", action="store_true", help="cari setelan terbaik otomatis")
    ap.add_argument("--dummy", action="store_true")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    log = setup_logging("backtest")
    symbol = args.symbol or cfg["symbols"][0]
    tf = args.tf or cfg["timeframe"]
    cfg["timeframe"] = tf
    lookback, pred_len = int(cfg["model"]["lookback"]), int(cfg["model"]["pred_len"])

    log.info("Mengambil data %s %s...", symbol, tf)
    df, ex = load_candles(cfg, symbol, tf, args.candles + lookback, args.csv)
    if len(df) < lookback + 20:
        raise SystemExit(f"Data terlalu sedikit ({len(df)} candle).")
    step_ms = tf_ms(ex, tf) if ex else int(df["ts"].diff().median())
    start = max(lookback, len(df) - args.candles)

    forecaster = make_forecaster(cfg, dummy=args.dummy)
    cfile = cache_path(symbol, tf, cfg, args.dummy)
    signals = compute_signals(df, symbol, cfg, forecaster, start, args.every, step_ms, cfile, log)
    s = {**{k: opt(cfg["strategy"], k) for k in ("trend_filter", "trend_period", "rsi_max", "min_rr", "sl_mode",
                                                   "sl_atr_mult", "tp_atr_mult", "trailing_on",
                                                   "trail_activate_pct", "trail_pct")}, **cfg["strategy"]}
    trades, curve, bal = simulate(df, signals, cfg, s, start, len(df), args.every)
    acc = forecast_accuracy(df, signals, pred_len)
    report(symbol, tf, trades, curve, bal, acc, log, "_dummy" if args.dummy else "")
    if args.optimasi:
        optimize(df, signals, cfg, start, args.every, log, symbol, tf, "_dummy" if args.dummy else "")
    log.info("SELESAI")


if __name__ == "__main__":
    main()
