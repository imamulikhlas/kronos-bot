"""Pasar yang didukung robot dan penghubung ke data & broker masing-masing.

  kripto : simbol berbentuk 'BTC/USDT'  -> Tokocrypto (CCXT)
  forex  : simbol berbentuk 'EURUSD'    -> MetaTrader 5 atau Yahoo Finance
"""
import time

import pandas as pd

from .forex import ForexData
from .market import fetch_history, fetch_recent, future_timestamps, make_exchange, retry, tf_ms, to_frame
from .strategy import strat, venue_of

VENUE_LABEL = {"crypto": "Kripto", "forex": "Forex"}


class CryptoData:
    kind = "crypto"
    source = "tokocrypto"

    def __init__(self, cfg: dict, ex=None):
        self.cfg = cfg
        self.ex = ex or make_exchange(cfg)

    def tf_ms(self, tf):
        return tf_ms(self.ex, tf)

    def now_ms(self):
        return int(self.ex.milliseconds())

    def raw(self, symbol, tf, n):
        return to_frame(retry(self.ex.fetch_ohlcv, symbol, tf, limit=min(int(n), 1000)))

    def recent(self, symbol, tf, n):
        return fetch_recent(self.ex, symbol, tf, n)

    def history(self, symbol, tf, n):
        return fetch_history(self.ex, symbol, tf, n)

    def price(self, symbol):
        return float(retry(self.ex.fetch_ticker, symbol)["last"])

    def future_ts(self, last_ts, tf, n):
        return future_timestamps(last_ts, self.tf_ms(tf), n)

    def pairs(self):
        quote = self.cfg.get("quote", "USDT")
        mk = retry(self.ex.load_markets)
        return sorted(s for s, m in mk.items() if s.endswith("/" + quote) and m.get("active", True))


class Markets:
    """Menyimpan penghubung data & broker per pasar (dibuat saat pertama dibutuhkan)."""

    def __init__(self, cfg: dict, store=None, live: bool = False):
        self.cfg, self.store, self.live = cfg, store, live
        self._data, self._brokers = {}, {}

    @staticmethod
    def venue(symbol):
        return venue_of(symbol)

    def venues(self):
        return sorted({venue_of(s) for s in self.cfg["symbols"]})

    def strat(self, venue):
        return strat(self.cfg, venue)

    def data(self, venue):
        if venue not in self._data:
            self._data[venue] = CryptoData(self.cfg) if venue == "crypto" else ForexData(self.cfg)
        return self._data[venue]

    def broker(self, venue):
        if venue not in self._brokers:
            from .broker import MT5Broker, PaperBroker, TokoBroker
            data = self.data(venue)
            if not self.live:
                b = PaperBroker(self.store, self.cfg, venue, data)
            elif venue == "crypto":
                b = TokoBroker(self.store, self.cfg, data, make_exchange(self.cfg, private=True))
            else:
                if data.source != "mt5":
                    raise RuntimeError("Trading forex sungguhan butuh MetaTrader 5. Hubungkan MT5 di halaman Akun.")
                b = MT5Broker(self.store, self.cfg, data)
            self._brokers[venue] = b
        return self._brokers[venue]

    def for_symbol(self, symbol):
        v = venue_of(symbol)
        return v, self.data(v), self.broker(v)


def wib_now():
    return pd.Timestamp(time.time(), unit="s", tz="Asia/Jakarta").tz_localize(None)
