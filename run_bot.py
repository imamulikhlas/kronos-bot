"""
Menjalankan bot auto trading Kronos.

    python run_bot.py                 # jalan terus (mode sesuai config.yaml)
    python run_bot.py --once          # satu kali siklus lalu keluar (untuk mencoba)
    python run_bot.py --dummy         # uji alur program dengan ramalan acak (tanpa model)
    python run_bot.py --status        # lihat posisi terbuka dan PnL
    python run_bot.py --tutup-semua   # jual semua posisi yang dibuka bot

Berhenti: tekan Ctrl+C. Posisi terbuka TIDAK otomatis dijual saat bot dimatikan.
Rem darurat: buat file bernama STOP di folder ini -> bot berhenti membuka posisi baru.
"""
import argparse
import signal
import sys
import time

from bot.broker import make_broker
from bot.config import live_unlocked, load_config, path_in_root, setup_logging
from bot.engine import Engine
from bot.forecast import make_forecaster
from bot.market import make_exchange
from bot.store import Store


def confirm_live(cfg, skip_prompt: bool):
    if not live_unlocked():
        raise SystemExit("mode: live di config.yaml, tetapi LIVE_TRADING di .env belum 'YA'. Bot tidak dijalankan.")
    r = cfg["risk"]
    print("\n" + "=" * 64)
    print("  ⚠️  MODE LIVE: bot akan memakai UANG SUNGGUHAN di Tokocrypto")
    print(f"  Pair: {', '.join(cfg['symbols'])}  | timeframe {cfg['timeframe']}")
    print(f"  Modal per trade: {r['order_size_quote']} {cfg['quote']}  | maks posisi: {r['max_open_positions']}")
    print(f"  Batas rugi harian: {r['max_daily_loss_quote']} {cfg['quote']}")
    print("=" * 64)
    if skip_prompt:
        return
    if input("Ketik SAYA PAHAM RISIKONYA untuk lanjut: ").strip().upper() != "SAYA PAHAM RISIKONYA":
        raise SystemExit("Dibatalkan.")


def print_status(store, broker):
    pos = store.open_positions()
    print(f"\nMode: {store.mode} | kas: {broker.cash():.2f} | PnL terealisasi hari ini: {store.realized_pnl_today():+.2f}")
    if not pos:
        print("Tidak ada posisi terbuka.")
    for p in pos:
        now = broker.price(p["symbol"])
        chg = (now / p["entry_price"] - 1) * 100
        print(f"  {p['symbol']}: {p['amount']:.8g} @ {p['entry_price']:,.6g} -> {now:,.6g} ({chg:+.2f}%) sejak {p['entry_time']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dummy", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--tutup-semua", action="store_true")
    ap.add_argument("--ya", action="store_true", help="lewati konfirmasi mode live (untuk jalan otomatis)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    log = setup_logging("bot")
    if cfg["mode"] == "live":
        if args.dummy:
            raise SystemExit("--dummy tidak boleh dipakai di mode live.")
        if not (args.status):
            confirm_live(cfg, args.ya)

    ex = make_exchange(cfg, private=cfg["mode"] == "live")
    store = Store(path_in_root(cfg["db_path"]), cfg["mode"])
    broker = make_broker(ex, store, cfg)

    if args.status:
        print_status(store, broker)
        return

    engine = Engine(cfg, ex, broker, store, forecaster=None)
    if args.tutup_semua:
        engine.close_all("ditutup manual (--tutup-semua)")
        print_status(store, broker)
        return

    store.set_kv("bot_state", "memuat model")
    try:
        engine.fc = make_forecaster(cfg, dummy=args.dummy)
    except Exception as e:  # noqa: BLE001
        log.error("Gagal memuat model AI. Pastikan internet tersambung. Detail: %s", e)
        store.event("ERROR", f"Gagal memuat model AI: {e}")
        store.set_kv("bot_state", "berhenti")
        return 1
    store.event("INFO", f"Robot mulai (mode {cfg['mode']}{', dummy' if args.dummy else ''})")
    log.info("Robot mulai | mode=%s | pair=%s | tf=%s", cfg["mode"], cfg["symbols"], cfg["timeframe"])

    def _term(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)

    tfms = engine.tfms
    delay = int(cfg["loop"]["delay_after_close_sec"]) * 1000
    check_ms = int(cfg["loop"]["price_check_sec"]) * 1000
    try:
        store.set_kv("bot_state", "meramal")
        engine.process_requests()
        engine.candle_cycle()
        if args.once:
            return
        next_run = (ex.milliseconds() // tfms + 1) * tfms + delay
        next_check = ex.milliseconds() + check_ms
        log.info("Menunggu candle berikutnya...")
        while True:
            now = ex.milliseconds()
            store.set_kv("heartbeat", now)
            store.set_kv("next_run", next_run)
            store.set_kv("bot_state", "berjalan")
            engine.process_requests()
            if now >= next_run:
                store.set_kv("bot_state", "meramal")
                engine.candle_cycle()
                next_run = (now // tfms + 1) * tfms + delay
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
