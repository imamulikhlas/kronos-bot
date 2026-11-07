"""Indikator teknikal sederhana untuk melengkapi ramalan Kronos."""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def snapshot(df: pd.DataFrame, trend_period: int = 200) -> dict:
    """Ringkasan kondisi pasar pada candle terakhir."""
    c = df["close"]
    tp = min(trend_period, max(20, len(df) // 2))
    e_slow = ema(c, tp)
    e_fast = ema(c, max(5, tp // 4))
    last = float(c.iloc[-1])
    slope_up = bool(e_slow.iloc[-1] > e_slow.iloc[-min(6, len(df))])
    slope_down = bool(e_slow.iloc[-1] < e_slow.iloc[-min(6, len(df))])
    return {
        "trend_down": bool(last < e_slow.iloc[-1] and slope_down),
        "ema_fast": float(e_fast.iloc[-1]),
        "ema_slow": float(e_slow.iloc[-1]),
        "trend_up": bool(last > e_slow.iloc[-1] and slope_up),
        "rsi": float(rsi(c).iloc[-1]),
        "atr_pct": float(atr(df).iloc[-1] / last * 100),
    }
