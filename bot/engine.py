"""Otak bot: tiap candle tutup -> ramal -> putuskan -> eksekusi. Di antaranya cek SL/TP."""
import logging

from .config import ROOT
from .forecast import build_signal
from .market import fetch_recent, future_timestamps, tf_ms
from .strategy import entry_decision, exit_levels, opt, price_exit, signal_exit, trail

log = logging.getLogger("engine")
STOP_FILE = ROOT / "STOP"


class Engine:
    def __init__(self, cfg, ex, broker, store, forecaster):
        self.cfg, self.ex, self.broker, self.store, self.fc = cfg, ex, broker, store, forecaster
        self.s, self.r, self.m = cfg["strategy"], cfg["risk"], cfg["model"]
        self.tf = cfg["timeframe"]
        self.tfms = tf_ms(ex, self.tf)

    # ------------------------------------------------------------------ siklus candle
    def forecast_symbol(self, sym):
        hist = fetch_recent(self.ex, sym, self.tf, int(self.m["lookback"]))
        if len(hist) < 100:
            raise RuntimeError(f"data hanya {len(hist)} candle")
        y_ts = future_timestamps(hist["timestamps"].iloc[-1], self.tfms, int(self.m["pred_len"]))
        sig = build_signal(sym, hist, self.fc.paths(hist, y_ts), self.s["fee_pct"], int(opt(self.s, "trend_period")))
        return sig, int(hist["ts"].iloc[-1])

    def candle_cycle(self):
        # 1) ramal semua pair
        sigs = {}
        for sym in self.cfg["symbols"]:
            try:
                sigs[sym] = self.forecast_symbol(sym)
            except Exception as e:  # noqa: BLE001
                log.exception("Error saat meramal %s", sym)
                self.store.event("ERROR", f"{sym}: {e}")
        decisions = {}
        # 2) urus posisi yang sudah ada dulu (jual / tahan)
        for sym, (sig, ts) in sigs.items():
            if self.store.open_positions(sym):
                try:
                    decisions[sym] = self._manage(sym, sig, ts)
                except Exception as e:  # noqa: BLE001
                    log.exception("Error mengelola posisi %s", sym)
                    decisions[sym] = ("ERROR", str(e))
        # 3) beli: sinyal terkuat didahulukan
        cands = sorted((x for x in sigs if x not in decisions), key=lambda x: sigs[x][0].score, reverse=True)
        for sym in cands:
            sig, ts = sigs[sym]
            try:
                decisions[sym] = self._maybe_buy(sym, sig, ts)
            except Exception as e:  # noqa: BLE001
                log.exception("Error membeli %s", sym)
                self.store.event("ERROR", f"Gagal membeli {sym}: {e}")
                decisions[sym] = ("ERROR", str(e))
        for sym, (sig, _) in sigs.items():
            action, reason = decisions.get(sym, ("-", ""))
            self.store.add_signal(sig, action, reason)
            log.info("%s  ->  %s (%s)", sig.summary(), action, reason)
        self.record_equity()

    def _stops(self, pos):
        sl, tp = pos.get("sl"), pos.get("tp")
        if sl is None or tp is None:
            sl, tp = exit_levels(pos["entry_price"], None, self.s)
        return sl, tp, pos.get("peak") or pos["entry_price"]

    def _manage(self, sym, sig, candle_ts):
        pos = self.store.open_positions(sym)[0]
        held = int((candle_ts - pos["entry_candle_ts"]) // self.tfms)
        why = self._check_price(pos, sig.last_close)
        if why:
            return "JUAL", why
        hit, why = signal_exit(held, sig, self.s)
        if hit:
            self.close(pos, why, candle_ts)
            return "JUAL", why
        chg = (sig.last_close / pos["entry_price"] - 1) * 100
        return "TAHAN", f"posisi {held} candle, {chg:+.2f}% dari harga beli"

    def _maybe_buy(self, sym, sig, candle_ts):
        ok, why = self.can_open(sym, candle_ts)
        if not ok:
            return "LEWATI", why
        ok, why = entry_decision(sig, self.s)
        if not ok:
            return "TUNGGU", why
        self.open(sym, why, candle_ts, sig)
        return "BELI", why

    def _check_price(self, pos, price) -> str:
        """Perbarui trailing stop lalu cek SL/TP. Mengembalikan alasan jual, atau "" jika tetap ditahan."""
        sl, tp, peak = self._stops(pos)
        peak = max(peak, price)
        sl = trail(pos["entry_price"], peak, sl, self.s)
        if (sl, tp, peak) != (pos.get("sl"), pos.get("tp"), pos.get("peak")):
            self.store.update_stops(pos["id"], sl, tp, peak)
        px, why = price_exit(pos["entry_price"], sl, tp, price, price, price)
        if px is not None:
            self.close(pos, why)
            return why
        return ""

    # ------------------------------------------------------------------ aturan risiko
    def order_size(self):
        return min(float(self.r["order_size_quote"]), float(self.r["max_order_size_quote"]))

    def can_open(self, sym, candle_ts):
        if STOP_FILE.exists() or self.store.get_kv("pause_entries", False):
            return False, "beli baru sedang dijeda"
        if len(self.store.open_positions()) >= int(self.r["max_open_positions"]):
            return False, "jumlah posisi maksimal tercapai"
        pnl_today = self.store.realized_pnl_today()
        if pnl_today <= -abs(float(self.r["max_daily_loss_quote"])):
            return False, f"batas rugi harian tercapai ({pnl_today:.2f})"
        last_exit = self.store.last_exit_candle(sym)
        if last_exit is not None and (candle_ts - last_exit) // self.tfms < int(self.s["cooldown_candles"]):
            return False, "masa jeda setelah jual"
        size = self.order_size()
        min_cost = self.broker.min_cost(sym)
        if size < min_cost:
            return False, f"ukuran order {size} < minimum bursa {min_cost}"
        cash = self.broker.cash()
        if cash < size:
            return False, f"saldo {cash:.2f} < ukuran order {size}"
        return True, ""

    # ------------------------------------------------------------------ eksekusi
    def open(self, sym, reason, candle_ts, sig=None):
        size = self.order_size()
        fill = self.broker.buy(sym, size)
        sl, tp = exit_levels(fill.price, sig, self.s)
        self.store.add_position(sym, fill, candle_ts, reason, sl, tp)
        msg = (f"Beli {sym} senilai {fill.cost:.2f} di harga {fill.price:,.6g}. "
               f"Stop-loss {sl:,.6g}, target {tp:,.6g}. Alasan: {reason}.")
        log.info("✅ %s", msg)
        self.store.event("TRADE", msg)

    def close(self, pos, reason, candle_ts=None):
        fill = self.broker.sell(pos["symbol"], pos["amount"])
        pnl = self.store.close_position(pos["id"], fill, reason)
        ts = candle_ts if candle_ts is not None else (self.ex.milliseconds() // self.tfms) * self.tfms
        self.store.set_kv(f"last_exit_ts:{self.store.mode}:{pos['symbol']}", int(ts))
        msg = (f"Jual {pos['symbol']} di harga {fill.price:,.6g}, {'untung' if pnl >= 0 else 'rugi'} "
               f"{abs(pnl):.2f} ({pnl / pos['cost'] * 100:+.2f}%). Alasan: {reason}.")
        log.info("%s %s", "🟢" if pnl >= 0 else "🔴", msg)
        self.store.event("TRADE", msg)

    def price_check(self):
        """Dipanggil tiap beberapa detik: cek stop-loss/take-profit dengan harga terkini."""
        for pos in self.store.open_positions():
            try:
                self._check_price(pos, self.broker.price(pos["symbol"]))
            except Exception as e:  # noqa: BLE001
                log.warning("Cek harga %s gagal: %s", pos["symbol"], e)

    def process_requests(self):
        """Permintaan dari Panel Kontrol: jual posisi tertentu / semua."""
        req = self.store.get_kv("close_requests", [])
        if not req:
            return
        self.store.set_kv("close_requests", [])
        for pos in self.store.open_positions():
            if "ALL" in req or pos["id"] in req:
                try:
                    self.close(pos, "dijual manual dari panel")
                except Exception as e:  # noqa: BLE001
                    log.exception("Gagal menjual %s", pos["symbol"])
                    self.store.event("ERROR", f"Gagal menjual {pos['symbol']}: {e}")

    def close_all(self, reason="ditutup manual"):
        for pos in self.store.open_positions():
            try:
                self.close(pos, reason)
            except Exception:  # noqa: BLE001
                log.exception("Gagal menutup %s", pos["symbol"])

    def record_equity(self):
        try:
            cash = self.broker.cash()
            value = 0.0
            for pos in self.store.open_positions():
                value += pos["amount"] * self.broker.price(pos["symbol"])
            self.store.add_equity(cash, value)
            log.info("💰 Ekuitas: %.2f (kas %.2f + posisi %.2f)", cash + value, cash, value)
        except Exception as e:  # noqa: BLE001
            log.warning("Gagal mencatat ekuitas: %s", e)
