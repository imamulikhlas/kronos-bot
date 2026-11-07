"""
PANEL ROBOT TRADING KRONOS (server lokal).
Dibuka otomatis oleh MULAI.bat / mulai.command -> http://localhost:8501
Hanya bisa diakses dari komputer ini (127.0.0.1).

Kripto dan forex punya robot, setelan, saldo simulasi, dan riwayat masing-masing.
Endpoint per market berbentuk /api/{venue}/... dengan venue = crypto | forex.
"""
import json
import os
import socket
import sqlite3
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from bot import control as ctl
from bot.config import KRONOS_DIR, ROOT, VENUES, api_keys, live_unlocked, load_config, path_in_root, venue_cfg
from bot.forecast import Signal, build_signal
from bot.forex import MT5, ForexData, label as fx_label
from bot.indicators import ema, rsi
from bot.store import WIB, Store
from bot.strategy import entry_side, strat, venue_of

PORT = 8501
STATIC = ROOT / "static"
BT_DIR = path_in_root("data/backtest/x").parent
CONFIRM_TEXT = "SAYA PAHAM RISIKONYA"
MODELS = {
    "light": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k"),
    "balanced": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base"),
    "accurate": ("NeoQuasar/Kronos-base", "NeoQuasar/Kronos-Tokenizer-base"),
}
TFS = ("15m", "30m", "1h", "4h", "1d")
TF_SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
POOL = ThreadPoolExecutor(max_workers=6)

app = FastAPI(title="Kronos")


# ===================================================================== utilitas
def full_cfg():
    return load_config()


def vcfg(venue):
    check_venue(venue)
    return venue_cfg(full_cfg(), venue)


def check_venue(venue):
    if venue not in VENUES:
        fail("Market tidak dikenal.", 404)


def db_path():
    return path_in_root(full_cfg()["db_path"])


def q(sql, args=()):
    p = db_path()
    if not p.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(p, timeout=10) as con:
            return pd.read_sql_query(sql, con, params=args)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def store(venue, mode=None):
    c = vcfg(venue)
    return Store(db_path(), mode or c["mode"], venue)


def fail(msg, code=400):
    raise HTTPException(status_code=code, detail=msg)


def records(df: pd.DataFrame):
    return json.loads(df.to_json(orient="records")) if not df.empty else []


def wib_epoch(ts) -> int:
    """Waktu WIB (tanpa zona) -> detik, diperlakukan sebagai UTC agar grafik menampilkan jam WIB."""
    return int(pd.Timestamp(ts).value // 10**9)


def series(times, values):
    """Titik grafik dengan waktu unik & naik (titik terakhir di detik yang sama dipakai)."""
    out = {}
    for t, v in zip(times, values):
        if v is not None and v == v:
            out[wib_epoch(t)] = float(v)
    return [{"time": k, "value": out[k]} for k in sorted(out)]


def display(sym):
    return sym if "/" in sym else fx_label(sym)


VCOL = "COALESCE(venue,'crypto')"

_mk = {"obj": None, "key": None}
_mk_lock = threading.Lock()


def markets():
    """Penghubung data pasar bersama (dibuat ulang jika sumber forex berubah)."""
    from bot.venues import Markets
    c = full_cfg()
    key = (c["crypto"]["exchange"], c["forex"].get("source"), MT5.enabled())
    with _mk_lock:
        if _mk["key"] != key:
            _mk["obj"], _mk["key"] = Markets(venue_cfg(c, "forex")), key
        return _mk["obj"]


def data_for(symbol):
    return markets().data(venue_of(symbol))


_ttl: dict = {}
_ttl_lock = threading.Lock()


def cached(key, ttl, fn):
    with _ttl_lock:
        hit = _ttl.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    with _ttl_lock:
        _ttl[key] = (time.time(), val)
    return val


def price_now(symbol):
    try:
        return cached(("px", symbol), 10, lambda: data_for(symbol).price(symbol))
    except Exception:  # noqa: BLE001
        return None


def candles_df(symbol, tf, n, ttl=20):
    return cached(("ohlcv", symbol, tf, n), ttl, lambda: data_for(symbol).raw(symbol, tf, n))


def sig_dict(sig: Signal, venue_c: dict, source: str):
    venue = venue_of(sig.symbol)
    side, why = entry_side(sig, strat(venue_c, venue))
    d = dict(sig.__dict__)
    d.update(direction=sig.direction, would=side, decision=why, source=source, venue=venue,
             label=display(sig.symbol), t0=wib_epoch(sig.time))
    d["calibrated"] = calibrated(sig, venue_c.get("timeframe"))
    return d


def calibrated(sig: Signal, tf):
    """'Waktu AI seyakin ini di backtest, harga benar-benar naik X% dari N kali.'"""
    p = sig.prob_up_raw if sig.prob_up_raw != 0.5 or not (sig.prob_up + sig.prob_down) else \
        sig.prob_up + (1 - sig.prob_up - sig.prob_down) / 2
    best = None
    for f in BT_DIR.glob(f"{sig.symbol.replace('/', '')}_*_meta.json") if BT_DIR.exists() else []:
        if f.name.endswith("_dummy_meta.json"):
            continue
        try:
            m = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        if tf and m.get("tf") != tf:
            continue
        if best is None or f.stat().st_mtime > best[0]:
            best = (f.stat().st_mtime, m)
    if not best:
        return None
    for b in (best[1].get("quality") or {}).get("calibration") or []:
        if b["from"] <= p < b["to"] or (p >= 1 and b["to"] >= 1):
            return {"p": p, "actual_up": b["actual"], "n": b["n"], "from": b["from"], "to": b["to"]}
    return None


def signal_from_row(row) -> Signal:
    def js(v):
        try:
            return json.loads(v) if v else []
        except Exception:  # noqa: BLE001
            return []
    g = row.get
    last = row["last_close"]
    return Signal(time=row["candle_time"], symbol=row["symbol"], last_close=last,
                  exp_ret_pct=row["exp_ret_pct"], median_ret_pct=g("median_ret_pct") or 0,
                  prob_up=row["prob_up"], prob_down=g("prob_down") or 0.0, pred_high=row["pred_high"],
                  pred_low=row["pred_low"], path=js(row["path"]), path_lo=js(g("path_lo")), path_hi=js(g("path_hi")),
                  trend_up=bool(g("trend_up")) if g("trend_up") is not None else True,
                  trend_down=bool(g("trend_down")) if g("trend_down") is not None else False,
                  rsi=g("rsi") or 50.0, atr_pct=g("atr_pct") or 0.0, rr=g("rr") or 0.0, rr_short=g("rr_short") or 0.0,
                  upside_pct=max(0.0, (row["pred_high"] / last - 1) * 100),
                  downside_pct=max(0.0, (1 - row["pred_low"] / last) * 100),
                  score=g("score") or 0.0, horizon=int(g("horizon") or len(js(row["path"]))))


def acc_for(venue, symbol, tf, horizon):
    try:
        return store(venue).accuracy(symbol, tf, horizon)
    except Exception:  # noqa: BLE001
        return {"hit": None, "n": 0, "live_n": 0, "bt_n": 0}


_forecasts: dict = {}   # (symbol, tf) -> (Signal, waktu)


def latest_signal(venue, symbol, tf):
    """Ramalan terbaru untuk satu pasar: ramalan manual dari panel atau ramalan robot, mana yang lebih baru."""
    c = vcfg(venue)
    hit = _forecasts.get((symbol, tf))
    row = q("SELECT * FROM signals WHERE symbol=? AND (tf=? OR tf IS NULL) ORDER BY id DESC LIMIT 1", (symbol, tf))
    bot_row = row.iloc[0].to_dict() if not row.empty and (row.iloc[0]["tf"] == tf or tf == c["timeframe"]) else None
    if hit and (bot_row is None or hit[1] >= pd.Timestamp(bot_row["created"]).tz_localize(WIB).timestamp()):
        sig, at = hit
        return sig, f"manual forecast {time.strftime('%H:%M', time.localtime(at))}"
    if bot_row is not None:
        sig = signal_from_row(bot_row)
        acc = acc_for(venue, symbol, tf, sig.horizon)
        sig.accuracy, sig.acc_n = acc["hit"], acc["n"]
        return sig, f"auto trading, candle {str(sig.time)[11:16]}"
    return None, ""


# ===================================================================== halaman
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(HTTPException)
def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
def any_error(_, exc: Exception):
    return JSONResponse({"error": f"Terjadi kesalahan: {exc}"}, status_code=500)


# ===================================================================== status
def venue_status(c_full, venue):
    c = venue_cfg(c_full, venue)
    s = Store(db_path(), c["mode"], venue)
    running = ctl.bot_running(venue)
    k, sec = api_keys()
    out = {
        "mode": c["mode"], "running": running, "crashed": ctl.bot_crashed(venue),
        "crash_log": ctl.tail(ctl.bot_console(venue), 25) if ctl.bot_crashed(venue) else "",
        "state": s.vget("bot_state", "berhenti") if running else "berhenti",
        "next_run": s.vget("next_run") if running else None, "paused": bool(s.vget("pause_entries", False)),
        "symbols": [{"symbol": x, "label": display(x)} for x in c["symbols"]], "timeframe": c["timeframe"],
        "max_positions": c["risk"]["max_open_positions"], "live_unlocked": live_unlocked(venue),
        "open_positions": len(s.open_positions()),
    }
    if venue == "crypto":
        out.update(source="tokocrypto", connected=bool(k and sec), market_open=True)
    else:
        src = "mt5" if (MT5.enabled() and MT5.installed() and c_full["forex"].get("source") != "yahoo") else "yahoo"
        out.update(source=src, connected=src == "mt5",
                   market_open=ForexData.market_open(pd.Timestamp.now(tz=WIB).tz_localize(None)))
    return out


@app.get("/api/status")
def status():
    c = full_cfg()
    has_bt = BT_DIR.exists() and any(BT_DIR.glob("*_ringkasan.txt"))
    sig = q(f"SELECT {VCOL} v, COUNT(*) n FROM signals GROUP BY 1")
    has_sig = dict(zip(sig["v"], sig["n"])) if not sig.empty else {}
    out = {"setup_ok": (KRONOS_DIR / "model").exists(), "server_time": int(time.time() * 1000), "markets": {}}
    for v in VENUES:
        out["markets"][v] = {**venue_status(c, v), "has_signals": bool(has_sig.get(v)),
                             "has_backtest": has_bt and any(f.name.startswith(tuple(x.replace("/", "") for x in c[v]["symbols"]))
                                                            for f in BT_DIR.glob("*_ringkasan.txt"))}
    return out


@app.post("/api/{venue}/bot/start")
def bot_start(venue: str):
    c = vcfg(venue)
    if c["mode"] == "live" and not live_unlocked(venue):
        fail("Mode live belum dikonfirmasi. Buka Settings.")
    if not (KRONOS_DIR / "model").exists():
        fail("Setup belum selesai: folder Kronos belum ada. Jalankan MULAI lagi.")
    ctl.start_bot(venue)
    return {"ok": True}


@app.post("/api/{venue}/bot/stop")
def bot_stop(venue: str):
    check_venue(venue)
    ctl.stop_bot(venue)
    store(venue).vset("bot_state", "berhenti")
    return {"ok": True}


@app.post("/api/{venue}/bot/dismiss")
def bot_dismiss(venue: str):
    check_venue(venue)
    ctl.bot_pid(venue).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/{venue}/bot/pause")
def bot_pause(venue: str, value: bool = Body(..., embed=True)):
    store(venue).vset("pause_entries", bool(value))
    return {"ok": True, "paused": bool(value)}


# ===================================================================== overview
def approach(venue, c):
    s, r = strat(c, venue), c["risk"]
    stop = (f"Stop-loss {s['sl_atr_mult']}× dan target {s['tp_atr_mult']}× gerak rata-rata harga (ATR)"
            if s.get("sl_mode") == "atr" else f"Stop-loss −{s['stop_loss_pct']}%, target +{s['take_profit_pct']}%")
    trail = (f"Trailing stop aktif setelah untung {s['trail_activate_pct']}%, jarak {s['trail_pct']}%"
             if s.get("trailing_on") else "Tanpa trailing stop")
    entry = f"Buka posisi kalau ramalan ≥ {s['min_expected_return_pct']}% dan peluang searah ≥ {round(s['min_prob_up'] * 100)}%"
    acc = (f"Hanya pair dengan akurasi ≥ {round(s['min_accuracy'] * 100)}% (setelah {s['min_accuracy_n']} ramalan)"
           if s.get("min_accuracy") else "Tanpa batas akurasi")
    if venue == "crypto":
        return [("Direction", "Spot, hanya Buy. Posisi ditutup dengan Sell."),
                ("Size", f"{r['order_size_quote']:g} USDT per posisi, maksimal {r['max_open_positions']} posisi"),
                ("Entry", entry), ("Exit", f"{stop}. {trail}."), ("Accuracy", acc), ("Market hours", "24 jam, 7 hari")]
    return [("Direction", "Buy dan Sell" if s.get("allow_short") else "Hanya Buy"),
            ("Size", f"Risiko {r['risk_pct']:g}% aset per posisi, lot dihitung otomatis (maks {r['max_lots']:g} lot)"),
            ("Entry", entry), ("Exit", f"{stop}. {trail}."), ("Accuracy", acc),
            ("Market hours", "Senin 04.00 – Sabtu 04.00 WIB. Lewat MT5, SL/TP juga dipasang di server broker.")]


@app.get("/api/{venue}/overview")
def overview(venue: str):
    c = vcfg(venue)
    mode = c["mode"]
    eq = q(f"SELECT time, equity FROM equity WHERE mode=? AND {VCOL}=? ORDER BY id", (mode, venue))
    closed = q(f"SELECT pnl, exit_time FROM positions WHERE mode=? AND status='closed' AND {VCOL}=?", (mode, venue))
    openp = q(f"SELECT * FROM positions WHERE mode=? AND status='open' AND {VCOL}=? ORDER BY id", (mode, venue))
    today = pd.Timestamp.now(tz=WIB).strftime("%Y-%m-%d")
    positions = []
    for p in records(openp):
        side = p.get("side") or "long"
        k = -1 if side == "short" else 1
        now = price_now(p["symbol"])
        p.update(side=side, label=display(p["symbol"]), price_now=now)
        p["pnl_pct_now"] = (now / p["entry_price"] - 1) * 100 * k if now else None
        if now is None:
            p["pnl_now"] = None
        elif venue == "crypto":
            p["pnl_now"] = now * p["amount"] - p["cost"]
        else:
            try:
                p["pnl_now"] = p["amount"] * (now - p["entry_price"]) * k * data_for(p["symbol"]).quote_to_usd(p["symbol"], now)
            except Exception:  # noqa: BLE001
                p["pnl_now"] = None
        positions.append(p)
    sig = q(f"SELECT * FROM signals WHERE mode=? AND {VCOL}=? ORDER BY id DESC LIMIT 300", (mode, venue))
    decisions = []
    if not sig.empty:
        for row in records(sig.drop_duplicates("symbol")):
            if row["symbol"] not in c["symbols"]:
                continue
            acc = acc_for(venue, row["symbol"], c["timeframe"], row.get("horizon") or c["model"]["pred_len"])
            decisions.append({**{k: row.get(k) for k in ("symbol", "candle_time", "last_close", "exp_ret_pct",
                                                          "prob_up", "prob_down", "direction", "action", "reason")},
                              "label": display(row["symbol"]), "accuracy": acc["hit"], "acc_n": acc["n"]})
    ev = q(f"SELECT time, level, message FROM events WHERE mode=? AND {VCOL}=? ORDER BY id DESC LIMIT 25", (mode, venue))
    start_eq = float(eq["equity"].iloc[0]) if not eq.empty else None
    tail = eq.tail(600)
    return {
        "venue": venue, "mode": mode, "balance_start": c["paper"]["starting_balance"],
        "equity": float(eq["equity"].iloc[-1]) if not eq.empty else None,
        "equity_change_pct": (float(eq["equity"].iloc[-1]) / start_eq - 1) * 100 if start_eq else None,
        "pnl_total": float(closed["pnl"].sum()) if not closed.empty else 0.0,
        "pnl_today": float(closed[closed["exit_time"].str.startswith(today)]["pnl"].sum()) if not closed.empty else 0.0,
        "trades": int(len(closed)),
        "win_pct": float((closed["pnl"] > 0).mean() * 100) if not closed.empty else None,
        "max_positions": c["risk"]["max_open_positions"],
        "positions": positions, "decisions": decisions, "events": records(ev),
        "equity_series": series(tail["time"], tail["equity"]),
        "approach": [{"k": k, "v": v} for k, v in approach(venue, c)],
    }


@app.post("/api/{venue}/positions/close")
def close_positions(venue: str, ids: list = Body(..., embed=True)):
    c = vcfg(venue)
    s = store(venue)
    if ctl.bot_running(venue):
        s.vset("close_requests", list(set(s.vget("close_requests", []) + ids)))
        return {"ok": True, "queued": True, "message": "Perintah close dikirim. Robot menutup dalam beberapa detik."}
    from bot.engine import Engine
    from bot.venues import Markets
    eng = Engine(c, s, None, Markets(c, s, live=c["mode"] == "live"))
    n = 0
    for pos in s.open_positions():
        if "ALL" in ids or pos["id"] in ids:
            eng.close(pos, "ditutup manual dari panel")
            n += 1
    return {"ok": True, "queued": False, "message": f"{n} posisi ditutup."}


# ===================================================================== settings
@app.get("/api/{venue}/config")
def get_config(venue: str):
    check_venue(venue)
    c = full_cfg()
    v = c[venue]
    model = next((k for k, m in MODELS.items() if m[0] == c["model"]["name"]), "balanced")
    return {"venue": venue, "symbols": v["symbols"], "watchlist": v["watchlist"], "timeframe": v["timeframe"],
            "mode": v["mode"], "source": v.get("source"), "risk": v["risk"], "paper_balance": v["paper_balance"],
            "strategy": strat(venue_cfg(c, venue), venue),
            "model": {"size": model, "n_paths": c["model"]["n_paths"], "pred_len": c["model"]["pred_len"],
                      "lookback": c["model"]["lookback"], "device": c["model"].get("device", "auto"),
                      "ensemble": bool(c["model"].get("ensemble"))}}


STRAT_TYPES = {"fee_pct": float, "min_expected_return_pct": float, "min_prob_up": float, "stop_loss_pct": float,
               "take_profit_pct": float, "max_hold_candles": int, "exit_prob_up_below": float,
               "cooldown_candles": int, "trend_filter": bool, "trend_period": int, "rsi_max": float, "min_rr": float,
               "sl_mode": str, "sl_atr_mult": float, "tp_atr_mult": float, "trailing_on": bool,
               "trail_activate_pct": float, "trail_pct": float, "min_accuracy": float, "min_accuracy_n": int,
               "require_proof": bool, "allow_short": bool}
RISK_TYPES = {"order_size_quote": float, "max_order_size_quote": float, "max_open_positions": int,
              "max_daily_loss_quote": float, "risk_pct": float, "max_lots": float, "leverage": float}


def clean_symbols(lst, venue):
    out = []
    for x in lst or []:
        x = str(x).strip().upper()
        if x and x not in out and venue_of(x) == venue:
            out.append(x)
    return out


def save_and_restart(c, venue):
    ctl.save_config(c)
    return ctl.restart_if_running(venue)


@app.post("/api/{venue}/config")
def save_config(venue: str, body: dict = Body(...)):
    check_venue(venue)
    c = full_cfg()
    v = c[venue]
    if "symbols" in body:
        syms = clean_symbols(body["symbols"], venue)
        if not syms:
            fail("Pilih minimal satu pair untuk auto trading.")
        v["symbols"] = syms
    if "watchlist" in body:
        v["watchlist"] = clean_symbols(body["watchlist"], venue)
    v["watchlist"] = list(dict.fromkeys(v["watchlist"] + v["symbols"]))
    if body.get("timeframe") in TFS:
        v["timeframe"] = body["timeframe"]
    for k, typ in STRAT_TYPES.items():
        if k in (body.get("strategy") or {}):
            try:
                v["strategy"][k] = typ(body["strategy"][k])
            except (TypeError, ValueError):
                fail(f"Nilai {k} tidak valid.")
    if v["strategy"].get("sl_mode") not in (None, "persen", "atr"):
        v["strategy"]["sl_mode"] = "persen"
    if venue == "crypto":
        v["strategy"].pop("allow_short", None)
    for k, typ in RISK_TYPES.items():
        if k in (body.get("risk") or {}):
            try:
                v["risk"][k] = typ(body["risk"][k])
            except (TypeError, ValueError):
                fail(f"Nilai {k} tidak valid.")
    if "paper_balance" in body:
        v["paper_balance"] = float(body["paper_balance"])
    if venue == "forex" and body.get("source") in ("auto", "mt5", "yahoo"):
        v["source"] = body["source"]
    m = body.get("model") or {}
    if m.get("size") in MODELS:
        c["model"]["name"], c["model"]["tokenizer"] = MODELS[m["size"]]
    for k, lo, hi in (("n_paths", 2, 100), ("pred_len", 2, 120), ("lookback", 64, 2048)):
        if k in m:
            try:
                c["model"][k] = max(lo, min(hi, int(m[k])))
            except (TypeError, ValueError):
                fail(f"Nilai {k} tidak valid.")
    if "mini" not in c["model"]["name"]:
        c["model"]["lookback"] = min(int(c["model"]["lookback"]), 512)
    if m.get("device") in ("auto", "gpu", "cpu"):
        c["model"]["device"] = m["device"]
    if "ensemble" in m:
        c["model"]["ensemble"] = bool(m["ensemble"])
    return {"ok": True, "restarted": save_and_restart(c, venue)}


@app.post("/api/{venue}/watchlist")
def watchlist(venue: str, add: str = Body("", embed=True), remove: str = Body("", embed=True),
              trade: str = Body("", embed=True), on: bool = Body(True, embed=True)):
    """Tambah/hapus pair dari daftar pantau, atau nyalakan/matikan auto trading untuk satu pair."""
    check_venue(venue)
    c = full_cfg()
    v = c[venue]
    if add:
        a = clean_symbols([add], venue)
        if not a:
            fail(f"{add} bukan pair {'kripto' if venue == 'crypto' else 'forex'}.")
        v["watchlist"] = list(dict.fromkeys(v["watchlist"] + a))
    if remove:
        r = remove.upper()
        if r in v["symbols"] and len(v["symbols"]) == 1:
            fail("Pair ini satu-satunya yang di-trade robot. Pilih pair lain dulu.")
        v["watchlist"] = [x for x in v["watchlist"] if x != r]
        v["symbols"] = [x for x in v["symbols"] if x != r]
    if trade:
        t = trade.upper()
        if on:
            v["symbols"] = list(dict.fromkeys(v["symbols"] + clean_symbols([t], venue)))
        else:
            if t in v["symbols"] and len(v["symbols"]) == 1:
                fail("Minimal satu pair harus di-trade robot.")
            v["symbols"] = [x for x in v["symbols"] if x != t]
        v["watchlist"] = list(dict.fromkeys(v["watchlist"] + v["symbols"]))
    restarted = save_and_restart(c, venue) if trade or remove else (ctl.save_config(c) or False)
    return {"ok": True, "restarted": restarted, "symbols": v["symbols"], "watchlist": v["watchlist"]}


@app.get("/api/{venue}/pairs")
def pairs(venue: str):
    check_venue(venue)
    try:
        lst = cached(("pairs", venue, MT5.enabled()), 1800, lambda: markets().data(venue).pairs())
        return {"pairs": [{"symbol": p, "label": display(p)} for p in lst]}
    except Exception as e:  # noqa: BLE001
        fallback = full_cfg()[venue]["watchlist"]
        return {"pairs": [{"symbol": p, "label": display(p)} for p in fallback], "error": f"Daftar tidak bisa diambil: {e}"}


# ===================================================================== monitoring & pembanding
BARS_24H = {"15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}


def watch_row(venue, symbol, tf, traded):
    row = {"symbol": symbol, "label": display(symbol), "trading": symbol in traded}
    try:
        df = candles_df(symbol, tf, 120, ttl=45)
        closes = df["close"].to_numpy(float)
        n = min(len(closes) - 1, BARS_24H.get(tf, 24) if tf != "1d" else 7)
        row.update(price=float(closes[-1]), change_pct=float((closes[-1] / closes[-1 - n] - 1) * 100) if n > 0 else None,
                   change_bars=n, spark=[float(x) for x in closes[-60:]],
                   high=float(df["high"].tail(n + 1).max()), low=float(df["low"].tail(n + 1).min()))
    except Exception as e:  # noqa: BLE001
        row["error"] = str(e)
    sig, src = latest_signal(venue, symbol, tf)
    if sig is not None:
        row["signal"] = {"direction": sig.direction, "exp_ret_pct": sig.exp_ret_pct, "prob_up": sig.prob_up,
                         "prob_down": sig.prob_down, "source": src, "time": sig.time}
    acc = acc_for(venue, symbol, tf, int(full_cfg()["model"]["pred_len"]))
    row.update(accuracy=acc["hit"], acc_n=acc["n"])
    return row


@app.get("/api/{venue}/watch")
def watch(venue: str, tf: str | None = None):
    c = vcfg(venue)
    tf = tf if tf in TFS else c["timeframe"]
    wl = full_cfg()[venue]["watchlist"]
    rows = list(POOL.map(lambda s: watch_row(venue, s, tf, c["symbols"]), wl))
    return {"tf": tf, "rows": rows}


@app.get("/api/compare")
def compare(symbols: str, tf: str = "1h", bars: int = 168):
    syms = [s for s in symbols.split(",") if s][:8]
    if len(syms) < 1:
        fail("Pilih pair yang mau dibandingkan.")
    if tf not in TFS:
        fail("Timeframe tidak dikenal.")
    bars = max(20, min(int(bars), 900))

    def one(s):
        try:
            return s, candles_df(s, tf, bars + 1, ttl=60)
        except Exception as e:  # noqa: BLE001
            return s, e
    out, rets = [], {}
    for s, df in POOL.map(one, syms):
        if isinstance(df, Exception):
            out.append({"symbol": s, "label": display(s), "error": str(df)})
            continue
        df = df.tail(bars + 1)
        cl = df["close"].to_numpy(float)
        norm = (cl / cl[0] - 1) * 100
        r = np.diff(np.log(cl))
        eqc = cl / np.maximum.accumulate(cl)
        out.append({"symbol": s, "label": display(s), "points": series(df["timestamps"], norm),
                    "return_pct": float(norm[-1]), "volatility_pct": float(r.std() * 100) if len(r) else 0.0,
                    "max_dd_pct": float((eqc.min() - 1) * 100), "high": float(cl.max()), "low": float(cl.min()),
                    "from": str(df["timestamps"].iloc[0])[:16], "to": str(df["timestamps"].iloc[-1])[:16]})
        rets[s] = pd.Series(r, index=pd.to_datetime(df["timestamps"].iloc[1:]).values)
    corr = {}
    if len(rets) > 1:
        m = pd.DataFrame(rets).dropna().corr()
        corr = {a: {b: (None if pd.isna(m.loc[a, b]) else round(float(m.loc[a, b]), 2)) for b in m.columns} for a in m.index}
    for row in out:
        if "error" in row:
            continue
        sig, src = latest_signal(venue_of(row["symbol"]), row["symbol"], tf)
        if sig is not None:
            row["signal"] = {"direction": sig.direction, "exp_ret_pct": sig.exp_ret_pct, "prob_up": sig.prob_up,
                             "prob_down": sig.prob_down}
        a = acc_for(venue_of(row["symbol"]), row["symbol"], tf, int(full_cfg()["model"]["pred_len"]))
        row.update(accuracy=a["hit"], acc_n=a["n"])
    return {"tf": tf, "bars": bars, "rows": out, "corr": corr}


# ===================================================================== chart & forecast
@app.get("/api/candles")
def candles(symbol: str, tf: str, limit: int = 300):
    if tf not in TFS:
        fail("Timeframe tidak dikenal.")
    data = data_for(symbol)
    try:
        df = candles_df(symbol, tf, min(limit, 1000), ttl=8)
    except Exception as e:  # noqa: BLE001
        fail(f"Data harga {display(symbol)} tidak bisa diambil: {e}", 502)
    if df.empty:
        fail(f"Data {display(symbol)} kosong.", 502)
    t = [wib_epoch(x) for x in df["timestamps"]]
    e50, e200, r = ema(df["close"], 50), ema(df["close"], 200), rsi(df["close"])
    has_vol = bool(df["volume"].sum() > 0)
    return {
        "candles": [{"time": a, "open": o, "high": h, "low": lo, "close": cl}
                    for a, o, h, lo, cl in zip(t, df["open"], df["high"], df["low"], df["close"])],
        "volume": [{"time": a, "value": v, "up": cl >= o} for a, v, o, cl in zip(t, df["volume"], df["open"], df["close"])] if has_vol else [],
        "ema50": series(df["timestamps"], e50), "ema200": series(df["timestamps"], e200),
        "rsi": series(df["timestamps"], r)[20:],
        "step": int(data.tf_ms(tf) // 1000), "venue": venue_of(symbol), "source": getattr(data, "source", ""),
        "last": float(df["close"].iloc[-1]), "prev_close": float(df["close"].iloc[-2]) if len(df) > 1 else None,
        "label": display(symbol),
    }


_fc_lock = threading.Lock()
_forecaster = {"obj": None, "key": None}


def get_forecaster(m):
    """Model AI bersama untuk panel (panggil di dalam _fc_lock)."""
    from bot.forecast import KronosForecaster
    key = (m["name"], m["tokenizer"], m["n_paths"], m.get("device", "auto"), bool(m.get("ensemble")))
    if _forecaster["key"] != key:
        _forecaster["obj"] = KronosForecaster({**m, "device": m.get("device", "auto")})
        _forecaster["key"] = key
    return _forecaster["obj"]


def run_forecast(symbol, tf) -> Signal:
    venue = venue_of(symbol)
    c = vcfg(venue)
    m = c["model"]
    s = strat(c, venue)
    data = data_for(symbol)
    hist = data.recent(symbol, tf, int(m["lookback"]))
    if len(hist) < 100:
        raise RuntimeError(f"data hanya {len(hist)} candle")
    y = data.future_ts(hist["timestamps"].iloc[-1], tf, int(m["pred_len"]))
    with _fc_lock:
        paths = get_forecaster(m).paths(hist, y)
    sig = build_signal(symbol, hist, paths, s["fee_pct"], int(s["trend_period"]))
    acc = acc_for(venue, symbol, tf, sig.horizon)
    sig.accuracy, sig.acc_n = acc["hit"], acc["n"]
    return sig


@app.get("/api/signal")
def get_signal(symbol: str, tf: str):
    venue = venue_of(symbol)
    sig, src = latest_signal(venue, symbol, tf)
    return {"signal": sig_dict(sig, vcfg(venue), src) if sig is not None else None}


@app.post("/api/forecast")
def forecast(symbol: str = Body(..., embed=True), tf: str = Body(..., embed=True)):
    if not (KRONOS_DIR / "model").exists():
        fail("Setup belum selesai: folder Kronos belum ada.")
    try:
        sig = run_forecast(symbol, tf)
    except Exception as e:  # noqa: BLE001
        fail(f"Gagal meramal {display(symbol)}: {e}", 502)
    _forecasts[(symbol, tf)] = (sig, time.time())
    return {"signal": sig_dict(sig, vcfg(venue_of(symbol)), "manual forecast")}


_jobs: dict = {}


@app.post("/api/hindcast")
def hindcast(symbol: str = Body(..., embed=True), tf: str = Body(..., embed=True), count: int = Body(12, embed=True)):
    """Ramalan AI di masa lalu (hanya memakai data sebelum titik itu) dibanding harga yang benar-benar terjadi."""
    if not (KRONOS_DIR / "model").exists():
        fail("Setup belum selesai: folder Kronos belum ada.")
    if tf not in TFS:
        fail("Timeframe tidak dikenal.")
    count = max(3, min(40, int(count)))
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "done": 0, "total": count, "finished": False, "error": "", "result": None}
    _jobs[jid] = job

    def work():
        import backtest as bt
        from bot.forecast import default_batch
        try:
            venue = venue_of(symbol)
            c = vcfg(venue)
            m, s = c["model"], strat(c, venue)
            lb, h = int(m["lookback"]), int(m["pred_len"])
            data = data_for(symbol)
            df = data.history(symbol, tf, lb + (count + 2) * h + 5)
            n = len(df)
            # titik ramalan di grid tetap (tiap h candle) supaya hasil lama bisa dipakai ulang dari cache
            grid = h * TF_SEC[tf] * 1000
            tsv = df["ts"].to_numpy("int64")
            origins = [t for t in range(lb, n + 1) if tsv[t - 1] % grid == 0][-count:]
            if not origins:
                raise RuntimeError(f"data hanya {n} candle")
            job["total"] = len(origins)
            cfile = bt.cache_path(symbol, tf, c, s, False)
            cache = json.loads(cfile.read_text()) if cfile.exists() else {}
            known = set(Signal.__dataclass_fields__)
            sigs = {}
            todo = []
            for t in origins:
                key = str(int(df["ts"].iloc[t - 1]))
                if key in cache:
                    sigs[t] = Signal(**{a: b for a, b in cache[key].items() if a in known})
                    job["done"] += 1
                else:
                    todo.append(t)
            if todo:
                with _fc_lock:
                    fc = get_forecaster(m)
                    bs = default_batch(getattr(fc, "device", "cpu"))
                    for i in range(0, len(todo), bs):
                        chunk = todo[i:i + bs]
                        items = []
                        for t in chunk:
                            hist = df.iloc[t - lb:t].reset_index(drop=True)
                            items.append((hist, data.future_ts(hist["timestamps"].iloc[-1], tf, h)))
                        for t, (hist, _), paths in zip(chunk, items, fc.paths_many(items)):
                            sig = build_signal(symbol, hist, paths, s["fee_pct"], int(s["trend_period"]))
                            sigs[t] = sig
                            cache[str(int(hist["ts"].iloc[-1]))] = sig.__dict__
                        job["done"] += len(chunk)
                cfile.parent.mkdir(parents=True, exist_ok=True)
                cfile.write_text(json.dumps(cache))
            close = df["close"].to_numpy(float)
            pts = []
            for t in origins:
                sig = sigs[t]
                k = min(h, n - t)
                actual = close[t:t + k]
                if not len(actual):
                    continue
                act_ret = (actual[-1] / sig.last_close - 1) * 100
                fin = sig.path[k - 1] if len(sig.path) >= k else sig.path[-1]
                lo = sig.path_lo[k - 1] if sig.path_lo else None
                hi = sig.path_hi[k - 1] if sig.path_hi else None
                pts.append({"t0": wib_epoch(sig.time), "last_close": sig.last_close, "path": sig.path, "path_lo": sig.path_lo,
                            "path_hi": sig.path_hi, "exp_ret_pct": sig.exp_ret_pct, "prob_up": sig.prob_up,
                            "prob_down": sig.prob_down, "direction": sig.direction, "actual_ret_pct": float(act_ret),
                            "hit": bool(np.sign(sig.exp_ret_pct) == np.sign(act_ret)) if act_ret else None,
                            "err_pct": float(abs(fin / actual[-1] - 1) * 100),
                            "in_band": bool(lo is not None and lo <= actual[-1] <= hi), "complete": k == h})
            done_pts = [p for p in pts if p["complete"]]
            rated = [p for p in done_pts if p["hit"] is not None]
            hits = sum(p["hit"] for p in rated)
            job["result"] = {"symbol": symbol, "tf": tf, "step": TF_SEC[tf], "points": pts,
                             "summary": {"n": len(rated), "hits": hits, "hit": hits / len(rated) if rated else None,
                                         "err_pct": float(np.mean([p["err_pct"] for p in done_pts])) if done_pts else None,
                                         "naive_err_pct": float(np.mean([abs(p["actual_ret_pct"]) for p in done_pts])) if done_pts else None,
                                         "in_band": float(np.mean([p["in_band"] for p in done_pts])) if done_pts else None,
                                         "strong_n": sum(1 for p in rated if p["direction"] != "SAMPING"),
                                         "strong_hits": sum(1 for p in rated if p["direction"] != "SAMPING" and p["hit"])}}
        except Exception as e:  # noqa: BLE001
            job["error"] = str(e)
        finally:
            job["finished"] = True

    threading.Thread(target=work, daemon=True).start()
    return {"job": jid}


@app.post("/api/scan")
def scan(symbols: list = Body(..., embed=True), tf: str = Body(..., embed=True)):
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "done": 0, "total": len(symbols), "current": "", "finished": False, "symbols": list(symbols)}
    _jobs[jid] = job

    def work():
        for sym in symbols:
            job["current"] = display(sym)
            try:
                _forecasts[(sym, tf)] = (run_forecast(sym, tf), time.time())
            except Exception as e:  # noqa: BLE001
                job.setdefault("errors", {})[sym] = str(e)
            job["done"] += 1
        job["finished"] = True
        job["current"] = ""

    threading.Thread(target=work, daemon=True).start()
    return {"job": jid}


@app.get("/api/scan/{jid}")
def scan_status(jid: str):
    job = _jobs.get(jid)
    if not job:
        fail("Proses tidak ditemukan.", 404)
    return job


# ===================================================================== scanner seluruh pasar
_scanner = {v: {"running": False, "phase": "", "done": 0, "total": 0} for v in VENUES}


def scan_file(venue):
    return path_in_root(f"data/scan_{venue}.json")


@app.post("/api/{venue}/scanner/start")
def scanner_start(venue: str, tf: str = Body("1h", embed=True), universe: str = Body("60", embed=True),
                  ai_top: int = Body(15, embed=True)):
    from bot import scanner as sc
    check_venue(venue)
    if tf not in TFS:
        fail("Timeframe tidak dikenal.")
    st = _scanner[venue]
    if st["running"]:
        fail("Scan masih berjalan.")
    ai_top = max(0, min(40, int(ai_top)))
    if ai_top and not (KRONOS_DIR / "model").exists():
        fail("Setup belum selesai: folder Kronos belum ada. Matikan AI check atau jalankan MULAI lagi.")
    st.update(running=True, phase="Mengambil daftar pair", done=0, total=0, error="")

    def work():
        t0 = time.time()
        try:
            c = vcfg(venue)
            vc = full_cfg()[venue]
            m, s = c["model"], strat(c, venue)
            fee = float(s["fee_pct"])
            data = markets().data(venue)
            if venue == "crypto":
                top = int(universe) if str(universe).isdigit() else 60
                uni = sc.crypto_universe(data, c.get("quote", "USDT"), top=top)
            else:
                uni = sc.forex_universe(data, "majors" if universe == "majors" else "all")
            if not uni:
                raise RuntimeError("Daftar pair kosong. Cek koneksi internet.")
            need = max(260, int(m["lookback"]))
            st.update(phase="Membaca grafik semua pair", total=len(uni))

            def load(u):
                try:
                    df = data.recent(u["symbol"], tf, need)
                    return u, df, sc.technical(df, tf, fee, venue, int(m["pred_len"]))
                except Exception as e:  # noqa: BLE001
                    return u, None, {"error": str(e)}
                finally:
                    st["done"] += 1

            loaded = list(POOL.map(load, uni))
            rows = []
            hists = {}
            for u, df, t in loaded:
                if not t or "error" in t:
                    continue
                rows.append({"symbol": u["symbol"], "label": display(u["symbol"]), "quote_volume": u.get("quote_volume"),
                             "tech_detail": t, "side": t["side"]})
                hists[u["symbol"]] = df
            rows.sort(key=lambda r: r["tech_detail"]["tech"], reverse=True)
            device = None
            if ai_top and rows:
                from bot.forecast import default_batch
                pick = [r for r in rows[:ai_top] if len(hists[r["symbol"]]) >= int(m["lookback"])]
                st.update(phase="AI meramal kandidat teratas", done=0, total=len(pick))
                items = []
                for r in pick:
                    hist = hists[r["symbol"]].tail(int(m["lookback"])).reset_index(drop=True)
                    items.append((r, hist, data.future_ts(hist["timestamps"].iloc[-1], tf, int(m["pred_len"]))))
                with _fc_lock:
                    fc = get_forecaster(m)
                    device = getattr(fc, "device_name", None)
                    bs = default_batch(getattr(fc, "device", "cpu"))
                    for i in range(0, len(items), bs):
                        chunk = items[i:i + bs]
                        for (r, hist, _), paths in zip(chunk, fc.paths_many([(h, y) for _, h, y in chunk])):
                            sig = build_signal(r["symbol"], hist, paths, fee, int(s["trend_period"]))
                            acc = acc_for(venue, r["symbol"], tf, sig.horizon)
                            sig.accuracy, sig.acc_n = acc["hit"], acc["n"]
                            _forecasts[(r["symbol"], tf)] = (sig, time.time())
                            sc.combine(r, sig, fee, acc, venue)
                        st["done"] += len(chunk)
            for r in rows:
                if "score" not in r:
                    sc.combine(r, None, fee, None, venue)
                t = r.pop("tech_detail")
                r.update({k: t[k] for k in ("price", "ret_1d", "ret_7d", "atr_pct", "day_move_pct", "trend", "rsi",
                                            "er", "vol_ratio", "cost_ratio", "tags", "spark")})
                r["tech"] = round(t["tech"] * 100)
                r["in_watchlist"] = r["symbol"] in vc["watchlist"]
                r["trading"] = r["symbol"] in vc["symbols"]
            rows.sort(key=lambda r: r["score"], reverse=True)
            res = {"venue": venue, "tf": tf, "time": int(time.time() * 1000), "seconds": round(time.time() - t0, 1),
                   "scanned": len(uni), "rated": len(rows), "ai_checked": sum(1 for r in rows if r.get("ai")),
                   "device": device, "rows": rows, "universe": universe}
            f = scan_file(venue)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(res, default=float))
        except Exception as e:  # noqa: BLE001
            st["error"] = str(e)
        finally:
            st.update(running=False, phase="")

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True}


@app.get("/api/{venue}/scanner")
def scanner_get(venue: str):
    check_venue(venue)
    f = scan_file(venue)
    res = None
    if f.exists():
        try:
            res = json.loads(f.read_text())
            c = full_cfg()[venue]
            for r in res["rows"]:
                r["in_watchlist"] = r["symbol"] in c["watchlist"]
                r["trading"] = r["symbol"] in c["symbols"]
        except Exception:  # noqa: BLE001
            res = None
    return {"status": _scanner[venue], "result": res}


# ===================================================================== accuracy & history
@app.get("/api/{venue}/accuracy")
def accuracy(venue: str):
    c = vcfg(venue)
    s = strat(c, venue)
    out = []
    for sym in full_cfg()[venue]["watchlist"]:
        a = acc_for(venue, sym, c["timeframe"], int(c["model"]["pred_len"]))
        need, n_min = float(s.get("min_accuracy") or 0), int(s.get("min_accuracy_n") or 0)
        state = "pending" if a["n"] < n_min else ("low" if need and a["hit"] is not None and a["hit"] < need else "pass")
        out.append({"symbol": sym, "label": display(sym), "trading": sym in c["symbols"], **a, "need": need,
                    "n_min": n_min, "state": state,
                    "blocking": state == "low" or (state == "pending" and bool(s.get("require_proof")))})
    return {"rows": out, "timeframe": c["timeframe"]}


@app.get("/api/{venue}/history")
def history(venue: str, mode: str | None = None):
    c = vcfg(venue)
    mode = mode if mode in ("paper", "live") else c["mode"]
    eq = q(f"SELECT time, equity FROM equity WHERE mode=? AND {VCOL}=? ORDER BY id", (mode, venue))
    tr = q("SELECT symbol, side, lots, entry_time, entry_price, exit_time, exit_price, cost, pnl, pnl_pct, "
           f"entry_reason, exit_reason FROM positions WHERE mode=? AND status='closed' AND {VCOL}=? ORDER BY id DESC",
           (mode, venue))
    modes = q(f"SELECT DISTINCT mode FROM positions WHERE {VCOL}=? UNION SELECT DISTINCT mode FROM equity WHERE {VCOL}=?",
              (venue, venue))
    stats = {}
    if not tr.empty:
        tr["side"] = tr["side"].fillna("long")
        tr["label"] = tr["symbol"].map(display)
        stats = {"trades": int(len(tr)), "win_pct": float((tr["pnl"] > 0).mean() * 100), "pnl": float(tr["pnl"].sum()),
                 "best": float(tr["pnl"].max()), "worst": float(tr["pnl"].min())}
        by = tr.groupby("label")["pnl"].agg(["count", "sum"]).reset_index().sort_values("sum", ascending=False)
        stats["by_pair"] = [{"label": r["label"], "trades": int(r["count"]), "pnl": float(r["sum"])} for _, r in by.iterrows()]
    return {"mode": mode, "modes": sorted(set(modes["mode"].tolist()) | {c["mode"]}) if not modes.empty else [c["mode"]],
            "equity": series(eq["time"], eq["equity"]), "trades": records(tr), "stats": stats}


# ===================================================================== backtest
_sys = {"t": 0, "v": None}


@app.get("/api/system")
def system():
    """Perangkat komputasi (GPU/CPU) dan kecepatan backtest terakhir per perangkat."""
    if time.time() - _sys["t"] > 60 or _sys["v"] is None:
        from bot.forecast import system_info
        _sys["v"], _sys["t"] = system_info(), time.time()
    speeds = {}
    if BT_DIR.exists():
        for f in sorted(BT_DIR.glob("*_meta.json"), key=lambda p: p.stat().st_mtime):
            try:
                sp = json.loads(f.read_text()).get("speed") or {}
            except Exception:  # noqa: BLE001
                continue
            if sp.get("sec_per_point") and not f.name.endswith("_dummy_meta.json"):
                kind = "cpu" if str(sp.get("device", "cpu")) == "cpu" else "gpu"
                speeds[kind] = {"sec_per_point": sp["sec_per_point"], "device_name": sp.get("device_name"),
                                "model": (json.loads(f.read_text()).get("model") or {}).get("name")}
    c = full_cfg()
    return {**_sys["v"], "speeds": speeds, "device_pref": c["model"].get("device", "auto"),
            "model": {"name": c["model"]["name"], "n_paths": c["model"]["n_paths"],
                      "pred_len": c["model"]["pred_len"], "lookback": c["model"]["lookback"]}}


@app.post("/api/backtest/start")
def bt_start(symbols: list = Body(None, embed=True), symbol: str = Body("", embed=True),
             tf: str = Body(..., embed=True), candles: int = Body(1000, embed=True),
             speed: int = Body(1, embed=True), optimize: bool = Body(True, embed=True),
             device: str = Body("auto", embed=True), folds: int = Body(0, embed=True),
             end: str = Body("", embed=True)):
    if ctl.backtest_running():
        fail("Backtest lain masih berjalan.")
    if not (KRONOS_DIR / "model").exists():
        fail("Setup belum selesai: folder Kronos belum ada.")
    syms = [x for x in (symbols or [symbol]) if x]
    if not syms:
        fail("Pilih minimal satu pair.")
    if len({venue_of(x) for x in syms}) > 1:
        fail("Pair crypto dan forex diuji terpisah.")
    if tf not in TFS:
        fail("Timeframe tidak dikenal.")
    if device not in ("auto", "gpu", "cpu"):
        device = "auto"
    if end:
        try:
            e = pd.Timestamp(end)
        except Exception:  # noqa: BLE001
            fail("Tanggal tidak valid.")
        if e > pd.Timestamp.now():
            end = ""
        else:
            end = e.strftime("%Y-%m-%d")
    ctl.start_backtest(syms[:12], tf, max(100, min(10000, int(candles))), max(1, int(speed)), optimize,
                       device, max(0, min(10, int(folds))), end or None)
    return {"ok": True}


@app.post("/api/backtest/stop")
def bt_stop():
    ctl.stop_backtest()
    return {"ok": True}


@app.get("/api/backtest/status")
def bt_status():
    import re
    log = ctl.tail(ctl.BT_LOG, 400)
    lines = [ln.split("| ", 2)[-1] for ln in log.splitlines() if ln.strip()]
    pct, phase, device = None, (lines[-1] if lines else ""), None
    for ln in reversed(lines):
        mt = re.match(r"Progres\s+(\d+(?:\.\d+)?)%\s*\|\s*(.*)", ln)
        if mt:
            pct, phase = float(mt.group(1)), mt.group(2)
            break
    for ln in lines:
        if "Perangkat:" in ln:
            device = ln.split("Perangkat:", 1)[1].split(",")[0].strip()
    running = ctl.backtest_running()
    failed = (not running) and ("Traceback" in log or "Error" in log or "SystemExit" in log) and "SELESAI" not in log
    errors = [ln for ln in lines if "dilewati:" in ln]
    error = ""
    if failed:
        last = [ln.strip() for ln in log.splitlines() if ln.strip()]
        error = last[-1] if last else ""
        error = error.split("SystemExit:", 1)[-1].strip() if "SystemExit" in error else error
    return {"running": running, "pct": pct, "phase": phase, "failed": failed, "device": device, "error": error,
            "warnings": errors[-5:], "log": "\n".join(lines[-12:]) if failed else ""}


def _meta(name):
    f = BT_DIR / f"{name}_meta.json"
    try:
        return json.loads(f.read_text()) if f.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


@app.get("/api/{venue}/backtest/results")
def bt_results(venue: str):
    check_venue(venue)
    if not BT_DIR.exists():
        return {"results": []}
    files = sorted(BT_DIR.glob("*_ringkasan.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files:
        name = f.name.replace("_ringkasan.txt", "")
        m = _meta(name)
        sym = m.get("symbol") or name.split("_")[0]
        v = m.get("venue") or ("forex" if "USDT" not in sym else "crypto")
        if v != venue:
            continue
        opf = BT_DIR / f"{name}_optimasi.json"
        og = None
        if opf.exists():
            try:
                o = json.loads(opf.read_text())
                og = o.get("grade") if o.get("version") == 2 else None
            except Exception:  # noqa: BLE001
                og = None
        g = og or m.get("grade") or {}
        out.append({"name": name, "symbol": sym, "label": display(sym) if m else sym, "tf": m.get("tf", ""),
                    "dummy": name.endswith("_dummy"), "return_pct": (m.get("metrics") or {}).get("return_pct"),
                    "hit": (m.get("accuracy") or {}).get("hit"), "n": (m.get("accuracy") or {}).get("n"),
                    "grade": g.get("letter"), "grade_label": g.get("label"),
                    "has_opt": og is not None, "candles": m.get("candles"),
                    "device": (m.get("speed") or {}).get("device_name"), "end": m.get("end"),
                    "period": m.get("period"),
                    "updated": time.strftime("%d %b, %H:%M", time.localtime(f.stat().st_mtime))})
    return {"results": out}


def describe(p, venue):
    stop = (f"SL {p['sl_atr_mult']}× ATR, TP {p['tp_atr_mult']}× ATR" if p.get("sl_mode") == "atr"
            else f"SL {p['stop_loss_pct']}%, TP {p['take_profit_pct']}%")
    trail = f"trailing {p['trail_pct']}% setelah +{p['trail_activate_pct']}%" if p.get("trailing_on") else "tanpa trailing"
    sides = "Buy & Sell" if p.get("allow_short") else "Buy saja"
    return {"entry": f"ramalan ≥ {p['min_expected_return_pct']}%, peluang ≥ {round(p['min_prob_up'] * 100)}%",
            "stop": stop, "trail": trail, "trend": "ikut tren" if p.get("trend_filter") else "abaikan tren",
            "sides": sides if venue == "forex" else ""}


@app.get("/api/backtest/result/{name}")
def bt_result(name: str):
    f = BT_DIR / f"{name}_ringkasan.txt"
    if "/" in name or ".." in name or not f.exists():
        fail("Hasil tidak ditemukan.", 404)
    res = {"name": name, "summary": f.read_text(encoding="utf-8").splitlines()}
    m = _meta(name)
    if m:
        res.update(symbol=m["symbol"], label=display(m["symbol"]), venue=m["venue"], tf=m["tf"],
                   metrics=m["metrics"], accuracy=m["accuracy"])
        for k in ("quality", "segments", "montecarlo", "grade", "speed", "model", "period", "candles", "folds", "end"):
            res[k] = m.get(k)
    eqf, trf, opf = BT_DIR / f"{name}_equity.csv", BT_DIR / f"{name}_trades.csv", BT_DIR / f"{name}_optimasi.json"
    if eqf.exists():
        cv = pd.read_csv(eqf)
        start_bal = float(cv["equity"].iloc[0]) if len(cv) else 1.0
        res["equity"] = series(cv["timestamps"], cv["equity"])
        res["buyhold"] = series(cv["timestamps"], start_bal * cv["close"] / float(cv["close"].iloc[0]))
        res["period"] = res.get("period") or [str(cv["timestamps"].iloc[0])[:16], str(cv["timestamps"].iloc[-1])[:16]]
    if trf.exists() and trf.stat().st_size > 5:
        res["trades"] = records(pd.read_csv(trf))
    if opf.exists():
        o = json.loads(opf.read_text())
        if o.get("version") == 2:
            v = o.get("venue", venue_of(o["symbol"]))
            o["current"]["desc"] = describe(o["current"]["params"], v)
            for r in o["candidates"]:
                r["desc"] = describe(r["params"], v)
            for w in o["walk_forward"]["steps"]:
                if w.get("params"):
                    w["desc"] = describe(w["params"], v)
            res["optim"] = o
        else:
            res["optim_old"] = True
    return res


@app.post("/api/backtest/apply")
def bt_apply(name: str = Body(..., embed=True), k: int = Body(..., embed=True)):
    opf = BT_DIR / f"{name}_optimasi.json"
    if "/" in name or not opf.exists():
        fail("Hasil optimasi tidak ditemukan.", 404)
    o = json.loads(opf.read_text())
    cands = o.get("candidates") or []
    if not (1 <= k <= len(cands)):
        fail("Kandidat tidak ada.")
    venue = o.get("venue", venue_of(o["symbol"]))
    c = full_cfg()
    p = cands[k - 1]["params"]
    c[venue]["strategy"].update({x: v for x, v in p.items() if x in STRAT_TYPES and v is not None})
    if venue == "crypto":
        c[venue]["strategy"].pop("allow_short", None)
    return {"ok": True, "restarted": save_and_restart(c, venue), "venue": venue}


# ===================================================================== account & mode
def mask(v):
    return ("•" * 6 + str(v)[-4:]) if v else ""


@app.get("/api/account")
def account():
    k, s = api_keys()
    c = full_cfg()
    env = ctl.read_env()
    return {"key": mask(k), "secret": mask(s), "has_keys": bool(k and s), "confirm_text": CONFIRM_TEXT,
            "modes": {v: c[v]["mode"] for v in VENUES},
            "mt5": {"installed": MT5.installed(), "enabled": MT5.enabled(), "login": env.get("MT5_LOGIN", ""),
                    "server": env.get("MT5_SERVER", ""), "path": env.get("MT5_PATH", ""),
                    "has_password": bool(env.get("MT5_PASSWORD")), "windows": os.name == "nt"}}


@app.post("/api/account/keys")
def set_keys(key: str = Body("", embed=True), secret: str = Body("", embed=True)):
    vals = {}
    if key.strip():
        vals["TOKOCRYPTO_API_KEY"] = key.strip()
    if secret.strip():
        vals["TOKOCRYPTO_API_SECRET"] = secret.strip()
    if not vals:
        fail("Isi API key atau secret key.")
    ctl.save_env(vals)
    return {"ok": True}


@app.post("/api/account/test")
def test_keys():
    from bot.market import make_exchange
    try:
        bal = make_exchange(vcfg("crypto"), private=True).fetch_balance()
    except SystemExit as e:
        fail(str(e))
    except Exception as e:  # noqa: BLE001
        fail(f"Tokocrypto menolak: {e}")
    free = bal.get("free") or {}
    return {"ok": True, "usdt": float(free.get("USDT", 0) or 0)}


@app.post("/api/mt5")
def set_mt5(enabled: bool = Body(..., embed=True), login: str = Body("", embed=True),
            password: str = Body("", embed=True), server: str = Body("", embed=True), path: str = Body("", embed=True)):
    if login.strip() and not login.strip().isdigit():
        fail("Nomor login MT5 hanya berisi angka.")
    vals = {"MT5_ENABLED": "YA" if enabled else "TIDAK", "MT5_LOGIN": login.strip(),
            "MT5_SERVER": server.strip(), "MT5_PATH": path.strip()}
    if password:
        vals["MT5_PASSWORD"] = password
    ctl.save_env(vals)
    MT5.mod = None
    with _ttl_lock:
        _ttl.clear()
    return {"ok": True}


@app.post("/api/mt5/test")
def test_mt5():
    if not MT5.installed():
        fail("Library MetaTrader5 belum terpasang. MT5 hanya bisa dipakai di Windows.")
    MT5.mod = None
    try:
        info = MT5.account()
    except Exception as e:  # noqa: BLE001
        fail(str(e))
    return {"ok": True, **info}


@app.post("/api/{venue}/mode")
def set_mode(venue: str, mode: str = Body(..., embed=True), confirm: str = Body("", embed=True)):
    check_venue(venue)
    c = full_cfg()
    key = "LIVE_CRYPTO" if venue == "crypto" else "LIVE_FOREX"
    if mode == "live":
        if confirm.strip().upper() != CONFIRM_TEXT:
            fail("Teks konfirmasi belum sesuai.")
        if venue == "crypto" and not all(api_keys()):
            fail("Hubungkan Tokocrypto dulu di Account.")
        if venue == "forex" and not (MT5.enabled() and MT5.installed()):
            fail("Hubungkan MetaTrader 5 dulu di Account.")
        ctl.save_env({key: "YA"})
    elif mode == "paper":
        ctl.save_env({key: "TIDAK"})
    else:
        fail("Mode tidak dikenal.")
    c[venue]["mode"] = mode
    return {"ok": True, "restarted": save_and_restart(c, venue)}


@app.post("/api/{venue}/reset-paper")
def reset_paper(venue: str):
    check_venue(venue)
    if ctl.bot_running(venue) and full_cfg()[venue]["mode"] == "paper":
        fail("Stop robot dulu sebelum reset simulasi.")
    s = Store(db_path(), "paper", venue)
    for t in ("positions", "equity", "events"):
        s.db.execute(f"DELETE FROM {t} WHERE mode='paper' AND {VCOL}=?", (venue,))
    s.db.execute("DELETE FROM kv WHERE key=?", (f"paper_cash:{venue}",))
    for sym in full_cfg()[venue]["watchlist"]:
        s.db.execute("DELETE FROM kv WHERE key=?", (f"last_exit_ts:paper:{sym}",))
    s.db.commit()
    return {"ok": True}


# ===================================================================== jalankan
def main():
    url = f"http://localhost:{PORT}"
    with socket.socket() as sck:
        if sck.connect_ex(("127.0.0.1", PORT)) == 0:
            print(f"Panel sudah berjalan. Membuka {url}")
            webbrowser.open(url)
            return
    import uvicorn
    print(f"\n  Panel Kronos: {url}\n  Biarkan jendela ini terbuka selama memakai panel.\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
