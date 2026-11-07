"""Data & koneksi forex.

Sumber data:
  - MetaTrader 5 (MT5) jika aplikasi MT5 terpasang di Windows dan diaktifkan di panel.
    Harga & order langsung dari broker kamu (bisa akun demo).
  - Yahoo Finance jika MT5 tidak tersedia. Cukup untuk analisa & simulasi, tidak untuk order sungguhan.
"""
import logging
import math
import os
import re
import threading
import time

import pandas as pd

from .market import TZ

log = logging.getLogger("forex")

TF_SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
                 "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "XAUUSD", "XAGUSD"]
YAHOO_SPECIAL = {"XAUUSD": "GC=F", "XAGUSD": "SI=F"}


# ===================================================================== simbol
def clean(sym: str) -> str:
    """'EURUSDm' / 'EURUSD.pro' -> 'EURUSD'."""
    return re.sub(r"[^A-Z]", "", str(sym).upper())[:6]


def base_quote(sym: str) -> tuple[str, str]:
    c = clean(sym)
    return c[:3], c[3:6]


def contract_size(sym: str) -> float:
    return {"XAU": 100.0, "XAG": 5000.0}.get(clean(sym)[:3], 100000.0)


def yahoo_symbol(sym: str) -> str:
    c = clean(sym)
    return YAHOO_SPECIAL.get(c, f"{c}=X")


def label(sym: str) -> str:
    b, q = base_quote(sym)
    return f"{b}/{q}"


# ===================================================================== MetaTrader 5
class MT5:
    """Koneksi tunggal ke aplikasi MetaTrader 5 di komputer ini."""
    mod = None
    lock = threading.RLock()
    _offset = None

    @staticmethod
    def installed() -> bool:
        try:
            import MetaTrader5  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def enabled() -> bool:
        return os.getenv("MT5_ENABLED", "").strip().upper() == "YA"

    @classmethod
    def connect(cls):
        with cls.lock:
            if cls.mod is not None:
                try:
                    if cls.mod.terminal_info() is not None and cls.mod.account_info() is not None:
                        return cls.mod
                except Exception:  # noqa: BLE001
                    pass
            if not cls.installed():
                raise RuntimeError("Library MetaTrader5 belum terpasang. MT5 hanya bisa dipakai di Windows.")
            import MetaTrader5 as mt5
            args, kw = [], {"timeout": 30000}
            if os.getenv("MT5_PATH", "").strip():
                args.append(os.getenv("MT5_PATH").strip())
            login = os.getenv("MT5_LOGIN", "").strip()
            if login:
                kw.update(login=int(login), password=os.getenv("MT5_PASSWORD", ""),
                          server=os.getenv("MT5_SERVER", "").strip())
            if not mt5.initialize(*args, **kw):
                err = mt5.last_error()
                mt5.shutdown()
                raise RuntimeError(f"MetaTrader 5 tidak bisa dihubungkan ({err}). Pastikan aplikasi MT5 terpasang, "
                                   "sudah login ke akun broker, dan opsi Algo Trading aktif.")
            cls.mod = mt5
            return mt5

    @classmethod
    def offset_sec(cls, symbol: str) -> int:
        """Selisih jam server broker terhadap UTC (MT5 memberi waktu dalam jam server)."""
        mt5 = cls.connect()
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None and tick.time:
            off = round((tick.time - time.time()) / 1800) * 1800
            if abs(off) <= 14 * 3600:   # tick segar (bukan akhir pekan)
                cls._offset = int(off)
        return cls._offset if cls._offset is not None else 2 * 3600

    @classmethod
    def account(cls) -> dict:
        mt5 = cls.connect()
        a = mt5.account_info()
        if a is None:
            raise RuntimeError(f"Info akun MT5 tidak terbaca: {mt5.last_error()}")
        demo = getattr(a, "trade_mode", None) == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        return {"login": a.login, "server": a.server, "name": a.name, "currency": a.currency,
                "balance": a.balance, "equity": a.equity, "margin_free": a.margin_free,
                "leverage": a.leverage, "demo": bool(demo), "trade_allowed": bool(a.trade_allowed)}


# ===================================================================== data
class ForexData:
    kind = "forex"

    def __init__(self, cfg: dict):
        want = (cfg.get("forex") or {}).get("source", "auto")
        self.source = "mt5" if (want in ("auto", "mt5") and MT5.enabled() and MT5.installed()) else "yahoo"
        if want == "mt5" and self.source != "mt5":
            log.warning("Sumber forex MT5 diminta, tetapi MT5 belum aktif/terpasang. Memakai Yahoo Finance.")
        self._px_cache: dict = {}

    # ---------- utilitas waktu
    def tf_ms(self, tf: str) -> int:
        return TF_SEC[tf] * 1000

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    @staticmethod
    def market_open(t: pd.Timestamp) -> bool:
        """Pasar forex tutup kira-kira Sabtu 04:00 – Senin 04:00 WIB."""
        wd, h = t.weekday(), t.hour
        return not ((wd == 5 and h >= 4) or wd == 6 or (wd == 0 and h < 4))

    def future_ts(self, last_ts, tf: str, n: int) -> pd.Series:
        step = pd.Timedelta(seconds=TF_SEC[tf])
        out, t = [], pd.Timestamp(last_ts)
        while len(out) < n:
            t = t + step
            if tf == "1d" or self.market_open(t):
                if tf == "1d" and t.weekday() >= 5:
                    continue
                out.append(t)
        return pd.Series(out)

    @staticmethod
    def _frame(idx_utc: pd.DatetimeIndex, df: pd.DataFrame, vol) -> pd.DataFrame:
        out = pd.DataFrame({
            "ts": (idx_utc.asi8 // 10**6).astype("int64"),
            "timestamps": idx_utc.tz_convert(TZ).tz_localize(None),
            "open": df["open"].to_numpy(float), "high": df["high"].to_numpy(float),
            "low": df["low"].to_numpy(float), "close": df["close"].to_numpy(float),
            "volume": pd.Series(vol).fillna(0).to_numpy(float),
        })
        out["amount"] = out["close"] * out["volume"]
        out = out.dropna(subset=["open", "high", "low", "close"])
        return out.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)

    # ---------- sumber: Yahoo Finance
    def _yahoo(self, symbol: str, tf: str, n: int) -> pd.DataFrame:
        import yfinance as yf
        interval = {"15m": "15m", "30m": "30m", "1h": "60m", "4h": "60m", "1d": "1d"}[tf]
        base_sec = 3600 if tf == "4h" else TF_SEC[tf]
        need = n * (4 if tf == "4h" else 1) * base_sec / 86400 * 1.5 + 6
        cap = {"15m": 58, "30m": 58, "60m": 725, "1d": 7000}[interval]
        start = pd.Timestamp.utcnow() - pd.Timedelta(days=min(cap, max(6, need)))
        df = yf.Ticker(yahoo_symbol(symbol)).history(start=start.strftime("%Y-%m-%d"), interval=interval,
                                                     auto_adjust=False, actions=False)
        if df is None or df.empty:
            raise RuntimeError(f"Data {label(symbol)} dari Yahoo Finance kosong. Cek koneksi internet.")
        df = df.rename(columns=str.lower)
        idx = df.index
        idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
        df.index = idx
        if tf == "4h":
            df = df.resample("4h", origin="epoch", label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        return self._frame(df.index, df, df.get("volume", pd.Series(0, index=df.index)))

    # ---------- sumber: MT5
    def _mt5(self, symbol: str, tf: str, n: int) -> pd.DataFrame:
        with MT5.lock:
            mt5 = MT5.connect()
            mt5.symbol_select(symbol, True)
            tfc = {"15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30, "1h": mt5.TIMEFRAME_H1,
                   "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1}[tf]
            rates = mt5.copy_rates_from_pos(symbol, tfc, 0, int(n))
            if rates is None or len(rates) == 0:
                raise RuntimeError(f"Data {symbol} dari MT5 kosong ({mt5.last_error()}). "
                                   "Pastikan nama simbol sama persis dengan di Market Watch MT5.")
            off = MT5.offset_sec(symbol)
        df = pd.DataFrame(rates)
        idx = pd.to_datetime((df["time"].astype("int64") - off) * 1000, unit="ms", utc=True)
        return self._frame(pd.DatetimeIndex(idx), df, df.get("tick_volume", 0))

    # ---------- antarmuka umum
    def raw(self, symbol: str, tf: str, n: int) -> pd.DataFrame:
        """n candle terakhir TERMASUK candle yang masih berjalan."""
        df = self._mt5(symbol, tf, n) if self.source == "mt5" else self._yahoo(symbol, tf, n)
        return df.tail(n).reset_index(drop=True)

    def _closed(self, df: pd.DataFrame, tf: str) -> pd.DataFrame:
        if len(df) and df["ts"].iloc[-1] + self.tf_ms(tf) > self.now_ms():
            df = df.iloc[:-1]
        return df

    def recent(self, symbol: str, tf: str, n: int) -> pd.DataFrame:
        return self._closed(self.raw(symbol, tf, n + 1), tf).tail(n).reset_index(drop=True)

    def history(self, symbol: str, tf: str, n: int) -> pd.DataFrame:
        return self.recent(symbol, tf, n)

    def price(self, symbol: str) -> float:
        hit = self._px_cache.get(symbol)
        if hit and time.time() - hit[0] < 10:
            return hit[1]
        if self.source == "mt5":
            with MT5.lock:
                mt5 = MT5.connect()
                mt5.symbol_select(symbol, True)
                t = mt5.symbol_info_tick(symbol)
                if t is None or not t.bid:
                    raise RuntimeError(f"Harga {symbol} dari MT5 tidak tersedia.")
                px = (t.bid + t.ask) / 2
        else:
            import yfinance as yf
            df = yf.Ticker(yahoo_symbol(symbol)).history(period="5d", interval="1m", auto_adjust=False, actions=False)
            if df is None or df.empty:
                raise RuntimeError(f"Harga {label(symbol)} dari Yahoo Finance tidak tersedia.")
            px = float(df["Close"].dropna().iloc[-1])
        self._px_cache[symbol] = (time.time(), float(px))
        return float(px)

    def pairs(self) -> list[str]:
        if self.source == "mt5":
            try:
                with MT5.lock:
                    syms = MT5.connect().symbols_get() or []
                vis = [s.name for s in syms if getattr(s, "visible", False)]
                fx = [s for s in vis if len(clean(s)) == 6]
                if fx:
                    return sorted(fx)
            except Exception as e:  # noqa: BLE001
                log.warning("Daftar simbol MT5 gagal: %s", e)
        return list(DEFAULT_PAIRS)

    def quote_to_usd(self, symbol: str, price: float) -> float:
        """Nilai 1 unit mata uang 'quote' dalam USD (untuk menghitung untung/rugi & ukuran posisi)."""
        b, q = base_quote(symbol)
        if q == "USD":
            return 1.0
        if b == "USD":
            return 1.0 / price if price else 1.0
        for direct, inv in ((f"{q}USD", False), (f"USD{q}", True)):
            try:
                px = self.price(direct)
                return 1.0 / px if inv else px
            except Exception:  # noqa: BLE001
                continue
        return 1.0


def round_down(x: float, step: float) -> float:
    return math.floor(x / step + 1e-9) * step if step > 0 else x
