"""
Menjalankan robot trading Kronos (biasanya dinyalakan dari panel).

    python run_bot.py --venue crypto  # robot kripto (jalan terus)
    python run_bot.py --venue forex   # robot forex (jalan terus)
    python run_bot.py --venue forex --once   # satu siklus lalu keluar
    python run_bot.py --dummy         # uji alur dengan ramalan acak (hanya mode simulasi)
    python run_bot.py --status        # lihat posisi terbuka
    python run_bot.py --tutup-semua   # tutup semua posisi yang dibuka robot

Berhenti: Ctrl+C. Posisi terbuka TIDAK otomatis ditutup saat robot dimatikan.
"""
import argparse
import signal
import sys
import time

from bot.config import live_unlocked, load_config, path_in_root, setup_logging, venue_cfg
from bot.engine import Engine
from bot.forecast import make_forecaster
from bot.store import Store
from bot.venues import Markets


def print_status(store, mk):
    pos = store.open_positions()
    print(f"\nMode: {store.mode} | untung/rugi hari ini: {store.realized_pnl_today():+.2f}")
    if not pos:
        print("Tidak ada posisi terbuka.")
    for p in pos:
        try:
            now = mk.for_symbol(p["symbol"])[2].price(p["symbol"])
        except Exception:  # noqa: BLE001
            now = float("nan")
        side = p.get("side") or "long"
        chg = (now / p["entry_price"] - 1) * 100 * (-1 if side == "short" else 1)
        print(f"  {p['symbol']} {side}: {p['entry_price']:,.6g} -> {now:,.6g} ({chg:+.2f}%) sejak {p['entry_time']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue", choices=["crypto", "forex"], default="crypto", help="market yang dijalankan")
    ap.add_argument("--config", default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dummy", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--tutup-semua", action="store_true")
    ap.add_argument("--ya", action="store_true", help="lewati konfirmasi mode live")
    args = ap.parse_args()

    venue = args.venue
    cfg = venue_cfg(load_config(args.config), venue)
    log = setup_logging(f"bot_{venue}")
    live = cfg["mode"] == "live"
    if live and args.dummy:
        raise SystemExit("--dummy tidak boleh dipakai di mode live.")
    if live and not args.status:
        if not live_unlocked(venue):
            raise SystemExit("Mode live belum dikonfirmasi di panel (halaman Akun).")
        if not args.ya and input("Mode LIVE (uang sungguhan). Ketik SAYA PAHAM RISIKONYA: ").strip().upper() != "SAYA PAHAM RISIKONYA":
            raise SystemExit("Dibatalkan.")

    store = Store(path_in_root(cfg["db_path"]), cfg["mode"], venue)
    mk = Markets(cfg, store, live=live)
    if args.status:
        print_status(store, mk)
        return

    engine = Engine(cfg, store, None, mk)
    if args.tutup_semua:
        engine.close_all("ditutup manual (--tutup-semua)")
        print_status(store, mk)
        return

    # siapkan koneksi pasar lebih awal agar masalah (mis. MT5 belum login) langsung terlihat
    try:
        mk.broker(venue)
    except Exception as e:  # noqa: BLE001
        log.error("Market %s belum siap: %s", venue, e)
        store.event("ERROR", f"Market belum siap: {e}")
        if live:
            return 1

    store.vset("bot_state", "memuat model")
    try:
        engine.fc = make_forecaster(cfg, dummy=args.dummy)
    except Exception as e:  # noqa: BLE001
        log.error("Gagal memuat model AI. Pastikan internet tersambung. Detail: %s", e)
        store.event("ERROR", f"Gagal memuat model AI: {e}")
        store.vset("bot_state", "berhenti")
        return 1
    store.event("INFO", f"Robot {venue} mulai ({'live' if live else 'simulasi'}{', dummy' if args.dummy else ''})")
    log.info("Robot mulai | mode=%s | pasar=%s | tf=%s", cfg["mode"], cfg["symbols"], cfg["timeframe"])

    def _term(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)

    step = engine.tfms(venue)
    delay = int(cfg["loop"]["delay_after_close_sec"]) * 1000
    check_ms = int(cfg["loop"]["price_check_sec"]) * 1000
    now_ms = lambda: int(time.time() * 1000)  # noqa: E731
    try:
        store.vset("bot_state", "meramal")
        engine.process_requests()
        engine.candle_cycle()
        if args.once:
            return
        next_run = (now_ms() // step + 1) * step + delay
        next_check = now_ms() + check_ms
        log.info("Menunggu candle berikutnya...")
        while True:
            now = now_ms()
            store.vset("heartbeat", now)
            store.vset("next_run", next_run)
            store.vset("bot_state", "berjalan")
            engine.process_requests()
            if now >= next_run:
                store.vset("bot_state", "meramal")
                engine.candle_cycle()
                next_run = (now // step + 1) * step + delay
            elif now >= next_check:
                engine.price_check()
                next_check = now + check_ms
            time.sleep(3)
    except KeyboardInterrupt:
        log.info("Robot dihentikan. Posisi terbuka tetap ada.")
    finally:
        store.vset("bot_state", "berhenti")
        store.event("INFO", "Robot dihentikan")


if __name__ == "__main__":
    sys.exit(main())
