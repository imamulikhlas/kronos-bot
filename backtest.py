"""
Backtest: uji strategi Kronos di data masa lalu SEBELUM memakai uang sungguhan.

    python backtest.py BTC/USDT --candles 500          # 500 candle terakhir (timeframe dari config)
    python backtest.py ETH/USDT --tf 4h --candles 300
    python backtest.py BTC/USDT --dummy                # uji alur cepat dengan ramalan acak

Model hanya melihat data SEBELUM tiap titik keputusan (walk-forward), jadi tidak "mengintip" masa depan.
Ramalan disimpan ke cache, sehingga mengubah angka strategy di config.yaml lalu backtest ulang
berjalan instan (tidak perlu meramal ulang). Hasil: folder data/backtest/.
"""
import argparse
import hashlib
import json
import time

import numpy as np
import pandas as pd

from bot.config import load_config, path_in_root, setup_logging
from bot.forecast import Signal, build_signal, make_forecaster
from bot.market import fetch_history, future_timestamps, make_exchange, tf_ms
from bot.strategy import entry_decision, price_exit, signal_exit

OUT = path_in_root("data/backtest/x").parent


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


def cache_path(symbol, tf, mcfg, fee, dummy):
    key = json.dumps({k: mcfg.get(k) for k in ["name", "lookback", "pred_len", "n_paths", "temperature", "top_p"]}
                     | {"fee": fee, "dummy": dummy}, sort_keys=True)
    h = hashlib.md5(key.encode()).hexdigest()[:8]
    return OUT / f"cache_{symbol.replace('/', '')}_{tf}_{h}.json"


def compute_signals(df, symbol, cfg, forecaster, start, every, step_ms, cache_file, log):
    m, fee = cfg["model"], cfg["strategy"]["fee_pct"]
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    lookback, pred_len = int(m["lookback"]), int(m["pred_len"])
    todo = [t for t in range(start, len(df)) if (t - start) % every == 0 and str(int(df["ts"].iloc[t - 1])) not in cache]
    if todo:
        log.info("Meramal %d titik (sisanya dari cache %d)...", len(todo), len(cache))
    t0 = time.time()
    for i, t in enumerate(todo, 1):
        hist = df.iloc[t - lookback:t].reset_index(drop=True)
        y_ts = future_timestamps(hist["timestamps"].iloc[-1], step_ms, pred_len)
        sig = build_signal(symbol, hist, forecaster.paths(hist, y_ts), fee)
        cache[str(int(hist["ts"].iloc[-1]))] = sig.__dict__
        if i % 10 == 0 or i == len(todo):
            el = time.time() - t0
            log.info("  %d/%d selesai | sisa ~%.1f menit", i, len(todo), el / i * (len(todo) - i) / 60)
            cache_file.write_text(json.dumps(cache))
    return {int(k): Signal(**v) for k, v in cache.items()}


def simulate(df, signals, cfg, start, every):
    s, r, p = cfg["strategy"], cfg["risk"], cfg["paper"]
    fee, slip = s["fee_pct"] / 100, p["slippage_pct"] / 100
    size = min(float(r["order_size_quote"]), float(r["max_order_size_quote"]))
    cash = float(p["starting_balance"])
    pos, trades, curve, cooldown_until = None, [], [], -1
    last_sig = None

    def sell(t, px, why):
        nonlocal cash, pos
        px = px * (1 - slip)
        gross = pos["amount"] * px
        proceeds = gross - gross * fee
        cash += proceeds
        trades.append({**pos, "exit_time": df["timestamps"].iloc[t], "exit_price": px,
                       "proceeds": proceeds, "pnl": proceeds - pos["cost"],
                       "pnl_pct": (proceeds / pos["cost"] - 1) * 100, "held": t - pos["i"], "exit_reason": why})
        pos = None

    for t in range(start, len(df)):
        o, h, l, c = (float(df[k].iloc[t]) for k in ("open", "high", "low", "close"))
        key = int(df["ts"].iloc[t - 1])
        new_sig = signals.get(key) if (t - start) % every == 0 else None
        if new_sig is not None:
            last_sig = new_sig
        # 1) keputusan dibuat saat candle t-1 tutup, dieksekusi di open candle t
        if pos is not None:
            hit, why = signal_exit(t - pos["i"], new_sig, s)
            if hit:
                sell(t, o, why)
                cooldown_until = t + int(s["cooldown_candles"])
        if pos is None and new_sig is not None and t >= cooldown_until and cash >= size:
            ok, why = entry_decision(new_sig, s)
            if ok:
                px = o * (1 + slip)
                amount = (size - size * fee) / px
                cash -= size
                pos = {"i": t, "entry_time": df["timestamps"].iloc[t], "entry_price": px,
                       "amount": amount, "cost": size, "entry_reason": why,
                       "exp_ret_pct": new_sig.exp_ret_pct, "prob_up": new_sig.prob_up}
        # 2) stop-loss / take-profit di dalam candle t
        if pos is not None:
            px, why = price_exit(pos["entry_price"], o if t > pos["i"] else pos["entry_price"], h, l, s)
            if px is not None:
                sell(t, px, why)
                cooldown_until = t + int(s["cooldown_candles"])
        value = pos["amount"] * c if pos else 0.0
        curve.append({"timestamps": df["timestamps"].iloc[t], "close": c, "equity": cash + value})

    if pos is not None:
        sell(len(df) - 1, float(df["close"].iloc[-1]), "akhir backtest")
        curve[-1]["equity"] = cash
    return pd.DataFrame(trades), pd.DataFrame(curve)


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


def report(symbol, tf, df, trades, curve, start_bal, acc, log, tag):
    eq = curve["equity"]
    total = (eq.iloc[-1] / start_bal - 1) * 100
    bh = (curve["close"].iloc[-1] / curve["close"].iloc[0] - 1) * 100
    dd = ((eq / eq.cummax()) - 1).min() * 100
    n = len(trades)
    win = (trades["pnl"] > 0).mean() * 100 if n else 0
    lines = [
        f"Backtest {symbol} {tf} | {curve['timestamps'].iloc[0]} s/d {curve['timestamps'].iloc[-1]}",
        f"  Akurasi arah ramalan : {acc[0]:.1%} dari {acc[2]} ramalan (rata-rata meleset {acc[1]:.2f} poin %)",
        f"  Jumlah trade         : {n}  | menang {win:.0f}%",
        f"  Hasil strategi       : {total:+.2f}%  (saldo {start_bal:.2f} -> {eq.iloc[-1]:.2f})",
        f"  Beli & tahan saja    : {bh:+.2f}%   (pembanding)",
        f"  Drawdown terdalam    : {dd:.2f}%",
    ]
    if n:
        lines.append(f"  Rata-rata per trade  : {trades['pnl_pct'].mean():+.2f}% | lama {trades['held'].mean():.1f} candle")
        lines.append("  Alasan keluar        : " + ", ".join(f"{k} {v}" for k, v in trades["exit_reason"].str.split(" ").str[:2].str.join(" ")
                                                           .str.replace(r"\s*\d.*$", "", regex=True).value_counts().items()))
    for ln in lines:
        log.info(ln)
    base = OUT / f"{symbol.replace('/', '')}_{tf}{tag}"
    trades.to_csv(f"{base}_trades.csv", index=False)
    curve.to_csv(f"{base}_equity.csv", index=False)
    (OUT / f"{symbol.replace('/', '')}_{tf}{tag}_ringkasan.txt").write_text("\n".join(lines), encoding="utf-8")
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.6, 0.4], vertical_spacing=0.05,
                            subplot_titles=(f"{symbol} {tf} + titik beli/jual", "Saldo strategi vs beli & tahan"))
        fig.add_trace(go.Scatter(x=curve["timestamps"], y=curve["close"], name="Harga", line=dict(width=1)), 1, 1)
        if n:
            fig.add_trace(go.Scatter(x=trades["entry_time"], y=trades["entry_price"], mode="markers", name="Beli",
                                     marker=dict(symbol="triangle-up", size=10, color="#16a34a")), 1, 1)
            fig.add_trace(go.Scatter(x=trades["exit_time"], y=trades["exit_price"], mode="markers", name="Jual",
                                     text=trades["exit_reason"],
                                     marker=dict(symbol="triangle-down", size=10, color="#dc2626")), 1, 1)
        fig.add_trace(go.Scatter(x=curve["timestamps"], y=eq, name="Strategi"), 2, 1)
        fig.add_trace(go.Scatter(x=curve["timestamps"], y=start_bal * curve["close"] / curve["close"].iloc[0],
                                 name="Beli & tahan", line=dict(dash="dot")), 2, 1)
        fig.update_layout(height=750, template="plotly_white", title="<br>".join(lines[:1] + lines[2:5]))
        fig.write_html(f"{base}_laporan.html")
        log.info("Laporan grafik: %s_laporan.html", base)
    except Exception as e:  # noqa: BLE001
        log.warning("Gagal membuat grafik: %s", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default=None)
    ap.add_argument("--tf", default=None)
    ap.add_argument("--candles", type=int, default=500, help="jumlah candle yang diuji")
    ap.add_argument("--every", type=int, default=1, help="meramal tiap N candle (lebih besar = lebih cepat)")
    ap.add_argument("--csv", default=None, help="pakai file CSV sendiri (kolom timestamps,open,high,low,close,volume)")
    ap.add_argument("--dummy", action="store_true")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    log = setup_logging("backtest")
    symbol = args.symbol or cfg["symbols"][0]
    tf = args.tf or cfg["timeframe"]
    lookback, pred_len = int(cfg["model"]["lookback"]), int(cfg["model"]["pred_len"])

    log.info("Mengambil data %s %s...", symbol, tf)
    df, ex = load_candles(cfg, symbol, tf, args.candles + lookback, args.csv)
    if len(df) < lookback + 20:
        raise SystemExit(f"Data terlalu sedikit ({len(df)} candle).")
    step_ms = tf_ms(ex, tf) if ex else int(df["ts"].diff().median())
    start = max(lookback, len(df) - args.candles)

    forecaster = make_forecaster(cfg, dummy=args.dummy)
    cfile = cache_path(symbol, tf, cfg["model"], cfg["strategy"]["fee_pct"], args.dummy)
    signals = compute_signals(df, symbol, cfg, forecaster, start, args.every, step_ms, cfile, log)
    trades, curve = simulate(df, signals, cfg, start, args.every)
    acc = forecast_accuracy(df, signals, pred_len)
    report(symbol, tf, df, trades, curve, float(cfg["paper"]["starting_balance"]), acc, log,
           "_dummy" if args.dummy else "")


if __name__ == "__main__":
    main()
