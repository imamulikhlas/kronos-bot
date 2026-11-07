"""
Menjalankan robot trading Kronos (biasanya dinyalakan dari panel).

    python run_bot.py                 # jalan terus (mode sesuai config.yaml)
    python run_bot.py --once          # satu siklus lalu keluar
    python run_bot.py --dummy         # uji alur dengan ramalan acak (hanya mode simulasi)
    python run_bot.py --status        # lihat posisi terbuka
    python run_bot.py --tutup-semua   # tutup semua posisi yang dibuka robot

Berhenti: Ctrl+C. Posisi terbuka TIDAK otomatis ditutup saat robot dimatikan.
"""
import argparse
import signal
import sys
import time

from bot.config import live_unlocked, load_config, path_in_root, setup_logging
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
    ap.add_argument("--config", default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dummy", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--tutup-semua", action="store_true")
    ap.add_argument("--ya", action="store_true", help="lewati konfirmasi mode live")
    args = ap.parse_args()

    cfg = load_config(args.config)
    log = setup_logging("bot")
    live = cfg["mode"] == "live"
    if live and args.dummy:
        raise SystemExit("--dummy tidak boleh dipakai di mode live.")
    if live and not args.status:
        if not live_unlocked():
            raise SystemExit("Mode live belum dikonfirmasi di panel (halaman Akun).")
        if not args.ya and input("Mode LIVE (uang sungguhan). Ketik SAYA PAHAM RISIKONYA: ").strip().upper() != "SAYA PAHAM RISIKONYA":
            raise SystemExit("Dibatalkan.")

    store = Store(path_in_root(cfg["db_path"]), cfg["mode"])
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
    for v in mk.venues():
        try:
            mk.broker(v)
        except Exception as e:  # noqa: BLE001
            log.error("Pasar %s belum siap: %s", v, e)
            store.event("ERROR", f"Pasar {'forex' if v == 'forex' else 'kripto'} belum siap: {e}")

    store.set_kv("bot_state", "memuat model")
    try:
        engine.fc = make_forecaster(cfg, dummy=args.dummy)
    except Exception as e:  # noqa: BLE001
        log.error("Gagal memuat model AI. Pastikan internet tersambung. Detail: %s", e)
        store.event("ERROR", f"Gagal memuat model AI: {e}")
        store.set_kv("bot_state", "berhenti")
        return 1
    store.event("INFO", f"Robot mulai ({'live' if live else 'simulasi'}{', dummy' if args.dummy else ''})")
    log.info("Robot mulai | mode=%s | pasar=%s | tf=%s", cfg["mode"], cfg["symbols"], cfg["timeframe"])

    def _term(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)

    step = engine.tfms(mk.venues()[0]) if mk.venues() else 3600 * 1000
    delay = int(cfg["loop"]["delay_after_close_sec"]) * 1000
    check_ms = int(cfg["loop"]["price_check_sec"]) * 1000
    now_ms = lambda: int(time.time() * 1000)  # noqa: E731
    try:
        store.set_kv("bot_state", "meramal")
        engine.process_requests()
        engine.candle_cycle()
        if args.once:
            return
        next_run = (now_ms() // step + 1) * step + delay
        next_check = now_ms() + check_ms
        log.info("Menunggu candle berikutnya...")
        while True:
            now = now_ms()
            store.set_kv("heartbeat", now)
            store.set_kv("next_run", next_run)
            store.set_kv("bot_state", "berjalan")
            engine.process_requests()
            if now >= next_run:
                store.set_kv("bot_state", "meramal")
                engine.candle_cycle()
                next_run = (now // step + 1) * step + delay
            elif now >= next_check:
                engine.price_check()
                next_check = now + check_ms
            time.sleep(3)
    except KeyboardInterrupt:
        log.info("Robot dihentikan. Posisi terbuka tetap ada.")
    finally:
        store.set_kv("bot_state", "berhenti")
        store.event("INFO", "Robot dihentikan")


if __name__ == "__main__":
    sys.exit(main())
