"""Eksekusi order.

PaperBroker   : simulasi dengan harga asli (kripto & forex), saldo virtual bersama.
TokoBroker    : order sungguhan ke Tokocrypto (kripto spot, hanya beli lalu jual).
MT5Broker     : order sungguhan ke MetaTrader 5 (forex, buy & sell). SL/TP juga dipasang di server broker.

Semua broker punya antarmuka sama:
  cash()                         saldo yang bisa dipakai
  price(symbol)                  harga sekarang
  plan(symbol, side, price, sl, equity) -> dict(units, lots, cost)   (raise SizingError jika tidak bisa)
  open(symbol, side, plan, sl, tp) -> Fill
  close(pos) -> Fill (dengan pnl)
  value(pos, price)              kontribusi posisi terhadap total aset
  modify(pos, sl, tp)            perbarui SL/TP di broker (MT5)
  sync(pos) -> Fill | None       cek apakah posisi sudah ditutup oleh broker (MT5)
"""
import logging
import time
from dataclasses import dataclass

from .forex import MT5, contract_size, round_down
from .market import retry
from .strategy import sgn

log = logging.getLogger("broker")


class SizingError(Exception):
    """Posisi tidak bisa dibuka karena modal/margin/aturan ukuran."""


@dataclass
class Fill:
    amount: float          # jumlah unit (koin / unit mata uang)
    price: float           # harga rata-rata
    cost: float = 0.0      # modal (kripto) atau margin (forex) dalam USD/USDT
    proceeds: float = 0.0
    fee: float = 0.0
    order_id: str = ""
    lots: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None


def _oid():
    return f"sim-{int(time.time() * 1000)}"


# ===================================================================== simulasi
class PaperBroker:
    live = False

    def __init__(self, store, cfg, venue, data):
        self.store, self.cfg, self.venue, self.data = store, cfg, venue, data
        from .strategy import strat
        self.s = strat(cfg, venue)
        self.slip = cfg["paper"]["slippage_pct"] / 100
        self.fx = cfg.get("forex") or {}
        self._cash_key = f"paper_cash:{venue}"
        if store.get_kv(self._cash_key) is None:
            store.set_kv(self._cash_key, float(cfg["paper"]["starting_balance"]))

    def cash(self) -> float:
        return float(self.store.get_kv(self._cash_key, 0.0))

    def _add_cash(self, v):
        self.store.set_kv(self._cash_key, self.cash() + v)

    def price(self, symbol) -> float:
        return self.data.price(symbol)

    # ---------- ukuran posisi
    def plan(self, symbol, side, price, sl, equity) -> dict:
        r = self.cfg["risk"]
        if self.venue == "crypto":
            if side != "long":
                raise SizingError("kripto spot hanya bisa beli (long)")
            cost = min(float(r["order_size_quote"]), float(r["max_order_size_quote"]))
            if self.cash() < cost:
                raise SizingError(f"saldo {self.cash():.2f} kurang dari modal per posisi {cost:.2f}")
            return {"cost": cost, "units": None, "lots": None}
        return forex_plan(symbol, price, sl, equity, self.fx, self.data, self._used_margin())

    def _used_margin(self):
        return sum(p["cost"] or 0 for p in self.store.open_positions() if (p.get("venue") or "crypto") == "forex")

    # ---------- buka / tutup
    def open(self, symbol, side, plan, sl=None, tp=None, price=None) -> Fill:
        px = price or self.price(symbol)
        if self.venue == "crypto":
            p = px * (1 + self.slip)
            cost = plan["cost"]
            fee = cost * self.s["fee_pct"] / 100
            self._add_cash(-cost)
            return Fill(amount=(cost - fee) / p, price=p, cost=cost, fee=fee, order_id=_oid())
        half = self.s["fee_pct"] / 200   # biaya forex = spread, separuh saat buka, separuh saat tutup
        p = px * (1 + sgn(side) * half)
        return Fill(amount=plan["units"], price=p, cost=plan["cost"], lots=plan["lots"], order_id=_oid())

    def close(self, pos, price=None) -> Fill:
        px = price or self.price(pos["symbol"])
        side = pos.get("side") or "long"
        if self.venue == "crypto":
            p = px * (1 - self.slip)
            gross = pos["amount"] * p
            fee = gross * self.s["fee_pct"] / 100
            proceeds = gross - fee
            self._add_cash(proceeds)
            pnl = proceeds - pos["cost"]
            return Fill(amount=pos["amount"], price=p, proceeds=proceeds, fee=fee, order_id=_oid(),
                        pnl=pnl, pnl_pct=pnl / pos["cost"] * 100 if pos["cost"] else 0)
        half = self.s["fee_pct"] / 200
        p = px * (1 - sgn(side) * half)
        pnl = pos["amount"] * (p - pos["entry_price"]) * sgn(side) * self.data.quote_to_usd(pos["symbol"], p)
        self._add_cash(pnl)
        return Fill(amount=pos["amount"], price=p, proceeds=pos["cost"] + pnl, order_id=_oid(), pnl=pnl,
                    pnl_pct=(p / pos["entry_price"] - 1) * 100 * sgn(side))

    def value(self, pos, price) -> float:
        if self.venue == "crypto":
            return pos["amount"] * price
        side = pos.get("side") or "long"
        return pos["amount"] * (price - pos["entry_price"]) * sgn(side) * self.data.quote_to_usd(pos["symbol"], price)

    def modify(self, pos, sl, tp):
        return None

    def sync(self, pos):
        return None


def forex_plan(symbol, price, sl, equity, fx, data, used_margin) -> dict:
    """Ukuran posisi forex simulasi: risiko tetap (% aset) per transaksi, dibulatkan ke 0,01 lot."""
    risk = equity * float(fx.get("risk_pct", 1.0)) / 100
    dist = abs(price - sl)
    if dist <= 0:
        raise SizingError("jarak stop-loss nol")
    q2u = data.quote_to_usd(symbol, price)
    units = risk / (dist * q2u)
    lot = contract_size(symbol)
    units = round_down(min(units, float(fx.get("max_lots", 1.0)) * lot), 0.01 * lot)
    if units <= 0:
        need = 0.01 * lot * dist * q2u
        raise SizingError(f"modal terlalu kecil: 0,01 lot butuh risiko {need:.2f} USD per transaksi")
    margin = units * price * q2u / max(1.0, float(fx.get("leverage", 100)))
    if used_margin + margin > equity * 0.8:
        raise SizingError(f"margin tidak cukup (butuh {margin:.2f} USD)")
    return {"units": units, "lots": units / lot, "cost": margin}


# ===================================================================== Tokocrypto live
class TokoBroker:
    live = True

    def __init__(self, store, cfg, data, ex):
        self.store, self.cfg, self.data, self.ex = store, cfg, data, ex
        from .strategy import strat
        self.s = strat(cfg, "crypto")
        self.quote = cfg.get("quote", "USDT")
        retry(self.ex.load_markets)

    def price(self, symbol) -> float:
        return float(retry(self.ex.fetch_ticker, symbol)["last"])

    def balance(self, currency) -> float:
        bal = retry(self.ex.fetch_balance)
        return float((bal.get("free") or {}).get(currency) or 0.0)

    def cash(self) -> float:
        return self.balance(self.quote)

    def plan(self, symbol, side, price, sl, equity) -> dict:
        if side != "long":
            raise SizingError("kripto spot hanya bisa beli (long)")
        r = self.cfg["risk"]
        cost = min(float(r["order_size_quote"]), float(r["max_order_size_quote"]))
        m = self.ex.market(symbol)
        min_cost = float(((m.get("limits") or {}).get("cost") or {}).get("min") or 0.0)
        if cost < min_cost:
            raise SizingError(f"modal {cost} di bawah minimal order bursa {min_cost}")
        if self.cash() < cost:
            raise SizingError(f"saldo {self.quote} kurang dari {cost}")
        return {"cost": cost, "units": None, "lots": None}

    def _wait(self, order, symbol):
        for _ in range(10):
            if order.get("status") == "closed" and order.get("filled"):
                return order
            time.sleep(1.5)
            try:
                order = self.ex.fetch_order(order.get("id"), symbol)
            except Exception as e:  # noqa: BLE001
                log.warning("Gagal cek status order: %s", e)
        return order

    def _fee_quote(self, order, symbol, price, fallback):
        base = self.ex.market(symbol)["base"]
        fees = order.get("fees") or ([order["fee"]] if order.get("fee") else [])
        q, b = 0.0, 0.0
        for f in fees:
            if f and f.get("cost") is not None:
                if f.get("currency") == self.quote:
                    q += float(f["cost"])
                elif f.get("currency") == base:
                    b += float(f["cost"])
        return (fallback, 0.0) if not fees else (q + b * price, b)

    def open(self, symbol, side, plan, sl=None, tp=None, price=None) -> Fill:
        try:
            cost = float(self.ex.cost_to_precision(symbol, plan["cost"]))
        except Exception:  # noqa: BLE001
            cost = round(plan["cost"], 2)
        order = self._wait(self.ex.create_market_buy_order_with_cost(symbol, cost), symbol)
        filled = float(order.get("filled") or 0)
        if filled <= 0:
            raise RuntimeError(f"Order beli {order.get('id')} belum terisi (status {order.get('status')})")
        spent = float(order.get("cost") or cost)
        avg = float(order.get("average") or spent / filled)
        fee_q, fee_b = self._fee_quote(order, symbol, avg, spent * self.s["fee_pct"] / 100)
        return Fill(amount=filled - fee_b, price=avg, cost=spent + (fee_q - fee_b * avg), fee=fee_q,
                    order_id=str(order.get("id")))

    def close(self, pos, price=None) -> Fill:
        symbol = pos["symbol"]
        base = self.ex.market(symbol)["base"]
        amt = float(self.ex.amount_to_precision(symbol, min(pos["amount"], self.balance(base))))
        if amt <= 0:
            raise RuntimeError(f"Saldo {base} tidak cukup untuk dijual")
        order = self._wait(self.ex.create_market_sell_order(symbol, amt), symbol)
        filled = float(order.get("filled") or amt)
        avg = float(order.get("average") or self.price(symbol))
        gross = float(order.get("cost") or filled * avg)
        fee_q, _ = self._fee_quote(order, symbol, avg, gross * self.s["fee_pct"] / 100)
        proceeds = gross - fee_q
        pnl = proceeds - pos["cost"]
        return Fill(amount=filled, price=avg, proceeds=proceeds, fee=fee_q, order_id=str(order.get("id")),
                    pnl=pnl, pnl_pct=pnl / pos["cost"] * 100 if pos["cost"] else 0)

    def value(self, pos, price) -> float:
        return pos["amount"] * price

    def modify(self, pos, sl, tp):
        return None

    def sync(self, pos):
        return None


# ===================================================================== MetaTrader 5 live
MAGIC = 260611


class MT5Broker:
    live = True

    def __init__(self, store, cfg, data):
        self.store, self.cfg, self.data = store, cfg, data
        self.fx = cfg.get("forex") or {}
        self.mt5 = MT5.connect()

    def _sym(self, symbol):
        mt5 = self.mt5
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Simbol {symbol} tidak ada di MT5. Tambahkan ke Market Watch.")
        return info

    def _filling(self, info):
        mt5 = self.mt5
        fm = int(getattr(info, "filling_mode", 0) or 0)
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def cash(self) -> float:
        return float(MT5.account()["margin_free"])

    def equity(self) -> float:
        return float(MT5.account()["equity"])

    def price(self, symbol) -> float:
        with MT5.lock:
            self._sym(symbol)
            t = self.mt5.symbol_info_tick(symbol)
        if t is None or not t.bid:
            raise RuntimeError(f"Harga {symbol} tidak tersedia di MT5 (pasar mungkin tutup).")
        return (t.bid + t.ask) / 2

    def plan(self, symbol, side, price, sl, equity) -> dict:
        mt5 = self.mt5
        with MT5.lock:
            info = self._sym(symbol)
            acc = MT5.account()
            if not acc["trade_allowed"]:
                raise SizingError("akun MT5 belum mengizinkan trading otomatis (aktifkan Algo Trading)")
            otype = mt5.ORDER_TYPE_BUY if side == "long" else mt5.ORDER_TYPE_SELL
            risk = acc["equity"] * float(self.fx.get("risk_pct", 1.0)) / 100
            loss1 = mt5.order_calc_profit(otype, symbol, 1.0, price, sl)
            if loss1 is None or loss1 >= 0:
                loss1 = -abs(price - sl) * info.trade_contract_size * self.data.quote_to_usd(symbol, price)
            step = info.volume_step or 0.01
            lots = round_down(min(risk / abs(loss1), float(self.fx.get("max_lots", 1.0)), info.volume_max), step)
            if lots < info.volume_min:
                raise SizingError(f"modal terlalu kecil: {info.volume_min} lot berisiko "
                                  f"{abs(loss1) * info.volume_min:.2f} {acc['currency']}")
            lots = round(lots, 8)
            margin = mt5.order_calc_margin(otype, symbol, lots, price) or 0.0
            if margin > acc["margin_free"] * 0.9:
                raise SizingError(f"margin tidak cukup (butuh {margin:.2f} {acc['currency']})")
        return {"units": lots * info.trade_contract_size, "lots": lots, "cost": float(margin)}

    def _send(self, req):
        res = self.mt5.order_send(req)
        if res is None:
            raise RuntimeError(f"Order MT5 gagal: {self.mt5.last_error()}")
        if res.retcode != self.mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"Order ditolak MT5: {res.comment} (kode {res.retcode})")
        return res

    def open(self, symbol, side, plan, sl=None, tp=None, price=None) -> Fill:
        mt5 = self.mt5
        with MT5.lock:
            info = self._sym(symbol)
            tick = mt5.symbol_info_tick(symbol)
            long = side == "long"
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(plan["lots"]),
                   "type": mt5.ORDER_TYPE_BUY if long else mt5.ORDER_TYPE_SELL,
                   "price": tick.ask if long else tick.bid, "deviation": 20, "magic": MAGIC,
                   "comment": "kronos", "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(info)}
            if sl:
                req["sl"] = round(float(sl), info.digits)
            if tp:
                req["tp"] = round(float(tp), info.digits)
            res = self._send(req)
            ticket = res.order
            try:
                deals = mt5.history_deals_get(ticket=res.deal)
                if deals:
                    ticket = deals[0].position_id
            except Exception:  # noqa: BLE001
                pass
        return Fill(amount=plan["units"], price=float(res.price or req["price"]), cost=plan["cost"],
                    lots=plan["lots"], order_id=str(ticket))

    def _position(self, pos):
        ps = self.mt5.positions_get(ticket=int(pos["order_id_buy"]))
        return ps[0] if ps else None

    def _closed_fill(self, pos, fallback_price=None) -> Fill:
        mt5 = self.mt5
        deals = mt5.history_deals_get(position=int(pos["order_id_buy"])) or []
        pnl = sum(float(d.profit) + float(d.commission) + float(d.swap) + float(getattr(d, "fee", 0) or 0)
                  for d in deals)
        outs = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, getattr(mt5, "DEAL_ENTRY_OUT_BY", -1))]
        px = float(outs[-1].price) if outs else float(fallback_price or pos["entry_price"])
        side = pos.get("side") or "long"
        return Fill(amount=pos["amount"], price=px, proceeds=(pos["cost"] or 0) + pnl, pnl=pnl,
                    pnl_pct=(px / pos["entry_price"] - 1) * 100 * sgn(side), order_id=str(pos["order_id_buy"]))

    def close(self, pos, price=None) -> Fill:
        mt5 = self.mt5
        with MT5.lock:
            p = self._position(pos)
            if p is None:
                return self._closed_fill(pos)
            info = self._sym(pos["symbol"])
            tick = mt5.symbol_info_tick(pos["symbol"])
            is_buy = p.type == mt5.POSITION_TYPE_BUY
            res = self._send({"action": mt5.TRADE_ACTION_DEAL, "symbol": pos["symbol"], "volume": p.volume,
                              "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                              "position": p.ticket, "price": tick.bid if is_buy else tick.ask,
                              "deviation": 20, "magic": MAGIC, "comment": "kronos tutup",
                              "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(info)})
        time.sleep(0.6)
        with MT5.lock:
            return self._closed_fill(pos, res.price)

    def value(self, pos, price) -> float:
        with MT5.lock:
            p = self._position(pos)
        return float(p.profit) if p is not None else 0.0

    def modify(self, pos, sl, tp):
        mt5 = self.mt5
        with MT5.lock:
            p = self._position(pos)
            if p is None:
                return
            info = self._sym(pos["symbol"])
            res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": pos["symbol"], "position": p.ticket,
                                  "sl": round(float(sl), info.digits), "tp": round(float(tp), info.digits)})
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                log.warning("Gagal memperbarui SL/TP %s: %s", pos["symbol"], getattr(res, "comment", mt5.last_error()))

    def sync(self, pos):
        with MT5.lock:
            if self._position(pos) is None:
                return self._closed_fill(pos)
        return None

