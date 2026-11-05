"""Halaman 📡 Analisa Realtime di Panel Kontrol."""
import json
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from .forecast import Signal, build_signal
from .indicators import ema, rsi
from .market import fetch_recent, future_timestamps, make_exchange, tf_ms, to_frame
from .strategy import entry_decision, opt

DIR_STYLE = {"NAIK": ("🟢", "green"), "TURUN": ("🔴", "red"), "SAMPING": ("🟡", "orange")}


@st.cache_resource(show_spinner=False)
def _exchange(name):
    return make_exchange({"exchange": name})


@st.cache_resource(show_spinner=False)
def _forecaster(model_name, tokenizer, n_paths, pred_len):
    from .forecast import KronosForecaster
    return KronosForecaster({"name": model_name, "tokenizer": tokenizer, "device": "auto",
                             "n_paths": n_paths, "pred_len": pred_len, "temperature": 1.0, "top_p": 0.9})


@st.cache_data(ttl=10, show_spinner=False)
def live_candles(name, symbol, tf, n=200):
    """Candle terbaru TERMASUK candle yang sedang berjalan."""
    raw = _exchange(name).fetch_ohlcv(symbol, tf, limit=n)
    return to_frame(raw)


def forecast_now(cfg, symbol, tf):
    m, s = cfg["model"], cfg["strategy"]
    fc = _forecaster(m["name"], m["tokenizer"], int(m["n_paths"]), int(m["pred_len"]))
    ex = _exchange(cfg["exchange"])
    hist = fetch_recent(ex, symbol, tf, int(m["lookback"]))
    y_ts = future_timestamps(hist["timestamps"].iloc[-1], tf_ms(ex, tf), int(m["pred_len"]))
    return build_signal(symbol, hist, fc.paths(hist, y_ts), s["fee_pct"], int(opt(s, "trend_period")))


def signal_from_row(row) -> Signal:
    def js(v):
        try:
            return json.loads(v) if v else []
        except Exception:  # noqa: BLE001
            return []
    return Signal(time=row["candle_time"], symbol=row["symbol"], last_close=row["last_close"],
                  exp_ret_pct=row["exp_ret_pct"], median_ret_pct=row["median_ret_pct"], prob_up=row["prob_up"],
                  pred_high=row["pred_high"], pred_low=row["pred_low"], path=js(row["path"]),
                  path_lo=js(row.get("path_lo")), path_hi=js(row.get("path_hi")),
                  trend_up=bool(row.get("trend_up") if row.get("trend_up") is not None else True),
                  rsi=row.get("rsi") or 50.0, atr_pct=row.get("atr_pct") or 0.0, rr=row.get("rr") or 0.0,
                  score=row.get("score") or 0.0)


def verdict(sig: Signal, s: dict):
    icon, color = DIR_STYLE[sig.direction]
    ok, why = entry_decision(sig, s)
    c = st.columns(4)
    c[0].markdown(f"### {icon} :{color}[{sig.direction}]")
    c[0].caption(f"Ramalan untuk {len(sig.path)} candle ke depan")
    c[1].metric("Perkiraan perubahan", f"{sig.exp_ret_pct:+.2f}%")
    c[2].metric("Peluang naik", f"{sig.prob_up:.0%}")
    c[3].metric("Untung : rugi", f"{sig.rr:.1f} : 1", help="Potensi naik dibanding potensi turun menurut ramalan")
    c = st.columns(4)
    c[0].metric("Potensi naik", f"+{sig.upside_pct:.2f}%")
    c[1].metric("Potensi turun", f"-{sig.downside_pct:.2f}%")
    c[2].metric("Tren", "Naik ↗" if sig.trend_up else "Turun ↘")
    c[3].metric("RSI", f"{sig.rsi:.0f}", help="Di atas 70 = jenuh beli, di bawah 30 = jenuh jual")
    if ok:
        st.success(f"🤖 Jika sekarang, robot akan **BELI** — {why}")
    else:
        st.info(f"🤖 Jika sekarang, robot **menunggu** — {why}")


def chart(df: pd.DataFrame, sig: Signal | None, tf_ms_val: int, title: str):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=df["timestamps"], open=df["open"], high=df["high"], low=df["low"],
                                 close=df["close"], name="Harga", increasing_line_color="#16a34a",
                                 decreasing_line_color="#dc2626"), 1, 1)
    fig.add_trace(go.Scatter(x=df["timestamps"], y=ema(df["close"], 50), name="EMA 50",
                             line=dict(width=1, color="#3b82f6")), 1, 1)
    fig.add_trace(go.Scatter(x=df["timestamps"], y=ema(df["close"], 200), name="EMA 200",
                             line=dict(width=1, color="#a855f7")), 1, 1)
    if sig is not None and sig.path:
        t0 = pd.to_datetime(sig.time)
        step = pd.Timedelta(milliseconds=tf_ms_val)
        xs = [t0] + [t0 + step * (i + 1) for i in range(len(sig.path))]
        if sig.path_lo and sig.path_hi:
            fig.add_trace(go.Scatter(x=xs, y=[sig.last_close] + sig.path_hi, line=dict(width=0),
                                     showlegend=False, hoverinfo="skip"), 1, 1)
            fig.add_trace(go.Scatter(x=xs, y=[sig.last_close] + sig.path_lo, fill="tonexty",
                                     fillcolor="rgba(245,158,11,0.18)", line=dict(width=0),
                                     name="Rentang ramalan (10–90%)"), 1, 1)
        fig.add_trace(go.Scatter(x=xs, y=[sig.last_close] + sig.path, name="Ramalan AI",
                                 line=dict(color="#f59e0b", width=2.5, dash="dash")), 1, 1)
    fig.add_trace(go.Scatter(x=df["timestamps"], y=rsi(df["close"]), name="RSI",
                             line=dict(width=1, color="#64748b")), 2, 1)
    fig.add_hline(y=70, line_dash="dot", line_color="#dc2626", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#16a34a", row=2, col=1)
    fig.update_layout(height=620, margin=dict(l=10, r=10, t=40, b=10), title=title,
                      xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.08))
    fig.update_yaxes(range=[0, 100], row=2, col=1)
    st.plotly_chart(fig, width="stretch")


def page(cfg, q, mode, all_pairs, timeframes):
    st.title("📡 Analisa Realtime")
    st.caption("Grafik harga live dari Tokocrypto + ramalan AI ke mana harga kemungkinan bergerak. "
               "Garis oranye = ramalan tengah, area oranye = rentang kemungkinan.")
    pairs = all_pairs or cfg["symbols"]
    c = st.columns([2, 1.2, 1.3, 1.3])
    sym = c[0].selectbox("Koin", pairs, index=pairs.index(cfg["symbols"][0]) if cfg["symbols"][0] in pairs else 0)
    tf = c[1].selectbox("Timeframe", list(timeframes), format_func=timeframes.get,
                        index=list(timeframes).index(cfg["timeframe"]) if cfg["timeframe"] in timeframes else 2)
    key = f"fc:{sym}:{tf}"
    if c[2].button("🔮 Ramal sekarang", type="primary", width="stretch"):
        with st.spinner("AI sedang meramal... (pertama kali memuat model bisa 1–3 menit)"):
            try:
                st.session_state[key] = (forecast_now(cfg, sym, tf), time.strftime("%H:%M:%S"))
            except Exception as e:  # noqa: BLE001
                st.error(f"Gagal meramal: {e}")
    scan = c[3].button("🔎 Pindai banyak koin", width="stretch")

    tfv = tf_ms(_exchange(cfg["exchange"]), tf)

    @st.fragment(run_every=15)
    def live():
        try:
            df = live_candles(cfg["exchange"], sym, tf)
        except Exception as e:  # noqa: BLE001
            st.error(f"Tidak bisa mengambil data harga: {e}")
            return
        sig, src = None, ""
        if key in st.session_state:
            sig, at = st.session_state[key]
            src = f"ramalan dibuat pukul {at}"
        elif tf == cfg["timeframe"]:
            row = q("SELECT * FROM signals WHERE mode=? AND symbol=? ORDER BY id DESC LIMIT 1", (mode, sym))
            if not row.empty:
                sig = signal_from_row(row.iloc[0].to_dict())
                src = f"ramalan robot terakhir (candle {sig.time})"
        last = df["close"].iloc[-1]
        prev = df["close"].iloc[-2]
        st.metric(f"{sym} sekarang", f"{last:,.6g}", f"{(last / prev - 1) * 100:+.2f}% candle ini")
        if sig is not None:
            verdict(sig, cfg["strategy"])
            st.caption(f"Sumber: {src}. Harga diperbarui otomatis tiap 15 detik.")
        else:
            st.info("Belum ada ramalan untuk koin & timeframe ini. Klik **🔮 Ramal sekarang**.")
        chart(df.tail(150), sig, tfv, f"{sym} · {timeframes.get(tf, tf)}")

    live()

    if scan:
        st.session_state["scan_open"] = True
    if st.session_state.get("scan_open"):
        st.subheader("🔎 Pindai banyak koin")
        pick = st.multiselect("Koin yang dipindai", pairs, default=[x for x in cfg["symbols"] if x in pairs][:6])
        if st.button("Mulai pindai"):
            rows, bar = [], st.progress(0.0, text="Memindai...")
            for i, p in enumerate(pick, 1):
                try:
                    sg = forecast_now(cfg, p, tf)
                    st.session_state[f"fc:{p}:{tf}"] = (sg, time.strftime("%H:%M:%S"))
                    ok, why = entry_decision(sg, cfg["strategy"])
                    rows.append({"Koin": p, "Arah": DIR_STYLE[sg.direction][0] + " " + sg.direction,
                                 "Perkiraan": f"{sg.exp_ret_pct:+.2f}%", "Peluang naik": f"{sg.prob_up:.0%}",
                                 "Untung:rugi": round(sg.rr, 2), "Tren": "naik" if sg.trend_up else "turun",
                                 "RSI": round(sg.rsi), "Skor": round(sg.score, 3),
                                 "Robot": "BELI" if ok else "tunggu", "Alasan": why})
                except Exception as e:  # noqa: BLE001
                    rows.append({"Koin": p, "Alasan": f"gagal: {e}"})
                bar.progress(i / max(1, len(pick)), text=f"Memindai {p}...")
            bar.empty()
            st.session_state["scan_rows"] = rows
        if st.session_state.get("scan_rows"):
            df = pd.DataFrame(st.session_state["scan_rows"])
            if "Skor" in df:
                df = df.sort_values("Skor", ascending=False)
            st.dataframe(df, hide_index=True, width="stretch")
            st.caption("Diurutkan dari sinyal terkuat. Pilih koin di atas untuk melihat grafiknya.")
