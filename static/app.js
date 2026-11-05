/* Robot Trading Kronos — Panel Kontrol (vanilla JS, tanpa build) */
"use strict";

/* ===================================================== utilitas */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TF = { "15m": "15 menit", "30m": "30 menit", "1h": "1 jam", "4h": "4 jam", "1d": "1 hari" };
const TF_SEC = { "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400 };
const C = { amber: "#F2B544", gain: "#2DD4A7", loss: "#FF6B6B", flat: "#9AA6D6", muted: "#8A93B2", line: "#252D48", ink: "#161C31", blue: "#6C8CFF", violet: "#B58CFF" };

function nf(v, d) { return Number(v).toLocaleString("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d }); }
function price(v) {
  if (v == null || isNaN(v)) return "–";
  const a = Math.abs(v);
  return nf(v, a >= 1000 ? 2 : a >= 1 ? 4 : a >= 0.01 ? 5 : 8);
}
function money(v, q = "USDT") { return v == null || isNaN(v) ? "–" : `${nf(v, 2)} ${q}`; }
function signed(v, d = 2, suf = "%") { return v == null || isNaN(v) ? "–" : `${v >= 0 ? "+" : "−"}${nf(Math.abs(v), d)}${suf}`; }
function cls(v) { return v == null ? "" : v >= 0 ? "gain" : "loss"; }
function pct0(v) { return v == null ? "–" : `${Math.round(v * 100)}%`; }
function hhmm(ms) { const d = new Date(ms); return d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }); }
function base(sym) { return String(sym).split("/")[0]; }
function symHtml(sym) { const [b, q] = String(sym).split("/"); return `<span class="sym">${esc(b)}<small>/${esc(q || "")}</small></span>`; }
function dirBadge(d) {
  const m = { NAIK: ["up", "Naik"], TURUN: ["down", "Turun"], SAMPING: ["flat", "Mendatar"] }[d] || ["flat", "–"];
  return `<span class="dir ${m[0]}">${m[1]}</span>`;
}
const ACT_LABEL = { BELI: "Beli", JUAL: "Jual", TAHAN: "Tahan", TUNGGU: "Tunggu", LEWATI: "Lewati", ERROR: "Gagal" };

async function api(path, body, method) {
  const opt = { method: method || (body !== undefined ? "POST" : "GET"), headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opt); } catch { throw new Error("Panel tidak terhubung ke server. Pastikan jendela MULAI masih terbuka."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Gagal (${res.status})`);
  return data;
}

function toast(msg, kind = "ok", ms = 4200) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}

function modal({ title, body = "", confirm = "Lanjutkan", danger = false, input = null, cancel = "Batal" }) {
  return new Promise((resolve) => {
    const m = $("#modal");
    m.innerHTML = `<div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="mt">
      <h3 id="mt">${esc(title)}</h3><div>${body}</div>
      ${input ? `<div class="field" style="margin-top:6px"><label for="mi">${input.label}</label><input id="mi" class="input" autocomplete="off" placeholder="${esc(input.placeholder || "")}"></div>` : ""}
      <div class="modal-actions"><button class="btn ghost" data-x>${esc(cancel)}</button>
      <button class="btn ${danger ? "danger" : "primary"}" data-ok>${esc(confirm)}</button></div></div>`;
    m.hidden = false;
    const done = (v) => { m.hidden = true; m.innerHTML = ""; document.removeEventListener("keydown", key); resolve(v); };
    const key = (e) => { if (e.key === "Escape") done(null); };
    document.addEventListener("keydown", key);
    m.onclick = (e) => { if (e.target === m) done(null); };
    $("[data-x]", m).onclick = () => done(null);
    $("[data-ok]", m).onclick = () => done(input ? $("#mi", m).value : true);
    (input ? $("#mi", m) : $("[data-ok]", m)).focus();
  });
}

async function busy(btn, fn) {
  const html = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${btn.dataset.busy || "Memproses…"}`;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = html; }
}

/* ===================================================== grafik */
function makeChart(el, extra = {}) {
  return LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, textColor: C.muted, fontFamily: getComputedStyle(document.body).fontFamily, fontSize: 12 },
    grid: { vertLines: { color: "rgba(37,45,72,.55)" }, horzLines: { color: "rgba(37,45,72,.55)" } },
    rightPriceScale: { borderColor: C.line },
    timeScale: { borderColor: C.line, timeVisible: true, secondsVisible: false, rightOffset: 4 },
    crosshair: { mode: 1, vertLine: { color: "#5D6688", labelBackgroundColor: "#323C5E" }, horzLine: { color: "#5D6688", labelBackgroundColor: "#323C5E" } },
    localization: { locale: "id-ID", priceFormatter: price },
    ...extra,
  });
}

/* ===================================================== router & siklus halaman */
const S = { status: null, pairs: null };
let current = { timers: [], charts: [], cleanup: [] };

function every(ms, fn) { fn(); const id = setInterval(fn, ms); current.timers.push(id); return id; }
function teardown() {
  current.timers.forEach(clearInterval);
  current.charts.forEach((c) => { try { c.remove(); } catch { /* sudah dihapus */ } });
  current.cleanup.forEach((f) => f());
  current = { timers: [], charts: [], cleanup: [] };
}

const ROUTES = {};
function route() {
  const name = (location.hash.replace("#/", "") || "beranda").split("?")[0];
  const fn = ROUTES[name] || ROUTES.beranda;
  teardown();
  $$(".rail a[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === name));
  const view = $("#view");
  view.innerHTML = "";
  fn(view);
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

async function loadPairs() {
  if (S.pairs) return S.pairs;
  const r = await api("/api/pairs").catch(() => ({ pairs: [] }));
  S.pairs = r.pairs || [];
  return S.pairs;
}

async function refreshStatus() {
  try { S.status = await api("/api/status"); } catch { return null; }
  const s = S.status;
  const dot = s.crashed ? "warn" : s.running ? "" : "off";
  $("#railStatus").innerHTML = `
    <div class="row"><span class="pulse ${dot}"></span>${s.crashed ? "Robot berhenti karena masalah" : s.running ? "Robot menyala" : "Robot mati"}</div>
    <div class="row"><span class="chip ${s.mode === "live" ? "live" : "sim"}">${s.mode === "live" ? "Live · uang sungguhan" : "Simulasi"}</span></div>`;
  return s;
}

/* combobox pencarian koin */
function pairCombo(el, { value, onPick, placeholder = "Cari koin, mis. SOL" }) {
  el.classList.add("combo");
  el.innerHTML = `<input class="input" value="${esc(value || "")}" placeholder="${esc(placeholder)}" aria-label="Pilih koin" autocomplete="off"><div class="combo-list" hidden></div>`;
  const inp = $("input", el), list = $(".combo-list", el);
  let hl = 0, items = [];
  const show = async () => {
    const all = await loadPairs();
    const t = inp.value.trim().toUpperCase();
    items = all.filter((p) => !t || p.includes(t) || t === value).slice(0, 60);
    if (t && t !== value) items.sort((a, b) => (a.startsWith(t) ? -1 : 0) - (b.startsWith(t) ? -1 : 0));
    hl = 0;
    list.innerHTML = items.length ? items.map((p, i) => `<button type="button" data-p="${esc(p)}" class="${i === 0 ? "hl" : ""}">${symHtml(p)}</button>`).join("") : `<div class="empty">Koin tidak ditemukan</div>`;
    list.hidden = false;
  };
  const pick = (p) => { value = p; inp.value = p; list.hidden = true; onPick(p); };
  inp.addEventListener("focus", () => { inp.select(); show(); });
  inp.addEventListener("input", show);
  inp.addEventListener("keydown", (e) => {
    const b = $$("button", list);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); if (!b.length) return;
      hl = (hl + (e.key === "ArrowDown" ? 1 : -1) + b.length) % b.length;
      b.forEach((x, i) => x.classList.toggle("hl", i === hl)); b[hl].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") { e.preventDefault(); if (items[hl]) pick(items[hl]); }
    else if (e.key === "Escape") { list.hidden = true; inp.value = value || ""; inp.blur(); }
  });
  list.addEventListener("mousedown", (e) => { const b = e.target.closest("button[data-p]"); if (b) { e.preventDefault(); pick(b.dataset.p); } });
  inp.addEventListener("blur", () => setTimeout(() => { list.hidden = true; if (!inp.value) inp.value = value || ""; }, 120));
  return { set(v) { value = v; inp.value = v; } };
}

function seg(el, options, value, onChange) {
  el.classList.add("seg");
  el.setAttribute("role", "radiogroup");
  el.innerHTML = Object.entries(options).map(([k, v]) => `<button type="button" role="radio" aria-checked="${k === value}" data-v="${esc(k)}" class="${k === value ? "on" : ""}">${esc(v)}</button>`).join("");
  el.onclick = (e) => {
    const b = e.target.closest("button[data-v]"); if (!b) return;
    $$("button", el).forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
    onChange(b.dataset.v);
  };
}

/* ===================================================== BERANDA */
ROUTES.beranda = (view) => {
  view.innerHTML = `
    <div id="crash"></div>
    <section class="control" id="control" aria-live="polite"></section>
    <section class="kpis" id="kpis"></section>
    <div class="grid cols-main">
      <div class="stack">
        <section class="panel"><div class="panel-title">Perkembangan total aset <small id="eqNote"></small></div><div class="chart md" id="eqChart"></div><div id="eqEmpty"></div></section>
        <section class="panel"><div class="panel-title">Posisi terbuka <span id="sellAllWrap"></span></div><div id="positions"></div></section>
      </div>
      <div class="stack">
        <section class="panel"><div class="panel-title">Keputusan terakhir robot <small>per koin</small></div><div class="radar" id="radar"></div></section>
        <section class="panel"><div class="panel-title">Aktivitas</div><div class="feed" id="feed"></div></section>
      </div>
    </div>`;

  const chart = makeChart($("#eqChart"), { timeScale: { borderColor: C.line, timeVisible: true } });
  current.charts.push(chart);
  const eqSeries = chart.addAreaSeries({ lineColor: C.flat, topColor: "rgba(154,166,214,.28)", bottomColor: "rgba(154,166,214,0)", lineWidth: 2, priceLineVisible: false });
  let eqLen = -1;

  const renderControl = (s) => {
    if (!s) return;
    const el = $("#control");
    el.className = `control ${s.running ? "" : "off"} ${s.mode === "live" ? "live" : ""}`;
    const step = (TF_SEC[s.timeframe] || 3600) * 1000;
    const now = Date.now() + ((s.server_time || Date.now()) - Date.now());
    let dial = `<div class="center"><span>robot<b>mati</b></span></div>`, frac = 0;
    let title = "Robot sedang mati", sub = "Nyalakan robot agar mulai memantau pasar dan trading otomatis. Posisi yang masih terbuka tidak dijaga selama robot mati.";
    if (s.running) {
      if (s.state === "memuat model") { title = "Menyiapkan otak AI…"; sub = "Model Kronos sedang dimuat. Pertama kali bisa beberapa menit karena perlu diunduh."; dial = `<div class="center"><span class="spinner"></span></div>`; }
      else if (s.state === "meramal") { title = "Sedang meramal harga…"; sub = "Robot membaca candle terbaru, meramal, lalu memutuskan beli, tahan, atau jual."; dial = `<div class="center"><span class="spinner"></span></div>`; frac = 1; }
      else {
        title = s.paused ? "Robot menjaga posisi, beli baru dijeda" : "Robot sedang memantau pasar";
        const left = Math.max(0, (s.next_run || now) - now);
        frac = 1 - Math.min(1, left / step);
        const mins = Math.floor(left / 60000), secs = Math.floor((left % 60000) / 1000);
        dial = `<div class="center"><span>ramalan<b>${mins >= 60 ? Math.floor(mins / 60) + "j " + (mins % 60) + "m" : mins + ":" + String(secs).padStart(2, "0")}</b></span></div>`;
        sub = `Ramalan berikutnya pukul ${s.next_run ? hhmm(s.next_run) : "–"}. Stop-loss, take-profit, dan trailing stop dijaga setiap menit.`;
      }
    }
    const R = 32, L = 2 * Math.PI * R;
    el.innerHTML = `
      <div class="dial" aria-hidden="true"><svg viewBox="0 0 74 74"><circle class="track" cx="37" cy="37" r="${R}" fill="none" stroke-width="5"/>
        <circle class="prog" cx="37" cy="37" r="${R}" fill="none" stroke-width="5" stroke-linecap="round" stroke-dasharray="${L}" stroke-dashoffset="${L * (1 - frac)}"/></svg>${dial}</div>
      <div><h2><span class="pulse ${s.running ? (s.paused ? "warn" : "") : "off"}"></span>&nbsp; ${title}</h2>
        <div class="sub">${sub}</div>
        <div class="chips"><span class="chip ${s.mode === "live" ? "live" : "sim"}">${s.mode === "live" ? "Live · uang sungguhan" : "Simulasi · uang virtual"}</span>
          <span class="chip">Setiap ${TF[s.timeframe] || s.timeframe}</span>
          ${s.symbols.map((x) => `<span class="chip">${esc(base(x))}</span>`).join("")}</div></div>
      <div class="control-actions">
        ${s.running ? `<button class="btn danger lg" id="stopBtn" data-busy="Mematikan…"><svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>Matikan robot</button>`
                    : `<button class="btn go lg" id="startBtn" data-busy="Menyalakan…"><svg viewBox="0 0 24 24"><path d="M7 5v14l11-7z" fill="currentColor"/></svg>Nyalakan robot</button>`}
        <label class="switch"><input type="checkbox" id="pause" ${s.paused ? "checked" : ""}><span class="knob"></span><span class="txt"><b>Jeda beli baru</b><span>Posisi yang ada tetap dijaga</span></span></label>
      </div>`;
    $("#startBtn")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (s.mode === "live") {
        const ok = await modal({ title: "Nyalakan robot di mode Live?", body: `<p>Robot akan membeli dan menjual dengan <b>uang sungguhan</b> di akun Tokocrypto Anda.</p>`, confirm: "Ya, nyalakan", danger: true });
        if (!ok) return;
      }
      try { await api("/api/bot/start", {}); toast("Robot dinyalakan."); } catch (err) { toast(err.message, "err"); }
      await tick();
    }));
    $("#stopBtn")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
      const ok = await modal({ title: "Matikan robot?", body: `<p>Posisi yang masih terbuka <b>tidak ikut dijual</b> dan tidak dijaga stop-loss selama robot mati.</p>`, confirm: "Matikan robot", danger: true });
      if (!ok) return;
      try { await api("/api/bot/stop", {}); toast("Robot dimatikan."); } catch (err) { toast(err.message, "err"); }
      await tick();
    }));
    $("#pause").addEventListener("change", async (e) => {
      try { await api("/api/bot/pause", { value: e.target.checked }); toast(e.target.checked ? "Beli baru dijeda." : "Robot boleh membeli lagi.", "info"); }
      catch (err) { toast(err.message, "err"); e.target.checked = !e.target.checked; }
    });
    const crash = $("#crash");
    crash.innerHTML = s.crashed ? `<div class="alert err"><div style="flex:1"><b>Robot berhenti karena ada masalah.</b> Baca pesan di bawah, perbaiki penyebabnya, lalu nyalakan lagi.<pre class="log">${esc(s.crash_log || "(tidak ada pesan)")}</pre></div><button class="btn sm" id="dismiss">Tutup</button></div>` : "";
    $("#dismiss")?.addEventListener("click", async () => { await api("/api/bot/dismiss-crash", {}); tick(); });
  };

  const renderOverview = (o) => {
    const q = o.quote;
    $("#kpis").innerHTML = `
      <div class="kpi big"><div class="label">Total aset</div><div class="value num">${money(o.equity, q)}</div>
        <div class="delta ${cls(o.equity_change_pct)}">${o.equity_change_pct == null ? "&nbsp;" : signed(o.equity_change_pct) + " sejak awal"}</div></div>
      <div class="kpi"><div class="label">Untung/rugi hari ini</div><div class="value num ${cls(o.pnl_today)}">${signed(o.pnl_today, 2, "")}</div><div class="delta muted">${q}</div></div>
      <div class="kpi"><div class="label">Untung/rugi total</div><div class="value num ${cls(o.pnl_total)}">${signed(o.pnl_total, 2, "")}</div><div class="delta muted">${q}</div></div>
      <div class="kpi"><div class="label">Posisi terbuka</div><div class="value num">${o.positions.length} <span class="muted" style="font-size:16px">/ ${o.max_positions}</span></div><div class="delta muted">maksimal</div></div>
      <div class="kpi"><div class="label">Trade menang</div><div class="value num">${o.win_pct == null ? "–" : Math.round(o.win_pct) + "%"}</div><div class="delta muted">dari ${o.trades} trade</div></div>`;

    if (o.equity_series.length !== eqLen) {
      eqSeries.setData(o.equity_series);
      if (eqLen <= 0) chart.timeScale().fitContent();
      eqLen = o.equity_series.length;
    }
    $("#eqChart").style.display = o.equity_series.length > 1 ? "" : "none";
    $("#eqEmpty").innerHTML = o.equity_series.length > 1 ? "" : `<div class="empty"><b>Belum ada catatan aset</b>Grafik muncul setelah robot menyala beberapa candle.</div>`;
    $("#eqNote").textContent = o.mode === "live" ? "saldo USDT di akun + nilai posisi" : "saldo virtual + nilai posisi";

    $("#sellAllWrap").innerHTML = o.positions.length > 1 ? `<button class="btn sm danger" id="sellAll">Jual semua</button>` : "";
    $("#positions").innerHTML = o.positions.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Koin</th><th class="r">Harga beli</th><th class="r">Sekarang</th><th class="r">Untung/rugi</th><th class="r">Batas jual</th><th>Dibeli</th><th></th></tr></thead><tbody>
      ${o.positions.map((p) => `<tr><td>${symHtml(p.symbol)}</td><td class="r num">${price(p.entry_price)}</td><td class="r num">${price(p.price_now)}</td>
        <td class="r num ${cls(p.pnl_pct_now)}"><b>${signed(p.pnl_pct_now)}</b><br><small>${signed(p.pnl_now, 2, " " + q)}</small></td>
        <td class="r num"><small class="loss">${p.sl ? price(p.sl) : "–"}</small><br><small class="gain">${p.tp ? price(p.tp) : "–"}</small></td>
        <td class="muted">${esc(String(p.entry_time).slice(5, 16))}</td>
        <td class="r"><button class="btn sm" data-sell="${p.id}" data-sym="${esc(p.symbol)}">Jual</button></td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty"><b>Belum ada posisi</b>Robot membeli otomatis saat ramalannya cukup kuat.</div>`;
    $$("[data-sell]").forEach((b) => b.addEventListener("click", async () => {
      const ok = await modal({ title: `Jual ${base(b.dataset.sym)} sekarang?`, body: `<p>Posisi dijual dengan harga pasar saat ini.</p>`, confirm: "Jual sekarang", danger: true });
      if (!ok) return;
      busy(b, async () => { try { const r = await api("/api/positions/sell", { ids: [Number(b.dataset.sell)] }); toast(r.message); } catch (e) { toast(e.message, "err"); } loadOverview(); });
    }));
    $("#sellAll")?.addEventListener("click", async (e) => {
      const ok = await modal({ title: "Jual semua posisi?", body: `<p>${o.positions.length} posisi akan dijual dengan harga pasar saat ini.</p>`, confirm: "Jual semua", danger: true });
      if (!ok) return;
      busy(e.currentTarget, async () => { try { const r = await api("/api/positions/sell", { ids: ["ALL"] }); toast(r.message); } catch (err) { toast(err.message, "err"); } loadOverview(); });
    });

    $("#radar").innerHTML = o.decisions.length ? o.decisions.map((d) => `
      <a class="radar-item" href="#/analisa?${encodeURIComponent(d.symbol)}" style="text-decoration:none">
        <div class="top">${symHtml(d.symbol)} ${dirBadge(d.direction)}</div>
        <div><span class="act ${esc(d.action)}">${ACT_LABEL[d.action] || esc(d.action)}</span></div>
        <div class="why">Ramalan <b class="${cls(d.exp_ret_pct)}">${signed(d.exp_ret_pct)}</b>, peluang naik <b>${pct0(d.prob_up)}</b>. ${esc(d.reason || "")}</div>
        <div class="meter" title="Peluang naik ${pct0(d.prob_up)}"><i style="width:${Math.round((d.prob_up || 0) * 100)}%"></i></div></a>`).join("")
      : `<div class="empty"><b>Belum ada keputusan</b>Muncul setelah robot meramal untuk pertama kali.</div>`;

    $("#feed").innerHTML = o.events.length ? o.events.map((e) => `<div><time>${esc(String(e.time).slice(11, 16))}</time><span class="${esc(e.level)}">${esc(e.message)}</span></div>`).join("")
      : `<div class="empty" style="grid-template-columns:1fr">Belum ada aktivitas.</div>`;
  };

  const loadOverview = async () => { try { renderOverview(await api("/api/overview")); } catch (e) { /* koneksi sesaat */ } };
  const tick = async () => renderControl(await refreshStatus());
  every(4000, tick);
  every(7000, loadOverview);
};

/* ===================================================== ANALISA REALTIME */
ROUTES.analisa = async (view) => {
  const st = S.status || (await refreshStatus()) || { symbols: ["BTC/USDT"], timeframe: "1h" };
  const fromHash = decodeURIComponent((location.hash.split("?")[1] || ""));
  const A = { sym: fromHash || st.symbols[0], tf: st.timeframe, signal: null, fitted: false, scanJob: null, scanPick: [...st.symbols] };

  view.innerHTML = `
    <div class="page-head"><div><h1>Analisa realtime</h1><p>Harga live dari Tokocrypto dan ke mana AI memperkirakan harga bergerak. Area amber adalah rentang kemungkinan, garis tebal adalah perkiraan tengah.</p></div></div>
    <div class="toolbar" style="margin-bottom:16px">
      <div id="symPick"></div><div id="tfPick"></div><div class="grow"></div>
      <button class="btn" id="scanOpen"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>Pindai banyak koin</button>
      <button class="btn primary" id="fcBtn" data-busy="AI sedang meramal…"><svg viewBox="0 0 24 24"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></svg>Ramal sekarang</button>
    </div>
    <div class="grid cols-main">
      <section class="panel">
        <div class="price-head"><span class="sym" id="phSym" style="font-size:18px"></span><span class="px num" id="phPx">–</span><span class="num" id="phChg"></span><span class="muted" id="phTime" style="margin-left:auto;font-size:13px"></span></div>
        <div class="chart" id="mainChart"></div>
        <div class="chart sm" id="rsiChart"></div>
        <div class="legend"><span><i style="background:${C.amber}"></i>Ramalan AI</span><span><i style="background:rgba(242,181,68,.35);height:8px"></i>Rentang 10–90%</span><span><i style="background:${C.blue}"></i>EMA 50</span><span><i style="background:${C.violet}"></i>EMA 200 (tren)</span><span><i style="background:${C.muted}"></i>RSI</span></div>
      </section>
      <section class="panel" id="verdict"></section>
    </div>
    <section class="panel" id="scanPanel" style="margin-top:18px" hidden></section>`;

  /* grafik utama */
  const main = makeChart($("#mainChart"));
  const rsiC = makeChart($("#rsiChart"), { localization: { locale: "id-ID", priceFormatter: (v) => Math.round(v) }, timeScale: { visible: false, borderColor: C.line }, rightPriceScale: { borderColor: C.line, scaleMargins: { top: .1, bottom: .1 } } });
  current.charts.push(main, rsiC);
  const vol = main.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
  main.priceScale("vol").applyOptions({ scaleMargins: { top: .82, bottom: 0 } });
  const coneHi = main.addAreaSeries({ lineColor: "rgba(242,181,68,.55)", lineWidth: 1, lineStyle: 2, topColor: "rgba(242,181,68,.22)", bottomColor: "rgba(242,181,68,.22)", lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
  const coneLo = main.addAreaSeries({ lineColor: "rgba(242,181,68,.55)", lineWidth: 1, lineStyle: 2, topColor: C.ink, bottomColor: C.ink, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
  const candles = main.addCandlestickSeries({ upColor: C.gain, downColor: C.loss, borderVisible: false, wickUpColor: C.gain, wickDownColor: C.loss });
  const e50 = main.addLineSeries({ color: C.blue, lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
  const e200 = main.addLineSeries({ color: C.violet, lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
  const fc = main.addLineSeries({ color: C.amber, lineWidth: 3, lastValueVisible: true, priceLineVisible: false, title: "AI" });
  const rsiS = rsiC.addLineSeries({ color: C.muted, lineWidth: 1.5, priceLineVisible: false });
  [70, 30].forEach((v) => rsiS.createPriceLine({ price: v, color: v === 70 ? "rgba(255,107,107,.5)" : "rgba(45,212,167,.5)", lineStyle: 2, lineWidth: 1, axisLabelVisible: true }));
  main.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) rsiC.timeScale().setVisibleLogicalRange(r); });

  let step = TF_SEC[A.tf];
  const drawForecast = () => {
    const s = A.signal;
    if (!s || !s.path || !s.path.length) { [coneHi, coneLo, fc].forEach((x) => x.setData([])); return; }
    const t = (i) => s.t0 + step * i;
    fc.setData([{ time: t(0), value: s.last_close }, ...s.path.map((v, i) => ({ time: t(i + 1), value: v }))]);
    if (s.path_hi?.length && s.path_lo?.length) {
      coneHi.setData([{ time: t(0), value: s.last_close }, ...s.path_hi.map((v, i) => ({ time: t(i + 1), value: v }))]);
      coneLo.setData([{ time: t(0), value: s.last_close }, ...s.path_lo.map((v, i) => ({ time: t(i + 1), value: v }))]);
    } else { coneHi.setData([]); coneLo.setData([]); }
  };

  const loadCandles = async () => {
    try {
      const d = await api(`/api/candles?symbol=${encodeURIComponent(A.sym)}&tf=${A.tf}&limit=300`);
      step = d.step;
      candles.setData(d.candles);
      vol.setData(d.volume.map((v) => ({ time: v.time, value: v.value, color: v.up ? "rgba(45,212,167,.25)" : "rgba(255,107,107,.25)" })));
      e50.setData(d.ema50); e200.setData(d.ema200); rsiS.setData(d.rsi);
      drawForecast();
      if (!A.fitted) { main.timeScale().setVisibleLogicalRange({ from: d.candles.length - 110, to: d.candles.length + 16 }); A.fitted = true; }
      const chg = (d.last / d.prev_close - 1) * 100;
      $("#phSym").innerHTML = symHtml(A.sym);
      $("#phPx").textContent = price(d.last);
      $("#phChg").innerHTML = `<span class="${cls(chg)}">${signed(chg)}</span> <span class="muted">candle ini</span>`;
      $("#phTime").textContent = `diperbarui ${new Date().toLocaleTimeString("id-ID")}`;
    } catch (e) {
      $("#phTime").innerHTML = `<span class="loss">${esc(e.message)}</span>`;
    }
  };

  const gauge = (p) => {
    const a = Math.PI * (1 - p), x = 60 + 48 * Math.cos(a), y = 60 - 48 * Math.sin(a);
    const col = p >= .6 ? C.gain : p <= .4 ? C.loss : C.amber;
    return `<div class="gauge" title="Peluang naik"><svg viewBox="0 0 120 66"><path d="M12 60a48 48 0 0 1 96 0" fill="none" stroke="${C.line}" stroke-width="9" stroke-linecap="round"/>
      <path d="M12 60A48 48 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}" fill="none" stroke="${col}" stroke-width="9" stroke-linecap="round"/></svg><div class="val num">${pct0(p)}</div></div>`;
  };

  const renderVerdict = () => {
    const s = A.signal, el = $("#verdict");
    if (!s) {
      el.innerHTML = `<div class="panel-title">Arah prediksi</div><div class="empty"><b>Belum ada ramalan untuk ${esc(base(A.sym))} · ${TF[A.tf]}</b>Klik <b>Ramal sekarang</b> agar AI memperkirakan arah harga berikutnya.</div>`;
      return;
    }
    const d = { NAIK: ["up", "Naik"], TURUN: ["down", "Turun"], SAMPING: ["flat", "Mendatar"] }[s.direction];
    const hours = (s.path.length * step) / 3600;
    const horizon = hours >= 24 ? `${nf(hours / 24, hours % 24 ? 1 : 0)} hari` : `${nf(hours, hours % 1 ? 1 : 0)} jam`;
    el.innerHTML = `
      <div class="panel-title">Arah prediksi <small>${esc(s.source)}</small></div>
      <div class="verdict">
        <div class="verdict-head">${gauge(s.prob_up)}<div><div class="big ${d[0]}">${d[1]}</div>
          <div class="muted" style="margin-top:6px">Perkiraan <b class="${cls(s.exp_ret_pct)}">${signed(s.exp_ret_pct)}</b> dalam ${horizon}<br>Peluang naik ${pct0(s.prob_up)} dari ${s.path_hi?.length ? "semua" : ""} skenario AI</div></div></div>
        <div class="facts">
          <div><span>Potensi naik</span><b class="num gain">${signed(s.upside_pct)}</b></div>
          <div><span>Potensi turun</span><b class="num loss">${signed(-s.downside_pct)}</b></div>
          <div><span>Untung : rugi</span><b class="num">${nf(s.rr, 1)} : 1</b></div>
          <div><span>Tren besar</span><b class="${s.trend_up ? "gain" : "loss"}">${s.trend_up ? "Naik" : "Turun"}</b></div>
          <div><span>RSI</span><b class="num">${Math.round(s.rsi)}</b> <small class="muted">${s.rsi > 70 ? "jenuh beli" : s.rsi < 30 ? "jenuh jual" : "wajar"}</small></div>
          <div><span>Volatilitas per candle</span><b class="num">${nf(s.atr_pct, 2)}%</b></div>
        </div>
        <div class="decision ${s.would_buy ? "buy" : "wait"}"><div><b>${s.would_buy ? "Robot akan membeli" : "Robot akan menunggu"}</b><span class="muted">${esc(s.decision)}</span></div></div>
        <div class="muted" style="font-size:13px">Kisaran ramalan: ${price(s.pred_low)} – ${price(s.pred_high)}. Ramalan adalah perkiraan, bukan kepastian.</div>
      </div>`;
  };

  const loadSignal = async () => {
    try { A.signal = (await api(`/api/signal?symbol=${encodeURIComponent(A.sym)}&tf=${A.tf}`)).signal; } catch { A.signal = null; }
    renderVerdict(); drawForecast();
  };

  const switchTo = () => { A.fitted = false; A.signal = null; renderVerdict(); loadCandles(); loadSignal(); history.replaceState(null, "", `#/analisa?${encodeURIComponent(A.sym)}`); };
  const combo = pairCombo($("#symPick"), { value: A.sym, onPick: (p) => { A.sym = p; switchTo(); } });
  seg($("#tfPick"), TF, A.tf, (v) => { A.tf = v; switchTo(); });

  $("#fcBtn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try { A.signal = (await api("/api/forecast", { symbol: A.sym, tf: A.tf })).signal; renderVerdict(); drawForecast(); toast(`Ramalan ${base(A.sym)} selesai.`); }
    catch (err) { toast(err.message, "err", 7000); }
  }));

  /* pindai */
  const scanPanel = $("#scanPanel");
  const renderScan = (job) => {
    const rows = job?.rows || [];
    scanPanel.innerHTML = `
      <div class="panel-title">Pindai banyak koin <small>diurutkan dari sinyal terkuat</small></div>
      <div class="toolbar" style="margin-bottom:12px"><div id="scanAdd"></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap" id="scanChips">${A.scanPick.map((p) => `<span class="chip">${esc(base(p))}<button class="btn ghost sm" style="padding:0 2px" data-rm="${esc(p)}" aria-label="Hapus ${esc(p)}">✕</button></span>`).join("")}</div>
        <div class="grow"></div><button class="btn primary" id="scanGo" ${job && !job.finished ? "disabled" : ""}>Mulai pindai ${A.scanPick.length} koin</button></div>
      ${job && !job.finished ? `<div class="progress"><i style="width:${(job.done / job.total) * 100}%"></i></div><p class="muted" style="font-size:13px">Meramal ${esc(job.current)}… (${job.done}/${job.total}). Pertama kali memuat model bisa 1–3 menit.</p>` : ""}
      ${rows.length ? `<div class="table-wrap" style="margin-top:8px"><table><thead><tr><th>Koin</th><th>Arah</th><th class="r">Perkiraan</th><th class="r">Peluang naik</th><th class="r">Untung:rugi</th><th>Tren</th><th class="r">RSI</th><th>Robot</th><th></th></tr></thead><tbody>
        ${rows.map((r) => r.error ? `<tr><td>${symHtml(r.symbol)}</td><td colspan="8" class="loss">${esc(r.error)}</td></tr>` : `<tr><td>${symHtml(r.symbol)}</td><td>${dirBadge(r.direction)}</td><td class="r num ${cls(r.exp_ret_pct)}">${signed(r.exp_ret_pct)}</td><td class="r num">${pct0(r.prob_up)}</td><td class="r num">${nf(r.rr, 1)}</td><td class="${r.trend_up ? "gain" : "loss"}">${r.trend_up ? "Naik" : "Turun"}</td><td class="r num">${Math.round(r.rsi)}</td><td><span class="act ${r.would_buy ? "BELI" : ""}">${r.would_buy ? "Beli" : "Tunggu"}</span></td><td class="r"><button class="btn sm" data-view="${esc(r.symbol)}">Lihat grafik</button></td></tr>`).join("")}
        </tbody></table></div>` : ""}`;
    pairCombo($("#scanAdd"), { value: "", placeholder: "Tambah koin…", onPick: (p) => { if (!A.scanPick.includes(p)) A.scanPick.push(p); renderScan(job); } });
    $$("[data-rm]", scanPanel).forEach((b) => b.onclick = () => { A.scanPick = A.scanPick.filter((x) => x !== b.dataset.rm); renderScan(job); });
    $$("[data-view]", scanPanel).forEach((b) => b.onclick = () => { A.sym = b.dataset.view; combo.set(A.sym); switchTo(); window.scrollTo({ top: 0, behavior: "smooth" }); });
    $("#scanGo").onclick = async () => {
      if (!A.scanPick.length) return toast("Tambahkan minimal satu koin.", "err");
      try {
        const { job: id } = await api("/api/scan", { symbols: A.scanPick, tf: A.tf });
        const poll = setInterval(async () => {
          try { const j = await api(`/api/scan/${id}`); renderScan(j); if (j.finished) { clearInterval(poll); toast("Pemindaian selesai."); } }
          catch { clearInterval(poll); }
        }, 1500);
        current.timers.push(poll);
        renderScan({ done: 0, total: A.scanPick.length, current: A.scanPick[0], rows: [], finished: false });
      } catch (err) { toast(err.message, "err"); }
    };
  };
  $("#scanOpen").onclick = () => { scanPanel.hidden = false; renderScan(null); scanPanel.scrollIntoView({ behavior: "smooth" }); };

  renderVerdict();
  loadSignal();
  every(10000, loadCandles);
  every(30000, loadSignal);
};

/* ===================================================== PENGATURAN */
const PRESETS = {
  hati: { label: "Hati-hati", desc: "Jarang beli, sinyal harus sangat kuat", v: [1.2, 0.75] },
  normal: { label: "Normal", desc: "Seimbang", v: [0.8, 0.65] },
  agresif: { label: "Agresif", desc: "Lebih sering beli, risiko lebih besar", v: [0.4, 0.55] },
  kustom: { label: "Atur sendiri", desc: "Tentukan angkanya", v: null },
};
const MODEL_SIZES = { ringan: ["Ringan", "Paling cepat, cocok untuk laptop biasa"], sedang: ["Sedang", "Seimbang, disarankan"], berat: ["Berat", "Paling teliti, butuh komputer kuat"] };

ROUTES.pengaturan = async (view) => {
  view.innerHTML = `<div class="page-head"><div><h1>Pengaturan robot</h1><p>Atur koin, modal, kapan robot membeli, dan kapan menjual. Jika robot sedang menyala, ia otomatis dinyalakan ulang setelah Anda menyimpan.</p></div></div><div class="panel"><div class="empty"><span class="spinner"></span></div></div>`;
  let saved, d;
  try { saved = await api("/api/config"); } catch (e) { view.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
  d = structuredClone(saved);
  const preset = () => Object.keys(PRESETS).find((k) => PRESETS[k].v && PRESETS[k].v[0] === d.strategy.min_expected_return_pct && PRESETS[k].v[1] === d.strategy.min_prob_up) || "kustom";
  let presetKey = preset();

  const num = (path, { unit = "", step = "any", min = 0, max, label, hint = "" }) => `
    <div class="field"><label for="f-${path}">${label}</label>
      <div class="input-group"><input class="input num" id="f-${path}" type="number" inputmode="decimal" step="${step}" min="${min}" ${max != null ? `max="${max}"` : ""} data-path="${path}">${unit ? `<span class="unit">${unit}</span>` : ""}</div>
      ${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
  const sw = (path, label, hint) => `<label class="switch"><input type="checkbox" data-path="${path}"><span class="knob"></span><span class="txt"><b>${label}</b><span>${hint}</span></span></label>`;

  view.innerHTML = `
    <div class="page-head"><div><h1>Pengaturan robot</h1><p>Atur koin, modal, kapan robot membeli, dan kapan menjual. Jika robot sedang menyala, ia otomatis dinyalakan ulang setelah Anda menyimpan.</p></div></div>
    <div class="panel">
      <div class="setting-group"><div><h3>Koin dan waktu</h3><div class="desc">Koin yang dipantau dan seberapa sering robot mengambil keputusan.</div></div>
        <div class="stack" style="gap:16px">
          <div class="field"><span class="label">Koin yang diperdagangkan</span><div class="toolbar"><div id="symAdd"></div><div id="symChips" style="display:flex;gap:6px;flex-wrap:wrap"></div></div><div class="hint">Semakin banyak koin, semakin lama robot meramal setiap candle.</div></div>
          <div class="field"><span class="label">Robot mengambil keputusan setiap</span><div id="tfSeg"></div></div>
        </div></div>

      <div class="setting-group"><div><h3>Modal dan batas</h3><div class="desc">Berapa uang yang dipakai dan kapan robot berhenti membeli.</div></div>
        <div class="stack" style="gap:14px"><div class="fields">
          ${num("risk.order_size_quote", { label: "Modal per posisi", unit: saved.quote, step: 1, min: 1 })}
          ${num("risk.max_open_positions", { label: "Maksimal posisi terbuka", unit: "posisi", step: 1, min: 1, max: 50 })}
          ${num("risk.max_daily_loss_quote", { label: "Berhenti beli jika rugi hari ini", unit: saved.quote, step: 1 })}
        </div><div class="callout" id="capNote"></div></div></div>

      <div class="setting-group"><div><h3>Kapan membeli</h3><div class="desc">Seberapa yakin robot harus sebelum membeli, plus penyaring tambahan.</div></div>
        <div class="stack" style="gap:16px">
          <div class="choice-cards" id="presets">${Object.entries(PRESETS).map(([k, p]) => `<button type="button" class="choice" data-preset="${k}"><b>${p.label}</b><span>${p.desc}</span></button>`).join("")}</div>
          <div class="fields" id="customBox">
            ${num("strategy.min_expected_return_pct", { label: "Minimal ramalan kenaikan", unit: "%", step: 0.1 })}
            <div class="field"><label for="f-prob">Minimal peluang naik</label><div class="range-row"><input id="f-prob" type="range" min="0.5" max="0.95" step="0.05" data-path="strategy.min_prob_up"><output id="probOut" class="num"></output></div></div>
          </div>
          <div class="fields">
            ${sw("strategy.trend_filter", "Hanya beli saat tren naik", "Harga di atas garis tren EMA dan garisnya menanjak")}
            <div class="field"><label for="f-rsi">Jangan beli jika RSI di atas</label><div class="range-row"><input id="f-rsi" type="range" min="50" max="100" step="1" data-path="strategy.rsi_max"><output id="rsiOut" class="num"></output></div><div class="hint">RSI tinggi berarti harga sudah naik terlalu cepat. 100 = abaikan.</div></div>
            ${num("strategy.min_rr", { label: "Minimal rasio untung : rugi", unit: "×", step: 0.1, hint: "Potensi naik harus sekian kali potensi turun. 0 = abaikan." })}
          </div></div></div>

      <div class="setting-group"><div><h3>Kapan menjual</h3><div class="desc">Batas rugi, target untung, dan cara mengunci untung.</div></div>
        <div class="stack" style="gap:16px">
          <div class="field"><span class="label">Cara menentukan batas jual</span><div id="slSeg"></div></div>
          <div class="fields" id="pctBox">
            ${num("strategy.stop_loss_pct", { label: "Stop-loss: jual jika rugi", unit: "%", step: 0.1, min: 0.1 })}
            ${num("strategy.take_profit_pct", { label: "Take-profit: jual jika untung", unit: "%", step: 0.1, min: 0.1 })}
          </div>
          <div class="fields" id="atrBox">
            ${num("strategy.sl_atr_mult", { label: "Stop-loss", unit: "× volatilitas", step: 0.5, min: 0.5 })}
            ${num("strategy.tp_atr_mult", { label: "Take-profit", unit: "× volatilitas", step: 0.5, min: 0.5 })}
          </div>
          <div class="fields">
            ${sw("strategy.trailing_on", "Trailing stop", "Saat harga naik, batas jual ikut naik agar untung tidak hilang")}
            ${num("strategy.trail_activate_pct", { label: "Aktif setelah untung", unit: "%", step: 0.1, min: 0.1 })}
            ${num("strategy.trail_pct", { label: "Jual jika turun dari puncak", unit: "%", step: 0.1, min: 0.1 })}
          </div>
          <div class="fields">${num("strategy.max_hold_candles", { label: "Jual paksa setelah", unit: "candle", step: 1, min: 1 })}</div>
          <div class="callout" id="exitNote"></div></div></div>

      <div class="setting-group"><div><h3>Otak AI</h3><div class="desc">Model Kronos yang lebih besar lebih teliti tetapi lebih lambat.</div></div>
        <div class="choice-cards" id="models">${Object.entries(MODEL_SIZES).map(([k, m]) => `<button type="button" class="choice" data-model="${k}"><b>${m[0]}</b><span>${m[1]}</span></button>`).join("")}</div></div>

      <div class="setting-group"><div><h3>Lanjutan</h3><div class="desc">Biarkan saja jika ragu.</div></div>
        <div class="fields">
          ${num("strategy.fee_pct", { label: "Biaya trading per transaksi", unit: "%", step: 0.01 })}
          ${num("paper.starting_balance", { label: "Saldo awal simulasi", unit: saved.quote, step: 1, min: 1 })}
          ${num("risk.max_order_size_quote", { label: "Batas keras per order", unit: saved.quote, step: 1, min: 1 })}
          ${num("model.n_paths", { label: "Jumlah skenario ramalan", unit: "skenario", step: 1, min: 2, max: 50 })}
          ${num("model.pred_len", { label: "Meramal ke depan", unit: "candle", step: 1, min: 2, max: 120 })}
          ${num("strategy.cooldown_candles", { label: "Jeda setelah jual", unit: "candle", step: 1 })}
          ${num("strategy.exit_prob_up_below", { label: "Jual jika peluang naik di bawah", step: 0.05, max: 0.5, hint: "0,35 berarti 35%" })}
        </div></div>
    </div>
    <div class="savebar" id="savebar" hidden><span>Ada perubahan yang belum disimpan.</span><span style="display:flex;gap:8px"><button class="btn ghost" id="revert">Batalkan</button><button class="btn primary" id="save" data-busy="Menyimpan…">Simpan perubahan</button></span></div>`;

  const get = (p) => p.split(".").reduce((o, k) => o?.[k], d);
  const set = (p, v) => { const ks = p.split("."); const last = ks.pop(); ks.reduce((o, k) => o[k], d)[last] = v; };
  const fill = () => {
    $$("[data-path]").forEach((el) => { const v = get(el.dataset.path); if (el.type === "checkbox") el.checked = !!v; else el.value = v; });
  };
  const derived = () => {
    const q = saved.quote, s = d.strategy;
    $("#capNote").innerHTML = `Modal maksimal yang bisa terpakai bersamaan: <b>${money(d.risk.order_size_quote * d.risk.max_open_positions, q)}</b>.`;
    $("#probOut").textContent = pct0(s.min_prob_up);
    $("#rsiOut").textContent = s.rsi_max >= 100 ? "abaikan" : Math.round(s.rsi_max);
    $("#customBox").hidden = presetKey !== "kustom";
    $$("[data-preset]").forEach((b) => b.classList.toggle("on", b.dataset.preset === presetKey));
    $$("[data-model]").forEach((b) => b.classList.toggle("on", b.dataset.model === d.model.size));
    $("#pctBox").hidden = s.sl_mode === "atr";
    $("#atrBox").hidden = s.sl_mode !== "atr";
    ["strategy.trail_activate_pct", "strategy.trail_pct"].forEach((p) => { $(`[data-path="${p}"]`).disabled = !s.trailing_on; });
    const hrs = (s.max_hold_candles * TF_SEC[d.timeframe]) / 3600;
    $("#exitNote").innerHTML = s.sl_mode === "atr"
      ? `Batas jual mengikuti volatilitas. Jika harga biasanya bergerak 1% per candle, stop-loss di <b>−${nf(s.sl_atr_mult, 1)}%</b> dan take-profit di <b>+${nf(s.tp_atr_mult, 1)}%</b>.`
      : `Contoh: beli di 100, dijual otomatis di <b class="loss">${nf(100 * (1 - s.stop_loss_pct / 100), 2)}</b> (rugi) atau <b class="gain">${nf(100 * (1 + s.take_profit_pct / 100), 2)}</b> (untung).`;
    $("#exitNote").innerHTML += ` Posisi dijual paksa setelah ${s.max_hold_candles} candle (≈ ${hrs >= 48 ? nf(hrs / 24, 1) + " hari" : nf(hrs, 0) + " jam"}).`;
    $("#symChips").innerHTML = d.symbols.map((p) => `<span class="chip">${esc(base(p))}<button class="btn ghost sm" style="padding:0 2px" data-rm="${esc(p)}" aria-label="Hapus ${esc(p)}">✕</button></span>`).join("");
    $$("#symChips [data-rm]").forEach((b) => b.onclick = () => { if (d.symbols.length === 1) return toast("Minimal satu koin.", "err"); d.symbols = d.symbols.filter((x) => x !== b.dataset.rm); changed(); });
    $("#savebar").hidden = JSON.stringify(d) === JSON.stringify(saved);
  };
  const changed = () => derived();

  view.addEventListener("input", (e) => {
    const el = e.target.closest("[data-path]"); if (!el) return;
    let v = el.type === "checkbox" ? el.checked : el.type === "number" || el.type === "range" ? parseFloat(el.value) : el.value;
    if (typeof v === "number" && isNaN(v)) return;
    set(el.dataset.path, v);
    if (el.dataset.path.startsWith("strategy.min_")) presetKey = preset() === "kustom" ? "kustom" : preset();
    changed();
  });
  view.addEventListener("change", (e) => { if (e.target.type === "checkbox") e.target.dispatchEvent(new Event("input", { bubbles: true })); });
  $("#presets").onclick = (e) => {
    const b = e.target.closest("[data-preset]"); if (!b) return;
    presetKey = b.dataset.preset;
    if (PRESETS[presetKey].v) [d.strategy.min_expected_return_pct, d.strategy.min_prob_up] = PRESETS[presetKey].v;
    fill(); changed();
  };
  $("#models").onclick = (e) => { const b = e.target.closest("[data-model]"); if (b) { d.model.size = b.dataset.model; changed(); } };
  seg($("#tfSeg"), TF, d.timeframe, (v) => { d.timeframe = v; changed(); });
  seg($("#slSeg"), { persen: "Persen tetap", atr: "Ikut volatilitas pasar (ATR)" }, d.strategy.sl_mode, (v) => { d.strategy.sl_mode = v; changed(); });
  pairCombo($("#symAdd"), { value: "", placeholder: "Tambah koin…", onPick: (p) => { if (!d.symbols.includes(p)) d.symbols.push(p); $("#symAdd input").value = ""; changed(); } });
  $("#revert").onclick = () => { d = structuredClone(saved); presetKey = preset(); fill(); route(); };
  $("#save").onclick = (e) => busy(e.currentTarget, async () => {
    try {
      const r = await api("/api/config", d);
      saved = structuredClone(d);
      toast(r.restarted ? "Pengaturan disimpan. Robot dinyalakan ulang." : "Pengaturan disimpan.");
      derived(); refreshStatus();
    } catch (err) { toast(err.message, "err"); }
  });
  fill(); derived();
};

/* ===================================================== AKUN & MODE */
ROUTES.akun = async (view) => {
  const render = async () => {
    let a;
    try { a = await api("/api/account"); } catch (e) { view.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
    view.innerHTML = `
      <div class="page-head"><div><h1>Akun &amp; mode</h1><p>Pilih apakah robot memakai uang virtual atau uang sungguhan, dan hubungkan akun Tokocrypto Anda.</p></div></div>
      <div class="stack">
        <section class="panel"><div class="panel-title">Mode trading</div>
          <div class="mode-cards">
            <button class="mode-card sim ${a.mode === "paper" ? "on" : ""}" data-mode="paper"><h3><span class="pulse ${a.mode === "paper" ? "" : "off"}"></span>Simulasi</h3><p>Harga asli dari Tokocrypto, uang virtual. Aman untuk mencoba dan menilai robot.</p></button>
            <button class="mode-card live ${a.mode === "live" ? "on" : ""}" data-mode="live"><h3><span class="pulse ${a.mode === "live" ? "warn" : "off"}"></span>Live</h3><p>Robot membeli dan menjual dengan uang sungguhan di akun Tokocrypto Anda.</p></button>
          </div></section>
        <div class="grid cols-2">
          <section class="panel"><div class="panel-title">API key Tokocrypto ${a.has_keys ? `<span class="chip sim">Tersimpan</span>` : `<span class="chip">Belum diisi</span>`}</div>
            <ol class="steps" style="margin-bottom:16px"><li>Buka Tokocrypto → <b>Manajemen API</b>, lalu buat API key baru.</li><li>Aktifkan izin <b>baca</b> dan <b>spot trading</b> saja.</li><li><b>Jangan aktifkan izin withdraw.</b></li><li>Tempel key dan secret di bawah, lalu simpan.</li></ol>
            <form id="keyForm" class="stack" style="gap:12px" autocomplete="off">
              <div class="field"><label for="k1">API key</label><input class="input" id="k1" type="password" placeholder="${esc(a.key || "Tempel API key")}"></div>
              <div class="field"><label for="k2">Secret key</label><input class="input" id="k2" type="password" placeholder="${esc(a.secret || "Tempel secret key")}"></div>
              <div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn primary" type="submit" data-busy="Menyimpan…">Simpan kunci</button><button class="btn" type="button" id="testBtn" data-busy="Menghubungkan…" ${a.has_keys ? "" : "disabled"}>Tes koneksi akun</button></div>
              <div id="testOut"></div>
              <div class="hint muted" style="font-size:13px">Kunci disimpan hanya di komputer ini (file .env) dan tidak pernah ikut ke GitHub.</div>
            </form></section>
          <section class="panel"><div class="panel-title">Reset simulasi</div>
            <p class="muted" style="margin-top:0">Menghapus semua riwayat mode Simulasi dan mengembalikan saldo virtual ke awal. Data mode Live tidak tersentuh.</p>
            <button class="btn danger" id="resetBtn" data-busy="Mereset…">Reset data simulasi</button></section>
        </div>
      </div>`;

    $$("[data-mode]").forEach((b) => b.onclick = async () => {
      const m = b.dataset.mode;
      if (m === a.mode) return;
      if (m === "live") {
        if (!a.has_keys) return toast("Simpan API key Tokocrypto dulu.", "err");
        const typed = await modal({
          title: "Aktifkan mode Live?",
          body: `<p>Robot akan trading dengan <b>uang sungguhan</b> dan bisa rugi. Sebaiknya jalankan Simulasi minimal 1–2 minggu dulu, dan mulai dengan modal kecil.</p>`,
          input: { label: `Ketik <b>${esc(a.confirm_text)}</b> untuk melanjutkan`, placeholder: a.confirm_text }, confirm: "Aktifkan Live", danger: true });
        if (typed == null) return;
        try { const r = await api("/api/account/mode", { mode: "live", confirm: typed }); toast(r.restarted ? "Mode Live aktif. Robot dinyalakan ulang." : "Mode Live aktif.", "info"); }
        catch (e) { return toast(e.message, "err"); }
      } else {
        const ok = await modal({ title: "Kembali ke Simulasi?", body: `<p>Posisi Live yang masih terbuka tetap ada di akun Tokocrypto Anda dan tidak lagi dijaga robot.</p>`, confirm: "Kembali ke Simulasi" });
        if (!ok) return;
        try { await api("/api/account/mode", { mode: "paper" }); toast("Kembali ke mode Simulasi."); } catch (e) { return toast(e.message, "err"); }
      }
      refreshStatus(); render();
    });
    $("#keyForm").onsubmit = (e) => {
      e.preventDefault();
      busy(e.submitter, async () => {
        try { await api("/api/account/keys", { key: $("#k1").value, secret: $("#k2").value }); toast("Kunci disimpan."); render(); }
        catch (err) { toast(err.message, "err"); }
      });
    };
    $("#testBtn").onclick = (e) => busy(e.currentTarget, async () => {
      try {
        const r = await api("/api/account/test", {});
        $("#testOut").innerHTML = `<div class="decision buy"><div><b>Terhubung ke Tokocrypto</b><span class="muted">Saldo USDT bebas: ${money(r.usdt)}${r.assets.length ? ` · aset lain: ${r.assets.filter(([k]) => k !== "USDT").map(([k, v]) => `${esc(k)} ${nf(v, 4)}`).join(", ") || "–"}` : ""}</span></div></div>`;
      } catch (err) { $("#testOut").innerHTML = `<div class="alert err" style="margin:0">${esc(err.message)}</div>`; }
    });
    $("#resetBtn").onclick = async (e) => {
      const ok = await modal({ title: "Reset data simulasi?", body: `<p>Semua riwayat trade, sinyal, dan saldo virtual mode Simulasi akan dihapus.</p>`, confirm: "Reset", danger: true });
      if (!ok) return;
      busy(e.target, async () => { try { await api("/api/account/reset-paper", {}); toast("Data simulasi direset."); } catch (err) { toast(err.message, "err"); } });
    };
  };
  render();
};

/* ===================================================== RIWAYAT */
ROUTES.riwayat = async (view) => {
  let mode = S.status?.mode;
  const render = async () => {
    let h;
    try { h = await api(`/api/history${mode ? `?mode=${mode}` : ""}`); } catch (e) { view.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
    mode = h.mode;
    const s = h.stats;
    teardown();
    view.innerHTML = `
      <div class="page-head"><div><h1>Riwayat</h1><p>Semua trade yang sudah selesai dan perkembangan aset robot.</p></div>${h.modes.length > 1 ? `<div id="modeSeg"></div>` : ""}</div>
      ${s.trades ? `<div class="compare"><div><span>Untung/rugi total</span><b class="num ${cls(s.pnl)}">${signed(s.pnl, 2, "")}</b></div><div><span>Trade menang</span><b class="num">${Math.round(s.win_pct)}%</b> <small class="muted">dari ${s.trades}</small></div><div><span>Rata-rata per trade</span><b class="num ${cls(s.avg)}">${signed(s.avg)}</b></div><div><span>Terbaik / terburuk</span><b class="num"><span class="gain">${signed(s.best)}</span> <span class="loss">${signed(s.worst)}</span></b></div></div>` : ""}
      <section class="panel" style="margin-bottom:18px"><div class="panel-title">Perkembangan total aset</div>${h.equity.length > 1 ? `<div class="chart md" id="hEq"></div>` : `<div class="empty"><b>Belum ada data</b>Nyalakan robot untuk mulai mencatat.</div>`}</section>
      <section class="panel"><div class="panel-title">Trade selesai <small>${h.trades.length} trade</small></div>
        ${h.trades.length ? `<div class="table-wrap"><table><thead><tr><th>Koin</th><th>Beli</th><th class="r">Harga beli</th><th>Jual</th><th class="r">Harga jual</th><th class="r">Untung/rugi</th><th>Alasan jual</th></tr></thead><tbody>
        ${h.trades.map((t) => `<tr><td>${symHtml(t.symbol)}</td><td class="muted">${esc(String(t.entry_time).slice(5, 16))}</td><td class="r num">${price(t.entry_price)}</td><td class="muted">${esc(String(t.exit_time).slice(5, 16))}</td><td class="r num">${price(t.exit_price)}</td><td class="r num ${cls(t.pnl)}"><b>${signed(t.pnl_pct)}</b> <small>${signed(t.pnl, 2, "")}</small></td><td class="muted">${esc(t.exit_reason)}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="empty"><b>Belum ada trade selesai</b>Trade muncul di sini setelah robot menjual posisinya.</div>`}</section>`;
    if (h.modes.length > 1) seg($("#modeSeg"), Object.fromEntries(h.modes.map((m) => [m, m === "live" ? "Live" : "Simulasi"])), mode, (v) => { mode = v; render(); });
    if (h.equity.length > 1) {
      const c = makeChart($("#hEq")); current.charts.push(c);
      c.addAreaSeries({ lineColor: C.flat, topColor: "rgba(154,166,214,.28)", bottomColor: "rgba(154,166,214,0)", lineWidth: 2 }).setData(h.equity);
      c.timeScale().fitContent();
    }
  };
  render();
};

/* ===================================================== UJI STRATEGI */
ROUTES.uji = async (view) => {
  const st = S.status || (await refreshStatus()) || { symbols: ["BTC/USDT"], timeframe: "1h" };
  const F = { sym: st.symbols[0], tf: st.timeframe, candles: 500, speed: "3", optimize: true };
  let selected = null, wasRunning = false;

  view.innerHTML = `
    <div class="page-head"><div><h1>Uji strategi</h1><p>Robot berpura-pura trading di data masa lalu memakai pengaturan Anda, lalu dibandingkan dengan sekadar membeli dan menahan. Tidak ada order sungguhan.</p></div></div>
    <section class="panel" style="margin-bottom:18px" id="btForm">
      <div class="fields" style="align-items:end">
        <div class="field"><span class="label">Koin</span><div id="btSym"></div></div>
        <div class="field"><span class="label">Timeframe</span><div id="btTf"></div></div>
        <div class="field"><label for="btN">Berapa candle ke belakang</label><div class="input-group"><input id="btN" class="input num" type="number" min="100" max="3000" step="50" value="500"><span class="unit">candle</span></div></div>
        <div class="field"><span class="label">Ketelitian</span><div id="btSpeed"></div></div>
      </div>
      <div style="display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-top:18px">
        <label class="switch"><input type="checkbox" id="btOpt" checked><span class="knob"></span><span class="txt"><b>Cari setelan terbaik otomatis</b><span>Mencoba ratusan kombinasi setelan, hanya beberapa detik tambahan</span></span></label>
        <button class="btn primary lg" id="btGo" data-busy="Memulai…">Mulai uji</button>
      </div>
      <div id="btRun" style="margin-top:16px"></div>
    </section>
    <div class="grid" style="grid-template-columns:minmax(220px,280px) minmax(0,1fr);align-items:start" id="btBody">
      <section class="panel"><div class="panel-title">Hasil uji</div><div class="result-list" id="btList"></div></section>
      <div id="btDetail" class="stack"></div>
    </div>`;
  if (matchMedia("(max-width: 860px)").matches) $("#btBody").style.gridTemplateColumns = "1fr";

  pairCombo($("#btSym"), { value: F.sym, onPick: (p) => (F.sym = p) });
  seg($("#btTf"), TF, F.tf, (v) => (F.tf = v));
  seg($("#btSpeed"), { "1": "Teliti", "3": "Sedang", "6": "Cepat" }, F.speed, (v) => (F.speed = v));
  $("#btGo").onclick = (e) => busy(e.currentTarget, async () => {
    try {
      await api("/api/backtest/start", { symbol: F.sym, tf: F.tf, candles: Number($("#btN").value) || 500, speed: Number(F.speed), optimize: $("#btOpt").checked });
      toast("Uji strategi dimulai.", "info"); pollRun();
    } catch (err) { toast(err.message, "err"); }
  });

  const pollRun = async () => {
    let s; try { s = await api("/api/backtest/status"); } catch { return; }
    const el = $("#btRun");
    $("#btGo").disabled = s.running;
    if (s.running) {
      el.innerHTML = `<div class="progress ${s.pct == null ? "indet" : ""}"><i style="width:${s.pct ?? 35}%"></i></div>
        <div style="display:flex;justify-content:space-between;gap:10px;margin-top:8px;font-size:13.5px"><span class="muted">${esc(s.phase)}</span><button class="btn sm ghost" id="btStop">Batalkan</button></div>
        <p class="muted" style="font-size:13px;margin:6px 0 0">Di komputer tanpa GPU, mode Teliti 500 candle bisa 20–40 menit. Hasil ramalan disimpan, jadi uji ulang berikutnya cepat.</p>`;
      $("#btStop").onclick = async () => { await api("/api/backtest/stop", {}); toast("Uji dibatalkan.", "info"); pollRun(); };
      wasRunning = true;
    } else {
      el.innerHTML = s.failed ? `<div class="alert err" style="margin:0"><div><b>Uji terakhir gagal.</b><pre class="log">${esc(s.log)}</pre></div></div>` : "";
      if (wasRunning) { wasRunning = false; selected = null; loadList(); if (!s.failed) toast("Uji strategi selesai."); }
    }
  };

  const loadList = async () => {
    const { results } = await api("/api/backtest/results").catch(() => ({ results: [] }));
    $("#btList").innerHTML = results.length ? results.map((r) => `<button data-r="${esc(r.name)}" class="${r.name === selected ? "on" : ""}"><b>${esc(r.name.replace(/_/g, " · ").replace("USDT", "/USDT"))}</b><small>${esc(r.updated)}${r.has_opt ? " · dengan optimasi" : ""}</small></button>`).join("")
      : `<div class="empty"><b>Belum ada hasil</b>Jalankan uji pertama di atas.</div>`;
    $$("[data-r]").forEach((b) => b.onclick = () => openResult(b.dataset.r));
    if (!selected && results.length) openResult(results[0].name);
    if (!results.length) $("#btDetail").innerHTML = "";
  };

  const openResult = async (name) => {
    selected = name;
    $$("[data-r]").forEach((b) => b.classList.toggle("on", b.dataset.r === name));
    current.charts.forEach((c) => c.remove()); current.charts = [];
    let r; try { r = await api(`/api/backtest/result/${encodeURIComponent(name)}`); } catch (e) { $("#btDetail").innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
    const m = r.metrics || {};
    const beat = m.return_pct != null && m.return_pct > m.buyhold_pct;
    const acc = (r.summary.find((x) => x.includes("Akurasi")) || "").split(":").slice(1).join(":").trim();
    const o = r.optim;
    $("#btDetail").innerHTML = `
      <section class="panel">
        <div class="panel-title">${esc(r.summary[0].replace(/^Uji /, "").split(" | ")[0])} <small>${esc((r.summary[0].split(" | ")[1] || "").replace(/:00(?=\s|$)/g, "").replace("s/d", "–"))}</small></div>
        <div class="compare">
          <div><span>Hasil robot</span><b class="num ${cls(m.return_pct)}">${signed(m.return_pct)}</b></div>
          <div><span>Beli &amp; tahan saja</span><b class="num ${cls(m.buyhold_pct)}">${signed(m.buyhold_pct)}</b></div>
          <div><span>Penurunan terdalam</span><b class="num loss">${signed(m.max_dd_pct)}</b></div>
          <div><span>Trade · menang</span><b class="num">${m.trades ?? 0}</b> <small class="muted">${m.win_pct != null ? Math.round(m.win_pct) + "%" : ""}</small></div>
        </div>
        <div class="callout" style="margin-bottom:14px">${beat ? `<b>Robot mengalahkan beli &amp; tahan</b> di periode ini.` : `<b>Robot belum mengalahkan beli &amp; tahan</b> di periode ini.`} Akurasi arah ramalan AI: ${esc(acc || "–")}.</div>
        <div class="chart md" id="btEq"></div>
        <div class="legend"><span><i style="background:${C.amber}"></i>Robot</span><span><i style="background:${C.muted}"></i>Beli &amp; tahan</span></div>
      </section>
      ${o ? `<section class="panel"><div class="panel-title">Setelan terbaik hasil optimasi</div>
        <p class="muted" style="margin-top:0;font-size:14px">Setelan dicari di periode latih (${esc(o.periode_latih[0].slice(0, 10))} – ${esc(o.periode_latih[1].slice(0, 10))}), lalu dinilai di periode uji (${esc(o.periode_uji[0].slice(0, 10))} – ${esc(o.periode_uji[1].slice(0, 10))}) yang tidak dipakai saat mencari. <b style="color:var(--text)">Kolom "Hasil uji" adalah gambaran yang lebih jujur.</b> Setelan yang bagus di latih tetapi rugi di uji kemungkinan hanya kebetulan.</p>
        <div class="table-wrap"><table><thead><tr><th></th><th class="r">Hasil latih</th><th class="r">Hasil uji</th><th class="r">Beli &amp; tahan (uji)</th><th class="r">Trade · menang (uji)</th><th>Setelan</th><th></th></tr></thead><tbody>
          ${[["Setelan sekarang", o.setelan_sekarang, 0], ...o.terbaik.map((x, i) => [`Kandidat ${i + 1}`, x, i + 1])].map(([n, x, k]) => `
          <tr class="opt-row ${k === 0 ? "current" : ""}"><td><b>${n}</b>${k === 1 ? ` <span class="tag">teratas</span>` : ""}</td>
            <td class="r num ${cls(x.latih.return_pct)}">${signed(x.latih.return_pct)}</td>
            <td class="r num ${cls(x.uji.return_pct)}"><b>${signed(x.uji.return_pct)}</b></td>
            <td class="r num muted">${signed(x.uji.buyhold_pct)}</td>
            <td class="r num">${x.uji.trades} · ${Math.round(x.uji.win_pct)}%</td>
            <td class="desc">${esc(x.desc.entry)}<br>${esc(x.desc.stop)}, ${esc(x.desc.trail)}, ${esc(x.desc.trend)}</td>
            <td class="r">${k ? `<button class="btn sm ${x.uji.return_pct > 0 ? "primary" : ""}" data-apply="${k}">Pakai</button>` : ""}</td></tr>`).join("")}
        </tbody></table></div></section>` : ""}
      ${r.trades?.length ? `<section class="panel"><div class="panel-title">Daftar trade <small>${r.trades.length} trade</small></div><div class="table-wrap" style="max-height:420px;overflow:auto"><table><thead><tr><th>Beli</th><th class="r">Harga beli</th><th>Jual</th><th class="r">Harga jual</th><th class="r">Hasil</th><th>Alasan jual</th></tr></thead><tbody>
        ${r.trades.map((t) => `<tr><td class="muted">${esc(String(t.entry_time).slice(5, 16))}</td><td class="r num">${price(t.entry_price)}</td><td class="muted">${esc(String(t.exit_time).slice(5, 16))}</td><td class="r num">${price(t.exit_price)}</td><td class="r num ${cls(t.pnl_pct)}">${signed(t.pnl_pct)}</td><td class="muted">${esc(t.exit_reason)}</td></tr>`).join("")}
        </tbody></table></div></section>` : ""}`;
    if (r.equity?.length) {
      const c = makeChart($("#btEq")); current.charts.push(c);
      c.addLineSeries({ color: C.muted, lineWidth: 1.5, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }).setData(r.buyhold);
      c.addLineSeries({ color: C.amber, lineWidth: 2.5, priceLineVisible: false }).setData(r.equity);
      c.timeScale().fitContent();
    }
    $$("[data-apply]").forEach((b) => b.onclick = async () => {
      const k = Number(b.dataset.apply), x = o.terbaik[k - 1];
      const ok = await modal({
        title: `Pakai setelan kandidat ${k}?`,
        body: `<p>${esc(x.desc.entry)}; ${esc(x.desc.stop)}; ${esc(x.desc.trail)}; ${esc(x.desc.trend)}.</p>${x.uji.return_pct <= 0 ? `<div class="alert warn" style="margin:0">Kandidat ini <b>rugi di periode uji</b>. Sebaiknya jangan dipakai.</div>` : ""}`,
        confirm: "Pakai setelan ini" });
      if (!ok) return;
      try { const res = await api("/api/backtest/apply", { name, k }); toast(res.restarted ? "Setelan dipakai. Robot dinyalakan ulang." : "Setelan dipakai."); } catch (e) { toast(e.message, "err"); }
    });
  };

  loadList();
  every(2500, pollRun);
};

/* ===================================================== mulai */
refreshStatus().then((s) => {
  if (s && !s.setup_ok) toast("Setup belum selesai: folder Kronos belum ada. Tutup panel lalu jalankan MULAI lagi.", "err", 12000);
  route();
});
setInterval(refreshStatus, 8000);
