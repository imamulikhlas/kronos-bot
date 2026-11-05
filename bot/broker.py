"""Eksekusi order.
PaperBroker = simulasi dengan harga asli.  LiveBroker = order sungguhan ke Tokocrypto."""
import logging
import time
from dataclasses import dataclass

from .market import retry

log = logging.getLogger("broker")


@dataclass
class Fill:
    amount: float       # jumlah koin
    price: float        # harga rata-rata
    cost: float = 0.0   # USDT yang keluar (beli)
    proceeds: float = 0.0  # USDT yang masuk bersih (jual)
    fee: float = 0.0    # biaya dalam USDT (perkiraan)
    order_id: str = ""


class PaperBroker:
    live = False

    def __init__(self, ex, store, cfg):
        self.ex, self.store, self.cfg = ex, store, cfg
        self.fee = cfg["strategy"]["fee_pct"] / 100
        self.slip = cfg["paper"]["slippage_pct"] / 100
        if store.get_kv("paper_cash") is None:
            store.set_kv("paper_cash", float(cfg["paper"]["starting_balance"]))

    def price(self, symbol) -> float:
        return float(retry(self.ex.fetch_ticker, symbol)["last"])

    def cash(self) -> float:
        return float(self.store.get_kv("paper_cash", 0.0))

    def min_cost(self, symbol) -> float:
        return 0.0

    def buy(self, symbol, cost, price=None) -> Fill:
        if cost > self.cash() + 1e-9:
            raise RuntimeError(f"Saldo simulasi kurang ({self.cash():.2f})")
        p = (price or self.price(symbol)) * (1 + self.slip)
        fee = cost * self.fee
        amount = (cost - fee) / p
        self.store.set_kv("paper_cash", self.cash() - cost)
        return Fill(amount=amount, price=p, cost=cost, fee=fee, order_id=f"paper-{int(time.time()*1000)}")

    def sell(self, symbol, amount, price=None) -> Fill:
        p = (price or self.price(symbol)) * (1 - self.slip)
        gross = amount * p
        fee = gross * self.fee
        proceeds = gross - fee
        self.store.set_kv("paper_cash", self.cash() + proceeds)
        return Fill(amount=amount, price=p, proceeds=proceeds, fee=fee, order_id=f"paper-{int(time.time()*1000)}")


class LiveBroker:
    live = True

    def __init__(self, ex, store, cfg):
        self.ex, self.store, self.cfg = ex, store, cfg
        self.quote = cfg.get("quote", "USDT")
        self.fee = cfg["strategy"]["fee_pct"] / 100
        retry(self.ex.load_markets)

    def price(self, symbol) -> float:
        return float(retry(self.ex.fetch_ticker, symbol)["last"])

    def balance(self, currency) -> float:
        bal = retry(self.ex.fetch_balance)
        return float((bal.get("free") or {}).get(currency) or 0.0)

    def cash(self) -> float:
        return self.balance(self.quote)

    def min_cost(self, symbol) -> float:
        m = self.ex.market(symbol)
        return float(((m.get("limits") or {}).get("cost") or {}).get("min") or 0.0)

    def _wait_filled(self, order, symbol):
        oid = order.get("id")
        for _ in range(10):
            if order.get("status") == "closed" and order.get("filled"):
                return order
            time.sleep(1.5)
            try:
                order = self.ex.fetch_order(oid, symbol)
            except Exception as e:  # noqa: BLE001
                log.warning("Gagal cek status order %s: %s", oid, e)
        return order

    def _fee_quote(self, order, symbol, price, fallback):
        base = self.ex.market(symbol)["base"]
        fees = order.get("fees") or ([order["fee"]] if order.get("fee") else [])
        total_q, total_b = 0.0, 0.0
        for f in fees:
            if not f or f.get("cost") is None:
                continue
            if f.get("currency") == self.quote:
                total_q += float(f["cost"])
            elif f.get("currency") == base:
                total_b += float(f["cost"])
        if not fees:
            return fallback, 0.0
        return total_q + total_b * price, total_b

    def buy(self, symbol, cost, price=None) -> Fill:
        try:
            cost = float(self.ex.cost_to_precision(symbol, cost))
        except Exception:  # noqa: BLE001
            cost = round(cost, 2)
        order = self.ex.create_market_buy_order_with_cost(symbol, cost)
        order = self._wait_filled(order, symbol)
        filled = float(order.get("filled") or 0)
        if filled <= 0:
            raise RuntimeError(f"Order beli {order.get('id')} belum terisi: status={order.get('status')}")
        avg = float(order.get("average") or (order.get("cost") or cost) / filled)
        spent = float(order.get("cost") or cost)
        fee_q, fee_base = self._fee_quote(order, symbol, avg, spent * self.fee)
        return Fill(amount=filled - fee_base, price=avg, cost=spent + (fee_q - fee_base * avg),
                    fee=fee_q, order_id=str(order.get("id")))

    def sell(self, symbol, amount, price=None) -> Fill:
        base = self.ex.market(symbol)["base"]
        free = self.balance(base)
        amt = float(self.ex.amount_to_precision(symbol, min(amount, free)))
        if amt <= 0:
            raise RuntimeError(f"Saldo {base} tidak cukup untuk dijual (free={free})")
        order = self.ex.create_market_sell_order(symbol, amt)
        order = self._wait_filled(order, symbol)
        filled = float(order.get("filled") or amt)
        avg = float(order.get("average") or self.price(symbol))
        gross = float(order.get("cost") or filled * avg)
        fee_q, _ = self._fee_quote(order, symbol, avg, gross * self.fee)
        return Fill(amount=filled, price=avg, proceeds=gross - fee_q, fee=fee_q, order_id=str(order.get("id")))


def make_broker(ex, store, cfg):
    return LiveBroker(ex, store, cfg) if cfg["mode"] == "live" else PaperBroker(ex, store, cfg)
