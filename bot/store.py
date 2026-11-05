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


class Store:
    def __init__(self, path, mode: str):
        self.mode = mode
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---------- key-value ----------
    def get_kv(self, key, default=None):
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_kv(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value)))
        self.db.commit()

    # ---------- positions ----------
    def open_positions(self, symbol=None):
        q = "SELECT * FROM positions WHERE mode=? AND status='open'"
        args = [self.mode]
        if symbol:
            q += " AND symbol=?"
            args.append(symbol)
        return [dict(r) for r in self.db.execute(q, args)]

    def add_position(self, symbol, fill, candle_ts, reason):
        self.db.execute(
            "INSERT INTO positions(mode,symbol,status,entry_time,entry_price,amount,cost,entry_fee,"
            "entry_candle_ts,entry_reason,order_id_buy) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (self.mode, symbol, "open", now_wib(), fill.price, fill.amount, fill.cost, fill.fee,
             int(candle_ts), reason, fill.order_id))
        self.db.commit()

    def close_position(self, pos_id, fill, reason):
        pos = dict(self.db.execute("SELECT * FROM positions WHERE id=?", (pos_id,)).fetchone())
        pnl = fill.proceeds - pos["cost"]
        self.db.execute(
            "UPDATE positions SET status='closed', exit_time=?, exit_price=?, proceeds=?, exit_fee=?,"
            " exit_reason=?, order_id_sell=?, pnl=?, pnl_pct=? WHERE id=?",
            (now_wib(), fill.price, fill.proceeds, fill.fee, reason, fill.order_id,
             pnl, pnl / pos["cost"] * 100 if pos["cost"] else 0, pos_id))
        self.db.commit()
        return pnl

    def last_exit_candle(self, symbol):
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (f"last_exit_ts:{self.mode}:{symbol}",)).fetchone()
        return json.loads(r["value"]) if r else None

    def realized_pnl_today(self) -> float:
        today = datetime.now(WIB).strftime("%Y-%m-%d")
        r = self.db.execute(
            "SELECT COALESCE(SUM(pnl),0) s FROM positions WHERE mode=? AND status='closed' AND exit_time LIKE ?",
            (self.mode, today + "%")).fetchone()
        return float(r["s"])

    # ---------- signals / equity / events ----------
    def add_signal(self, sig, action, reason):
        self.db.execute(
            "INSERT INTO signals(mode,created,candle_time,symbol,last_close,exp_ret_pct,median_ret_pct,"
            "prob_up,pred_high,pred_low,action,reason,path) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.mode, now_wib(), sig.time, sig.symbol, sig.last_close, sig.exp_ret_pct,
             sig.median_ret_pct, sig.prob_up, sig.pred_high, sig.pred_low, action, reason,
             json.dumps(sig.path)))
        self.db.commit()

    def add_equity(self, cash, pos_value):
        self.db.execute("INSERT INTO equity(mode,time,cash,positions_value,equity) VALUES(?,?,?,?,?)",
                        (self.mode, now_wib(), cash, pos_value, cash + pos_value))
        self.db.commit()

    def event(self, level, message):
        self.db.execute("INSERT INTO events(mode,time,level,message) VALUES(?,?,?,?)",
                        (self.mode, now_wib(), level, message))
        self.db.commit()
