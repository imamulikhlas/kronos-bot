"""
PANEL ROBOT TRADING KRONOS (server lokal).
Dibuka otomatis oleh MULAI.bat / mulai.command -> http://localhost:8501
Hanya bisa diakses dari komputer ini (127.0.0.1).
"""
import json
import os
import socket
import sqlite3
import threading
import time
import uuid
import webbrowser

import pandas as pd
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from bot import control as ctl
from bot.config import KRONOS_DIR, ROOT, api_keys, live_unlocked, load_config, path_in_root
from bot.forecast import Signal, build_signal
from bot.forex import MT5, label as fx_label
from bot.indicators import ema, rsi
from bot.store import WIB, Store
from bot.strategy import entry_side, strat, venue_of

PORT = 8501
STATIC = ROOT / "static"
BT_DIR = path_in_root("data/backtest/x").parent
CONFIRM_TEXT = "SAYA PAHAM RISIKONYA"
MODELS = {
    "ringan": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k"),
    "sedang": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base"),
    "berat": ("NeoQuasar/Kronos-base", "NeoQuasar/Kronos-Tokenizer-base"),
}
TFS = ("15m", "30m", "1h", "4h", "1d")

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


def series(times, values):
    """Titik grafik dengan waktu unik & naik (titik terakhir di detik yang sama dipakai)."""
    out = {}
    for t, v in zip(times, values):
        if v is not None and v == v:
            out[wib_epoch(t)] = float(v)
    return [{"time": k, "value": out[k]} for k in sorted(out)]


def display(sym):
    return sym if "/" in sym else fx_label(sym)


_mk = {"obj": None, "key": None}
_mk_lock = threading.Lock()


def markets():
    """Penghubung data pasar bersama (dibuat ulang jika sumber forex berubah)."""
    from bot.venues import Markets
    c = cfg()
    key = (c.get("exchange"), json.dumps(c.get("forex") or {}, sort_keys=True), MT5.enabled())
    with _mk_lock:
        if _mk["key"] != key:
            _mk["obj"], _mk["key"] = Markets(c), key
        return _mk["obj"]


_ttl: dict = {}


def cached(key, ttl, fn):
    hit = _ttl.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _ttl[key] = (time.time(), val)
    return val


def price_now(symbol):
    try:
        return cached(("px", symbol), 10, lambda: markets().data(venue_of(symbol)).price(symbol))
    except Exception:  # noqa: BLE001
        return None


def sig_dict(sig: Signal, c: dict, source: str):
    venue = venue_of(sig.symbol)
    side, why = entry_side(sig, strat(c, venue))
    d = dict(sig.__dict__)
    d.update(direction=sig.direction, would=side, decision=why, source=source, venue=venue,
             label=display(sig.symbol), t0=wib_epoch(sig.time))
    return d


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


def acc_for(symbol, tf, horizon):
    try:
        return store().accuracy(symbol, tf, horizon)
    except Exception:  # noqa: BLE001
        return {"hit": None, "n": 0, "live_n": 0, "bt_n": 0}


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
    k, sec = api_keys()
    return {
        "mode": c["mode"], "running": running, "crashed": ctl.bot_crashed(),
        "crash_log": ctl.tail(ctl.BOT_CONSOLE, 25) if ctl.bot_crashed() else "",
        "state": s.get_kv("bot_state", "berhenti") if running else "berhenti",
        "next_run": s.get_kv("next_run") if running else None,
        "paused": bool(s.get_kv("pause_entries", False)),
        "symbols": [{"symbol": x, "label": display(x), "venue": venue_of(x)} for x in c["symbols"]],
        "timeframe": c["timeframe"], "max_positions": c["risk"]["max_open_positions"],
        "live_unlocked": live_unlocked(), "setup_ok": (KRONOS_DIR / "model").exists(),
        "toko_keys": bool(k and sec), "mt5_enabled": MT5.enabled(), "mt5_installed": MT5.installed(),
        "forex_source": "mt5" if (MT5.enabled() and MT5.installed()) else "yahoo",
        "has_backtest": BT_DIR.exists() and any(BT_DIR.glob("*_ringkasan.txt")),
        "has_signals": not q("SELECT 1 FROM signals LIMIT 1").empty,
        "server_time": int(time.time() * 1000),
    }


@app.post("/api/bot/start")
def bot_start():
    c = cfg()
    if c["mode"] == "live" and not live_unlocked():
        fail("Mode live belum dikonfirmasi. Buka halaman Akun.")
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
    mk = markets()
    positions = []
    for p in records(openp):
        side = p.get("side") or "long"
        k = -1 if side == "short" else 1
        now = price_now(p["symbol"])
        p.update(side=side, venue=p.get("venue") or venue_of(p["symbol"]), label=display(p["symbol"]), price_now=now)
        p["pnl_pct_now"] = (now / p["entry_price"] - 1) * 100 * k if now else None
        if now is None:
            p["pnl_now"] = None
        elif p["venue"] == "crypto":
            p["pnl_now"] = now * p["amount"] - p["cost"]
        else:
            try:
                p["pnl_now"] = p["amount"] * (now - p["entry_price"]) * k * mk.data("forex").quote_to_usd(p["symbol"], now)
            except Exception:  # noqa: BLE001
                p["pnl_now"] = None
        positions.append(p)
    sig = q("SELECT * FROM signals WHERE mode=? ORDER BY id DESC LIMIT 300", (mode,))
    decisions = []
    if not sig.empty:
        for row in records(sig.drop_duplicates("symbol")):
            if row["symbol"] not in c["symbols"]:
                continue
            acc = acc_for(row["symbol"], c["timeframe"], row.get("horizon") or c["model"]["pred_len"])
            decisions.append({**{k: row.get(k) for k in ("symbol", "candle_time", "last_close", "exp_ret_pct",
                                                          "prob_up", "prob_down", "direction", "action", "reason")},
                              "label": display(row["symbol"]), "venue": venue_of(row["symbol"]),
                              "accuracy": acc["hit"], "acc_n": acc["n"]})
    ev = q("SELECT time, level, message FROM events WHERE mode=? ORDER BY id DESC LIMIT 25", (mode,))
    start_eq = float(eq["equity"].iloc[0]) if not eq.empty else None
    tail = eq.tail(600)
    return {
        "mode": mode,
        "equity": float(eq["equity"].iloc[-1]) if not eq.empty else None,
        "equity_change_pct": (float(eq["equity"].iloc[-1]) / start_eq - 1) * 100 if start_eq else None,
        "pnl_total": float(closed["pnl"].sum()) if not closed.empty else 0.0,
        "pnl_today": float(closed[closed["exit_time"].str.startswith(today)]["pnl"].sum()) if not closed.empty else 0.0,
        "trades": int(len(closed)),
        "win_pct": float((closed["pnl"] > 0).mean() * 100) if not closed.empty else None,
        "max_positions": c["risk"]["max_open_positions"],
        "positions": positions, "decisions": decisions, "events": records(ev),
        "equity_series": series(tail["time"], tail["equity"]),
    }


@app.post("/api/positions/close")
def close_positions(ids: list = Body(..., embed=True)):
    """ids = daftar id posisi, atau ["ALL"]."""
    c = cfg()
    if ctl.bot_running():
        s = store(c["mode"])
        s.set_kv("close_requests", list(set(s.get_kv("close_requests", []) + ids)))
        return {"ok": True, "queued": True, "message": "Perintah tutup dikirim. Robot menutup dalam beberapa detik."}
    from bot.engine import Engine
    from bot.venues import Markets
    s = store(c["mode"])
    eng = Engine(c, s, None, Markets(c, s, live=c["mode"] == "live"))
    n = 0
    for pos in s.open_positions():
        if "ALL" in ids or pos["id"] in ids:
            eng.close(pos, "ditutup manual dari panel")
            n += 1
    return {"ok": True, "queued": False, "message": f"{n} posisi ditutup."}


# ===================================================================== pengaturan
@app.get("/api/config")
def get_config():
    c = cfg()
    model = next((k for k, v in MODELS.items() if v[0] == c["model"]["name"]), "sedang")
    return {"symbols": c["symbols"], "timeframe": c["timeframe"], "risk": c["risk"],
            "strategy": strat(c, "crypto"), "strategy_forex": strat(c, "forex"),
            "forex": {"source": "auto", "leverage": 100, "risk_pct": 1.0, "max_lots": 1.0, **(c.get("forex") or {})},
            "model": {**c["model"], "size": model}, "paper": c["paper"]}


STRAT_TYPES = {"fee_pct": float, "min_expected_return_pct": float, "min_prob_up": float, "stop_loss_pct": float,
               "take_profit_pct": float, "max_hold_candles": int, "exit_prob_up_below": float,
               "cooldown_candles": int, "trend_filter": bool, "trend_period": int, "rsi_max": float, "min_rr": float,
               "sl_mode": str, "sl_atr_mult": float, "tp_atr_mult": float, "trailing_on": bool,
               "trail_activate_pct": float, "trail_pct": float, "min_accuracy": float, "min_accuracy_n": int,
               "require_proof": bool, "allow_short": bool}
NUM = {
    "risk": {"order_size_quote": float, "max_order_size_quote": float, "max_open_positions": int,
             "max_daily_loss_quote": float},
    "strategy": STRAT_TYPES, "strategy_forex": STRAT_TYPES,
    "forex": {"source": str, "leverage": float, "risk_pct": float, "max_lots": float},
    "paper": {"starting_balance": float, "slippage_pct": float},
}


@app.post("/api/config")
def save_config(body: dict = Body(...)):
    c = cfg()
    if "symbols" in body:
        syms = []
        for x in body["symbols"]:
            x = str(x).strip().upper()
            if x and x not in syms:
                syms.append(x)
        if not syms:
            fail("Pilih minimal satu pasar.")
        c["symbols"] = syms
    if body.get("timeframe") in TFS:
        c["timeframe"] = body["timeframe"]
    for sec, fields in NUM.items():
        src = body.get(sec) or {}
        c.setdefault(sec, {})
        for k, typ in fields.items():
            if k in src:
                try:
                    c[sec][k] = typ(src[k])
                except (TypeError, ValueError):
                    fail(f"Nilai {k} tidak valid.")
    for sec in ("strategy", "strategy_forex"):
        if c[sec].get("sl_mode") not in ("persen", "atr"):
            c[sec]["sl_mode"] = "persen"
    if c["forex"].get("source") not in ("auto", "mt5", "yahoo"):
        c["forex"]["source"] = "auto"
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
def pairs(venue: str = "crypto"):
    if venue not in ("crypto", "forex"):
        fail("Pasar tidak dikenal.")
    try:
        lst = cached(("pairs", venue, MT5.enabled()), 1800, lambda: markets().data(venue).pairs())
        return {"pairs": [{"symbol": p, "label": display(p)} for p in lst]}
    except Exception as e:  # noqa: BLE001
        fallback = [x for x in cfg()["symbols"] if venue_of(x) == venue]
        return {"pairs": [{"symbol": p, "label": display(p)} for p in fallback], "error": f"Daftar tidak bisa diambil: {e}"}


# ===================================================================== akun & mode
def mask(v):
    return ("•" * 6 + str(v)[-4:]) if v else ""


@app.get("/api/account")
def account():
    k, s = api_keys()
    c = cfg()
    env = ctl.read_env()
    return {"mode": c["mode"], "key": mask(k), "secret": mask(s), "has_keys": bool(k and s),
            "live_unlocked": live_unlocked(), "running": ctl.bot_running(), "confirm_text": CONFIRM_TEXT,
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
    c = cfg()
    try:
        bal = make_exchange(c, private=True).fetch_balance()
    except SystemExit as e:
        fail(str(e))
    except Exception as e:  # noqa: BLE001
        fail(f"Tokocrypto menolak: {e}")
    free = bal.get("free") or {}
    assets = sorted(((k, float(v)) for k, v in free.items() if v and float(v) > 0), key=lambda x: -x[1])[:8]
    return {"ok": True, "usdt": float(free.get(c.get("quote", "USDT"), 0) or 0), "assets": assets}


@app.post("/api/mt5")
def set_mt5(enabled: bool = Body(..., embed=True), login: str = Body("", embed=True),
            password: str = Body("", embed=True), server: str = Body("", embed=True), path: str = Body("", embed=True)):
    vals = {"MT5_ENABLED": "YA" if enabled else "TIDAK", "MT5_LOGIN": login.strip(),
            "MT5_SERVER": server.strip(), "MT5_PATH": path.strip()}
    if login.strip() and not login.strip().isdigit():
        fail("Nomor login MT5 hanya berisi angka.")
    if password:
        vals["MT5_PASSWORD"] = password
    ctl.save_env(vals)
    MT5.mod = None
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


@app.post("/api/account/mode")
def set_mode(mode: str = Body(..., embed=True), confirm: str = Body("", embed=True)):
    c = cfg()
    if mode == "live":
        if confirm.strip().upper() != CONFIRM_TEXT:
            fail("Teks konfirmasi belum sesuai.")
        need_toko = any(venue_of(x) == "crypto" for x in c["symbols"])
        need_mt5 = any(venue_of(x) == "forex" for x in c["symbols"])
        if need_toko and not all(api_keys()):
            fail("Simpan API key Tokocrypto dulu (ada pasar kripto di daftar kamu).")
        if need_mt5 and not (MT5.enabled() and MT5.installed()):
            fail("Hubungkan MetaTrader 5 dulu (ada pasar forex di daftar kamu).")
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
    for t in ("positions", "equity", "events"):
        s.db.execute(f"DELETE FROM {t} WHERE mode='paper'")
    s.db.execute("DELETE FROM kv WHERE key='paper_cash' OR key LIKE 'last_exit_ts:paper:%'")
    s.db.commit()
    return {"ok": True}


# ===================================================================== analisa
@app.get("/api/candles")
def candles(symbol: str, tf: str, limit: int = 300):
    if tf not in TFS:
        fail("Timeframe tidak dikenal.")
    venue = venue_of(symbol)
    data = markets().data(venue)
    try:
        df = cached(("ohlcv", symbol, tf), 8, lambda: data.raw(symbol, tf, min(limit, 1000)))
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
        "ema50": [{"time": a, "value": float(v)} for a, v in zip(t, e50)],
        "ema200": [{"time": a, "value": float(v)} for a, v in zip(t, e200)],
        "rsi": [{"time": a, "value": float(v)} for a, v in zip(t, r)][20:],
        "step": int(data.tf_ms(tf) // 1000), "venue": venue, "source": getattr(data, "source", ""),
        "last": float(df["close"].iloc[-1]), "prev_close": float(df["close"].iloc[-2]) if len(df) > 1 else None,
        "label": display(symbol),
    }


_forecasts: dict = {}
_fc_lock = threading.Lock()
_forecaster = {"obj": None, "key": None}


def run_forecast(c, symbol, tf) -> Signal:
    from bot.forecast import KronosForecaster
    m = c["model"]
    venue = venue_of(symbol)
    s = strat(c, venue)
    key = (m["name"], m["tokenizer"], m["n_paths"])
    data = markets().data(venue)
    hist = data.recent(symbol, tf, int(m["lookback"]))
    if len(hist) < 100:
        raise RuntimeError(f"data hanya {len(hist)} candle")
    y = data.future_ts(hist["timestamps"].iloc[-1], tf, int(m["pred_len"]))
    with _fc_lock:
        if _forecaster["key"] != key:
            _forecaster["obj"] = KronosForecaster({**m, "device": m.get("device", "auto")})
            _forecaster["key"] = key
        paths = _forecaster["obj"].paths(hist, y)
    sig = build_signal(symbol, hist, paths, s["fee_pct"], int(s["trend_period"]))
    acc = acc_for(symbol, tf, sig.horizon)
    sig.accuracy, sig.acc_n = acc["hit"], acc["n"]
    return sig


@app.get("/api/signal")
def get_signal(symbol: str, tf: str):
    c = cfg()
    hit = _forecasts.get((symbol, tf))
    bot_row = None
    row = q("SELECT * FROM signals WHERE mode=? AND symbol=? AND (tf=? OR tf IS NULL) ORDER BY id DESC LIMIT 1",
            (c["mode"], symbol, tf))
    if not row.empty and (row.iloc[0]["tf"] == tf or tf == c["timeframe"]):
        bot_row = row.iloc[0].to_dict()
    if hit and (bot_row is None or hit[1] >= pd.Timestamp(bot_row["created"]).tz_localize(WIB).timestamp()):
        sig, at = hit
        return {"signal": sig_dict(sig, c, f"ramalan manual {time.strftime('%H:%M', time.localtime(at))}")}
    if bot_row is not None:
        sig = signal_from_row(bot_row)
        acc = acc_for(symbol, tf, sig.horizon)
        sig.accuracy, sig.acc_n = acc["hit"], acc["n"]
        return {"signal": sig_dict(sig, c, f"ramalan robot, candle {str(sig.time)[11:16]}")}
    return {"signal": None}


@app.post("/api/forecast")
def forecast(symbol: str = Body(..., embed=True), tf: str = Body(..., embed=True)):
    c = cfg()
    if not (KRONOS_DIR / "model").exists():
        fail("Setup belum selesai: folder Kronos belum ada.")
    try:
        sig = run_forecast(c, symbol, tf)
    except Exception as e:  # noqa: BLE001
        fail(f"Gagal meramal {display(symbol)}: {e}", 502)
    _forecasts[(symbol, tf)] = (sig, time.time())
    return {"signal": sig_dict(sig, c, "ramalan manual barusan")}


_jobs: dict = {}


@app.post("/api/scan")
def scan(symbols: list = Body(..., embed=True), tf: str = Body(..., embed=True)):
    c = cfg()
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "done": 0, "total": len(symbols), "current": "", "rows": [], "finished": False}
    _jobs[jid] = job

    def work():
        for sym in symbols:
            job["current"] = display(sym)
            try:
                sig = run_forecast(c, sym, tf)
                _forecasts[(sym, tf)] = (sig, time.time())
                job["rows"].append(sig_dict(sig, c, "pindai"))
            except Exception as e:  # noqa: BLE001
                job["rows"].append({"symbol": sym, "label": display(sym), "error": str(e)})
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
    keys = ("symbol", "label", "venue", "direction", "exp_ret_pct", "prob_up", "prob_down", "rr", "rr_short",
            "trend_up", "trend_down", "rsi", "score", "would", "decision", "accuracy", "acc_n", "error")

    def strength(r):
        return max(r.get("exp_ret_pct", 0) * r.get("prob_up", 0), -r.get("exp_ret_pct", 0) * r.get("prob_down", 0)) \
            if "error" not in r else -1e9
    rows = sorted(job["rows"], key=strength, reverse=True)
    return {**job, "rows": [{k: r.get(k) for k in keys} for r in rows]}


# ===================================================================== rapor akurasi
@app.get("/api/accuracy")
def accuracy():
    c = cfg()
    out = []
    for sym in c["symbols"]:
        v = venue_of(sym)
        s = strat(c, v)
        a = acc_for(sym, c["timeframe"], int(c["model"]["pred_len"]))
        need, n_min = float(s.get("min_accuracy") or 0), int(s.get("min_accuracy_n") or 0)
        if a["n"] < n_min:
            state = "belum"
        elif need and a["hit"] is not None and a["hit"] < need:
            state = "kurang"
        else:
            state = "lolos"
        out.append({"symbol": sym, "label": display(sym), "venue": v, **a, "need": need, "n_min": n_min,
                    "state": state, "blocking": state == "kurang" or (state == "belum" and bool(s.get("require_proof")))})
    return {"rows": out, "timeframe": c["timeframe"]}


# ===================================================================== riwayat
@app.get("/api/history")
def history(mode: str | None = None):
    c = cfg()
    mode = mode or c["mode"]
    eq = q("SELECT time, equity FROM equity WHERE mode=? ORDER BY id", (mode,))
    tr = q("SELECT symbol, side, venue, lots, entry_time, entry_price, exit_time, exit_price, cost, pnl, pnl_pct, "
           "entry_reason, exit_reason FROM positions WHERE mode=? AND status='closed' ORDER BY id DESC", (mode,))
    modes = q("SELECT DISTINCT mode FROM equity UNION SELECT DISTINCT mode FROM positions")
    stats = {}
    if not tr.empty:
        tr["side"] = tr["side"].fillna("long")
        tr["label"] = tr["symbol"].map(display)
        stats = {"trades": int(len(tr)), "win_pct": float((tr["pnl"] > 0).mean() * 100), "pnl": float(tr["pnl"].sum()),
                 "best": float(tr["pnl"].max()), "worst": float(tr["pnl"].min())}
    return {"mode": mode, "modes": sorted(set(modes["mode"].tolist()) | {c["mode"]}) if not modes.empty else [c["mode"]],
            "equity": series(eq["time"], eq["equity"]),
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
    failed = (not running) and ("Traceback" in log or "Error" in log or "SystemExit" in log) and "SELESAI" not in log
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
        meta = BT_DIR / f"{name}_meta.json"
        m = json.loads(meta.read_text()) if meta.exists() else {}
        sym = m.get("symbol") or name.split("_")[0]
        out.append({"name": name, "symbol": sym, "label": display(sym) if m else sym, "tf": m.get("tf", ""),
                    "venue": m.get("venue", venue_of(sym)), "dummy": name.endswith("_dummy"),
                    "return_pct": (m.get("metrics") or {}).get("return_pct"),
                    "has_opt": (BT_DIR / f"{name}_optimasi.json").exists(),
                    "updated": time.strftime("%d %b, %H:%M", time.localtime(f.stat().st_mtime))})
    return {"results": out}


def describe(p, venue):
    stop = (f"SL {p['sl_atr_mult']}× volatilitas, target {p['tp_atr_mult']}×" if p.get("sl_mode") == "atr"
            else f"SL {p['stop_loss_pct']}%, target {p['take_profit_pct']}%")
    trail = (f"trailing {p['trail_pct']}% setelah +{p['trail_activate_pct']}%" if p.get("trailing_on")
             else "tanpa trailing")
    sides = "buy & sell" if p.get("allow_short") else "buy saja"
    return {"entry": f"ramalan ≥ {p['min_expected_return_pct']}%, peluang ≥ {round(p['min_prob_up'] * 100)}%",
            "stop": stop, "trail": trail, "trend": "ikut tren" if p.get("trend_filter") else "abaikan tren",
            "sides": sides if venue == "forex" else ""}


@app.get("/api/backtest/result/{name}")
def bt_result(name: str):
    f = BT_DIR / f"{name}_ringkasan.txt"
    if "/" in name or ".." in name or not f.exists():
        fail("Hasil tidak ditemukan.", 404)
    res = {"name": name, "summary": f.read_text(encoding="utf-8").splitlines()}
    meta = BT_DIR / f"{name}_meta.json"
    if meta.exists():
        m = json.loads(meta.read_text())
        res.update(symbol=m["symbol"], label=display(m["symbol"]), venue=m["venue"], tf=m["tf"],
                   metrics=m["metrics"], accuracy=m["accuracy"])
    eqf, trf, opf = BT_DIR / f"{name}_equity.csv", BT_DIR / f"{name}_trades.csv", BT_DIR / f"{name}_optimasi.json"
    if eqf.exists():
        cv = pd.read_csv(eqf)
        start_bal = float(cv["equity"].iloc[0]) if len(cv) else 1.0
        res["equity"] = series(cv["timestamps"], cv["equity"])
        res["buyhold"] = series(cv["timestamps"], start_bal * cv["close"] / float(cv["close"].iloc[0]))
        res["period"] = [str(cv["timestamps"].iloc[0])[:16], str(cv["timestamps"].iloc[-1])[:16]]
    if trf.exists() and trf.stat().st_size > 5:
        res["trades"] = records(pd.read_csv(trf))
    if opf.exists():
        o = json.loads(opf.read_text())
        v = o.get("venue", venue_of(o["symbol"]))
        o["setelan_sekarang"]["desc"] = describe(o["setelan_sekarang"]["params"], v)
        for r in o["terbaik"]:
            r["desc"] = describe(r["params"], v)
        res["optim"] = o
    return res


@app.post("/api/backtest/apply")
def bt_apply(name: str = Body(..., embed=True), k: int = Body(..., embed=True)):
    opf = BT_DIR / f"{name}_optimasi.json"
    if "/" in name or not opf.exists():
        fail("Hasil optimasi tidak ditemukan.", 404)
    o = json.loads(opf.read_text())
    if not (1 <= k <= len(o["terbaik"])):
        fail("Kandidat tidak ada.")
    venue = o.get("venue", venue_of(o["symbol"]))
    sec = "strategy" if venue == "crypto" else "strategy_forex"
    p = o["terbaik"][k - 1]["params"]
    c = cfg()
    c.setdefault(sec, {})
    c[sec].update({x: v for x, v in p.items() if x in STRAT_TYPES and v is not None})
    if venue == "crypto":
        c[sec].pop("allow_short", None)
    ctl.save_config(c)
    restarted = False
    if ctl.bot_running():
        ctl.restart_bot()
        restarted = True
    return {"ok": True, "restarted": restarted, "venue": venue}


# ===================================================================== jalankan
def main():
    url = f"http://localhost:{PORT}"
    with socket.socket() as sck:
        if sck.connect_ex(("127.0.0.1", PORT)) == 0:
            print(f"Panel sudah berjalan. Membuka {url}")
            webbrowser.open(url)
            return
    import uvicorn
    print(f"\n  Panel robot: {url}\n  Biarkan jendela ini terbuka selama memakai panel.\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
