"""
Uji strategi di data masa lalu (biasanya dijalankan dari panel, menu Uji strategi).

    python backtest.py BTC/USDT --candles 500
    python backtest.py EURUSD --candles 800 --optimasi       # forex + cari setelan terbaik
    python backtest.py BTC/USDT --dummy                       # uji alur cepat dengan ramalan acak

Model hanya melihat data SEBELUM tiap titik keputusan (walk-forward), jadi tidak "mengintip" masa depan.
Ramalan disimpan ke cache, sehingga menguji ulang dengan setelan berbeda berjalan instan.
Akurasi arah ramalan disimpan ke rapor akurasi robot.

Optimasi: setelan dicari di 70% data awal (periode LATIH), lalu dinilai di 30% data akhir (periode UJI)
yang tidak dipakai saat mencari. Hasil periode UJI adalah gambaran yang lebih jujur.
"""
import argparse
import hashlib
import itertools
import json
import time

import numpy as np
import pandas as pd

from bot.config import load_config, path_in_root, setup_logging, venue_cfg
from bot.forecast import Signal, build_signal, make_forecaster
from bot.forex import base_quote, contract_size, round_down
from bot.strategy import entry_side, exit_levels, price_exit, sgn, signal_exit, strat, trail, venue_of

OUT = path_in_root("data/backtest/x").parent


def safe(symbol):
    return symbol.replace("/", "")


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
    key = {k: m.get(k) for k in ["name", "lookback", "pred_len", "n_paths", "temperature", "top_p"]}
    key |= {"fee": s["fee_pct"], "trend": s["trend_period"], "dummy": dummy, "v": 3}
    h = hashlib.md5(json.dumps(key, sort_keys=True).encode()).hexdigest()[:8]
    return OUT / f"cache_{safe(symbol)}_{tf}_{h}.json"


def compute_signals(df, symbol, cfg, s, forecaster, start, every, future, cache_file, log):
    m = cfg["model"]
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    lookback, pred_len = int(m["lookback"]), int(m["pred_len"])
    todo = [t for t in range(start, len(df))
            if (t - start) % every == 0 and str(int(df["ts"].iloc[t - 1])) not in cache]
    if todo:
        log.info("Meramal %d titik (sisanya dari cache %d)...", len(todo), len(cache))
    t0 = time.time()
    for i, t in enumerate(todo, 1):
        hist = df.iloc[t - lookback:t].reset_index(drop=True)
        y_ts = future(hist["timestamps"].iloc[-1], pred_len)
        sig = build_signal(symbol, hist, forecaster.paths(hist, y_ts), s["fee_pct"], int(s["trend_period"]))
        cache[str(int(hist["ts"].iloc[-1]))] = sig.__dict__
        if i % 10 == 0 or i == len(todo):
            el = time.time() - t0
            log.info("  Progres %d/%d (%.0f%%) | sisa ~%.1f menit", i, len(todo), i / len(todo) * 100,
                     el / i * (len(todo) - i) / 60)
            cache_file.write_text(json.dumps(cache))
    known = set(Signal.__dataclass_fields__)
    return {int(k): Signal(**{a: b for a, b in v.items() if a in known}) for k, v in cache.items()}


# ============================================================ simulasi
def q2usd(symbol, price):
    b, q = base_quote(symbol)
    if q == "USD":
        return 1.0
    if b == "USD":
        return 1.0 / price
    return 1.0   # silang (mis. EURGBP): perkiraan


def simulate(df, signals, cfg, symbol, s, start, end, every):
    venue = venue_of(symbol)
    r, p, fx = cfg["risk"], cfg["paper"], cfg.get("forex") or {}
    fee, slip = s["fee_pct"] / 100, p["slippage_pct"] / 100
    cash = start_cash = float(p["starting_balance"])
    O, H, L, C, TS = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "ts"))
    times = df["timestamps"].to_numpy()
    pos, trades, eq, cooldown_until, skipped = None, [], [], -1, 0

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
            px = px * (1 - k * fee / 2)
            pnl = pos["units"] * (px - pos["entry"]) * k * q2usd(symbol, px)
            cash += pnl
            pct = (px / pos["entry"] - 1) * 100 * k
        trades.append({"side": pos["side"], "entry_time": times[pos["i"]], "entry_price": pos["entry"],
                       "exit_time": times[t], "exit_price": px, "cost": pos["cost"], "pnl": pnl, "pnl_pct": pct,
                       "held": t - pos["i"], "exit_reason": why})
        pos = None

    for t in range(start, end):
        o, h, lo, c = O[t], H[t], L[t], C[t]
        sig = signals.get(int(TS[t - 1])) if (t - start) % every == 0 else None
        # keputusan dibuat saat candle t-1 tutup, dieksekusi di harga open candle t
        if pos is not None:
            hit, why = signal_exit(t - pos["i"], sig, pos["side"], s)
            if hit:
                close(t, o, why)
                cooldown_until = t + int(s["cooldown_candles"])
        if pos is None and sig is not None and t >= cooldown_until:
            side, _ = entry_side(sig, s)
            if side:
                k = sgn(side)
                equity = cash
                if venue == "crypto":
                    cost = min(float(r["order_size_quote"]), float(r["max_order_size_quote"]), cash)
                    px = o * (1 + slip)
                    if cost > 0:
                        sl, tp = exit_levels(px, side, sig, s)
                        cash -= cost
                        pos = {"i": t, "side": side, "entry": px, "units": cost * (1 - fee) / px, "cost": cost,
                               "sl": sl, "tp": tp, "best": px}
                else:
                    px = o * (1 + k * fee / 2)
                    sl, tp = exit_levels(px, side, sig, s)
                    lot = contract_size(symbol)
                    units = equity * float(fx.get("risk_pct", 1.0)) / 100 / (abs(px - sl) * q2usd(symbol, px))
                    units = round_down(min(units, float(fx.get("max_lots", 1.0)) * lot), 0.01 * lot)
                    if units > 0:
                        margin = units * px * q2usd(symbol, px) / max(1.0, float(fx.get("leverage", 100)))
                        pos = {"i": t, "side": side, "entry": px, "units": units, "cost": margin,
                               "sl": sl, "tp": tp, "best": px}
                    else:
                        skipped += 1
        # stop-loss / take-profit / trailing di dalam candle t
        if pos is not None:
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
    return pd.DataFrame(trades), curve, start_cash, skipped


def metrics(trades, curve, start_cash):
    eqv = curve["equity"]
    n = len(trades)
    return {
        "return_pct": float((eqv.iloc[-1] / start_cash - 1) * 100),
        "buyhold_pct": float((curve["close"].iloc[-1] / curve["close"].iloc[0] - 1) * 100),
        "max_dd_pct": float(((eqv / eqv.cummax()) - 1).min() * 100),
        "trades": n,
        "win_pct": float((trades["pnl"] > 0).mean() * 100) if n else 0.0,
        "avg_trade_pct": float(trades["pnl_pct"].mean()) if n else 0.0,
        "longs": int((trades["side"] == "long").sum()) if n else 0,
        "shorts": int((trades["side"] == "short").sum()) if n else 0,
    }


def forecast_accuracy(df, signals, pred_len):
    """Seberapa sering arah ramalan benar (terlepas dari strategi)."""
    idx = {int(ts): i for i, ts in enumerate(df["ts"])}
    hits, n, errs = 0, 0, []
    for ts, sig in signals.items():
        i = idx.get(ts)
        if i is None or i + pred_len >= len(df) or sig.exp_ret_pct == 0:
            continue
        actual = (df["close"].iloc[i + pred_len] / sig.last_close - 1) * 100
        if actual == 0:
            continue
        hits += (actual > 0) == (sig.exp_ret_pct > 0)
        errs.append(abs(actual - sig.exp_ret_pct))
        n += 1
    return hits, n, (float(np.mean(errs)) if errs else float("nan"))


# ============================================================ optimasi
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


def optimize(df, signals, cfg, symbol, base, start, every, log, tf, tag=""):
    venue = venue_of(symbol)
    split = start + int((len(df) - start) * 0.7)
    grid = GRIDS[venue]
    combos = [dict(zip(grid, v)) for v in itertools.product(*grid.values())]
    log.info("Optimasi: mencoba %d kombinasi setelan...", len(combos))

    def run(s, a, b):
        tr, cv, sc, _ = simulate(df, signals, cfg, symbol, s, a, b, every)
        return metrics(tr, cv, sc)

    rows = []
    for i, cb in enumerate(combos, 1):
        s = apply_params(base, cb)
        m = run(s, start, split)
        rows.append({"params": {k: s[k] for k in PARAM_KEYS}, "latih": m,
                     "nilai": m["return_pct"] - 0.5 * abs(m["max_dd_pct"]) if m["trades"] >= 3 else -1e9,
                     "_s": s})
        if i % 50 == 0:
            log.info("  Progres optimasi %d/%d (%.0f%%)", i, len(combos), i / len(combos) * 100)
    rows.sort(key=lambda x: x["nilai"], reverse=True)
    top = [r for r in rows if r["nilai"] > -1e9][:10]
    for r in top:
        r["uji"] = run(r.pop("_s"), split, len(df))
    cur = dict(base, min_accuracy=0)
    current = {"params": {k: cur.get(k) for k in PARAM_KEYS}, "latih": run(cur, start, split),
               "uji": run(cur, split, len(df))}
    res = {"symbol": symbol, "venue": venue, "tf": tf, "dibuat": time.strftime("%Y-%m-%d %H:%M"),
           "periode_latih": [str(df["timestamps"].iloc[start]), str(df["timestamps"].iloc[split - 1])],
           "periode_uji": [str(df["timestamps"].iloc[split]), str(df["timestamps"].iloc[-1])],
           "setelan_sekarang": current, "terbaik": [{k: v for k, v in r.items() if k != "nilai"} for r in top]}
    path = OUT / f"{safe(symbol)}_{tf}{tag}_optimasi.json"
    path.write_text(json.dumps(res, indent=1, default=str))
    log.info("Setelan sekarang  : latih %+.2f%% | uji %+.2f%%", current["latih"]["return_pct"],
             current["uji"]["return_pct"])
    for j, r in enumerate(top[:5], 1):
        log.info("Kandidat #%d       : latih %+.2f%% | uji %+.2f%% (%d trade)", j, r["latih"]["return_pct"],
                 r["uji"]["return_pct"], r["uji"]["trades"])


# ============================================================ laporan
def report(symbol, tf, trades, curve, start_bal, acc, log, tag, skipped):
    m = metrics(trades, curve, start_bal)
    hits, n, err = acc
    lines = [
        f"Uji {symbol} {tf} | {curve['timestamps'].iloc[0]} s/d {curve['timestamps'].iloc[-1]}",
        f"  Akurasi arah ramalan : {hits / n if n else float('nan'):.1%} dari {n} ramalan (rata-rata meleset {err:.2f} poin %)",
        f"  Jumlah trade         : {m['trades']} (buy {m['longs']}, sell {m['shorts']})  | menang {m['win_pct']:.0f}%",
        f"  Hasil robot          : {m['return_pct']:+.2f}%  (saldo {start_bal:.2f} -> {curve['equity'].iloc[-1]:.2f})",
        f"  Beli & tahan saja    : {m['buyhold_pct']:+.2f}%   (pembanding)",
        f"  Penurunan terdalam   : {m['max_dd_pct']:.2f}%",
    ]
    if m["trades"]:
        lines.append(f"  Rata-rata per trade  : {m['avg_trade_pct']:+.2f}% | lama {trades['held'].mean():.1f} candle")
        reasons = trades["exit_reason"].str.replace(r"\s*[\d(].*$", "", regex=True).value_counts()
        lines.append("  Alasan tutup         : " + ", ".join(f"{k} {v}" for k, v in reasons.items()))
    if skipped:
        lines.append(f"  Dilewati             : {skipped} sinyal (modal terlalu kecil untuk 0,01 lot)")
    for ln in lines:
        log.info(ln)
    base = OUT / f"{safe(symbol)}_{tf}{tag}"
    trades.to_csv(f"{base}_trades.csv", index=False)
    curve.to_csv(f"{base}_equity.csv", index=False)
    meta = {"symbol": symbol, "venue": venue_of(symbol), "tf": tf, "metrics": m,
            "accuracy": {"hits": hits, "n": n, "hit": hits / n if n else None, "err": err}}
    (OUT / f"{safe(symbol)}_{tf}{tag}_meta.json").write_text(json.dumps(meta, default=str))
    (OUT / f"{safe(symbol)}_{tf}{tag}_ringkasan.txt").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default=None)
    ap.add_argument("--tf", default=None)
    ap.add_argument("--candles", type=int, default=500, help="jumlah candle yang diuji")
    ap.add_argument("--every", type=int, default=1, help="meramal tiap N candle (lebih besar = lebih cepat)")
    ap.add_argument("--csv", default=None, help="file CSV sendiri (kolom timestamps,open,high,low,close,volume)")
    ap.add_argument("--optimasi", action="store_true", help="cari setelan terbaik otomatis")
    ap.add_argument("--dummy", action="store_true")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    full = load_config(args.config)
    log = setup_logging("backtest")
    symbol = args.symbol or full["crypto"]["symbols"][0]
    venue = venue_of(symbol)
    cfg = venue_cfg(full, venue)
    tf = args.tf or cfg["timeframe"]
    cfg["timeframe"] = tf
    s = strat(cfg, venue)
    lookback, pred_len = int(cfg["model"]["lookback"]), int(cfg["model"]["pred_len"])

    log.info("Mengambil data %s %s...", symbol, tf)
    df, data = load_candles(cfg, symbol, tf, args.candles + lookback, args.csv)
    if len(df) < lookback + 20:
        raise SystemExit(f"Data terlalu sedikit ({len(df)} candle). Untuk forex 15/30 menit, Yahoo hanya "
                         "menyediakan ±60 hari; kurangi jumlah candle atau pakai timeframe lebih besar.")
    if data is not None:
        future = lambda last, n: data.future_ts(last, tf, n)  # noqa: E731
    else:
        step = pd.Timedelta(milliseconds=int(df["ts"].diff().median()))
        future = lambda last, n: pd.Series([last + step * (i + 1) for i in range(n)])  # noqa: E731
    start = max(lookback, len(df) - args.candles)

    forecaster = make_forecaster(cfg, dummy=args.dummy)
    cfile = cache_path(symbol, tf, cfg, s, args.dummy)
    signals = compute_signals(df, symbol, cfg, s, forecaster, start, args.every, future, cfile, log)
    run_s = dict(s, min_accuracy=0)
    trades, curve, bal, skipped = simulate(df, signals, cfg, symbol, run_s, start, len(df), args.every)
    acc = forecast_accuracy(df, signals, pred_len)
    tag = "_dummy" if args.dummy else ""
    report(symbol, tf, trades, curve, bal, acc, log, tag, skipped)
    if not args.dummy and acc[1]:
        from bot.store import Store
        Store(path_in_root(cfg["db_path"]), cfg["mode"], venue).set_backtest_accuracy(symbol, tf, pred_len, acc[0], acc[1])
    if args.optimasi:
        optimize(df, signals, cfg, symbol, s, start, args.every, log, tf, tag)
    log.info("SELESAI")


if __name__ == "__main__":
    main()
