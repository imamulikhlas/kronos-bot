"""
Pemeriksaan sebelum menjalankan bot.

    python cek_koneksi.py            # cek semuanya: library, data, model, API key
    python cek_koneksi.py --pasar    # daftar pair USDT di Tokocrypto
    python cek_koneksi.py --tanpa-model
"""
import argparse
import sys
import time

OK, NO = "✅", "❌"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pasar", action="store_true")
    ap.add_argument("--tanpa-model", action="store_true")
    args = ap.parse_args()

    print(f"Python {sys.version.split()[0]}", OK if sys.version_info >= (3, 10) else f"{NO} butuh Python 3.10+")
    from bot.config import KRONOS_DIR, api_keys, live_unlocked, load_config
    cfg = load_config()
    print(f"Config: mode={cfg['mode']} pair={cfg['symbols']} tf={cfg['timeframe']}")

    from bot.market import fetch_recent, future_timestamps, make_exchange, tf_ms
    ex = make_exchange(cfg)
    try:
        markets = ex.load_markets()
        print(f"{OK} Terhubung ke {cfg['exchange']} ({len(markets)} pair)")
    except Exception as e:  # noqa: BLE001
        print(f"{NO} Gagal terhubung ke bursa: {e}")
        return
    if args.pasar:
        q = cfg.get("quote", "USDT")
        print("\n".join(sorted(s for s, m in markets.items() if s.endswith("/" + q) and m.get("active", True))))
        return
    for s in cfg["symbols"]:
        if s not in markets:
            print(f"{NO} Pair {s} tidak ada di bursa. Lihat: python cek_koneksi.py --pasar")
            continue
        df = fetch_recent(ex, s, cfg["timeframe"], int(cfg["model"]["lookback"]))
        print(f"{OK} {s}: {len(df)} candle, terakhir {df['timestamps'].iloc[-1]} close {df['close'].iloc[-1]:,.6g}")
        lim = (markets[s].get("limits") or {}).get("cost") or {}
        if lim.get("min"):
            print(f"   minimal order {lim['min']} {cfg.get('quote', 'USDT')}")

    if not args.tanpa_model:
        print(f"{OK if (KRONOS_DIR / 'model').exists() else NO} Folder Kronos: {KRONOS_DIR}")
        from bot.forecast import KronosForecaster, build_signal
        t0 = time.time()
        fc = KronosForecaster(cfg["model"])
        s = cfg["symbols"][0]
        df = fetch_recent(ex, s, cfg["timeframe"], int(cfg["model"]["lookback"]))
        y = future_timestamps(df["timestamps"].iloc[-1], tf_ms(ex, cfg["timeframe"]), int(cfg["model"]["pred_len"]))
        t1 = time.time()
        sig = build_signal(s, df, fc.paths(df, y), cfg["strategy"]["fee_pct"])
        print(f"{OK} Ramalan berhasil ({time.time() - t1:.1f} detik per pair): {sig.summary()}")
        print(f"   total waktu termasuk memuat model: {time.time() - t0:.0f} detik")

    key, sec = api_keys()
    if key and sec:
        try:
            pex = make_exchange(cfg, private=True)
            bal = pex.fetch_balance()
            q = cfg.get("quote", "USDT")
            print(f"{OK} API key valid. Saldo {q} bebas: {(bal.get('free') or {}).get(q, 0)}")
        except Exception as e:  # noqa: BLE001
            print(f"{NO} API key ditolak: {e}")
    else:
        print("ℹ️  API key belum diisi (tidak perlu untuk mode paper).")
    print(f"ℹ️  Mode live {'TERBUKA' if live_unlocked() else 'terkunci'} (LIVE_TRADING di .env)")


if __name__ == "__main__":
    main()
