"""
PANEL KONTROL ROBOT TRADING KRONOS (server lokal).
Dibuka otomatis oleh MULAI.bat / mulai.command -> http://localhost:8501
Hanya bisa diakses dari komputer ini (127.0.0.1).
"""
import json
import socket
import sqlite3
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import pandas as pd
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from bot import control as ctl
from bot.config import KRONOS_DIR, ROOT, api_keys, live_unlocked, load_config, path_in_root
from bot.forecast import Signal, build_signal
from bot.indicators import ema, rsi
from bot.store import WIB, Store
from bot.strategy import DEFAULTS, entry_decision, opt

PORT = 8501
STATIC = ROOT / "static"
BT_DIR = path_in_root("data/backtest/x").parent
CONFIRM_TEXT = "SAYA PAHAM RISIKONYA"
MODELS = {
    "ringan": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k"),
    "sedang": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base"),
    "berat": ("NeoQuasar/Kronos-base", "NeoQuasar/Kronos-Tokenizer-base"),
}

app = FastAPI(title="Robot Trading Kronos")


# ===================================================================== utilitas
def cfg():
    return load_config()


def db_path(c=None):
    return path_in_root((c or cfg())["db_path"])


def q(sql, args=()):
    p = db_path()
    if not p.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(p, timeout=10) as con:
            return pd.read_sql_query(sql, con, params=args)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def store(mode=None):
    c = cfg()
    return Store(db_path(c), mode or c["mode"])


def fail(msg, code=400):
    raise HTTPException(status_code=code, detail=msg)


def records(df: pd.DataFrame):
    return json.loads(df.to_json(orient="records")) if not df.empty else []


def wib_epoch(ts) -> int:
    """Waktu WIB (tanpa zona) -> detik, diperlakukan sebagai UTC agar grafik menampilkan jam WIB."""
    return int(pd.Timestamp(ts).value // 10**9)


_ex_cache, _lock = {}, threading.Lock()


def public_ex(name):
    with _lock:
        if name not in _ex_cache:
            from bot.market import make_exchange
            _ex_cache[name] = make_exchange({"exchange": name})
        return _ex_cache[name]


_ttl_cache: dict = {}


def cached(key, ttl, fn):
    hit = _ttl_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _ttl_cache[key] = (time.time(), val)
    return val


def price_now(c, symbol):
    try:
        return cached(("px", symbol), 10, lambda: float(public_ex(c["exchange"]).fetch_ticker(symbol)["last"]))
    except Exception:  # noqa: BLE001
        return None


def sig_dict(sig: Signal, s: dict, source: str):
    ok, why = entry_decision(sig, s)
    d = dict(sig.__dict__)
    d.update(direction=sig.direction, would_buy=ok, decision=why, source=source,
             t0=wib_epoch(sig.time))
    return d


def signal_from_row(row) -> Signal:
    def js(v):
        try:
            return json.loads(v) if v else []
        except Exception:  # noqa: BLE001
            return []
    g = row.get
    return Signal(time=row["candle_time"], symbol=row["symbol"], last_close=row["last_close"],
                  exp_ret_pct=row["exp_ret_pct"], median_ret_pct=row["median_ret_pct"] or 0,
                  prob_up=row["prob_up"], pred_high=row["pred_high"], pred_low=row["pred_low"],
                  path=js(row["path"]), path_lo=js(g("path_lo")), path_hi=js(g("path_hi")),
                  trend_up=bool(g("trend_up")) if g("trend_up") is not None else True,
                  rsi=g("rsi") or 50.0, atr_pct=g("atr_pct") or 0.0, rr=g("rr") or 0.0,
                  upside_pct=max(0.0, (row["pred_high"] / row["last_close"] - 1) * 100),
                  downside_pct=max(0.0, (1 - row["pred_low"] / row["last_close"]) * 100),
                  score=g("score") or 0.0)


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


# ===================================================================== status & kontrol
@app.get("/api/status")
def status():
    c = cfg()
    s = store(c["mode"])
    running = ctl.bot_running()
    return {
        "mode": c["mode"], "running": running, "crashed": ctl.bot_crashed(),
        "crash_log": ctl.tail(ctl.BOT_CONSOLE, 25) if ctl.bot_crashed() else "",
        "state": s.get_kv("bot_state", "berhenti") if running else "berhenti",
        "next_run": s.get_kv("next_run") if running else None,
        "paused": bool(s.get_kv("pause_entries", False)),
        "symbols": c["symbols"], "timeframe": c["timeframe"], "quote": c.get("quote", "USDT"),
        "max_positions": c["risk"]["max_open_positions"], "live_unlocked": live_unlocked(),
        "setup_ok": (KRONOS_DIR / "model").exists(), "server_time": int(time.time() * 1000),
    }


@app.post("/api/bot/start")
def bot_start():
    c = cfg()
    if c["mode"] == "live" and not live_unlocked():
        fail("Mode live belum dikonfirmasi. Buka halaman Akun & mode.")
    if not (KRONOS_DIR / "model").exists():
        fail("Setup belum selesai: folder Kronos belum ada. Jalankan MULAI lagi.")
    ctl.start_bot()
    return {"ok": True}


@app.post("/api/bot/stop")
def bot_stop():
    ctl.stop_bot()
    store().set_kv("bot_state", "berhenti")
    return {"ok": True}


@app.post("/api/bot/dismiss-crash")
def dismiss_crash():
    ctl.BOT_PID.unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/bot/pause")
def bot_pause(value: bool = Body(..., embed=True)):
    store().set_kv("pause_entries", bool(value))
    return {"ok": True, "paused": bool(value)}


# ===================================================================== ringkasan
@app.get("/api/overview")
def overview():
    c = cfg()
    mode = c["mode"]
    eq = q("SELECT time, equity, cash FROM equity WHERE mode=? ORDER BY id", (mode,))
    closed = q("SELECT pnl, exit_time FROM positions WHERE mode=? AND status='closed'", (mode,))
    openp = q("SELECT * FROM positions WHERE mode=? AND status='open' ORDER BY id", (mode,))
    today = pd.Timestamp.now(tz=WIB).strftime("%Y-%m-%d")
    positions = []
    for p in records(openp):
        now = price_now(c, p["symbol"])
        p["price_now"] = now
        p["pnl_pct_now"] = (now / p["entry_price"] - 1) * 100 if now else None
        p["pnl_now"] = (now * p["amount"] - p["cost"]) if now else None
        positions.append(p)
    sig = q("SELECT * FROM signals WHERE mode=? ORDER BY id DESC LIMIT 200", (mode,))
    decisions = []
    if not sig.empty:
        for row in records(sig.drop_duplicates("symbol")):
            decisions.append({k: row.get(k) for k in ("symbol", "candle_time", "last_close", "exp_ret_pct", "prob_up",
                                                       "direction", "action", "reason", "rr", "rsi", "trend_up")})
    ev = q("SELECT time, level, message FROM events WHERE mode=? ORDER BY id DESC LIMIT 20", (mode,))
    start_eq = float(eq["equity"].iloc[0]) if not eq.empty else None
    eq_tail = eq.tail(500)
    return {
        "mode": mode, "quote": c.get("quote", "USDT"),
        "equity": float(eq["equity"].iloc[-1]) if not eq.empty else None,
        "cash": float(eq["cash"].iloc[-1]) if not eq.empty else None,
        "equity_change_pct": (float(eq["equity"].iloc[-1]) / start_eq - 1) * 100 if start_eq else None,
        "pnl_total": float(closed["pnl"].sum()) if not closed.empty else 0.0,
        "pnl_today": float(closed[closed["exit_time"].str.startswith(today)]["pnl"].sum()) if not closed.empty else 0.0,
        "trades": int(len(closed)),
        "win_pct": float((closed["pnl"] > 0).mean() * 100) if not closed.empty else None,
        "max_positions": c["risk"]["max_open_positions"],
        "positions": positions, "decisions": decisions, "events": records(ev),
        "equity_series": [{"time": wib_epoch(t), "value": float(v)} for t, v in zip(eq_tail["time"], eq_tail["equity"])],
    }


@app.post("/api/positions/sell")
def sell(ids: list = Body(..., embed=True)):
    """ids = daftar id posisi, atau ["ALL"]."""
    c = cfg()
    if ctl.bot_running():
        s = store(c["mode"])
        s.set_kv("close_requests", list(set(s.get_kv("close_requests", []) + ids)))
        return {"ok": True, "queued": True, "message": "Perintah jual dikirim. Robot menjual dalam beberapa detik."}
    from bot.broker import make_broker
    from bot.engine import Engine
    from bot.market import make_exchange
    ex = make_exchange(c, private=c["mode"] == "live")
    s = store(c["mode"])
    eng = Engine(c, ex, make_broker(ex, s, c), s, None)
    n = 0
    for pos in s.open_positions():
        if "ALL" in ids or pos["id"] in ids:
            eng.close(pos, "dijual manual dari panel")
            n += 1
    return {"ok": True, "queued": False, "message": f"{n} posisi terjual."}


# ===================================================================== pengaturan
@app.get("/api/config")
def get_config():
    c = cfg()
    s = {**DEFAULTS, **c["strategy"]}
    model = next((k for k, v in MODELS.items() if v[0] == c["model"]["name"]), "sedang")
    return {"symbols": c["symbols"], "timeframe": c["timeframe"], "risk": c["risk"], "strategy": s,
            "model": {**c["model"], "size": model}, "paper": c["paper"], "quote": c.get("quote", "USDT")}


NUM = {
    "risk": {"order_size_quote": float, "max_order_size_quote": float, "max_open_positions": int,
             "max_daily_loss_quote": float},
    "strategy": {"fee_pct": float, "min_expected_return_pct": float, "min_prob_up": float, "stop_loss_pct": float,
                 "take_profit_pct": float, "max_hold_candles": int, "exit_prob_up_below": float,
                 "cooldown_candles": int, "trend_filter": bool, "trend_period": int, "rsi_max": float,
                 "min_rr": float, "sl_mode": str, "sl_atr_mult": float, "tp_atr_mult": float, "trailing_on": bool,
                 "trail_activate_pct": float, "trail_pct": float},
    "paper": {"starting_balance": float, "slippage_pct": float},
}


@app.post("/api/config")
def save_config(body: dict = Body(...)):
    c = cfg()
    if "symbols" in body:
        syms = [x.strip().upper() for x in body["symbols"] if str(x).strip()]
        if not syms:
            fail("Pilih minimal satu koin.")
        c["symbols"] = syms
    if body.get("timeframe") in ("15m", "30m", "1h", "4h", "1d"):
        c["timeframe"] = body["timeframe"]
    for sec, fields in NUM.items():
        for k, typ in fields.items():
            if k in (body.get(sec) or {}):
                try:
                    c[sec][k] = typ(body[sec][k])
                except (TypeError, ValueError):
                    fail(f"Nilai {k} tidak valid.")
    if c["strategy"].get("sl_mode") not in ("persen", "atr"):
        c["strategy"]["sl_mode"] = "persen"
    c["risk"]["max_order_size_quote"] = max(c["risk"]["max_order_size_quote"], c["risk"]["order_size_quote"])
    m = body.get("model") or {}
    if m.get("size") in MODELS:
        c["model"]["name"], c["model"]["tokenizer"] = MODELS[m["size"]]
    for k in ("n_paths", "pred_len"):
        if k in m:
            c["model"][k] = int(m[k])
    ctl.save_config(c)
    restarted = False
    if ctl.bot_running():
        ctl.restart_bot()
        restarted = True
    return {"ok": True, "restarted": restarted}


@app.get("/api/pairs")
def pairs():
    c = cfg()
    try:
        quote = c.get("quote", "USDT")
        lst = cached(("pairs", quote), 3600, lambda: sorted(
            s for s, m in public_ex(c["exchange"]).load_markets().items()
            if s.endswith("/" + quote) and m.get("active", True)))
        return {"pairs": lst}
    except Exception as e:  # noqa: BLE001
        return {"pairs": c["symbols"], "error": f"Daftar koin tidak bisa diambil: {e}"}


# ===================================================================== akun & mode
def mask(v):
    return ("•" * 8 + v[-4:]) if v else ""


@app.get("/api/account")
def account():
    k, s = api_keys()
    c = cfg()
    return {"mode": c["mode"], "key": mask(k), "secret": mask(s), "has_keys": bool(k and s),
            "live_unlocked": live_unlocked(), "running": ctl.bot_running(), "confirm_text": CONFIRM_TEXT}


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
    c = cfg()
    try:
        ex = make_exchange(c, private=True)
        bal = ex.fetch_balance()
    except SystemExit as e:
        fail(str(e))
    except Exception as e:  # noqa: BLE001
        fail(f"Tokocrypto menolak: {e}")
    free = bal.get("free") or {}
    assets = sorted(((k, float(v)) for k, v in free.items() if v and float(v) > 0), key=lambda x: -x[1])[:8]
    return {"ok": True, "usdt": float(free.get(c.get("quote", "USDT"), 0) or 0), "assets": assets}


@app.post("/api/account/mode")
def set_mode(mode: str = Body(..., embed=True), confirm: str = Body("", embed=True)):
    c = cfg()
    if mode == "live":
        if confirm.strip().upper() != CONFIRM_TEXT:
            fail("Teks konfirmasi belum sesuai.")
        if not all(api_keys()):
            fail("Simpan API key Tokocrypto dulu.")
        ctl.save_env({"LIVE_TRADING": "YA"})
    elif mode == "paper":
        ctl.save_env({"LIVE_TRADING": "TIDAK"})
    else:
        fail("Mode tidak dikenal.")
    c["mode"] = mode
    ctl.save_config(c)
    restarted = False
    if ctl.bot_running():
        ctl.restart_bot()
        restarted = True
    return {"ok": True, "restarted": restarted}


@app.post("/api/account/reset-paper")
def reset_paper():
    c = cfg()
    if ctl.bot_running() and c["mode"] == "paper":
        fail("Matikan robot dulu sebelum mereset simulasi.")
    s = Store(db_path(c), "paper")
    for t in ("positions", "signals", "equity", "events"):
        s.db.execute(f"DELETE FROM {t} WHERE mode='paper'")
    s.db.execute("DELETE FROM kv WHERE key='paper_cash' OR key LIKE 'last_exit_ts:paper:%'")
    s.db.commit()
    return {"ok": True}


# ===================================================================== analisa realtime
@app.get("/api/candles")
def candles(symbol: str, tf: str, limit: int = 300):
    from bot.market import to_frame
    c = cfg()
    try:
        raw = cached(("ohlcv", symbol, tf), 8,
                     lambda: public_ex(c["exchange"]).fetch_ohlcv(symbol, tf, limit=min(limit, 1000)))
    except Exception as e:  # noqa: BLE001
        fail(f"Data harga {symbol} tidak bisa diambil: {e}", 502)
    df = to_frame(raw)
    t = [wib_epoch(x) for x in df["timestamps"]]
    e50, e200, r = ema(df["close"], 50), ema(df["close"], 200), rsi(df["close"])
    return {
        "candles": [{"time": a, "open": o, "high": h, "low": lo, "close": cl}
                    for a, o, h, lo, cl in zip(t, df["open"], df["high"], df["low"], df["close"])],
        "volume": [{"time": a, "value": v, "up": cl >= o} for a, v, o, cl in zip(t, df["volume"], df["open"], df["close"])],
        "ema50": [{"time": a, "value": float(v)} for a, v in zip(t, e50)],
        "ema200": [{"time": a, "value": float(v)} for a, v in zip(t, e200)],
        "rsi": [{"time": a, "value": float(v)} for a, v in zip(t, r)][20:],
        "step": int(public_ex(c["exchange"]).parse_timeframe(tf)),
        "last": float(df["close"].iloc[-1]), "prev_close": float(df["close"].iloc[-2]),
    }


_forecasts: dict = {}   # (symbol, tf) -> (signal dict, waktu)
_fc_lock = threading.Lock()
_forecaster = {"obj": None, "key": None}


def run_forecast(c, symbol, tf) -> Signal:
    from bot.forecast import KronosForecaster
    from bot.market import fetch_recent, future_timestamps, tf_ms
    m, s = c["model"], c["strategy"]
    key = (m["name"], m["tokenizer"], m["n_paths"])
    with _fc_lock:
        if _forecaster["key"] != key:
            _forecaster["obj"] = KronosForecaster({**m, "device": m.get("device", "auto")})
            _forecaster["key"] = key
        fc = _forecaster["obj"]
        ex = public_ex(c["exchange"])
        hist = fetch_recent(ex, symbol, tf, int(m["lookback"]))
        y = future_timestamps(hist["timestamps"].iloc[-1], tf_ms(ex, tf), int(m["pred_len"]))
        return build_signal(symbol, hist, fc.paths(hist, y), s["fee_pct"], int(opt(s, "trend_period")))


@app.get("/api/signal")
def get_signal(symbol: str, tf: str):
    c = cfg()
    s = {**DEFAULTS, **c["strategy"]}
    hit = _forecasts.get((symbol, tf))
    bot_row = None
    if tf == c["timeframe"]:
        row = q("SELECT * FROM signals WHERE mode=? AND symbol=? ORDER BY id DESC LIMIT 1", (c["mode"], symbol))
        if not row.empty:
            bot_row = row.iloc[0].to_dict()
    if hit and (bot_row is None or hit[1] >= pd.Timestamp(bot_row["created"]).tz_localize(WIB).timestamp()):
        sig, at = hit
        return {"signal": sig_dict(sig, s, f"Ramalan manual pukul {time.strftime('%H:%M', time.localtime(at))}")}
    if bot_row is not None:
        sig = signal_from_row(bot_row)
        return {"signal": sig_dict(sig, s, f"Ramalan robot, candle {str(sig.time)[11:16]}")}
    return {"signal": None}


@app.post("/api/forecast")
def forecast(symbol: str = Body(..., embed=True), tf: str = Body(..., embed=True)):
    c = cfg()
    if not (KRONOS_DIR / "model").exists():
        fail("Setup belum selesai: folder Kronos belum ada.")
    try:
        sig = run_forecast(c, symbol, tf)
    except Exception as e:  # noqa: BLE001
        fail(f"Gagal meramal {symbol}: {e}", 502)
    _forecasts[(symbol, tf)] = (sig, time.time())
    return {"signal": sig_dict(sig, {**DEFAULTS, **c["strategy"]}, "Ramalan manual barusan")}


_jobs: dict = {}


@app.post("/api/scan")
def scan(symbols: list = Body(..., embed=True), tf: str = Body(..., embed=True)):
    c = cfg()
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "done": 0, "total": len(symbols), "current": "", "rows": [], "finished": False}
    _jobs[jid] = job
    s = {**DEFAULTS, **c["strategy"]}

    def work():
        for sym in symbols:
            job["current"] = sym
            try:
                sig = run_forecast(c, sym, tf)
                _forecasts[(sym, tf)] = (sig, time.time())
                job["rows"].append(sig_dict(sig, s, "pindai"))
            except Exception as e:  # noqa: BLE001
                job["rows"].append({"symbol": sym, "error": str(e)})
            job["done"] += 1
        job["finished"] = True
        job["current"] = ""

    threading.Thread(target=work, daemon=True).start()
    return {"job": jid}


@app.get("/api/scan/{jid}")
def scan_status(jid: str):
    job = _jobs.get(jid)
    if not job:
        fail("Pemindaian tidak ditemukan.", 404)
    rows = sorted(job["rows"], key=lambda r: r.get("score", -1e9), reverse=True)
    return {**job, "rows": [{k: r.get(k) for k in ("symbol", "direction", "exp_ret_pct", "prob_up", "rr", "trend_up",
                                                  "rsi", "score", "would_buy", "decision", "error")} for r in rows]}


# ===================================================================== riwayat
@app.get("/api/history")
def history(mode: str | None = None):
    c = cfg()
    mode = mode or c["mode"]
    eq = q("SELECT time, equity FROM equity WHERE mode=? ORDER BY id", (mode,))
    tr = q("SELECT symbol, entry_time, entry_price, exit_time, exit_price, cost, proceeds, pnl, pnl_pct, "
           "entry_reason, exit_reason FROM positions WHERE mode=? AND status='closed' ORDER BY id DESC", (mode,))
    modes = q("SELECT DISTINCT mode FROM equity UNION SELECT DISTINCT mode FROM positions")
    stats = {}
    if not tr.empty:
        stats = {"trades": int(len(tr)), "win_pct": float((tr["pnl"] > 0).mean() * 100), "pnl": float(tr["pnl"].sum()),
                 "best": float(tr["pnl_pct"].max()), "worst": float(tr["pnl_pct"].min()),
                 "avg": float(tr["pnl_pct"].mean())}
    return {"mode": mode, "modes": sorted(set(modes["mode"].tolist()) | {c["mode"]}) if not modes.empty else [c["mode"]],
            "equity": [{"time": wib_epoch(t), "value": float(v)} for t, v in zip(eq["time"], eq["equity"])],
            "trades": records(tr), "stats": stats}


# ===================================================================== uji strategi
@app.post("/api/backtest/start")
def bt_start(symbol: str = Body(..., embed=True), tf: str = Body(..., embed=True),
             candles: int = Body(500, embed=True), speed: int = Body(3, embed=True),
             optimize: bool = Body(True, embed=True)):
    if ctl.backtest_running():
        fail("Uji strategi lain masih berjalan.")
    if not (KRONOS_DIR / "model").exists():
        fail("Setup belum selesai: folder Kronos belum ada.")
    ctl.start_backtest(symbol, tf, int(candles), max(1, int(speed)), optimize)
    return {"ok": True}


@app.post("/api/backtest/stop")
def bt_stop():
    ctl.stop_backtest()
    return {"ok": True}


@app.get("/api/backtest/status")
def bt_status():
    log = ctl.tail(ctl.BT_LOG, 40)
    lines = [ln.split("| ", 2)[-1] for ln in log.splitlines() if ln.strip()]
    pct, phase = None, (lines[-1] if lines else "")
    for ln in reversed(lines):
        if "Progres" in ln and "%" in ln:
            try:
                pct = float(ln.split("(")[1].split("%")[0])
            except (IndexError, ValueError):
                pass
            break
    running = ctl.backtest_running()
    failed = (not running) and ("Traceback" in log or "Error" in log) and "SELESAI" not in log
    return {"running": running, "pct": pct, "phase": phase, "failed": failed,
            "log": "\n".join(lines[-12:]) if failed else ""}


@app.get("/api/backtest/results")
def bt_results():
    if not BT_DIR.exists():
        return {"results": []}
    files = sorted(BT_DIR.glob("*_ringkasan.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files:
        name = f.name.replace("_ringkasan.txt", "")
        out.append({"name": name, "title": f.read_text(encoding="utf-8").splitlines()[0],
                    "has_opt": (BT_DIR / f"{name}_optimasi.json").exists(),
                    "updated": time.strftime("%d %b %H:%M", time.localtime(f.stat().st_mtime))})
    return {"results": out}


def describe(p):
    stop = (f"SL {p['sl_atr_mult']}×ATR · TP {p['tp_atr_mult']}×ATR" if p.get("sl_mode") == "atr"
            else f"SL {p['stop_loss_pct']}% · TP {p['take_profit_pct']}%")
    trail = (f"trailing {p['trail_pct']}% setelah +{p['trail_activate_pct']}%" if p.get("trailing_on")
             else "tanpa trailing")
    return {"entry": f"ramalan ≥ {p['min_expected_return_pct']}%, peluang ≥ {p['min_prob_up']:.0%}",
            "stop": stop, "trail": trail, "trend": "ikut tren" if p.get("trend_filter") else "abaikan tren"}


@app.get("/api/backtest/result/{name}")
def bt_result(name: str):
    f = BT_DIR / f"{name}_ringkasan.txt"
    if not f.exists() or "/" in name:
        fail("Hasil tidak ditemukan.", 404)
    res = {"name": name, "summary": f.read_text(encoding="utf-8").splitlines()}
    eqf, trf, opf = BT_DIR / f"{name}_equity.csv", BT_DIR / f"{name}_trades.csv", BT_DIR / f"{name}_optimasi.json"
    if eqf.exists():
        cv = pd.read_csv(eqf)
        start_bal = float(cfg()["paper"]["starting_balance"])
        res["equity"] = [{"time": wib_epoch(t), "value": float(v)} for t, v in zip(cv["timestamps"], cv["equity"])]
        res["buyhold"] = [{"time": wib_epoch(t), "value": start_bal * float(c0) / float(cv["close"].iloc[0])}
                          for t, c0 in zip(cv["timestamps"], cv["close"])]
        eqv = cv["equity"]
        res["metrics"] = {"return_pct": float((eqv.iloc[-1] / start_bal - 1) * 100),
                          "buyhold_pct": float((cv["close"].iloc[-1] / cv["close"].iloc[0] - 1) * 100),
                          "max_dd_pct": float(((eqv / eqv.cummax()) - 1).min() * 100)}
    if trf.exists() and trf.stat().st_size > 5:
        tr = pd.read_csv(trf)
        res["trades"] = records(tr)
        if len(tr):
            res["metrics"].update(trades=int(len(tr)), win_pct=float((tr["pnl"] > 0).mean() * 100))
    if opf.exists():
        o = json.loads(opf.read_text())
        o["setelan_sekarang"]["desc"] = describe(o["setelan_sekarang"]["params"])
        for r in o["terbaik"]:
            r["desc"] = describe(r["params"])
        res["optim"] = o
    return res


@app.post("/api/backtest/apply")
def bt_apply(name: str = Body(..., embed=True), k: int = Body(..., embed=True)):
    opf = BT_DIR / f"{name}_optimasi.json"
    if not opf.exists():
        fail("Hasil optimasi tidak ditemukan.", 404)
    o = json.loads(opf.read_text())
    if not (1 <= k <= len(o["terbaik"])):
        fail("Kandidat tidak ada.")
    p = o["terbaik"][k - 1]["params"]
    keys = ["min_expected_return_pct", "min_prob_up", "sl_mode", "stop_loss_pct", "take_profit_pct",
            "sl_atr_mult", "tp_atr_mult", "trailing_on", "trail_activate_pct", "trail_pct", "trend_filter"]
    c = cfg()
    c["strategy"].update({x: p[x] for x in keys if x in p})
    ctl.save_config(c)
    restarted = False
    if ctl.bot_running():
        ctl.restart_bot()
        restarted = True
    return {"ok": True, "restarted": restarted}


# ===================================================================== jalankan
def main():
    url = f"http://localhost:{PORT}"
    with socket.socket() as sck:
        if sck.connect_ex(("127.0.0.1", PORT)) == 0:
            print(f"Panel sudah berjalan. Membuka {url}")
            webbrowser.open(url)
            return
    import uvicorn
    print(f"\n  Panel Kontrol: {url}\n  Biarkan jendela ini terbuka selama memakai panel.\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
