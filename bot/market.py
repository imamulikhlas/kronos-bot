"""Koneksi ke bursa dan pengambilan data candle (OHLCV)."""
import time

import ccxt
import pandas as pd

from .config import api_keys

TZ = "Asia/Jakarta"
MAX_LIMIT = 1000  # batas candle per request di Tokocrypto/Binance spot


def make_exchange(cfg: dict, private: bool = False):
    params = {"enableRateLimit": True, "timeout": 30000}
    if private:
        key, secret = api_keys()
        if not key or not secret:
            raise SystemExit("API key belum diisi. Isi TOKOCRYPTO_API_KEY dan TOKOCRYPTO_API_SECRET di file .env")
        params.update(apiKey=key, secret=secret)
    name = cfg.get("exchange", "tokocrypto")
    if not hasattr(ccxt, name):
        raise SystemExit(f"Exchange '{name}' tidak dikenal oleh CCXT.")
    return getattr(ccxt, name)(params)


def tf_ms(ex, tf: str) -> int:
    return int(ex.parse_timeframe(tf) * 1000)


def to_frame(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["timestamps"] = (pd.to_datetime(df["ts"], unit="ms", utc=True)
                        .dt.tz_convert(TZ).dt.tz_localize(None))
    df["amount"] = df["close"] * df["volume"]
    return df[["ts", "timestamps", "open", "high", "low", "close", "volume", "amount"]]


def _drop_unfinished(ex, df: pd.DataFrame, tf: str) -> pd.DataFrame:
    if len(df) and df["ts"].iloc[-1] + tf_ms(ex, tf) > ex.milliseconds():
        df = df.iloc[:-1]
    return df


def retry(fn, *args, tries: int = 4, **kwargs):
    for i in range(tries):
        try:
            return fn(*args, **kwargs)
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout):
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def fetch_recent(ex, symbol: str, tf: str, n: int) -> pd.DataFrame:
    """n candle terakhir yang SUDAH selesai."""
    raw = retry(ex.fetch_ohlcv, symbol, tf, limit=min(n + 1, MAX_LIMIT))
    if not raw:
        raise RuntimeError(f"Tidak ada data candle untuk {symbol}")
    df = _drop_unfinished(ex, to_frame(raw), tf)
    return df.tail(n).reset_index(drop=True)


def fetch_history(ex, symbol: str, tf: str, n: int) -> pd.DataFrame:
    """Ambil n candle terakhir (bisa lebih dari 1000) dengan beberapa request."""
    step = tf_ms(ex, tf)
    since = ex.milliseconds() - step * (n + 2)
    rows: list = []
    while True:
        raw = retry(ex.fetch_ohlcv, symbol, tf, since=since, limit=MAX_LIMIT)
        if not raw:
            break
        rows += raw
        since = raw[-1][0] + step
        if since >= ex.milliseconds():
            break
    if not rows:
        raise RuntimeError(f"Tidak ada data historis untuk {symbol}")
    df = _drop_unfinished(ex, to_frame(rows), tf)
    return df.tail(n).reset_index(drop=True)


def future_timestamps(last_ts: pd.Timestamp, step_ms: int, n: int) -> pd.Series:
    step = pd.Timedelta(milliseconds=step_ms)
    return pd.Series([last_ts + step * (i + 1) for i in range(n)])
