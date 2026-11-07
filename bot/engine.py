"""Otak robot: tiap candle tutup -> nilai ramalan lama -> ramal -> putuskan -> eksekusi.
Di antara candle: jaga stop-loss, take-profit, trailing stop, dan cek posisi yang ditutup broker."""
import logging

from .broker import SizingError
from .config import ROOT
from .forecast import build_signal
from .strategy import entry_side, exit_levels, price_exit, sgn, side_score, signal_exit, trail, venue_of

log = logging.getLogger("engine")
STOP_FILE = ROOT / "STOP"
SIDE_WORD = {"long": "Buy", "short": "Sell"}


class Engine:
    def __init__(self, cfg, store, forecaster, markets):
        self.cfg, self.store, self.fc, self.mk = cfg, store, forecaster, markets
        self.r, self.m = cfg["risk"], cfg["model"]
        self.tf = cfg["timeframe"]

    # ------------------------------------------------------------------ util
    def tfms(self, venue):
        return self.mk.data(venue).tf_ms(self.tf)

    def now_ms(self):
        v = self.mk.venues()
        return self.mk.data(v[0] if v else "crypto").now_ms()

    # ------------------------------------------------------------------ ramalan
    def forecast_symbol(self, sym):
        venue = venue_of(sym)
        data, s = self.mk.data(venue), self.mk.strat(venue)
        hist = data.recent(sym, self.tf, int(self.m["lookback"]))
        if len(hist) < 100:
            raise RuntimeError(f"data hanya {len(hist)} candle")
        self.store.evaluate_signals(sym, self.tf, hist)
        y_ts = data.future_ts(hist["timestamps"].iloc[-1], self.tf, int(self.m["pred_len"]))
        sig = build_signal(sym, hist, self.fc.paths(hist, y_ts), s["fee_pct"], int(s["trend_period"]))
        acc = self.store.accuracy(sym, self.tf, sig.horizon)
        sig.accuracy, sig.acc_n = acc["hit"], acc["n"]
        return sig, int(hist["ts"].iloc[-1])

    def candle_cycle(self):
        sigs = {}
        for sym in self.cfg["symbols"]:
            try:
                sigs[sym] = self.forecast_symbol(sym)
            except Exception as e:  # noqa: BLE001
                log.exception("Gagal meramal %s", sym)
                self.store.event("ERROR", f"Gagal meramal {sym}: {e}")
        decisions = {}
        # 1) urus posisi yang sudah ada dulu
        for sym, (sig, ts) in sigs.items():
            if self.store.open_positions(sym):
                try:
                    decisions[sym] = self._manage(sym, sig, ts)
                except Exception as e:  # noqa: BLE001
                    log.exception("Gagal mengelola posisi %s", sym)
                    decisions[sym] = ("ERROR", str(e))
        # 2) buka posisi baru: sinyal terkuat didahulukan
        cands = sorted((x for x in sigs if x not in decisions),
                       key=lambda x: side_score(sigs[x][0], self.mk.strat(venue_of(x))), reverse=True)
        for sym in cands:
            sig, ts = sigs[sym]
            try:
                decisions[sym] = self._maybe_open(sym, sig, ts)
            except Exception as e:  # noqa: BLE001
                log.exception("Gagal membuka posisi %s", sym)
                self.store.event("ERROR", f"Gagal membuka posisi {sym}: {e}")
                decisions[sym] = ("ERROR", str(e))
        for sym, (sig, _) in sigs.items():
            action, reason = decisions.get(sym, ("-", ""))
            self.store.add_signal(sig, action, reason, venue_of(sym), self.tf)
            log.info("%s  ->  %s (%s)", sig.summary(), action, reason)
        self.record_equity()

    # ------------------------------------------------------------------ posisi
    def _stops(self, pos):
        sl, tp = pos.get("sl"), pos.get("tp")
        side = pos.get("side") or "long"
        if sl is None or tp is None:
            sl, tp = exit_levels(pos["entry_price"], side, None, self.mk.strat(venue_of(pos["symbol"])))
        return sl, tp, pos.get("peak") or pos["entry_price"]

    def _manage(self, sym, sig, candle_ts):
        pos = self.store.open_positions(sym)[0]
        side = pos.get("side") or "long"
        venue = venue_of(sym)
        held = int((candle_ts - pos["entry_candle_ts"]) // self.tfms(venue))
        why = self._check_price(pos, sig.last_close)
        if why:
            return "TUTUP", why
        hit, why = signal_exit(held, sig, side, self.mk.strat(venue))
        if hit:
            self.close(pos, why, candle_ts)
            return "TUTUP", why
        chg = (sig.last_close / pos["entry_price"] - 1) * 100 * sgn(side)
        return "TAHAN", f"posisi {'buy' if side == 'long' else 'sell'} {held} candle, {chg:+.2f}%"

    def _maybe_open(self, sym, sig, candle_ts):
        s = self.mk.strat(venue_of(sym))
        ok, why = self.can_open(sym, candle_ts)
        if not ok:
            return "LEWATI", why
        side, why = entry_side(sig, s)
        if side is None:
            return "TUNGGU", why
        try:
            self.open(sym, side, why, candle_ts, sig)
        except SizingError as e:
            return "LEWATI", str(e)
        return ("BELI" if side == "long" else "JUAL"), why

    def _check_price(self, pos, price) -> str:
        """Perbarui trailing stop lalu cek SL/TP. Mengembalikan alasan tutup, atau "" jika tetap ditahan."""
        side = pos.get("side") or "long"
        venue = venue_of(pos["symbol"])
        sl, tp, best = self._stops(pos)
        best = min(best, price) if side == "short" else max(best, price)
        new_sl = trail(pos["entry_price"], best, sl, side, self.mk.strat(venue))
        if (new_sl, tp, best) != (pos.get("sl"), pos.get("tp"), pos.get("peak")):
            self.store.update_stops(pos["id"], new_sl, tp, best)
            if new_sl != sl:
                try:
                    self.mk.broker(venue).modify(pos, new_sl, tp)
                except Exception as e:  # noqa: BLE001
                    log.warning("Gagal menggeser stop di broker: %s", e)
        px, why = price_exit(pos["entry_price"], new_sl, tp, side, price, price, price)
        if px is not None:
            self.close(pos, why)
            return why
        return ""

    # ------------------------------------------------------------------ aturan risiko
    def equity(self) -> float:
        try:
            return self.record_equity(save=False)
        except Exception:  # noqa: BLE001
            return float(self.cfg["paper"]["starting_balance"])

    def can_open(self, sym, candle_ts):
        if STOP_FILE.exists() or self.store.vget("pause_entries", False):
            return False, "posisi baru sedang dijeda"
        if len(self.store.open_positions()) >= int(self.r["max_open_positions"]):
            return False, "jumlah posisi maksimal tercapai"
        pnl_today = self.store.realized_pnl_today()
        if pnl_today <= -abs(float(self.r["max_daily_loss_quote"])):
            return False, f"batas rugi harian tercapai ({pnl_today:.2f})"
        venue = venue_of(sym)
        last_exit = self.store.last_exit_candle(sym)
        if last_exit is not None and (candle_ts - last_exit) // self.tfms(venue) < int(self.mk.strat(venue)["cooldown_candles"]):
            return False, "masa jeda setelah menutup posisi"
        return True, ""

    # ------------------------------------------------------------------ eksekusi
    def open(self, sym, side, reason, candle_ts, sig):
        venue = venue_of(sym)
        broker, s = self.mk.broker(venue), self.mk.strat(venue)
        price = broker.price(sym)
        sl0, tp0 = exit_levels(price, side, sig, s)
        plan = broker.plan(sym, side, price, sl0, self.equity())
        fill = broker.open(sym, side, plan, sl0, tp0)
        sl, tp = exit_levels(fill.price, side, sig, s)
        self.store.add_position(sym, fill, candle_ts, reason, sl, tp, side, venue)
        if broker.live and (abs(sl - sl0) > 0 or abs(tp - tp0) > 0):
            broker.modify({"symbol": sym, "order_id_buy": fill.order_id}, sl, tp)
        size = f"{fill.lots:.2f} lot" if fill.lots else f"senilai {fill.cost:.2f}"
        msg = (f"{SIDE_WORD[side]} {sym} {size} di harga {fill.price:,.6g}. "
               f"Stop-loss {sl:,.6g}, target {tp:,.6g}. Alasan: {reason}.")
        log.info("%s", msg)
        self.store.event("TRADE", msg)

    def _record_close(self, pos, fill, reason, candle_ts=None):
        pnl = self.store.close_position(pos["id"], fill, reason)
        venue = venue_of(pos["symbol"])
        step = self.tfms(venue)
        ts = candle_ts if candle_ts is not None else (self.now_ms() // step) * step
        self.store.set_kv(f"last_exit_ts:{self.store.mode}:{pos['symbol']}", int(ts))
        msg = (f"Tutup {pos['symbol']} di harga {fill.price:,.6g}, {'untung' if pnl >= 0 else 'rugi'} "
               f"{abs(pnl):.2f}. Alasan: {reason}.")
        log.info("%s", msg)
        self.store.event("TRADE", msg)

    def close(self, pos, reason, candle_ts=None):
        fill = self.mk.broker(venue_of(pos["symbol"])).close(pos)
        self._record_close(pos, fill, reason, candle_ts)

    def price_check(self):
        """Dipanggil berkala: cek posisi yang ditutup broker, lalu SL/TP/trailing dengan harga terkini."""
        for pos in self.store.open_positions():
            try:
                broker = self.mk.broker(venue_of(pos["symbol"]))
                done = broker.sync(pos)
                if done is not None:
                    self._record_close(pos, done, "kena stop-loss/target di server broker")
                    continue
                self._check_price(pos, broker.price(pos["symbol"]))
            except Exception as e:  # noqa: BLE001
                log.warning("Cek harga %s gagal: %s", pos["symbol"], e)

    def process_requests(self):
        """Permintaan dari panel: tutup posisi tertentu / semua."""
        req = self.store.vget("close_requests", [])
        if not req:
            return
        self.store.vset("close_requests", [])
        for pos in self.store.open_positions():
            if "ALL" in req or pos["id"] in req:
                try:
                    self.close(pos, "ditutup manual dari panel")
                except Exception as e:  # noqa: BLE001
                    log.exception("Gagal menutup %s", pos["symbol"])
                    self.store.event("ERROR", f"Gagal menutup {pos['symbol']}: {e}")

    def close_all(self, reason="ditutup manual"):
        for pos in self.store.open_positions():
            try:
                self.close(pos, reason)
            except Exception:  # noqa: BLE001
                log.exception("Gagal menutup %s", pos["symbol"])

    def record_equity(self, save=True) -> float:
        """Total aset = saldo + nilai posisi. Mode live: jumlah dari tiap akun yang dipakai."""
        openp = self.store.open_positions()
        venues = set(self.mk.venues()) | {venue_of(p["symbol"]) for p in openp}
        cash, value = 0.0, 0.0
        if not self.mk.live:
            cash = self.mk.broker(self.cfg.get("venue") or (sorted(venues)[0] if venues else "crypto")).cash()
            for pos in openp:
                b = self.mk.broker(venue_of(pos["symbol"]))
                value += b.value(pos, b.price(pos["symbol"]))
        else:
            for v in venues:
                b = self.mk.broker(v)
                if v == "forex":
                    cash += b.equity()   # ekuitas MT5 sudah termasuk posisi terbuka
                    continue
                cash += b.cash()
                for pos in openp:
                    if venue_of(pos["symbol"]) == v:
                        value += b.value(pos, b.price(pos["symbol"]))
        if save:
            self.store.add_equity(cash, value)
            log.info("Total aset: %.2f (saldo %.2f + posisi %.2f)", cash + value, cash, value)
        return cash + value
