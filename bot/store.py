"""Penyimpanan SQLite: posisi, riwayat trade, sinyal, dan kurva ekuitas.
Dashboard membaca file database yang sama."""
import json
import sqlite3
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT, symbol TEXT, status TEXT,
    entry_time TEXT, entry_price REAL, amount REAL, cost REAL, entry_fee REAL,
    entry_candle_ts INTEGER, entry_reason TEXT, order_id_buy TEXT,
    exit_time TEXT, exit_price REAL, proceeds REAL, exit_fee REAL, exit_reason TEXT, order_id_sell TEXT,
    pnl REAL, pnl_pct REAL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT, created TEXT, candle_time TEXT, symbol TEXT, last_close REAL,
    exp_ret_pct REAL, median_ret_pct REAL, prob_up REAL, pred_high REAL, pred_low REAL,
    action TEXT, reason TEXT, path TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT, time TEXT, cash REAL, positions_value REAL, equity REAL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, time TEXT, level TEXT, message TEXT
);
"""


def now_wib() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")


VCOL = "COALESCE(venue,'crypto')"   # data lama tanpa kolom market dianggap kripto


class Store:
    """mode = 'paper' | 'live'. venue = 'crypto' | 'forex' (None = semua market, untuk laporan)."""

    def __init__(self, path, mode: str, venue: str | None = None):
        self.mode, self.venue = mode, venue
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self):
        """Tambah kolom baru ke database lama tanpa menghapus data."""
        want = {
            "positions": {"sl": "REAL", "tp": "REAL", "peak": "REAL", "side": "TEXT", "venue": "TEXT",
                          "lots": "REAL"},
            "signals": {"path_lo": "TEXT", "path_hi": "TEXT", "trend_up": "INTEGER", "rsi": "REAL",
                        "atr_pct": "REAL", "rr": "REAL", "score": "REAL", "direction": "TEXT",
                        "prob_down": "REAL", "trend_down": "INTEGER", "rr_short": "REAL", "venue": "TEXT",
                        "tf": "TEXT", "horizon": "INTEGER", "eval_ret_pct": "REAL", "hit": "INTEGER"},
            "equity": {"venue": "TEXT"},
            "events": {"venue": "TEXT"},
        }
        for table, cols in want.items():
            have = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for c, t in cols.items():
                if c not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {c} {t}")

    # ---------- key-value ----------
    def get_kv(self, key, default=None):
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_kv(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value)))
        self.db.commit()

    # status per market (mis. 'bot_state:forex')
    def vkey(self, name):
        return f"{name}:{self.venue}" if self.venue else name

    def vget(self, name, default=None):
        return self.get_kv(self.vkey(name), default)

    def vset(self, name, value):
        self.set_kv(self.vkey(name), value)

    def _vfilter(self, q, args):
        if self.venue:
            q += f" AND {VCOL}=?"
            args.append(self.venue)
        return q, args

    # ---------- positions ----------
    def open_positions(self, symbol=None):
        q, args = self._vfilter("SELECT * FROM positions WHERE mode=? AND status='open'", [self.mode])
        if symbol:
            q += " AND symbol=?"
            args.append(symbol)
        return [dict(r) for r in self.db.execute(q, args)]

    def add_position(self, symbol, fill, candle_ts, reason, sl=None, tp=None, side="long", venue="crypto"):
        self.db.execute(
            "INSERT INTO positions(mode,symbol,status,entry_time,entry_price,amount,cost,entry_fee,"
            "entry_candle_ts,entry_reason,order_id_buy,sl,tp,peak,side,venue,lots)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.mode, symbol, "open", now_wib(), fill.price, fill.amount, fill.cost, fill.fee,
             int(candle_ts), reason, fill.order_id, sl, tp, fill.price, side, venue, fill.lots))
        self.db.commit()

    def update_stops(self, pos_id, sl, tp, peak):
        self.db.execute("UPDATE positions SET sl=?, tp=?, peak=? WHERE id=?", (sl, tp, peak, pos_id))
        self.db.commit()

    def close_position(self, pos_id, fill, reason):
        pos = dict(self.db.execute("SELECT * FROM positions WHERE id=?", (pos_id,)).fetchone())
        pnl = fill.pnl if fill.pnl is not None else fill.proceeds - pos["cost"]
        pct = fill.pnl_pct if fill.pnl_pct is not None else (pnl / pos["cost"] * 100 if pos["cost"] else 0)
        self.db.execute(
            "UPDATE positions SET status='closed', exit_time=?, exit_price=?, proceeds=?, exit_fee=?,"
            " exit_reason=?, order_id_sell=?, pnl=?, pnl_pct=? WHERE id=?",
            (now_wib(), fill.price, fill.proceeds, fill.fee, reason, fill.order_id, pnl, pct, pos_id))
        self.db.commit()
        return pnl

    def last_exit_candle(self, symbol):
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (f"last_exit_ts:{self.mode}:{symbol}",)).fetchone()
        return json.loads(r["value"]) if r else None

    def realized_pnl_today(self) -> float:
        today = datetime.now(WIB).strftime("%Y-%m-%d")
        q, args = self._vfilter("SELECT COALESCE(SUM(pnl),0) s FROM positions WHERE mode=? AND status='closed' "
                                "AND exit_time LIKE ?", [self.mode, today + "%"])
        r = self.db.execute(q, args).fetchone()
        return float(r["s"])

    # ---------- signals / equity / events ----------
    def add_signal(self, sig, action, reason, venue="crypto", tf=""):
        self.db.execute(
            "INSERT INTO signals(mode,created,candle_time,symbol,last_close,exp_ret_pct,median_ret_pct,"
            "prob_up,pred_high,pred_low,action,reason,path,path_lo,path_hi,trend_up,rsi,atr_pct,rr,score,direction,"
            "prob_down,trend_down,rr_short,venue,tf,horizon)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.mode, now_wib(), sig.time, sig.symbol, sig.last_close, sig.exp_ret_pct,
             sig.median_ret_pct, sig.prob_up, sig.pred_high, sig.pred_low, action, reason,
             json.dumps(sig.path), json.dumps(sig.path_lo), json.dumps(sig.path_hi), int(sig.trend_up),
             sig.rsi, sig.atr_pct, sig.rr, sig.score, sig.direction,
             sig.prob_down, int(sig.trend_down), sig.rr_short, venue, tf, sig.horizon))
        self.db.commit()

    # ---------- rapor akurasi ----------
    def evaluate_signals(self, symbol, tf, hist):
        """Nilai ramalan lama yang horizonnya sudah lewat: apakah arah ramalannya benar?"""
        rows = self.db.execute(
            "SELECT id, candle_time, last_close, exp_ret_pct, horizon FROM signals "
            "WHERE symbol=? AND tf=? AND hit IS NULL AND horizon > 0", (symbol, tf)).fetchall()
        if not rows:
            return 0
        times = [str(t) for t in hist["timestamps"]]
        idx = {t: i for i, t in enumerate(times)}
        closes = hist["close"].to_numpy(float)
        first = times[0] if times else ""
        n = 0
        for r in rows:
            i = idx.get(str(r["candle_time"]))
            if i is None:
                if str(r["candle_time"]) < first:
                    self.db.execute("UPDATE signals SET hit=-1 WHERE id=?", (r["id"],))
                continue
            j = i + int(r["horizon"])
            if j >= len(closes):
                continue
            actual = (closes[j] / r["last_close"] - 1) * 100
            hit = -1 if r["exp_ret_pct"] == 0 or actual == 0 else int((actual > 0) == (r["exp_ret_pct"] > 0))
            self.db.execute("UPDATE signals SET eval_ret_pct=?, hit=? WHERE id=?", (actual, hit, r["id"]))
            n += 1
        self.db.commit()
        return n

    def set_backtest_accuracy(self, symbol, tf, horizon, hits, n):
        self.set_kv(f"acc_bt:{symbol}:{tf}", {"hits": int(hits), "n": int(n), "horizon": int(horizon),
                                              "at": now_wib()})

    def accuracy(self, symbol, tf, horizon, last=80) -> dict:
        """Akurasi arah: gabungan ramalan robot yang sudah dinilai + hasil uji strategi."""
        rows = self.db.execute(
            "SELECT hit FROM (SELECT candle_time, MAX(id) id, hit FROM signals WHERE symbol=? AND tf=? AND horizon=? "
            "AND hit IN (0,1) GROUP BY candle_time) ORDER BY id DESC LIMIT ?", (symbol, tf, int(horizon), last)).fetchall()
        live_n = len(rows)
        live_hits = sum(r["hit"] for r in rows)
        bt = self.get_kv(f"acc_bt:{symbol}:{tf}") or {}
        bt_n = int(bt.get("n", 0)) if int(bt.get("horizon", -1)) == int(horizon) else 0
        bt_hits = int(bt.get("hits", 0)) if bt_n else 0
        n = live_n + bt_n
        return {"hit": (live_hits + bt_hits) / n if n else None, "n": n, "live_n": live_n,
                "live_hit": live_hits / live_n if live_n else None, "bt_n": bt_n,
                "bt_hit": bt_hits / bt_n if bt_n else None, "bt_at": bt.get("at") if bt_n else None}

    def add_equity(self, cash, pos_value):
        self.db.execute("INSERT INTO equity(mode,time,cash,positions_value,equity,venue) VALUES(?,?,?,?,?,?)",
                        (self.mode, now_wib(), cash, pos_value, cash + pos_value, self.venue))
        self.db.commit()

    def event(self, level, message):
        self.db.execute("INSERT INTO events(mode,time,level,message,venue) VALUES(?,?,?,?,?)",
                        (self.mode, now_wib(), level, message, self.venue))
        self.db.commit()
