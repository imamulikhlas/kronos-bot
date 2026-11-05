"""PANEL KONTROL ROBOT TRADING KRONOS — dibuka otomatis oleh MULAI.bat / mulai.command"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bot import control as ctl
from bot.store import WIB
from bot.strategy import opt as sopt
from bot import ui_analysis
from bot.config import KRONOS_DIR, api_keys, live_unlocked, load_config, path_in_root

st.set_page_config(page_title="Robot Trading Kronos", page_icon="🤖", layout="wide")

MODELS = {
    "Ringan (paling cepat)": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k"),
    "Sedang (disarankan)": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base"),
    "Berat (paling teliti, lambat)": ("NeoQuasar/Kronos-base", "NeoQuasar/Kronos-Tokenizer-base"),
}
TIMEFRAMES = {"15m": "15 menit", "30m": "30 menit", "1h": "1 jam", "4h": "4 jam", "1d": "1 hari"}
PRESETS = {  # (min ekspektasi %, min peluang naik)
    "Hati-hati (jarang beli, sinyal harus kuat)": (1.2, 0.75),
    "Normal": (0.8, 0.65),
    "Agresif (sering beli, lebih berisiko)": (0.4, 0.55),
}
CONFIRM_TEXT = "SAYA PAHAM RISIKONYA"

cfg = load_config()
DB = path_in_root(cfg["db_path"])
BT_DIR = path_in_root("data/backtest/x").parent
MODE = cfg["mode"]
MODE_LABEL = "🔴 LIVE (uang sungguhan)" if MODE == "live" else "🟢 SIMULASI (uang virtual)"


# ======================================================================= helpers
def q(sql, args=()):
    if not DB.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(DB, timeout=10) as con:
            return pd.read_sql_query(sql, con, params=args)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def store():
    from bot.store import Store
    return Store(DB, MODE)


@st.cache_resource
def public_exchange(name):
    from bot.market import make_exchange
    return make_exchange({"exchange": name})


@st.cache_data(ttl=3600, show_spinner=False)
def all_pairs(name, quote):
    try:
        mk = public_exchange(name).load_markets()
        return sorted(s for s, m in mk.items() if s.endswith("/" + quote) and m.get("active", True))
    except Exception:  # noqa: BLE001
        return []


@st.cache_data(ttl=15, show_spinner=False)
def price_now(name, symbol):
    try:
        return float(public_exchange(name).fetch_ticker(symbol)["last"])
    except Exception:  # noqa: BLE001
        return None


def money(v):
    return f"{v:,.2f} {cfg.get('quote', 'USDT')}"


def sell_positions(ids):
    """ids = list id posisi atau ['ALL']"""
    if ctl.bot_running():
        s = store()
        s.set_kv("close_requests", list(set(s.get_kv("close_requests", []) + ids)))
        st.toast("Perintah jual dikirim. Robot akan menjual dalam beberapa detik.", icon="📤")
        return
    try:
        from bot.broker import make_broker
        from bot.engine import Engine
        from bot.market import make_exchange
        ex = make_exchange(cfg, private=MODE == "live")
        s = store()
        eng = Engine(cfg, ex, make_broker(ex, s, cfg), s, None)
        for pos in s.open_positions():
            if "ALL" in ids or pos["id"] in ids:
                eng.close(pos, "dijual manual dari panel")
        st.toast("Posisi berhasil dijual.", icon="✅")
    except Exception as e:  # noqa: BLE001
        st.error(f"Gagal menjual: {e}")


def apply_and_restart(new_cfg, msg="Pengaturan disimpan."):
    ctl.save_config(new_cfg)
    if ctl.bot_running():
        ctl.restart_bot()
        msg += " Robot dinyalakan ulang dengan pengaturan baru."
    st.session_state["flash"] = msg
    st.rerun()


# ======================================================================= sidebar
st.sidebar.title("🤖 Robot Trading")
page = st.sidebar.radio("Menu", ["🏠 Beranda", "📡 Analisa Realtime", "⚙️ Pengaturan Robot", "🔑 Akun & Mode",
                                 "📊 Riwayat & Grafik", "🧪 Uji Strategi"], label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.markdown(f"**Mode:** {MODE_LABEL}")
st.sidebar.markdown(f"**Robot:** {'🟢 menyala' if ctl.bot_running() else '⚪ mati'}")
st.sidebar.caption(f"Pair: {', '.join(cfg['symbols'])}  \nTimeframe: {TIMEFRAMES.get(cfg['timeframe'], cfg['timeframe'])}")

if not (KRONOS_DIR / "model").exists():
    st.error("Setup belum selesai (folder Kronos belum ada). Tutup jendela ini lalu jalankan file MULAI lagi.")
    st.stop()
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))


# ======================================================================= BERANDA
def page_home():
    st.title("🏠 Beranda")
    if MODE == "live":
        st.error("MODE LIVE: robot memakai UANG SUNGGUHAN di akun Tokocrypto Anda.")

    @st.fragment(run_every=5)
    def live_panel():
        running = ctl.bot_running()
        s = store()
        state = s.get_kv("bot_state", "berhenti")
        nxt = s.get_kv("next_run")

        # ----- kartu status + tombol
        box = st.container(border=True)
        c1, c2, c3 = box.columns([3, 1.3, 1.6])
        if running:
            txt = {"memuat model": "⏳ Sedang memuat model AI (pertama kali bisa beberapa menit)...",
                   "meramal": "🔮 Sedang meramal harga dan mengambil keputusan..."}.get(state, "🟢 Robot menyala dan memantau pasar")
            c1.subheader(txt)
            if nxt:
                c1.caption("Ramalan berikutnya: " + datetime.fromtimestamp(nxt / 1000).strftime("%H:%M") +
                           " · stop-loss/take-profit dicek terus setiap menit")
            if c2.button("⏹️ Matikan Robot", width="stretch"):
                ctl.stop_bot()
                s.set_kv("bot_state", "berhenti")
                st.rerun(scope="app")
        else:
            c1.subheader("⚪ Robot mati")
            c1.caption("Posisi yang masih terbuka tidak dijaga stop-loss selama robot mati.")
            if c2.button("▶️ Nyalakan Robot", type="primary", width="stretch"):
                if MODE == "live" and not live_unlocked():
                    st.error("Mode live belum dikonfirmasi. Buka menu 🔑 Akun & Mode.")
                else:
                    ctl.start_bot()
                    st.rerun(scope="app")
        paused = bool(s.get_kv("pause_entries", False))
        new_paused = c3.toggle("⏸️ Jeda beli baru", value=paused,
                               help="Robot tidak membuka posisi baru, tapi tetap menjaga & menjual posisi yang ada.")
        if new_paused != paused:
            s.set_kv("pause_entries", new_paused)

        if ctl.bot_crashed():
            with st.container(border=True):
                st.error("Robot berhenti karena ada masalah. Lihat pesan di bawah, perbaiki, lalu nyalakan lagi.")
                st.code(ctl.tail(ctl.BOT_CONSOLE, 25) or "(tidak ada pesan)")
                if st.button("Tutup pesan ini"):
                    ctl.BOT_PID.unlink(missing_ok=True)
                    st.rerun(scope="app")

        # ----- angka utama
        eq = q("SELECT equity, cash FROM equity WHERE mode=? ORDER BY id", (MODE,))
        closed = q("SELECT pnl, exit_time FROM positions WHERE mode=? AND status='closed'", (MODE,))
        openp = q("SELECT * FROM positions WHERE mode=? AND status='open' ORDER BY id", (MODE,))
        today = datetime.now(WIB).strftime("%Y-%m-%d")
        m = st.columns(5)
        m[0].metric("Total aset", money(eq["equity"].iloc[-1]) if not eq.empty else "–",
                    f"{(eq['equity'].iloc[-1] / eq['equity'].iloc[0] - 1) * 100:+.2f}%" if len(eq) > 1 else None)
        m[1].metric("Untung/rugi total", money(closed["pnl"].sum()) if not closed.empty else money(0))
        m[2].metric("Untung/rugi hari ini",
                    money(closed[closed["exit_time"].str.startswith(today)]["pnl"].sum()) if not closed.empty else money(0))
        m[3].metric("Posisi terbuka", f"{len(openp)} / {cfg['risk']['max_open_positions']}")
        m[4].metric("Trade menang", f"{(closed['pnl'] > 0).mean() * 100:.0f}% dari {len(closed)}" if not closed.empty else "–")

        # ----- posisi terbuka
        st.subheader("📂 Posisi terbuka")
        if openp.empty:
            st.caption("Belum ada posisi. Robot akan membeli otomatis saat sinyalnya cukup kuat.")
        else:
            head = st.columns([1.3, 1.4, 1.4, 1.4, 1.2, 1.6, 1.2])
            for h, t in zip(head, ["Pair", "Harga beli", "Harga sekarang", "Modal", "Untung/rugi", "Sejak", ""]):
                h.markdown(f"**{t}**")
            for _, p in openp.iterrows():
                now = price_now(cfg["exchange"], p["symbol"])
                pct = (now / p["entry_price"] - 1) * 100 if now else 0
                r = st.columns([1.3, 1.4, 1.4, 1.4, 1.2, 1.6, 1.2])
                r[0].write(p["symbol"])
                r[1].write(f"{p['entry_price']:,.6g}")
                r[2].write(f"{now:,.6g}" if now else "–")
                r[3].write(money(p["cost"]))
                r[4].markdown(f":{'green' if pct >= 0 else 'red'}[{pct:+.2f}%]")
                r[5].write(str(p["entry_time"])[5:16])
                if r[6].button("Jual", key=f"sell{p['id']}"):
                    sell_positions([int(p["id"])])
            with st.popover("💸 Jual semua posisi"):
                st.write("Semua posisi yang dibuka robot akan dijual dengan harga pasar sekarang.")
                if st.button("Ya, jual semua", type="primary"):
                    sell_positions(["ALL"])

        # ----- keputusan terakhir
        st.subheader("🧠 Keputusan terakhir robot")
        sig = q("SELECT candle_time, symbol, last_close, exp_ret_pct, prob_up, direction, action, reason FROM signals "
                "WHERE mode=? ORDER BY id DESC LIMIT 50", (MODE,))
        if sig.empty:
            st.caption("Belum ada. Nyalakan robot untuk mulai.")
        else:
            lat = sig.drop_duplicates("symbol").copy()
            icon = {"BELI": "🟢 BELI", "JUAL": "🔴 JUAL", "TAHAN": "✋ TAHAN", "TUNGGU": "⏳ TUNGGU", "LEWATI": "⏭️ LEWATI"}
            lat["Keputusan"] = lat["action"].map(icon).fillna(lat["action"])
            lat["Ramalan naik/turun"] = lat["exp_ret_pct"].map(lambda v: f"{v:+.2f}%")
            lat["Peluang naik"] = lat["prob_up"].map(lambda v: f"{v:.0%}")
            lat["Arah"] = lat["direction"].map({"NAIK": "🟢 NAIK", "TURUN": "🔴 TURUN", "SAMPING": "🟡 SAMPING"}).fillna("-")
            st.dataframe(lat.rename(columns={"symbol": "Pair", "candle_time": "Waktu", "last_close": "Harga",
                                             "reason": "Alasan"})[
                ["Pair", "Waktu", "Harga", "Arah", "Ramalan naik/turun", "Peluang naik", "Keputusan", "Alasan"]],
                hide_index=True, width="stretch")

        st.subheader("📝 Aktivitas terbaru")
        ev = q("SELECT time AS Waktu, message AS Kejadian FROM events WHERE mode=? ORDER BY id DESC LIMIT 12", (MODE,))
        st.dataframe(ev, hide_index=True, width="stretch") if not ev.empty else st.caption("Belum ada aktivitas.")

    live_panel()


# ======================================================================= PENGATURAN
def page_settings():
    st.title("⚙️ Pengaturan Robot")
    st.caption("Ubah lalu klik **Simpan**. Jika robot sedang menyala, robot otomatis dinyalakan ulang.")
    s_, r_, m_ = cfg["strategy"], cfg["risk"], cfg["model"]
    pairs = all_pairs(cfg["exchange"], cfg.get("quote", "USDT"))
    cur_preset = next((k for k, v in PRESETS.items()
                       if abs(v[0] - s_["min_expected_return_pct"]) < 1e-9 and abs(v[1] - s_["min_prob_up"]) < 1e-9), "Kustom")
    cur_model = next((k for k, v in MODELS.items() if v[0] == m_["name"]), "Sedang (disarankan)")

    with st.form("settings"):
        st.subheader("1. Koin yang diperdagangkan")
        if pairs:
            symbols = st.multiselect("Pilih pair", pairs, default=[x for x in cfg["symbols"] if x in pairs],
                                     help="Semakin banyak pair, semakin lama robot meramal tiap candle.")
        else:
            st.warning("Daftar pair tidak bisa diambil (cek internet). Ketik manual, pisahkan dengan koma.")
            symbols = [x.strip().upper() for x in st.text_input("Pair", ", ".join(cfg["symbols"])).split(",") if x.strip()]
        tf = st.selectbox("Robot mengambil keputusan setiap", list(TIMEFRAMES), format_func=TIMEFRAMES.get,
                          index=list(TIMEFRAMES).index(cfg["timeframe"]) if cfg["timeframe"] in TIMEFRAMES else 2)

        st.subheader("2. Modal & batas posisi")
        c = st.columns(3)
        size = c[0].number_input("Modal per posisi (USDT)", 1.0, 100000.0, float(r_["order_size_quote"]), 1.0,
                                 help="Uang yang dipakai setiap kali robot membeli.")
        maxpos = c[1].number_input("Maksimal posisi terbuka bersamaan", 1, 50, int(r_["max_open_positions"]))
        dloss = c[2].number_input("Berhenti beli jika rugi hari ini mencapai (USDT)", 0.0, 100000.0,
                                  float(r_["max_daily_loss_quote"]), 1.0)
        st.caption(f"Modal maksimal yang bisa terpakai sekaligus: **{size * maxpos:,.2f} USDT**")

        st.subheader("3. Kapan menjual")
        c = st.columns(3)
        sl = c[0].number_input("Stop-loss: jual jika rugi (%)", 0.1, 50.0, float(s_["stop_loss_pct"]), 0.1)
        tp = c[1].number_input("Take-profit: jual jika untung (%)", 0.1, 200.0, float(s_["take_profit_pct"]), 0.1)
        hold = c[2].number_input("Jual paksa setelah berapa candle", 1, 1000, int(s_["max_hold_candles"]))
        st.caption(f"Contoh: beli di 100 → dijual otomatis di {100 * (1 - sl / 100):.2f} (rugi) "
                   f"atau {100 * (1 + tp / 100):.2f} (untung).")

        st.subheader("4. Kapan membeli")
        preset = st.radio("Seberapa yakin robot sebelum membeli?", list(PRESETS) + ["Kustom"],
                          index=(list(PRESETS) + ["Kustom"]).index(cur_preset))
        with st.expander("Angka kustom"):
            c = st.columns(2)
            cexp = c[0].number_input("Minimal ramalan kenaikan (%)", 0.0, 50.0, float(s_["min_expected_return_pct"]), 0.1)
            cprob = c[1].slider("Minimal peluang naik", 0.5, 1.0, float(s_["min_prob_up"]), 0.05)

        st.subheader("5. Kecerdasan tambahan")
        st.caption("Penyaring agar robot tidak asal beli, dan cara menjaga untung.")
        c = st.columns(3)
        trend_on = c[0].toggle("Hanya beli saat tren naik", value=bool(sopt(s_, "trend_filter")),
                               help="Harga harus di atas garis EMA tren dan garisnya sedang menanjak.")
        rsi_max = c[1].slider("Jangan beli jika RSI di atas", 50, 100, int(sopt(s_, "rsi_max")),
                              help="RSI tinggi = harga sudah naik terlalu cepat (jenuh beli). 100 = abaikan.")
        min_rr = c[2].number_input("Minimal rasio untung : rugi", 0.0, 10.0, float(sopt(s_, "min_rr")), 0.1,
                                   help="Potensi naik harus sekian kali potensi turun menurut ramalan. 0 = abaikan.")
        sl_mode = st.radio("Cara menentukan stop-loss & take-profit",
                           ["Persen tetap (bagian 3)", "Otomatis mengikuti volatilitas (ATR)"],
                           index=1 if sopt(s_, "sl_mode") == "atr" else 0, horizontal=True)
        c = st.columns(2)
        sl_atr = c[0].number_input("ATR: stop-loss = volatilitas ×", 0.5, 10.0, float(sopt(s_, "sl_atr_mult")), 0.5)
        tp_atr = c[1].number_input("ATR: take-profit = volatilitas ×", 0.5, 20.0, float(sopt(s_, "tp_atr_mult")), 0.5)
        c = st.columns(3)
        trail_on = c[0].toggle("Trailing stop (kunci untung)", value=bool(sopt(s_, "trailing_on")),
                               help="Saat harga naik, batas jual ikut naik. Untung tidak hilang saat harga berbalik.")
        trail_act = c[1].number_input("Aktif setelah untung (%)", 0.1, 50.0, float(sopt(s_, "trail_activate_pct")), 0.1)
        trail_pct = c[2].number_input("Jual jika turun dari puncak (%)", 0.1, 50.0, float(sopt(s_, "trail_pct")), 0.1)

        st.subheader("6. Otak AI")
        model_label = st.selectbox("Ukuran model Kronos", list(MODELS), index=list(MODELS).index(cur_model))

        with st.expander("Pengaturan lanjutan (biarkan saja jika ragu)"):
            c = st.columns(3)
            fee = c[0].number_input("Biaya trading per transaksi (%)", 0.0, 2.0, float(s_["fee_pct"]), 0.01)
            start_bal = c[1].number_input("Saldo awal simulasi (USDT)", 1.0, 1e7, float(cfg["paper"]["starting_balance"]))
            maxorder = c[2].number_input("Batas keras per order (USDT)", 1.0, 1e7, float(r_["max_order_size_quote"]))
            c = st.columns(3)
            npaths = c[0].number_input("Jumlah skenario ramalan", 2, 50, int(m_["n_paths"]))
            plen = c[1].number_input("Meramal berapa candle ke depan", 2, 120, int(m_["pred_len"]))
            cool = c[2].number_input("Jeda setelah jual (candle)", 0, 100, int(s_["cooldown_candles"]))
            exitp = st.slider("Jual jika peluang naik turun di bawah", 0.0, 0.5, float(s_["exit_prob_up_below"]), 0.05)

        saved = st.form_submit_button("💾 Simpan pengaturan", type="primary")

    if saved:
        if not symbols:
            st.error("Pilih minimal satu pair.")
            return
        new = json.loads(json.dumps(cfg))
        exp_, prob_ = (cexp, cprob) if preset == "Kustom" else PRESETS[preset]
        new["symbols"], new["timeframe"] = symbols, tf
        new["risk"].update(order_size_quote=size, max_open_positions=int(maxpos), max_daily_loss_quote=dloss,
                           max_order_size_quote=max(maxorder, size))
        new["strategy"].update(stop_loss_pct=sl, take_profit_pct=tp, max_hold_candles=int(hold),
                               min_expected_return_pct=exp_, min_prob_up=prob_, fee_pct=fee,
                               cooldown_candles=int(cool), exit_prob_up_below=exitp,
                               trend_filter=bool(trend_on), rsi_max=int(rsi_max), min_rr=float(min_rr),
                               sl_mode="atr" if sl_mode.startswith("Otomatis") else "persen",
                               sl_atr_mult=float(sl_atr), tp_atr_mult=float(tp_atr), trailing_on=bool(trail_on),
                               trail_activate_pct=float(trail_act), trail_pct=float(trail_pct))
        new["model"].update(name=MODELS[model_label][0], tokenizer=MODELS[model_label][1],
                            n_paths=int(npaths), pred_len=int(plen))
        new["paper"]["starting_balance"] = start_bal
        apply_and_restart(new)


# ======================================================================= AKUN & MODE
def page_account():
    st.title("🔑 Akun Tokocrypto & Mode")
    st.markdown(f"Mode sekarang: **{MODE_LABEL}**")

    with st.container(border=True):
        st.subheader("1. API key Tokocrypto")
        st.caption("Hanya diperlukan untuk mode Live. Buat di Tokocrypto → Manajemen API. "
                   "Aktifkan izin **baca + spot trading** saja. **JANGAN aktifkan izin withdraw.**")
        key, sec = api_keys()
        with st.form("keys"):
            k = st.text_input("API Key", type="password", placeholder="(sudah tersimpan)" if key else "")
            s = st.text_input("Secret Key", type="password", placeholder="(sudah tersimpan)" if sec else "")
            if st.form_submit_button("💾 Simpan API key"):
                vals = {}
                if k.strip():
                    vals["TOKOCRYPTO_API_KEY"] = k.strip()
                if s.strip():
                    vals["TOKOCRYPTO_API_SECRET"] = s.strip()
                if vals:
                    ctl.save_env(vals)
                    st.success("API key disimpan di komputer Anda (file .env).")
        if st.button("🔌 Tes koneksi akun"):
            try:
                from bot.market import make_exchange
                ex = make_exchange(cfg, private=True)
                bal = ex.fetch_balance()
                st.success(f"Berhasil terhubung. Saldo USDT bebas: {(bal.get('free') or {}).get('USDT', 0)}")
            except SystemExit as e:
                st.error(str(e))
            except Exception as e:  # noqa: BLE001
                st.error(f"Gagal: {e}")

    with st.container(border=True):
        st.subheader("2. Pilih mode")
        choice = st.radio("Mode", ["Simulasi (uang virtual)", "Live (uang sungguhan)"],
                          index=1 if MODE == "live" else 0, horizontal=True)
        if choice.startswith("Live"):
            st.warning("Di mode Live robot akan membeli dan menjual sungguhan di akun Tokocrypto Anda. "
                       "Robot bisa rugi. Gunakan modal kecil yang siap hilang. "
                       "Sebaiknya jalankan mode Simulasi dulu minimal 1–2 minggu.")
            typed = st.text_input(f"Ketik **{CONFIRM_TEXT}** untuk mengaktifkan mode Live")
            if st.button("Aktifkan mode Live", type="primary"):
                if typed.strip().upper() != CONFIRM_TEXT:
                    st.error("Teks konfirmasi belum sesuai.")
                elif not all(api_keys()):
                    st.error("Isi dan simpan API key dulu.")
                else:
                    ctl.save_env({"LIVE_TRADING": "YA"})
                    new = dict(cfg, mode="live")
                    apply_and_restart(new, "Mode LIVE aktif.")
        elif MODE == "live":
            if st.button("Kembali ke mode Simulasi", type="primary"):
                ctl.save_env({"LIVE_TRADING": "TIDAK"})
                apply_and_restart(dict(cfg, mode="paper"),
                                  "Kembali ke mode Simulasi. Posisi live yang masih terbuka tetap ada di akun Anda.")

    with st.container(border=True):
        st.subheader("3. Reset simulasi")
        st.caption("Menghapus semua riwayat mode Simulasi dan mengembalikan saldo virtual ke awal.")
        if ctl.bot_running() and MODE == "paper":
            st.info("Matikan robot dulu untuk mereset.")
        elif st.button("🗑️ Reset data simulasi"):
            from bot.store import Store
            s_ = Store(DB, "paper")
            for t in ("positions", "signals", "equity", "events"):
                s_.db.execute(f"DELETE FROM {t} WHERE mode='paper'")
            s_.db.execute("DELETE FROM kv WHERE key='paper_cash' OR key LIKE 'last_exit_ts:paper:%'")
            s_.db.commit()
            st.success("Data simulasi direset.")


# ======================================================================= RIWAYAT
def page_history():
    st.title("📊 Riwayat & Grafik")
    modes = q("SELECT DISTINCT mode FROM equity UNION SELECT DISTINCT mode FROM positions")
    opts = sorted(set(modes["mode"].tolist()) | {MODE}) if not modes.empty else [MODE]
    mode = st.radio("Tampilkan data", opts, index=opts.index(MODE), horizontal=True,
                    format_func=lambda m: "Live" if m == "live" else "Simulasi")

    eq = q("SELECT time, equity FROM equity WHERE mode=? ORDER BY id", (mode,))
    if not eq.empty:
        fig = go.Figure(go.Scatter(x=pd.to_datetime(eq["time"]), y=eq["equity"], mode="lines", fill="tozeroy"))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10), title="Perkembangan total aset",
                          yaxis=dict(range=[eq["equity"].min() * 0.995, eq["equity"].max() * 1.005]))
        st.plotly_chart(fig, width="stretch")

    st.subheader("Riwayat trade")
    tr = q("SELECT symbol AS Pair, entry_time AS Beli, entry_price AS 'Harga beli', exit_time AS Jual, "
           "exit_price AS 'Harga jual', cost AS Modal, pnl AS 'Untung/rugi', pnl_pct AS '%', "
           "exit_reason AS 'Alasan jual' FROM positions WHERE mode=? AND status='closed' ORDER BY id DESC", (mode,))
    if tr.empty:
        st.caption("Belum ada trade yang selesai.")
    else:
        st.dataframe(tr.style.format({"Untung/rugi": "{:+.2f}", "%": "{:+.2f}%"}), hide_index=True, width="stretch")

    st.subheader("Ramalan terakhir per pair")
    sig = q("SELECT * FROM signals WHERE mode=? ORDER BY id DESC LIMIT 500", (mode,))
    if sig.empty:
        st.caption("Belum ada ramalan.")
        return
    for _, row in sig.drop_duplicates("symbol").iterrows():
        path = json.loads(row["path"] or "[]")
        hist = sig[sig["symbol"] == row["symbol"]].iloc[::-1].tail(72)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=pd.to_datetime(hist["candle_time"]), y=hist["last_close"], name="Harga"))
        if path:
            step = pd.Timedelta(cfg["timeframe"].replace("m", "min"))
            t0 = pd.to_datetime(row["candle_time"])
            fig.add_trace(go.Scatter(x=[t0] + [t0 + step * (i + 1) for i in range(len(path))],
                                     y=[row["last_close"]] + path, name="Ramalan AI", line=dict(dash="dash")))
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=10),
                          title=f"{row['symbol']} — keputusan: {row['action']} ({row['reason']})")
        st.plotly_chart(fig, width="stretch")


# ======================================================================= UJI STRATEGI
def page_backtest():
    st.title("🧪 Uji Strategi di Data Masa Lalu")
    st.caption("Robot berpura-pura trading di masa lalu memakai pengaturan Anda sekarang, "
               "lalu dibandingkan dengan sekadar membeli dan menahan. Tidak ada order sungguhan.")
    pairs = all_pairs(cfg["exchange"], cfg.get("quote", "USDT")) or cfg["symbols"]

    @st.fragment(run_every=3)
    def progress():
        if ctl.backtest_running():
            st.info("⏳ Uji strategi sedang berjalan...")
            st.code(ctl.tail(ctl.BT_LOG, 6))
            if st.button("Batalkan uji"):
                ctl.stop_backtest()
                st.rerun(scope="app")
        elif ctl.BT_PID.exists():
            ctl.BT_PID.unlink(missing_ok=True)
            st.rerun(scope="app")

    if not ctl.backtest_running():
        with st.form("bt"):
            c = st.columns(4)
            sym = c[0].selectbox("Pair", pairs, index=pairs.index(cfg["symbols"][0]) if cfg["symbols"][0] in pairs else 0)
            tf = c[1].selectbox("Timeframe", list(TIMEFRAMES), format_func=TIMEFRAMES.get,
                                index=list(TIMEFRAMES).index(cfg["timeframe"]) if cfg["timeframe"] in TIMEFRAMES else 2)
            n = c[2].number_input("Berapa candle ke belakang", 100, 3000, 500, 50)
            speed = c[3].selectbox("Kecepatan", ["Teliti (lambat)", "Sedang", "Cepat (kasar)"], index=1)
            optim = st.checkbox("🎯 Sekalian cari setelan terbaik otomatis (optimasi)", value=True,
                                help="Mencoba ratusan kombinasi setelan. Hanya butuh beberapa detik tambahan.")
            st.caption("Di komputer tanpa GPU, mode Teliti 500 candle bisa 20–40 menit. Hasil ramalan disimpan, "
                       "jadi uji ulang berikutnya berjalan cepat.")
            if st.form_submit_button("▶️ Mulai uji", type="primary"):
                ctl.start_backtest(sym, tf, int(n), {"Teliti (lambat)": 1, "Sedang": 3, "Cepat (kasar)": 6}[speed],
                                   optimize=optim)
                st.rerun()
    progress()

    files = sorted(BT_DIR.glob("*_ringkasan.txt"), key=lambda p: p.stat().st_mtime, reverse=True) if BT_DIR.exists() else []
    if not files:
        if not ctl.backtest_running():
            out = ctl.tail(ctl.BT_LOG, 15)
            if "Error" in out or "Traceback" in out:
                st.error("Uji terakhir gagal:")
                st.code(out)
        return
    st.subheader("Hasil")
    pick = st.selectbox("Pilih hasil", files, format_func=lambda p: p.name.replace("_ringkasan.txt", ""))
    st.code(pick.read_text(encoding="utf-8"))
    base = str(pick).replace("_ringkasan.txt", "")
    if Path(base + "_equity.csv").exists():
        cv = pd.read_csv(base + "_equity.csv")
        bal = float(cfg["paper"]["starting_balance"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=cv["timestamps"], y=cv["equity"], name="Robot"))
        fig.add_trace(go.Scatter(x=cv["timestamps"], y=bal * cv["close"] / cv["close"].iloc[0],
                                 name="Beli & tahan saja", line=dict(dash="dot")))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
    if Path(base + "_trades.csv").exists():
        with st.expander("Daftar trade"):
            st.dataframe(pd.read_csv(base + "_trades.csv"), hide_index=True, width="stretch")
    optim_section(Path(base + "_optimasi.json"))


def describe(p):
    stop = (f"SL {p['sl_atr_mult']}×ATR / TP {p['tp_atr_mult']}×ATR" if p.get("sl_mode") == "atr"
            else f"SL {p['stop_loss_pct']}% / TP {p['take_profit_pct']}%")
    trail = f"trailing {p['trail_pct']}% (aktif +{p['trail_activate_pct']}%)" if p.get("trailing_on") else "tanpa trailing"
    return (f"beli jika ramalan ≥ {p['min_expected_return_pct']}% & peluang ≥ {p['min_prob_up']:.0%} · {stop} · "
            f"{trail} · {'ikut tren' if p.get('trend_filter') else 'abaikan tren'}")


def optim_section(path: Path):
    if not path.exists():
        return
    res = json.loads(path.read_text())
    st.subheader("🎯 Hasil optimasi setelan")
    st.caption(f"Setelan dicari di periode LATIH ({res['periode_latih'][0][:10]} – {res['periode_latih'][1][:10]}), "
               f"lalu dinilai di periode UJI ({res['periode_uji'][0][:10]} – {res['periode_uji'][1][:10]}) yang tidak "
               "dipakai saat mencari. **Lihat kolom Hasil UJI**: itu gambaran yang lebih jujur. "
               "Setelan yang bagus di latih tapi rugi di uji kemungkinan hanya kebetulan.")
    rows = [("Setelan sekarang", res["setelan_sekarang"])] + [(f"Kandidat #{i}", r) for i, r in enumerate(res["terbaik"], 1)]
    table = pd.DataFrame([{
        "": name, "Hasil LATIH": f"{r['latih']['return_pct']:+.2f}%", "Hasil UJI": f"{r['uji']['return_pct']:+.2f}%",
        "Trade (uji)": r["uji"]["trades"], "Menang (uji)": f"{r['uji']['win_pct']:.0f}%",
        "Penurunan (uji)": f"{r['uji']['max_dd_pct']:.2f}%", "Beli&tahan (uji)": f"{r['uji']['buyhold_pct']:+.2f}%",
        "Setelan": describe(r["params"])} for name, r in rows])
    st.dataframe(table, hide_index=True, width="stretch")
    if not res["terbaik"]:
        st.info("Tidak ada kombinasi yang cukup sering trading di periode latih.")
        return
    c = st.columns([2, 1])
    k = c[0].selectbox("Pilih kandidat untuk dipakai robot", range(1, len(res["terbaik"]) + 1),
                       format_func=lambda i: f"Kandidat #{i} (uji {res['terbaik'][i - 1]['uji']['return_pct']:+.2f}%)")
    chosen = res["terbaik"][k - 1]
    if chosen["uji"]["return_pct"] <= 0:
        c[0].warning("Kandidat ini rugi di periode UJI. Sebaiknya jangan dipakai.")
    if c[1].button("✅ Pakai setelan ini", type="primary", width="stretch"):
        keys = ["min_expected_return_pct", "min_prob_up", "sl_mode", "stop_loss_pct", "take_profit_pct",
                "sl_atr_mult", "tp_atr_mult", "trailing_on", "trail_activate_pct", "trail_pct", "trend_filter"]
        new = json.loads(json.dumps(cfg))
        new["strategy"].update({x: chosen["params"][x] for x in keys if x in chosen["params"]})
        apply_and_restart(new, f"Setelan kandidat #{k} dipakai.")


def page_analysis():
    ui_analysis.page(cfg, q, MODE, all_pairs(cfg["exchange"], cfg.get("quote", "USDT")), TIMEFRAMES)


{"🏠 Beranda": page_home, "📡 Analisa Realtime": page_analysis, "⚙️ Pengaturan Robot": page_settings, "🔑 Akun & Mode": page_account,
 "📊 Riwayat & Grafik": page_history, "🧪 Uji Strategi": page_backtest}[page]()
