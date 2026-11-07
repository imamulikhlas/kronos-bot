/* kronos — panel trading (vanilla JS, tanpa build)
   Struktur: pilih market (crypto / forex) -> Overview · Markets · Chart · Backtest · Settings. Account global. */
"use strict";

/* ===================================================================== utilitas */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TF = { "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D" };
const TF_LONG = { "15m": "15 menit", "30m": "30 menit", "1h": "1 jam", "4h": "4 jam", "1d": "1 hari" };
const TF_SEC = { "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400 };
const MKT = { crypto: "Crypto", forex: "Forex" };
const isFx = (sym) => !String(sym).includes("/");
const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function hexA(hex, a) {
  const h = String(hex).replace("#", ""); const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
function nf(v, d) { return Number(v).toLocaleString("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d }); }
function decimals(v, sym) {
  if (sym && isFx(sym)) { const s = String(sym).toUpperCase(); return s.startsWith("XA") ? 2 : s.slice(3, 6) === "JPY" ? 3 : 5; }
  const a = Math.abs(v); return a >= 1000 ? 2 : a >= 1 ? 4 : a >= 0.01 ? 5 : 8;
}
function price(v, sym) { return v == null || isNaN(v) ? "–" : nf(v, decimals(v, sym)); }
function money(v) { return v == null || isNaN(v) ? "–" : `${v < 0 ? "−" : ""}$${nf(Math.abs(v), 2)}`; }
function sMoney(v) { return v == null || isNaN(v) ? "–" : `${v >= 0 ? "+" : "−"}$${nf(Math.abs(v), 2)}`; }
function pct(v, d = 2) { return v == null || isNaN(v) ? "–" : `${v >= 0 ? "+" : "−"}${nf(Math.abs(v), d)}%`; }
function p0(v) { return v == null || isNaN(v) ? "–" : `${Math.round(v * 100)}%`; }
function tone(v) { return v == null || isNaN(v) ? "" : v >= 0 ? "up" : "down"; }
function hhmm(ms) { return new Date(ms).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }); }
function labelOf(sym) { if (!isFx(sym)) return sym; const c = String(sym).toUpperCase().replace(/[^A-Z]/g, ""); return `${c.slice(0, 3)}/${c.slice(3, 6)}`; }
function pair(label) { const [b, q] = String(label).split("/"); return `<span class="pair">${esc(b)}<small>/${esc(q || "")}</small></span>`; }
function sideTag(side) { return side === "short" ? `<span class="tag short">Sell</span>` : `<span class="tag long">Buy</span>`; }
const DIRS = {
  NAIK: ["up", "Up", '<path d="M12 19V5M6 11l6-6 6 6"/>'],
  TURUN: ["down", "Down", '<path d="M12 5v14M6 13l6 6 6-6"/>'],
  SAMPING: ["flat", "Sideways", '<path d="M5 12h14M14 7l5 5-5 5"/>'],
};
function dir(d) { const a = DIRS[d] || DIRS.SAMPING; return `<span class="dir ${a[0]}"><svg viewBox="0 0 24 24">${a[2]}</svg>${a[1]}</span>`; }
const ACT = { BELI: ["long", "Opened Buy"], JUAL: ["short", "Opened Sell"], TAHAN: ["acc", "Holding"], TUTUP: ["", "Closed"], TUNGGU: ["", "Waiting"], LEWATI: ["", "Skipped"], ERROR: ["short", "Error"] };
function actTag(a) { const x = ACT[a] || ["", String(a || "–")]; return `<span class="tag ${x[0]}">${x[1]}</span>`; }
function spark(vals, up) {
  if (!vals || vals.length < 2) return `<svg class="spark"></svg>`;
  const w = 240, h = 46, mn = Math.min(...vals), mx = Math.max(...vals);
  const sx = w / (vals.length - 1), sy = mx === mn ? 0 : (h - 8) / (mx - mn);
  const pts = vals.map((v, i) => `${(i * sx).toFixed(1)},${(h - 4 - (v - mn) * sy).toFixed(1)}`);
  const col = up ? "var(--up)" : "var(--down)";
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="M${pts.join(" L")} L${w},${h} L0,${h} Z" style="fill:${col};opacity:.09"/><polyline points="${pts.join(" ")}" style="fill:none;stroke:${col};stroke-width:1.7" vector-effect="non-scaling-stroke"/></svg>`;
}
function tug(up, down, cls = "mini-tug") {
  const mid = Math.max(0, 1 - up - down);
  return `<div class="${cls}"><i class="u" style="width:${up * 100}%"></i><i class="m" style="width:${mid * 100}%"></i><i class="d" style="width:${down * 100}%"></i></div>`;
}

async function api(path, body, method) {
  const opt = { method: method || (body !== undefined ? "POST" : "GET"), headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opt); } catch { throw new Error("Panel tidak tersambung ke server. Pastikan jendela MULAI masih terbuka."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Gagal (${res.status})`);
  return data;
}
function toast(msg, kind = "ok", ms = 3800) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`; el.textContent = msg;
  $("#toasts").append(el); setTimeout(() => el.remove(), ms);
}
function modal({ title, body = "", confirm = "Confirm", danger = false, input = null, cancel = "Cancel" }) {
  return new Promise((resolve) => {
    const m = $("#modal");
    m.innerHTML = `<div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="mt"><h3 id="mt">${esc(title)}</h3><div>${body}</div>
      ${input ? `<div class="field" style="margin-top:8px"><label for="mi">${input.label}</label><input id="mi" class="input" autocomplete="off" placeholder="${esc(input.placeholder || "")}"></div>` : ""}
      <div class="modal-actions"><button class="btn ghost" data-x>${esc(cancel)}</button><button class="btn ${danger ? "danger" : "dark"}" data-ok>${esc(confirm)}</button></div></div>`;
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
  if (!btn) return fn();
  const html = btn.innerHTML; btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${esc(btn.dataset.busy || "Working…")}`;
  try { return await fn(); } finally { if (btn.isConnected) { btn.disabled = false; btn.innerHTML = html; } }
}
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* tidak tersedia */ } },
};

/* ===================================================================== tema */
function applyTheme(t) {
  if (t === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  try { t === "system" ? localStorage.removeItem("kronos-theme") : localStorage.setItem("kronos-theme", t); } catch { /* abaikan */ }
}
$("#themeBtn").addEventListener("click", () => {
  const t = document.documentElement.dataset.theme;
  const dark = t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(dark ? "light" : "dark"); route();
});

/* ===================================================================== grafik */
function makeChart(el, fmt, extra = {}) {
  return LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, textColor: cssv("--ink-3"), fontFamily: cssv("--text") || "sans-serif", fontSize: 12 },
    grid: { vertLines: { color: hexA(cssv("--line"), 0.7) }, horzLines: { color: hexA(cssv("--line"), 0.7) } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 4 },
    crosshair: { mode: 1, vertLine: { color: cssv("--ink-3"), labelBackgroundColor: cssv("--ink") }, horzLine: { color: cssv("--ink-3"), labelBackgroundColor: cssv("--ink") } },
    localization: { locale: "id-ID", priceFormatter: typeof fmt === "function" ? fmt : (v) => (fmt === "$" ? money(v) : price(v, fmt)) },
    ...extra,
  });
}
const PALETTE = () => [cssv("--acc-text"), "#E07A2E", "#1F9E89", "#C2477B", "#6B7A90", "#B08A1E", "#3FA0D8", "#8E5B3A"];

/* ===================================================================== router & status */
const S = { status: null, pairs: {} };
let M = store.get("kronos-market", null) || null;
let cur = { timers: [], charts: [] };
function every(ms, fn) { fn(); const id = setInterval(fn, ms); cur.timers.push(id); return id; }
function teardown() {
  cur.timers.forEach(clearInterval);
  cur.charts.forEach((c) => { try { c.remove(); } catch { /* sudah dihapus */ } });
  cur = { timers: [], charts: [] };
}
const PAGES = {};
function setMarket(m) {
  M = m; store.set("kronos-market", m);
  document.documentElement.dataset.market = m;
  $$("#marketSwitch a").forEach((a) => a.classList.toggle("on", a.dataset.m === m));
  $$(".subnav a").forEach((a) => (a.href = `#/${m}/${a.dataset.nav}`));
}
function route() {
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  teardown();
  const view = $("#view"); view.innerHTML = "";
  document.body.classList.remove("landing");
  $$(".subnav a").forEach((a) => a.classList.remove("on"));
  $(".acct").classList.remove("on");
  if (parts[0] === "account") {
    $(".acct").classList.add("on");
    if (M) setMarket(M);
    PAGES.account(view);
  } else if (parts[0] === "crypto" || parts[0] === "forex") {
    setMarket(parts[0]);
    const page = PAGES[parts[1]] ? parts[1] : "overview";
    $$(".subnav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === page));
    PAGES[page](view, decodeURIComponent(query || ""));
  } else if (M && parts[0] !== "start") {
    location.replace(`#/${M}/overview`); return;
  } else {
    document.body.classList.add("landing");
    $$("#marketSwitch a").forEach((a) => a.classList.remove("on"));
    PAGES.start(view);
  }
  renderBotPill();
  view.focus({ preventScroll: true }); window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

async function refreshStatus() {
  try { S.status = await api("/api/status"); } catch { return null; }
  for (const m of ["crypto", "forex"]) {
    const st = S.status.markets[m];
    const dot = $(`[data-dot="${m}"]`);
    dot.className = `pulse-dot ${st.crashed ? "err" : st.running ? "run" : ""}`;
  }
  renderBotPill();
  return S.status;
}
function renderBotPill() {
  const el = $("#botPill");
  const st = M && S.status?.markets[M];
  if (!st) { el.innerHTML = ""; return; }
  el.href = `#/${M}/overview`;
  el.className = `bot-pill ${st.crashed ? "err" : st.running ? "run" : ""}`;
  el.innerHTML = `<i></i>Auto trading <b>${st.crashed ? "error" : st.running ? "running" : "off"}</b> · ${st.mode === "live" ? "Live" : "Simulation"}`;
}
const mstat = () => S.status?.markets[M] || null;

async function loadPairs(venue) {
  if (S.pairs[venue]) return S.pairs[venue];
  const r = await api(`/api/${venue}/pairs`).catch(() => ({ pairs: [] }));
  S.pairs[venue] = r.pairs || [];
  return S.pairs[venue];
}
const clean = (s) => String(s).toUpperCase().replace(/[^A-Z]/g, "");

/* pemilih pair (khusus market aktif, bisa diketik) */
function picker(el, { venue, value = "", onPick, placeholder = "Search pair", exclude = [] }) {
  el.classList.add("picker");
  el.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>
    <input class="input" value="${esc(value ? labelOf(value) : "")}" placeholder="${esc(placeholder)}" aria-label="Pilih pair" autocomplete="off" spellcheck="false"><div class="picker-list" hidden></div>`;
  const inp = $("input", el), list = $(".picker-list", el);
  let items = [], hl = 0;
  const show = async () => {
    const t = clean(inp.value);
    const all = (await loadPairs(venue)).filter((p) => !exclude.includes(p.symbol));
    const f = all.filter((p) => !t || clean(p.symbol).includes(t));
    if (t) f.sort((a, b) => (clean(b.symbol).startsWith(t) ? 1 : 0) - (clean(a.symbol).startsWith(t) ? 1 : 0));
    items = f.slice(0, 50).map((p) => p.symbol);
    const custom = !items.length && venue === "forex" && t.length >= 6;
    if (custom) items = [inp.value.trim().toUpperCase()];
    hl = 0;
    list.innerHTML = custom ? `<button type="button" data-p="${esc(items[0])}" class="hl">Use “${esc(items[0])}” <span class="in">simbol broker</span></button>`
      : items.length ? f.slice(0, 50).map((p, i) => `<button type="button" data-p="${esc(p.symbol)}" class="${i === 0 ? "hl" : ""}">${pair(p.label)}</button>`).join("")
        : `<div class="empty">Tidak ketemu</div>`;
    list.hidden = false;
  };
  const pick = (p) => { value = p; inp.value = labelOf(p); list.hidden = true; inp.blur(); onPick(p); };
  inp.addEventListener("focus", () => { inp.select(); show(); });
  inp.addEventListener("input", show);
  inp.addEventListener("keydown", (e) => {
    const b = $$("button", list);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); if (!b.length) return;
      hl = (hl + (e.key === "ArrowDown" ? 1 : -1) + b.length) % b.length;
      b.forEach((x, i) => x.classList.toggle("hl", i === hl)); b[hl].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") { e.preventDefault(); if (items[hl]) pick(items[hl]); }
    else if (e.key === "Escape") { list.hidden = true; inp.value = value ? labelOf(value) : ""; inp.blur(); }
  });
  list.addEventListener("mousedown", (e) => { const b = e.target.closest("button[data-p]"); if (b) { e.preventDefault(); pick(b.dataset.p); } });
  inp.addEventListener("blur", () => setTimeout(() => { list.hidden = true; if (!inp.value) inp.value = value ? labelOf(value) : ""; }, 150));
  return { set(v) { value = v; inp.value = labelOf(v); }, clear() { value = ""; inp.value = ""; } };
}
function seg(el, options, value, onChange) {
  el.classList.add("seg"); el.setAttribute("role", "radiogroup");
  el.innerHTML = Object.entries(options).map(([k, v]) => `<button type="button" role="radio" aria-checked="${k === value}" data-v="${esc(k)}" class="${k === value ? "on" : ""}">${esc(v)}</button>`).join("");
  el.onclick = (e) => {
    const b = e.target.closest("button[data-v]"); if (!b) return;
    $$("button", el).forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
    onChange(b.dataset.v);
  };
}

/* ===================================================================== START: pilih market */
PAGES.start = (view) => {
  view.innerHTML = `
    <div class="choose">
      <h1>Mau trading di mana?</h1>
      <p>Kripto dan forex punya robot, setelan, saldo simulasi, dan riwayat masing-masing. Kamu bisa pindah kapan saja lewat tombol di atas.</p>
      <div class="choose-grid">
        <a class="mcard crypto" href="#/crypto/overview">
          <span class="ic"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M9.5 8h4a2 2 0 0 1 0 4h-4m0 0h4.5a2 2 0 0 1 0 4H9.5V8M11 6.5V8m0 8v1.5"/></svg></span>
          <h2>Crypto</h2>
          <ul><li>BTC, ETH, SOL, dan ratusan koin lain di Tokocrypto</li><li>Spot: robot hanya Buy lalu Sell untuk menutup</li><li>Pasar buka 24 jam, gerak harga lebih liar</li><li>Modal tetap per posisi (USDT)</li></ul>
          <div class="foot"><span class="faint small" id="cInfo"></span><span class="btn dark" style="background:#17171A;color:#fff;box-shadow:3px 3px 0 #fff">Open Crypto</span></div></a>
        <a class="mcard forex" href="#/forex/overview">
          <span class="ic"><svg viewBox="0 0 24 24"><path d="M4 8h13l-3-3M20 16H7l3 3"/></svg></span>
          <h2>Forex</h2>
          <ul><li>EUR/USD, GBP/USD, USD/JPY, emas (XAU/USD), dan lainnya</li><li>Bisa Buy dan Sell, lewat MetaTrader 5</li><li>Pasar buka Senin–Jumat, gerak harga lebih halus</li><li>Ukuran lot dihitung dari risiko per posisi</li></ul>
          <div class="foot"><span class="faint small" id="fInfo"></span><span class="btn dark" style="background:#17171A;color:#fff;box-shadow:3px 3px 0 #fff">Open Forex</span></div></a>
      </div>
    </div>`;
  refreshStatus().then((s) => {
    if (!s) return;
    const info = (m) => { const st = s.markets[m]; return `${st.symbols.length} pairs · ${st.running ? "auto trading on" : "auto trading off"}`; };
    $("#cInfo").textContent = info("crypto"); $("#fInfo").textContent = info("forex");
  });
};

/* ===================================================================== OVERVIEW */
PAGES.overview = (view) => {
  const m = M;
  view.innerHTML = `
    <div id="crash"></div>
    <section class="autopanel" id="auto"></section>
    <section id="steps"></section>
    <section class="kpis" id="kpis"></section>
    <div class="grid split">
      <div class="stack">
        <section class="card"><div class="card-head"><h2>Open positions</h2><span id="closeAllWrap"></span></div><div id="positions"></div></section>
        <section class="card"><div class="card-head"><h2>Equity</h2><small id="eqNote"></small></div><div class="chart md" id="eqChart"></div><div id="eqEmpty"></div></section>
        <section class="card"><div class="card-head"><h2>Activity</h2></div><div class="feed" id="feed"></div></section>
      </div>
      <div class="stack">
        <section class="card" id="oppCard"><div class="card-head"><h2>Top opportunities</h2><a class="link" href="#/${m}/scanner">Scanner</a></div><div class="rows" id="opps"><div class="faint small">…</div></div></section>
        <section class="card"><div class="card-head"><h2>Latest signals</h2><a class="link" href="#/${m}/markets">All markets</a></div><div class="rows" id="decisions"></div></section>
        <section class="card"><div class="card-head"><h2>How this bot trades</h2><a class="link" href="#/${m}/settings">Edit rules</a></div><dl class="rules" id="rules"></dl></section>
        <section class="card"><div class="card-head"><h2>Accuracy</h2><small>arah ramalan yang benar</small></div><div id="acc"></div></section>
      </div>
    </div>`;
  const chart = makeChart($("#eqChart"), "$"); cur.charts.push(chart);
  const eqS = chart.addAreaSeries({ lineColor: cssv("--acc-text"), topColor: hexA(cssv("--acc-text"), 0.16), bottomColor: hexA(cssv("--acc-text"), 0), lineWidth: 2, priceLineVisible: false });
  let eqLen = -1;

  const renderAuto = () => {
    const st = mstat(); if (!st) return;
    const n = st.symbols.length, live = st.mode === "live";
    let cls = "", stateTxt = "Stopped", h = "Auto trading is off", p = `Tekan Start supaya robot mulai memantau ${n} pair setiap ${TF_LONG[st.timeframe]} dan membuka posisi sendiri. Selama mati, posisi yang masih terbuka tidak dijaga.`;
    if (st.crashed) { cls = "err"; stateTxt = "Error"; h = "Auto trading stopped"; p = "Robot berhenti karena ada masalah. Lihat pesannya di atas."; }
    else if (st.running) {
      cls = "run";
      if (st.state === "memuat model") { stateTxt = "Starting"; h = "Loading AI model…"; p = "Pertama kali bisa beberapa menit karena modelnya perlu diunduh."; }
      else if (st.state === "meramal") { stateTxt = "Running"; h = "Reading the market…"; p = "Robot sedang meramal tiap pair, lalu memutuskan buka, tahan, atau tutup posisi."; }
      else {
        stateTxt = st.paused ? "Paused" : "Running"; h = st.paused ? "Guarding open positions" : `Watching ${n} pair${n > 1 ? "s" : ""}`;
        const left = st.next_run ? Math.max(0, st.next_run - Date.now()) : 0;
        p = `Ramalan berikutnya pukul ${st.next_run ? hhmm(st.next_run) : "–"}${left > 60000 ? ` (${Math.round(left / 60000)} menit lagi)` : ""}. Stop-loss, take-profit, dan trailing stop dicek tiap menit.`;
        if (st.paused) p = "Posisi baru dijeda, posisi yang sudah ada tetap dijaga. " + p;
      }
    }
    const closedMkt = m === "forex" && !st.market_open;
    $("#auto").className = `autopanel ${cls}`;
    $("#auto").innerHTML = `
      <div>
        <div class="eyebrow"><span class="state ${cls}"><i></i>${stateTxt}</span>
          <span class="tag ${live ? "live" : ""}">${live ? "Live" : "Simulation"}</span>
          ${m === "forex" ? `<span class="tag ${closedMkt ? "warn" : ""}">${closedMkt ? "Market closed" : "Market open"}</span>` : ""}
          <span class="tag">${TF[st.timeframe]}</span></div>
        <h1>${esc(h)}</h1><p>${esc(p)}${live ? " <b>Mode live memakai uang sungguhan.</b>" : ""}</p>
        ${closedMkt ? `<p class="small" style="margin-top:6px">Pasar forex tutup di akhir pekan dan buka lagi Senin sekitar 04.00 WIB. Robot tetap bisa dinyalakan, tetapi baru beraksi saat pasar buka.</p>` : ""}
      </div>
      <div class="actions">
        ${st.running ? `<button class="btn danger lg" id="stopBtn" data-busy="Stopping…"><svg viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>Stop</button>`
                     : `<button class="btn go lg" id="startBtn" data-busy="Starting…"><svg viewBox="0 0 24 24"><path d="M8 5.5v13l10-6.5z" fill="currentColor" stroke="none"/></svg>Start</button>`}
        <label class="check"><input type="checkbox" id="pause" ${st.paused ? "checked" : ""}><span class="box"></span><span class="t"><b>Pause new entries</b><span>posisi yang ada tetap dijaga</span></span></label>
      </div>`;
    $("#startBtn")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (live && !(await modal({ title: `Start ${MKT[m]} in Live mode?`, body: "<p>Robot akan membuka dan menutup posisi memakai <b>uang sungguhan</b>.</p>", confirm: "Start", danger: true }))) return;
      try { await api(`/api/${m}/bot/start`, {}); toast(`${MKT[m]} auto trading started.`); } catch (err) { toast(err.message, "err"); }
      await refreshStatus(); renderAuto();
    }));
    $("#stopBtn")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const ok = await modal({ title: `Stop ${MKT[m]} auto trading?`, body: `<p>Posisi yang masih terbuka <b>tidak ikut ditutup</b> dan tidak dijaga robot.${m === "forex" ? " Untuk forex lewat MT5, stop-loss dan take-profit tetap ada di server broker." : ""}</p>`, confirm: "Stop", danger: true });
      if (!ok) return;
      busy(btn, async () => { try { await api(`/api/${m}/bot/stop`, {}); toast("Auto trading stopped."); } catch (err) { toast(err.message, "err"); } await refreshStatus(); renderAuto(); });
    });
    $("#pause").onchange = async (e) => {
      try { await api(`/api/${m}/bot/pause`, { value: e.target.checked }); toast(e.target.checked ? "New entries paused." : "New entries resumed."); }
      catch (err) { toast(err.message, "err"); e.target.checked = !e.target.checked; }
    };
    $("#crash").innerHTML = st.crashed ? `<div class="notice err" style="margin-bottom:14px;display:block"><b>Robot ${MKT[m]} berhenti karena ada masalah.</b> Perbaiki penyebabnya, lalu tekan Start lagi.<pre class="log">${esc(st.crash_log || "(tidak ada pesan)")}</pre><button class="btn sm" id="dismiss" style="margin-top:10px">Dismiss</button></div>` : "";
    $("#dismiss")?.addEventListener("click", async () => { await api(`/api/${m}/bot/dismiss`, {}); await refreshStatus(); renderAuto(); });
    $("#steps").innerHTML = st.has_signals ? "" : `<div class="steps">
      <a class="step done" href="#/${m}/markets"><span class="n">1</span><b>Pick pairs</b><span>${n} pair dipilih untuk auto trading. Atur di Markets.</span></a>
      <a class="step ${st.has_backtest ? "done" : ""}" href="#/${m}/backtest"><span class="n">2</span><b>Run a backtest</b><span>Cek seberapa tepat ramalannya di data lama.</span></a>
      <a class="step" id="stepStart"><span class="n">3</span><b>Start auto trading</b><span>Mulai dari mode Simulation: harga asli, uang virtual.</span></a></div>`;
    $("#stepStart")?.addEventListener("click", () => $("#startBtn")?.click());
  };

  const renderOverview = (o) => {
    const startBal = o.balance_start;
    $("#kpis").innerHTML = `
      <div class="kpi"><div class="k">Equity</div><div class="v">${money(o.equity ?? startBal)}</div><div class="d ${tone(o.equity_change_pct)}">${o.equity_change_pct == null ? `saldo awal ${money(startBal)}` : pct(o.equity_change_pct) + " sejak awal"}</div></div>
      <div class="kpi"><div class="k">Today</div><div class="v ${tone(o.pnl_today)}">${sMoney(o.pnl_today)}</div><div class="d">dari posisi yang ditutup</div></div>
      <div class="kpi"><div class="k">Total P&amp;L</div><div class="v ${tone(o.pnl_total)}">${sMoney(o.pnl_total)}</div><div class="d">${o.trades} trade</div></div>
      <div class="kpi"><div class="k">Open positions</div><div class="v">${o.positions.length}<span class="faint" style="font-size:.6em"> / ${o.max_positions}</span></div><div class="d">maksimal ${o.max_positions}</div></div>
      <div class="kpi"><div class="k">Win rate</div><div class="v">${o.win_pct == null ? "–" : Math.round(o.win_pct) + "%"}</div><div class="d">dari ${o.trades} trade</div></div>`;
    if (o.equity_series.length !== eqLen) { eqS.setData(o.equity_series); if (eqLen <= 0) chart.timeScale().fitContent(); eqLen = o.equity_series.length; }
    $("#eqChart").style.display = o.equity_series.length > 1 ? "" : "none";
    $("#eqEmpty").innerHTML = o.equity_series.length > 1 ? "" : `<div class="empty"><b>No equity history yet</b>Grafik muncul setelah robot berjalan beberapa candle.</div>`;
    $("#eqNote").textContent = o.mode === "live" ? "saldo akun + nilai posisi" : "saldo virtual + nilai posisi";

    $("#closeAllWrap").innerHTML = o.positions.length > 1 ? `<button class="btn sm danger" id="closeAll">Close all</button>` : "";
    $("#positions").innerHTML = o.positions.length ? o.positions.map((p) => {
      const frac = p.sl && p.tp && p.price_now ? Math.min(1, Math.max(0, (p.price_now - p.sl) / (p.tp - p.sl))) : null;
      return `<div class="pos">
        <div><div class="meta">${pair(p.label)} ${sideTag(p.side)}</div>
          <div class="soft small" style="margin-top:3px">${p.lots ? nf(p.lots, 2) + " lot" : "size " + money(p.cost)} · opened ${esc(String(p.entry_time).slice(5, 16))}</div></div>
        <div class="pnl"><b class="${tone(p.pnl_pct_now)}">${pct(p.pnl_pct_now)}</b><span class="small ${tone(p.pnl_now)}">${sMoney(p.pnl_now)}</span></div>
        ${frac != null ? `<div class="lane" title="posisi harga di antara stop-loss (kiri) dan take-profit (kanan)"><i style="left:${(frac * 100).toFixed(1)}%"></i></div>` : ""}
        <div class="levels"><div><span>Stop-loss</span><b class="down">${price(p.sl, p.symbol)}</b></div><div><span>Entry → now</span>${price(p.entry_price, p.symbol)} → ${price(p.price_now, p.symbol)}</div><div><span>Take-profit</span><b class="up">${price(p.tp, p.symbol)}</b></div>
          <div style="text-align:right"><button class="btn sm" data-close="${p.id}" data-label="${esc(p.label)}">Close</button></div></div></div>`;
    }).join("") : `<div class="empty"><b>No open positions</b>Robot membuka posisi sendiri kalau ramalannya cukup kuat.</div>`;
    $$("[data-close]").forEach((b) => b.onclick = async () => {
      if (!(await modal({ title: `Close ${b.dataset.label}?`, body: "<p>Posisi ditutup di harga pasar sekarang.</p>", confirm: "Close position", danger: true }))) return;
      busy(b, async () => { try { toast((await api(`/api/${m}/positions/close`, { ids: [Number(b.dataset.close)] })).message); } catch (e) { toast(e.message, "err"); } load(); });
    });
    $("#closeAll")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      if (!(await modal({ title: "Close all positions?", body: `<p>${o.positions.length} posisi ditutup di harga pasar sekarang.</p>`, confirm: "Close all", danger: true }))) return;
      busy(btn, async () => { try { toast((await api(`/api/${m}/positions/close`, { ids: ["ALL"] })).message); } catch (err) { toast(err.message, "err"); } load(); });
    });
    $("#decisions").innerHTML = o.decisions.length ? o.decisions.map((d) => `
      <div class="rowi"><a class="l" href="#/${m}/chart?${encodeURIComponent(d.symbol)}">${pair(d.label)} ${dir(d.direction)}</a><div>${actTag(d.action)}</div>
        <div class="note">Ramalan <b class="${tone(d.exp_ret_pct)}">${pct(d.exp_ret_pct)}</b> · naik ${p0(d.prob_up)} / turun ${p0(d.prob_down)}${d.accuracy != null ? ` · akurasi ${p0(d.accuracy)}` : ""}. ${esc(d.reason || "")}</div></div>`).join("")
      : `<div class="empty"><b>No signals yet</b>Muncul setelah robot meramal pertama kali, atau buka Chart untuk meramal manual.</div>`;
    $("#rules").innerHTML = o.approach.map((r) => `<div><dt>${esc(r.k)}</dt><dd>${esc(r.v)}</dd></div>`).join("");
    $("#feed").innerHTML = o.events.length ? o.events.map((e) => `<div><time>${esc(String(e.time).slice(11, 16))}</time><span class="${esc(e.level)}">${esc(e.message)}</span></div>`).join("") : `<div class="faint" style="grid-template-columns:1fr">Belum ada aktivitas.</div>`;
  };
  const renderAcc = (a) => {
    const rows = a.rows.filter((r) => r.trading);
    $("#acc").innerHTML = rows.length ? rows.map((r) => `<div class="acc-row"><span>${pair(r.label)}</span>
        <span class="bar">${r.n ? `<i class="${r.state === "pass" ? "ok" : r.state === "low" ? "low" : ""}" style="width:${(r.hit || 0) * 100}%"></i>` : ""}${r.need ? `<u style="left:${r.need * 100}%"></u>` : ""}</span>
        <span class="v">${r.hit == null ? "–" : p0(r.hit)}<small>${r.n ? `of ${r.n}` : "not rated"}</small></span></div>`).join("")
      + `<p class="faint small" style="margin:12px 0 0">Garis tegak = batas minimal. ${rows.some((r) => r.blocking) ? "Pair di bawah garis tidak akan dibuka posisinya." : "Isi rapor dengan menjalankan Backtest tiap pair."}</p>`
      : `<div class="empty">Belum ada pair untuk auto trading.</div>`;
  };
  const load = async () => { try { renderOverview(await api(`/api/${m}/overview`)); } catch { /* koneksi sesaat */ } };
  api(`/api/${m}/scanner`).then(({ result: r }) => {
    if (!$("#opps")) return;
    if (!r) { $("#opps").innerHTML = `<div class="empty" style="padding:8px">Scan seluruh pasar untuk menemukan pair yang sedang bergerak.<br><a class="btn sm accent" href="#/${m}/scanner">Scan market</a></div>`; return; }
    const age = Math.round((Date.now() - r.time) / 60000);
    $("#opps").innerHTML = r.rows.slice(0, 4).map((x) => `<div class="rowi"><a class="l" href="#/${m}/chart?${encodeURIComponent(x.symbol)}">${pair(x.label)} ${sideTag(x.side)}</a><b>${x.score}</b>
      <div class="note">${x.ai ? `${p0(x.ai.prob)} skenario ${x.side === "short" ? "turun" : "naik"}, potensi ${pct(x.ai.net_pct)} setelah biaya` : "skor teknikal"}${x.in_watchlist ? "" : " · belum di watchlist"}</div></div>`).join("")
      + `<p class="faint small" style="margin:10px 0 0">Scan ${age < 1 ? "baru saja" : age < 60 ? age + " menit lalu" : Math.round(age / 60) + " jam lalu"}, ${TF[r.tf]}.</p>`;
  }).catch(() => {});
  every(4000, async () => { await refreshStatus(); renderAuto(); });
  every(7000, load);
  every(30000, async () => { try { renderAcc(await api(`/api/${m}/accuracy`)); } catch { /* abaikan */ } });
};

/* ===================================================================== MARKETS: monitoring & pembanding */
const PERIODS = { "24h": 86400, "7d": 604800, "30d": 2592000 };
PAGES.markets = (view) => {
  const m = M;
  const st = mstat();
  let tf = store.get(`kronos-mtf-${m}`, st?.timeframe || "1h");
  let period = store.get(`kronos-period-${m}`, "7d");
  let sel = store.get(`kronos-cmp-${m}`, null);
  let rows = [];
  view.innerHTML = `
    <div class="head"><div><h1>${MKT[m]} markets</h1><p>Pantau beberapa pair sekaligus, lihat ramalan AI-nya, dan pilih pair mana yang di-trade robot (tombol <b>Auto</b>). Centang <b>Compare</b> untuk membandingkan performanya di bawah.</p></div><a class="btn accent" href="#/${m}/scanner">Find more pairs in Scanner</a></div>
    <div class="toolbar" style="margin-bottom:16px"><div id="addPick"></div><div id="tfSeg"></div><div class="grow"></div>
      <span class="faint small" id="scanInfo"></span>
      <button class="btn accent" id="scanBtn" data-busy="Forecasting…"><svg viewBox="0 0 24 24"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/></svg>Forecast all</button></div>
    <div class="wgrid" id="grid"><div class="empty"><span class="spinner"></span></div></div>
    <section class="card" id="cmpCard">
      <div class="card-head"><h2>Compare</h2><div class="toolbar"><div id="perSeg"></div></div></div>
      <div id="cmpBody"><div class="empty">Centang <b>Compare</b> di minimal dua pair.</div></div>
    </section>`;
  const addP = picker($("#addPick"), { venue: m, placeholder: "Add pair to watchlist", exclude: [], onPick: async (p) => {
    try { await api(`/api/${m}/watchlist`, { add: p }); toast(`${labelOf(p)} added.`); addP.clear(); loadWatch(); } catch (e) { toast(e.message, "err"); }
  } });
  seg($("#tfSeg"), TF, tf, (v) => { tf = v; store.set(`kronos-mtf-${m}`, v); loadWatch(); loadCompare(); });
  seg($("#perSeg"), { "24h": "24H", "7d": "7D", "30d": "30D" }, period, (v) => { period = v; store.set(`kronos-period-${m}`, v); loadCompare(); });

  const renderGrid = () => {
    $("#grid").innerHTML = rows.map((r) => {
      const s = r.signal, on = sel.includes(r.symbol);
      return `<article class="wcard ${on ? "sel" : ""}">
        <div class="row1"><a class="name" href="#/${m}/chart?${encodeURIComponent(r.symbol)}">${pair(r.label)}</a>
          <button class="auto-chip ${r.trading ? "on" : ""}" data-auto="${esc(r.symbol)}" title="${r.trading ? "Di-trade robot. Klik untuk berhenti." : "Klik supaya pair ini di-trade robot."}">Auto<span class="sw"></span></button></div>
        ${r.error ? `<div class="notice err">${esc(r.error)}</div>` : `
        <div class="row2"><span class="px">${price(r.price, r.symbol)}</span><span class="${tone(r.change_pct)}" style="font-weight:600">${pct(r.change_pct)}</span></div>
        ${spark(r.spark, (r.change_pct || 0) >= 0)}
        <div class="row2 small faint"><span>L ${price(r.low, r.symbol)}</span><span>24H range</span><span>H ${price(r.high, r.symbol)}</span></div>`}
        <div class="sig">${s ? `<div class="r1">${dir(s.direction)}<span class="${tone(s.exp_ret_pct)}" style="font-weight:600">${pct(s.exp_ret_pct)}</span></div>${tug(s.prob_up, s.prob_down)}
          <div class="r1 faint small"><span>naik ${p0(s.prob_up)} · turun ${p0(s.prob_down)}</span><span>${r.accuracy != null ? `akurasi ${p0(r.accuracy)}` : "belum dinilai"}</span></div>`
          : `<div class="r1 faint small"><span>Belum ada ramalan</span><a href="#/${m}/chart?${encodeURIComponent(r.symbol)}">Forecast</a></div>`}</div>
        <div class="foot"><button class="cmp-btn ${on ? "on" : ""}" data-cmp="${esc(r.symbol)}"><span class="sq"></span>Compare</button>
          <span><a class="btn ghost sm" href="#/${m}/chart?${encodeURIComponent(r.symbol)}">Chart</a><button class="btn ghost sm" data-rm="${esc(r.symbol)}" aria-label="Hapus ${esc(r.label)}">Remove</button></span></div>
      </article>`;
    }).join("") || `<div class="empty"><b>Watchlist kosong</b>Tambah pair lewat kolom di atas.</div>`;
    $$("[data-auto]").forEach((b) => b.onclick = async () => {
      const sym = b.dataset.auto, on = !b.classList.contains("on");
      try {
        const r = await api(`/api/${m}/watchlist`, { trade: sym, on });
        toast(`${labelOf(sym)} ${on ? "ditambahkan ke" : "dikeluarkan dari"} auto trading${r.restarted ? ", robot di-restart" : ""}.`);
        rows.forEach((x) => (x.trading = r.symbols.includes(x.symbol))); renderGrid(); refreshStatus();
      } catch (e) { toast(e.message, "err"); }
    });
    $$("[data-cmp]").forEach((b) => b.onclick = () => {
      const sym = b.dataset.cmp;
      sel = sel.includes(sym) ? sel.filter((x) => x !== sym) : [...sel, sym].slice(-8);
      store.set(`kronos-cmp-${m}`, sel); renderGrid(); loadCompare();
    });
    $$("[data-rm]").forEach((b) => b.onclick = async () => {
      const sym = b.dataset.rm, r = rows.find((x) => x.symbol === sym);
      if (r?.trading && !(await modal({ title: `Remove ${labelOf(sym)}?`, body: "<p>Pair ini sedang di-trade robot dan akan dikeluarkan dari auto trading juga. Posisi yang sudah terbuka tidak ikut ditutup.</p>", confirm: "Remove", danger: true }))) return;
      try { await api(`/api/${m}/watchlist`, { remove: sym }); sel = sel.filter((x) => x !== sym); store.set(`kronos-cmp-${m}`, sel); loadWatch(); loadCompare(); } catch (e) { toast(e.message, "err"); }
    });
  };
  const loadWatch = async () => {
    try {
      const w = await api(`/api/${m}/watch?tf=${tf}`);
      rows = w.rows;
      if (sel == null) { sel = rows.slice(0, 3).map((r) => r.symbol); store.set(`kronos-cmp-${m}`, sel); loadCompare(); }
      sel = sel.filter((s) => rows.some((r) => r.symbol === s));
      renderGrid();
    } catch (e) { $("#grid").innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  };
  const loadCompare = async () => {
    cur.charts.forEach((c) => c.remove()); cur.charts = [];
    const body = $("#cmpBody");
    if (!sel || sel.length < 2) { body.innerHTML = `<div class="empty">Centang <b>Compare</b> di minimal dua pair untuk membandingkan performanya.</div>`; return; }
    body.innerHTML = `<div class="empty"><span class="spinner"></span></div>`;
    const bars = Math.max(20, Math.min(900, Math.round(PERIODS[period] / TF_SEC[tf])));
    let c;
    try { c = await api(`/api/compare?symbols=${encodeURIComponent(sel.join(","))}&tf=${tf}&bars=${bars}`); } catch (e) { body.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; return; }
    if (!$("#cmpBody")) return;
    const pal = PALETTE();
    const ok = c.rows.filter((r) => !r.error);
    const base = ok[0]?.symbol;
    const corrCell = (v) => v == null ? "–" : `<span class="corr" style="background:${hexA(v >= 0 ? cssv("--up") : cssv("--down"), Math.min(0.35, Math.abs(v) * 0.4))}">${nf(v, 2)}</span>`;
    body.innerHTML = `
      <div class="legend-dots" style="margin-bottom:8px">${ok.map((r, i) => `<span><i style="background:${pal[i % pal.length]}"></i>${esc(r.label)}</span>`).join("")}</div>
      <div class="chart cmp" id="cmpChart"></div>
      <p class="faint small" style="margin:8px 0 14px">Perubahan harga dalam persen sejak awal periode (${esc(ok[0]?.from || "")} sampai ${esc(ok[0]?.to || "")}), jadi pair dengan harga berbeda bisa dibandingkan langsung.</p>
      <div class="table-wrap"><table><thead><tr><th>Pair</th><th class="r">Return</th><th class="r">Volatility</th><th class="r">Max drawdown</th><th class="r">Range</th><th>AI outlook</th><th class="r">Accuracy</th><th class="r">Correlation vs ${esc(ok[0]?.label || "")}</th></tr></thead><tbody>
      ${c.rows.map((r) => r.error ? `<tr><td>${pair(r.label)}</td><td colspan="7" class="down">${esc(r.error)}</td></tr>` : `<tr>
        <td><span class="dotname"><i style="background:${pal[ok.indexOf(r) % pal.length]}"></i>${pair(r.label)}</span></td>
        <td class="r ${tone(r.return_pct)}"><b>${pct(r.return_pct)}</b></td><td class="r">${nf(r.volatility_pct, 2)}%</td><td class="r down">${pct(r.max_dd_pct)}</td>
        <td class="r faint">${price(r.low, r.symbol)} – ${price(r.high, r.symbol)}</td>
        <td>${r.signal ? `${dir(r.signal.direction)} <span class="${tone(r.signal.exp_ret_pct)}">${pct(r.signal.exp_ret_pct)}</span>` : `<span class="faint">–</span>`}</td>
        <td class="r">${r.accuracy == null ? "–" : p0(r.accuracy)}</td><td class="r">${r.symbol === base ? "–" : corrCell(c.corr?.[base]?.[r.symbol])}</td></tr>`).join("")}
      </tbody></table></div>`;
    const ch = makeChart($("#cmpChart"), (v) => `${v >= 0 ? "+" : ""}${nf(v, 2)}%`); cur.charts.push(ch);
    ok.forEach((r, i) => ch.addLineSeries({ color: pal[i % pal.length], lineWidth: i === 0 ? 2.5 : 2, priceLineVisible: false, lastValueVisible: true }).setData(r.points));
    ch.addLineSeries({ color: hexA(cssv("--ink-3"), 0.6), lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
      .setData(ok[0] ? ok[0].points.map((p) => ({ time: p.time, value: 0 })) : []);
    ch.timeScale().fitContent();
  };
  $("#scanBtn").onclick = (e) => busy(e.currentTarget, async () => {
    try {
      const { job } = await api("/api/scan", { symbols: rows.map((r) => r.symbol), tf });
      await new Promise((resolve) => {
        const poll = setInterval(async () => {
          try {
            const j = await api(`/api/scan/${job}`);
            if ($("#scanInfo")) $("#scanInfo").textContent = j.finished ? "" : `${j.current} (${j.done}/${j.total})`;
            if (j.finished) { clearInterval(poll); resolve(); toast(j.errors ? `Selesai, ${Object.keys(j.errors).length} pair gagal.` : "Forecast selesai."); }
          } catch { clearInterval(poll); resolve(); }
        }, 1500);
        cur.timers.push(poll);
      });
      loadWatch(); loadCompare();
    } catch (err) { toast(err.message, "err"); }
  });
  loadWatch().then(() => { if (sel && sel.length >= 2) loadCompare(); });
  const t = setInterval(loadWatch, 45000); cur.timers.push(t);
};

/* ===================================================================== SCANNER: seluruh pasar */
const TREND_TXT = { 1: "Up", "-1": "Down", 0: "Flat" };
PAGES.scanner = async (view) => {
  const m = M;
  const fx = m === "forex";
  const st0 = mstat() || (await refreshStatus())?.markets[m];
  const P = store.get(`kronos-scan-${m}`, null) || { tf: st0?.timeframe || "1h", uni: fx ? "all" : "60", ai: 15, side: "all", hideWatch: false };
  const save = () => store.set(`kronos-scan-${m}`, P);
  let res = null, wasRunning = false;
  view.innerHTML = `
    <div class="head"><div><h1>Scanner</h1><p>Cari ${fx ? "pair forex dan logam" : "koin"} yang sedang bergerak dan punya peluang paling bagus di seluruh pasar, bukan cuma watchlist-mu. Kandidat teratas dicek AI, lalu bisa langsung kamu pantau atau serahkan ke robot.</p></div></div>
    <section class="card scan-ctl">
      <div class="field"><span class="label">Timeframe</span><div id="sTf"></div></div>
      <div class="field"><span class="label">${fx ? "Pairs" : "Coins"}</span><div id="sUni"></div></div>
      <div class="field"><span class="label">AI check</span><div id="sAi"></div></div>
      <div class="grow"></div>
      <button class="btn accent lg" id="sGo" data-busy="Starting…"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>Scan market</button>
    </section>
    <div id="sRun"></div>
    <div id="sOut"></div>`;
  seg($("#sTf"), TF, P.tf, (v) => { P.tf = v; save(); });
  seg($("#sUni"), fx ? { majors: "Majors + gold", all: "All 30" } : { 30: "Top 30", 60: "Top 60", 100: "Top 100" }, String(P.uni), (v) => { P.uni = v; save(); });
  seg($("#sAi"), { 0: "Off", 10: "Top 10", 15: "Top 15", 30: "Top 30" }, String(P.ai), (v) => { P.ai = Number(v); save(); });
  $("#sGo").onclick = (e) => busy(e.currentTarget, async () => {
    try { await api(`/api/${m}/scanner/start`, { tf: P.tf, universe: String(P.uni), ai_top: P.ai }); poll(); }
    catch (err) { toast(err.message, "err", 7000); }
  });

  const act = (r) => r.in_watchlist
    ? `<button class="auto-chip ${r.trading ? "on" : ""}" data-auto="${esc(r.symbol)}" title="${r.trading ? "Di-trade robot" : "Serahkan ke robot"}">Auto<span class="sw"></span></button>`
    : `<button class="btn sm" data-watch="${esc(r.symbol)}">+ Watch</button>`;
  const chance = (r) => {
    if (!r.ai) return `<span class="faint">teknikal saja</span>`;
    const dirW = r.side === "short" ? "turun" : "naik";
    return `<b>${p0(r.ai.prob)}</b> skenario ${dirW}`;
  };
  const render = () => {
    const out = $("#sOut"); if (!out) return;
    if (!res) {
      out.innerHTML = `<div class="card"><div class="empty"><b>Belum pernah scan</b>Tekan Scan market untuk memeriksa ${fx ? "30 pair forex dan logam" : "koin teramai di Tokocrypto"}. ${P.ai ? "Dengan AI check, butuh beberapa menit di CPU dan jauh lebih cepat dengan GPU." : ""}</div></div>`;
      return;
    }
    let rows = res.rows.filter((r) => (P.side === "all" || r.side === P.side) && !(P.hideWatch && r.in_watchlist));
    const picks = rows.filter((r) => !(r.flags || []).includes("Move too small after costs")).slice(0, 3);
    const hrs = (h) => { const x = (h * TF_SEC[res.tf]) / 3600; return x >= 24 ? `${nf(x / 24, x % 24 ? 1 : 0)} hari` : `${nf(x, 0)} jam`; };
    out.innerHTML = `
      <div class="scan-meta">
        <span>Scanned <b>${res.scanned}</b> ${fx ? "pairs" : "coins"} · <b>${res.ai_checked}</b> checked by AI · ${TF[res.tf]} · ${new Date(res.time).toLocaleString("id-ID", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} · ${nf(res.seconds, 0)} detik${res.device ? ` · ${esc(res.device)}` : ""}</span>
        <span class="toolbar">${fx ? `<span id="sSide"></span>` : ""}<label class="check"><input type="checkbox" id="hideW" ${P.hideWatch ? "checked" : ""}><span class="box"></span><span class="t"><b>Hide my watchlist</b></span></label></span>
      </div>
      ${res.tf !== P.tf ? `<div class="notice warn" style="margin-bottom:14px">Hasil ini untuk timeframe ${TF[res.tf]}. Tekan Scan market untuk ${TF[P.tf]}.</div>` : ""}
      <div class="picks">${picks.map((r, i) => `
        <article class="pick ${i === 0 ? "first" : ""}">
          <div class="row1"><span class="rank">#${i + 1}</span><span class="score">${r.score}<small>/100</small></span></div>
          <a class="name" href="#/${m}/chart?${encodeURIComponent(r.symbol)}">${pair(r.label)}</a>
          <div class="meta">${sideTag(r.side)} ${dir(r.ai?.direction || (r.side === "short" ? "TURUN" : "NAIK"))}</div>
          ${spark(r.spark, (r.ret_1d || 0) >= 0)}
          <p>${r.ai ? `AI: ${chance(r)} dalam ${hrs(r.ai.horizon)}, harga diperkirakan <b class="${tone(r.ai.exp_ret_pct)}">${pct(r.ai.exp_ret_pct)}</b>, potensi untung ${r.side === "short" ? "untuk Sell " : ""}<b class="${tone(r.ai.net_pct)}">${pct(r.ai.net_pct)}</b> setelah biaya.` : `Skor teknikal ${r.tech}/100. Aktifkan AI check untuk peluang skenario.`}
            Gerak harian rata-rata ${nf(r.day_move_pct, 2)}%.${r.accuracy != null ? ` Akurasi AI di pair ini ${p0(r.accuracy)} dari ${r.acc_n}.` : " Akurasi AI di pair ini belum diuji."}</p>
          <div class="chips">${(r.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}${(r.flags || []).map((t) => `<span class="tag warn">${esc(t)}</span>`).join("")}</div>
          <div class="foot">${act(r)}<span><a class="btn ghost sm" href="#/${m}/chart?${encodeURIComponent(r.symbol)}">Chart</a><a class="btn ghost sm" href="#/${m}/backtest" data-bt="${esc(r.symbol)}">Backtest</a></span></div>
        </article>`).join("") || `<div class="empty">Tidak ada pair yang cocok dengan filter.</div>`}</div>
      <section class="card">
        <div class="card-head"><h2>All results</h2><small>${rows.length} ${fx ? "pairs" : "coins"}, diurutkan dari skor</small></div>
        <div class="table-wrap"><table class="scan-t"><thead><tr><th>#</th><th>Pair</th><th>Score</th>${fx ? "<th>Side</th>" : ""}<th>AI chance</th><th class="r">AI forecast</th><th class="r">24h</th><th class="r">7d</th><th class="r">Daily move</th><th>Trend</th><th class="r">RSI</th>${fx ? "" : `<th class="r">Volume 24h</th>`}<th>Notes</th><th></th></tr></thead><tbody>
        ${rows.map((r, i) => `<tr>
          <td class="faint">${i + 1}</td>
          <td><a href="#/${m}/chart?${encodeURIComponent(r.symbol)}" style="text-decoration:none">${pair(r.label)}</a>${r.in_watchlist ? ` <span class="tag">${r.trading ? "auto" : "watch"}</span>` : ""}</td>
          <td><span class="scorebar"><i style="width:${r.score}%"></i></span> <b>${r.score}</b></td>
          ${fx ? `<td>${sideTag(r.side)}</td>` : ""}
          <td>${r.ai ? `${tug(r.ai.prob_up, r.ai.prob_down)}<span class="small">${chance(r)}</span>` : `<span class="faint small">–</span>`}</td>
          <td class="r">${r.ai ? `<span class="${tone(r.ai.exp_ret_pct)}">${pct(r.ai.exp_ret_pct)}</span>` : "–"}</td>
          <td class="r ${tone(r.ret_1d)}">${pct(r.ret_1d, 1)}</td><td class="r ${tone(r.ret_7d)}">${pct(r.ret_7d, 1)}</td>
          <td class="r">${nf(r.day_move_pct, 2)}%</td><td>${TREND_TXT[r.trend]}</td><td class="r">${Math.round(r.rsi)}</td>
          ${fx ? "" : `<td class="r">${r.quote_volume ? "$" + compact(r.quote_volume) : "–"}</td>`}
          <td class="wrap" style="min-width:130px;font-size:12.5px">${[...(r.tags || []), ...(r.flags || [])].map(esc).join(", ")}</td>
          <td class="r">${act(r)}</td></tr>`).join("")}
        </tbody></table></div>
      </section>
      <details class="card how"><summary><b>Cara skor dihitung</b></summary>
        <p>Tahap 1, semua pair: tren (EMA 50/200), momentum 7 hari dibanding volatilitasnya, seberapa rapi geraknya, breakout, ${fx ? "" : "lonjakan volume, "}RSI, dan apakah gerak wajarnya cukup besar dibanding biaya. ${fx ? "Arah Buy dan Sell dinilai terpisah." : "Crypto spot hanya dinilai untuk Buy."}</p>
        <p>Tahap 2, kandidat teratas: AI Kronos membuat beberapa skenario harga. Skor akhir = 45% peluang skenario searah + 30% skor teknikal + 25% besar gerakan setelah biaya. Pair yang di backtest sering salah ditebak AI diturunkan skornya.</p>
        <p>Skor hanya untuk mengurutkan, bukan jaminan untung. Sebelum menyerahkan pair ke robot, jalankan <a href="#/${m}/backtest">Backtest</a> dan pilih yang dapat nilai A atau B.</p></details>`;
    if (fx) seg($("#sSide"), { all: "Buy & Sell", long: "Buy", short: "Sell" }, P.side, (v) => { P.side = v; save(); render(); });
    $("#hideW").onchange = (e) => { P.hideWatch = e.target.checked; save(); render(); };
    $$("[data-watch]").forEach((b) => b.onclick = async () => {
      try { await api(`/api/${m}/watchlist`, { add: b.dataset.watch }); toast(`${labelOf(b.dataset.watch)} added to watchlist.`); res.rows.forEach((r) => { if (r.symbol === b.dataset.watch) r.in_watchlist = true; }); render(); }
      catch (e) { toast(e.message, "err"); }
    });
    $$("[data-auto]").forEach((b) => b.onclick = async () => {
      const sym = b.dataset.auto, on = !b.classList.contains("on");
      if (on && !(await modal({ title: `Let the bot trade ${labelOf(sym)}?`, body: "<p>Robot akan membuka posisi di pair ini kalau sinyalnya memenuhi aturan masuk. Sebaiknya jalankan Backtest dulu.</p>", confirm: "Turn on Auto" }))) return;
      try {
        const r = await api(`/api/${m}/watchlist`, { trade: sym, on });
        res.rows.forEach((x) => { x.trading = r.symbols.includes(x.symbol); });
        toast(`${labelOf(sym)} ${on ? "added to" : "removed from"} auto trading${r.restarted ? ", bot restarted" : ""}.`); render(); refreshStatus();
      } catch (e) { toast(e.message, "err"); }
    });
    $$("[data-bt]").forEach((a) => a.onclick = async (e) => {
      e.preventDefault();
      const k = `kronos-lab-${m}`, F = store.get(k, {}) || {};
      F.syms = [a.dataset.bt]; store.set(k, F);
      await api(`/api/${m}/watchlist`, { add: a.dataset.bt }).catch(() => {});
      location.hash = `#/${m}/backtest`;
    });
  };
  const poll = async () => {
    let r; try { r = await api(`/api/${m}/scanner`); } catch { return; }
    const s = r.status, el = $("#sRun"); if (!el) return;
    if ($("#sGo")) $("#sGo").disabled = s.running;
    if (s.running) {
      const p = s.total ? Math.round((s.done / s.total) * 100) : null;
      el.innerHTML = `<div class="runbox"><div class="top"><span class="pct">${p == null ? "…" : p + "%"}</span><span class="soft small">${esc(s.phase)} ${s.total ? `${s.done}/${s.total}` : ""}</span></div>
        <div class="progress ${p == null ? "indet" : ""}"><i style="width:${p ?? 30}%"></i></div></div>`;
      wasRunning = true;
    } else {
      el.innerHTML = s.error ? `<div class="notice err" style="margin-bottom:16px"><b>Scan gagal:</b> ${esc(s.error)}</div>` : "";
      if (wasRunning || !res) { if (wasRunning && !s.error) toast("Scan finished."); wasRunning = false; res = r.result; render(); }
    }
  };
  every(1500, poll);
};
function compact(v) {
  return v >= 1e9 ? nf(v / 1e9, 1) + "B" : v >= 1e6 ? nf(v / 1e6, 1) + "M" : v >= 1e3 ? nf(v / 1e3, 0) + "K" : nf(v, 0);
}

/* ===================================================================== CHART: analisa satu pair */
PAGES.chart = async (view, query) => {
  const m = M;
  const st = mstat() || (await refreshStatus())?.markets[m];
  let watch = [];
  try { watch = (await api(`/api/${m}/config`)).watchlist; } catch { watch = (st?.symbols || []).map((x) => x.symbol); }
  const traded = (st?.symbols || []).map((x) => x.symbol);
  const A = { sym: query || store.get(`kronos-chart-${m}`, traded[0] || watch[0]), tf: st?.timeframe || "1h", signal: null, fitted: false };
  view.innerHTML = `
    <div class="head"><div><h1>Chart</h1><p>Grafik live satu pair dan ke mana AI memperkirakan harganya bergerak. Garis tebal = perkiraan tengah, garis putus-putus = batas atas dan bawah kemungkinan.</p></div></div>
    <div class="toolbar" style="margin-bottom:12px"><div class="quick" id="quick"></div></div>
    <div class="toolbar" style="margin-bottom:16px"><div id="symPick"></div><div id="tfPick"></div><div class="grow"></div>
      <button class="btn accent" id="fcBtn" data-busy="Forecasting…"><svg viewBox="0 0 24 24"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/></svg>Run forecast</button></div>
    <div class="grid split">
      <section class="card">
        <div class="price-line"><span id="phSym" style="font-size:18px"></span><span class="px" id="phPx">–</span><span id="phChg"></span><span class="faint small" id="phTime" style="margin-left:auto"></span></div>
        <div class="chart" id="mainChart"></div><div class="chart rsi" id="rsiChart"></div>
        <div class="legend"><span><i style="background:var(--acc-text)"></i>AI forecast</span><span><i style="background:repeating-linear-gradient(90deg,var(--acc-text) 0 4px,transparent 4px 7px);opacity:.7"></i>forecast range</span><span><i style="background:var(--ink-3)"></i>EMA 50</span><span><i style="background:var(--ink)"></i>EMA 200 (trend)</span><span><i style="background:var(--ink-2);height:2px"></i>RSI</span></div>
      </section>
      <section class="card" id="verdict"></section>
    </div>`;
  const renderQuick = () => {
    $("#quick").innerHTML = watch.map((s) => `<button data-q="${esc(s)}" class="${s === A.sym ? "on" : ""}">${traded.includes(s) ? `<i title="auto trading"></i>` : ""}${esc(labelOf(s))}</button>`).join("");
    $$("[data-q]").forEach((b) => b.onclick = () => { A.sym = b.dataset.q; pk.set(A.sym); switchTo(); });
  };
  let step = TF_SEC[A.tf];
  const mkCharts = () => {
    cur.charts.forEach((c) => c.remove()); cur.charts = [];
    const main = makeChart($("#mainChart"), A.sym);
    const rsiC = makeChart($("#rsiChart"), (v) => Math.round(v), { timeScale: { visible: false } });
    rsiC.applyOptions({ layout: { attributionLogo: false } });
    cur.charts.push(main, rsiC);
    const up = cssv("--up"), down = cssv("--down"), acc = cssv("--acc-text");
    const vol = main.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    main.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    const band = { color: hexA(acc, 0.55), lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
    const hi = main.addLineSeries(band), lo = main.addLineSeries(band);
    const candles = main.addCandlestickSeries({ upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down });
    const e50 = main.addLineSeries({ color: cssv("--ink-3"), lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    const e200 = main.addLineSeries({ color: cssv("--ink"), lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    const fc = main.addLineSeries({ color: acc, lineWidth: 3, priceLineVisible: false, title: "AI" });
    const rs = rsiC.addLineSeries({ color: cssv("--ink-2"), lineWidth: 1.5, priceLineVisible: false });
    [70, 30].forEach((v) => rs.createPriceLine({ price: v, color: hexA(v === 70 ? down : up, 0.55), lineStyle: 2, lineWidth: 1, axisLabelVisible: false }));
    main.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) rsiC.timeScale().setVisibleLogicalRange(r); });
    return { main, vol, hi, lo, candles, e50, e200, fc, rs };
  };
  let C = mkCharts();
  const drawForecast = () => {
    const s = A.signal;
    if (!s || !s.path?.length) { [C.hi, C.lo, C.fc].forEach((x) => x.setData([])); return; }
    const t = (i) => s.t0 + step * i;
    const line = (arr) => [{ time: t(0), value: s.last_close }, ...arr.map((v, i) => ({ time: t(i + 1), value: v }))];
    C.fc.setData(line(s.path));
    if (s.path_hi?.length) { C.hi.setData(line(s.path_hi)); C.lo.setData(line(s.path_lo)); } else { C.hi.setData([]); C.lo.setData([]); }
  };
  const loadCandles = async () => {
    try {
      const d = await api(`/api/candles?symbol=${encodeURIComponent(A.sym)}&tf=${A.tf}&limit=300`);
      if (!$("#phPx")) return;
      step = d.step;
      C.candles.setData(d.candles);
      C.vol.setData(d.volume.map((v) => ({ time: v.time, value: v.value, color: hexA(v.up ? cssv("--up") : cssv("--down"), 0.22) })));
      C.e50.setData(d.ema50); C.e200.setData(d.ema200); C.rs.setData(d.rsi);
      drawForecast();
      if (!A.fitted) { C.main.timeScale().setVisibleLogicalRange({ from: d.candles.length - 110, to: d.candles.length + 16 }); A.fitted = true; }
      const chg = d.prev_close ? (d.last / d.prev_close - 1) * 100 : null;
      $("#phSym").innerHTML = pair(d.label);
      $("#phPx").textContent = price(d.last, A.sym);
      $("#phChg").innerHTML = `<span class="${tone(chg)}">${pct(chg)}</span> <span class="faint small">this candle</span>`;
      const src = { mt5: "MetaTrader 5", yahoo: "Yahoo Finance", tokocrypto: "Tokocrypto" }[d.source] || d.source;
      $("#phTime").textContent = `${src} · ${new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    } catch (e) { if ($("#phTime")) $("#phTime").innerHTML = `<span class="down">${esc(e.message)}</span>`; }
  };
  const renderVerdict = () => {
    const s = A.signal, el = $("#verdict"); if (!el) return;
    if (!s) {
      el.innerHTML = `<div class="card-head"><h2>Outlook</h2></div><div class="empty"><b>No forecast for ${esc(labelOf(A.sym))} yet</b>Tekan Run forecast supaya AI memperkirakan arah harga berikutnya.<br><button class="btn accent" id="fc2">Run forecast</button></div>`;
      $("#fc2").onclick = () => $("#fcBtn").click(); return;
    }
    const a = DIRS[s.direction] || DIRS.SAMPING;
    const hrs = (s.path.length * step) / 3600;
    const horizon = hrs >= 24 ? `${nf(hrs / 24, hrs % 24 ? 1 : 0)} hari` : `${nf(hrs, hrs % 1 ? 1 : 0)} jam`;
    const note = s.would === "long" ? ["ok", "Auto trading would open a Buy"] : s.would === "short" ? ["err", "Auto trading would open a Sell"] : ["", "Auto trading would wait"];
    el.innerHTML = `
      <div class="card-head"><h2>Outlook</h2><small>${esc(s.source)}</small></div>
      <div class="verdict-word ${a[0]}">${a[1]}</div>
      <div class="soft">AI memperkirakan harga ${s.exp_ret_pct >= 0 ? "naik" : "turun"} <b class="${tone(s.exp_ret_pct)}">${pct(s.exp_ret_pct)}</b> dalam ${horizon} ke depan.</div>
      ${tug(s.prob_up, s.prob_down, "tug")}
      <div class="tug-l"><span>Up <b class="up">${p0(s.prob_up)}</b></span><span>Down <b class="down">${p0(s.prob_down)}</b></span></div>
      <div class="facts">
        <div><span>Upside</span><b class="up">${pct(s.upside_pct)}</b></div><div><span>Downside</span><b class="down">${pct(-s.downside_pct)}</b></div>
        <div><span>Trend</span><b>${s.trend_up ? "Up" : s.trend_down ? "Down" : "Flat"}</b></div>
        <div><span>RSI</span><b>${Math.round(s.rsi)}</b> <small class="faint">${s.rsi > 70 ? "overbought" : s.rsi < 30 ? "oversold" : "neutral"}</small></div>
        <div><span>Avg move / candle</span><b>${nf(s.atr_pct, 2)}%</b></div>
        <div><span>Accuracy here</span><b>${s.accuracy == null ? "–" : p0(s.accuracy)}</b> <small class="faint">${s.acc_n ? `of ${s.acc_n}` : "not rated"}</small></div></div>
      <div class="notice ${note[0]}" style="display:block"><b style="display:block">${note[1]}</b>${esc(s.decision)}</div>
      ${s.calibrated ? `<div class="notice" style="margin-top:10px">Di backtest, waktu AI seyakin ini (${Math.round(s.calibrated.from * 100)}–${Math.round(Math.min(s.calibrated.to, 1) * 100)}% naik), harga benar-benar naik <b>${p0(s.calibrated.actual_up)}</b> dari ${s.calibrated.n} kali.</div>`
        : `<p class="faint small" style="margin:10px 0 0">Jalankan Backtest untuk pair ini supaya bisa dicek seberapa sering ramalan seperti ini benar.</p>`}
      <p class="faint small" style="margin:12px 0 0">Kisaran ramalan ${price(s.pred_low, A.sym)} – ${price(s.pred_high, A.sym)}. Ramalan adalah perkiraan, bukan kepastian.</p>`;
  };
  const loadSignal = async () => {
    try { A.signal = (await api(`/api/signal?symbol=${encodeURIComponent(A.sym)}&tf=${A.tf}`)).signal; } catch { A.signal = null; }
    renderVerdict(); drawForecast();
  };
  const switchTo = () => {
    store.set(`kronos-chart-${m}`, A.sym);
    A.fitted = false; A.signal = null; C = mkCharts(); renderQuick(); renderVerdict(); loadCandles(); loadSignal();
    history.replaceState(null, "", `#/${m}/chart?${encodeURIComponent(A.sym)}`);
  };
  const pk = picker($("#symPick"), { venue: m, value: A.sym, onPick: (p) => { A.sym = p; switchTo(); } });
  seg($("#tfPick"), TF, A.tf, (v) => { A.tf = v; switchTo(); });
  $("#fcBtn").onclick = (e) => busy(e.currentTarget, async () => {
    try { A.signal = (await api("/api/forecast", { symbol: A.sym, tf: A.tf })).signal; renderVerdict(); drawForecast(); toast(`${labelOf(A.sym)} forecast ready.`); }
    catch (err) { toast(err.message, "err", 7000); }
  });
  renderQuick(); renderVerdict();
  history.replaceState(null, "", `#/${m}/chart?${encodeURIComponent(A.sym)}`);
  every(10000, loadCandles);
  every(30000, loadSignal);
};

/* ===================================================================== BACKTEST LAB */
const CANDLE_OPTS = [500, 1000, 2000, 4000];
const MODEL_COST = (name) => (/mini/.test(name) ? 0.5 : /base/.test(name) ? 2.5 : 1);
function span(candles, tf) {
  const h = (candles * TF_SEC[tf]) / 3600;
  return h >= 48 ? `${nf(h / 24, 0)} hari` : `${nf(h, 0)} jam`;
}
function mins(sec) {
  if (sec < 90) return `${Math.max(1, Math.round(sec))} detik`;
  if (sec < 5400) return `${Math.round(sec / 60)} menit`;
  return `${nf(sec / 3600, 1)} jam`;
}
function gradeBadge(g, cls = "") { return `<span class="gbadge ${g || "x"} ${cls}">${g || "–"}</span>`; }
const GRADE_TXT = {
  A: "Semua pemeriksaan lolos. Layak dicoba live dengan modal kecil.",
  B: "Ada harapan, tapi beberapa pemeriksaan belum lolos. Lanjutkan di Simulation dulu.",
  C: "Lemah. Hasilnya bisa jadi kebetulan. Jangan dipakai live.",
  D: "Hindari. Di data lama, cara ini merugi atau tidak bisa dinilai.",
};
const GRADE_EN = { A: "Ready to try live", B: "Promising", C: "Weak", D: "Avoid" };
function segDots(segs) { return `<span class="dots" title="untung/rugi per segmen waktu">${(segs || []).map((x) => `<i class="${x.return_pct > 0 ? "p" : x.return_pct < 0 ? "n" : ""}"></i>`).join("")}</span>`; }
function segBars(items, labels, cls = "") {
  const mx = Math.max(0.01, ...items.map((v) => Math.abs(v ?? 0))) / 0.72;
  const fmt = (v) => pct(v, Math.abs(v) < 1 ? 2 : 1);
  return `<div class="segbars ${cls}">${items.map((v, i) => {
    const hgt = (Math.abs(v ?? 0) / mx) * 100;
    return `<div><div class="pos-h">${v > 0 ? `<i style="height:${hgt}%"></i><span class="val up" style="bottom:calc(${hgt}% + 2px)">${fmt(v)}</span>` : ""}</div>
      <div class="neg-h">${v < 0 ? `<i style="height:${hgt}%"></i><span class="val down" style="top:calc(${hgt}% + 2px)">${fmt(v)}</span>` : v === 0 || v == null ? `<span class="val faint" style="top:4px">0%</span>` : ""}</div>
      <div class="lab-s">${esc(labels[i] || "")}</div></div>`;
  }).join("")}</div>`;
}
function mcBar(mc) {
  if (!mc) return `<p class="faint small">Terlalu sedikit trade untuk Monte Carlo.</p>`;
  const lo = Math.min(mc.p5, 0, mc.p50) - 1, hi = Math.max(mc.p95, 0, mc.p50) + 1;
  const x = (v) => ((v - lo) / (hi - lo)) * 100;
  return `<div class="mcbar"><div class="range" style="left:${x(mc.p5)}%;width:${x(mc.p95) - x(mc.p5)}%"></div>
      <div class="zero" style="left:${x(0)}%"></div><div class="mid" style="left:${x(mc.p50)}%"></div>
      <span class="t" style="left:${x(mc.p5)}%">${pct(mc.p5, 1)}</span><span class="t" style="left:${x(mc.p95)}%">${pct(mc.p95, 1)}</span></div>
    <p class="soft small" style="margin:0">Urutan trade diacak ${nf(mc.runs, 0)} kali. 90% hasil jatuh di antara <b>${pct(mc.p5, 1)}</b> dan <b>${pct(mc.p95, 1)}</b>, tengahnya <b>${pct(mc.p50, 1)}</b>. Peluang berakhir rugi <b class="${mc.prob_loss > 0.35 ? "down" : "up"}">${p0(mc.prob_loss)}</b>.</p>`;
}

PAGES.backtest = async (view) => {
  const m = M;
  const st = mstat() || (await refreshStatus())?.markets[m];
  const [cfg, sys] = await Promise.all([api(`/api/${m}/config`).catch(() => null), api("/api/system").catch(() => null)]);
  const watch = cfg?.watchlist || (st?.symbols || []).map((x) => x.symbol);
  const traded = (st?.symbols || []).map((x) => x.symbol);
  const F = store.get(`kronos-lab-${m}`, null) || {};
  F.syms = (F.syms || traded).filter((x) => watch.includes(x));
  if (!F.syms.length) F.syms = watch.slice(0, 1);
  F.tf = F.tf || st?.timeframe || "1h";
  F.candles = F.candles || 1000;
  F.every = F.every || 1;
  F.device = F.device || (sys?.best && sys.best !== "cpu" ? "gpu" : "auto");
  F.opt = F.opt ?? true;
  const save = () => store.set(`kronos-lab-${m}`, F);
  let selected = null, wasRunning = false, tab = "overview";

  view.innerHTML = `
    <div class="head"><div><h1>Backtest lab</h1><p>Robot ${MKT[m]} trading pura-pura di data lama, lalu dinilai A sampai D. Hasilnya menjawab dua hal: apakah ramalan AI benar-benar tepat di pair ini, dan setelan apa yang paling konsisten.</p></div></div>
    ${sys?.gpu_unused ? `<div class="notice warn" style="margin-bottom:16px"><b>Kartu grafis NVIDIA terdeteksi, tapi belum dipakai.</b> Tutup panel lalu jalankan MULAI lagi. Versi GPU dipasang otomatis (sekali saja, sekitar 2–3 GB). Kalau sudah pernah dicoba, hapus file <code>.venv\\gpu_checked</code> dulu.</div>` : ""}
    <div id="runArea"></div>
    <div class="lab">
      <section class="card lab-form">
        <div class="lab-row"><div class="k">Pairs<small>bisa lebih dari satu</small></div><div class="pairpick" id="pp"></div></div>
        <div class="lab-row"><div class="k">Timeframe</div><div id="tfSeg"></div></div>
        <div class="lab-row"><div class="k">History<small id="spanTxt"></small></div><div id="cSeg"></div></div>
        <div class="lab-row"><div class="k">Forecast every</div><div><div id="eSeg"></div><div class="hint" style="margin-top:6px">Tiap candle = paling mirip robot live. Lebih jarang = lebih cepat, tapi lebih kasar.</div></div></div>
        <div class="lab-row"><div class="k">Compute</div><div class="devices" id="dev"></div></div>
        <div class="lab-row"><div class="k">Optimize</div>
          <label class="check"><input type="checkbox" id="opt"><span class="box"></span><span class="t"><b>Find the most consistent settings</b><span>${m === "crypto" ? 432 : 864} kombinasi dinilai per segmen waktu, lalu dicek walk-forward</span></span></label></div>
      </section>
      <aside class="card estimate" id="est"></aside>
    </div>
    <div class="grid" style="grid-template-columns:minmax(220px,280px) minmax(0,1fr);align-items:start" id="btBody">
      <section class="card"><div class="card-head"><h2>Results</h2></div><div class="rlist" id="btList"></div></section>
      <div id="btDetail" class="stack"></div></div>`;
  if (matchMedia("(max-width: 860px)").matches) $("#btBody").style.gridTemplateColumns = "1fr";

  const renderPairs = () => {
    $("#pp").innerHTML = watch.map((s) => `<button type="button" data-s="${esc(s)}" class="${F.syms.includes(s) ? "on" : ""}" aria-pressed="${F.syms.includes(s)}">${traded.includes(s) ? `<i title="auto trading"></i>` : ""}${esc(labelOf(s))}</button>`).join("")
      + `<a class="btn ghost sm" href="#/${m}/markets">+ Add pair</a>`;
    $$("#pp [data-s]").forEach((b) => b.onclick = () => {
      const s = b.dataset.s;
      F.syms = F.syms.includes(s) ? F.syms.filter((x) => x !== s) : [...F.syms, s].slice(0, 12);
      save(); renderPairs(); renderEst();
    });
  };
  const gpuName = sys?.gpu || null;
  const renderDev = () => {
    const opts = [
      ["auto", "Auto", gpuName ? `pakai ${gpuName}` : "pakai CPU, GPU tidak terdeteksi"],
      ["gpu", "GPU", gpuName ? `${gpuName}${sys.vram_gb ? ` · ${nf(sys.vram_gb, 0)} GB` : ""}` : (sys?.gpu_unused ? "terdeteksi, perlu MULAI ulang" : "tidak terdeteksi")],
      ["cpu", "CPU", `${sys?.threads || "?"} thread`],
    ];
    $("#dev").innerHTML = opts.map(([k, t, d]) => `<button type="button" class="device ${F.device === k ? "on" : ""}" data-d="${k}" ${k === "gpu" && !gpuName ? "disabled" : ""}><b>${t}</b><span>${esc(d)}</span></button>`).join("");
    $$("#dev [data-d]").forEach((b) => b.onclick = () => { F.device = b.dataset.d; save(); renderDev(); renderEst(); });
  };
  const renderEst = () => {
    const usesGpu = F.device !== "cpu" && gpuName;
    const kind = usesGpu ? "gpu" : "cpu";
    const measured = sys?.speeds?.[kind];
    const mdl = sys?.model || { name: "Kronos-small", n_paths: 10 };
    const rough = (usesGpu ? 0.06 : 1.6) * MODEL_COST(mdl.name) * (mdl.n_paths / 10);
    const spp = measured?.sec_per_point || rough;
    const points = F.syms.length * Math.ceil(F.candles / F.every);
    $("#spanTxt").textContent = `≈ ${span(F.candles, F.tf)}`;
    $("#est").innerHTML = `
      <div class="card-head" style="margin:0"><h2>Estimate</h2><small>${measured ? "dari backtest terakhir" : "perkiraan kasar"}</small></div>
      <div><div class="big">~${mins(points * spp)}</div><div class="soft small">paling lama. Titik yang sudah pernah diramal diambil dari cache, jadi uji ulang jauh lebih cepat.</div></div>
      <dl>
        <div><dt>Forecasts</dt><dd>${nf(points, 0)} titik</dd></div>
        <div><dt>Pairs</dt><dd>${F.syms.length}</dd></div>
        <div><dt>Device</dt><dd>${usesGpu ? esc(gpuName) : "CPU"}</dd></div>
        <div><dt>AI model</dt><dd>${esc(String(mdl.name).split("/").pop())} · ${mdl.n_paths} skenario</dd></div>
      </dl>
      <button class="btn dark lg" id="btGo" data-busy="Starting…" ${F.syms.length ? "" : "disabled"}>Run backtest</button>
      ${!usesGpu ? `<p class="faint small" style="margin:0">Punya kartu grafis NVIDIA? Pilih GPU supaya 10–30× lebih cepat.</p>` : ""}`;
    $("#btGo").onclick = (e) => busy(e.currentTarget, async () => {
      try {
        await api("/api/backtest/start", { symbols: F.syms, tf: F.tf, candles: F.candles, speed: F.every, optimize: F.opt, device: F.device });
        toast("Backtest started."); poll();
      } catch (err) { toast(err.message, "err"); }
    });
  };
  renderPairs(); renderDev();
  seg($("#tfSeg"), TF, F.tf, (v) => { F.tf = v; save(); renderEst(); });
  seg($("#cSeg"), Object.fromEntries(CANDLE_OPTS.map((n) => [n, nf(n, 0)])), String(F.candles), (v) => { F.candles = Number(v); save(); renderEst(); });
  seg($("#eSeg"), { 1: "Every candle", 2: "Every 2", 4: "Every 4" }, String(F.every), (v) => { F.every = Number(v); save(); renderEst(); });
  $("#opt").checked = F.opt;
  $("#opt").onchange = (e) => { F.opt = e.target.checked; save(); };
  renderEst();

  const poll = async () => {
    let s; try { s = await api("/api/backtest/status"); } catch { return; }
    const el = $("#runArea"); if (!el) return;
    if ($("#btGo")) $("#btGo").disabled = s.running || !F.syms.length;
    if (s.running) {
      el.innerHTML = `<div class="runbox">
        <div class="top"><span class="pct">${s.pct == null ? "…" : Math.round(s.pct) + "%"}</span><button class="btn sm" id="btStop">Cancel</button></div>
        <div class="progress ${s.pct == null ? "indet" : ""}"><i style="width:${s.pct ?? 30}%"></i></div>
        <div class="soft small">${esc(s.phase || "Menyiapkan…")}${s.device ? ` · <b>${esc(s.device)}</b>` : ""}</div>
        ${s.warnings?.length ? `<div class="notice warn">${s.warnings.map(esc).join("<br>")}</div>` : ""}</div>`;
      $("#btStop").onclick = async () => { await api("/api/backtest/stop", {}); toast("Backtest cancelled."); poll(); };
      wasRunning = true;
    } else {
      el.innerHTML = s.failed ? `<div class="notice err" style="margin-bottom:16px"><b>Backtest terakhir gagal:</b> ${esc(s.error || "lihat detail")}
        <details style="margin-top:6px"><summary class="small" style="cursor:pointer">Detail teknis</summary><pre class="log">${esc(s.log)}</pre></details></div>` : "";
      if (wasRunning) { wasRunning = false; selected = null; loadList(); if (!s.failed) toast("Backtest finished."); }
    }
  };

  const loadList = async () => {
    const { results } = await api(`/api/${m}/backtest/results`).catch(() => ({ results: [] }));
    if (!$("#btList")) return;
    $("#btList").innerHTML = results.length ? results.map((r) => `<button data-r="${esc(r.name)}" class="${r.name === selected ? "on" : ""}">
        ${gradeBadge(r.grade)}<span>${pair(r.label)} <span class="faint small">${esc(TF[r.tf] || r.tf)}</span></span><b class="${tone(r.return_pct)}">${pct(r.return_pct, 1)}</b>
        <small>${r.hit != null ? `arah benar ${p0(r.hit)} · ` : ""}${esc(r.updated)}${r.dummy ? " · ramalan acak" : ""}</small></button>`).join("")
      : `<div class="empty"><b>No results yet</b>Pilih pair di atas lalu tekan Run backtest.</div>`;
    $$("[data-r]").forEach((b) => b.onclick = () => openResult(b.dataset.r));
    if (!selected && results.length) openResult(results[0].name);
    if (!results.length) $("#btDetail").innerHTML = "";
  };

  const openResult = async (name) => {
    selected = name;
    $$("[data-r]").forEach((b) => b.classList.toggle("on", b.dataset.r === name));
    let r; try { r = await api(`/api/backtest/result/${encodeURIComponent(name)}`); } catch (e) { $("#btDetail").innerHTML = `<div class="notice err">${esc(e.message)}</div>`; return; }
    if (!$("#btDetail")) return;
    const o = r.optim;
    const tabs = { overview: "Verdict", ai: "AI accuracy", settings: o ? "Best settings" : null, trades: `Trades (${r.trades?.length || 0})` };
    if (!tabs[tab]) tab = "overview";
    $("#btDetail").innerHTML = `<section class="card">
      <div class="card-head" style="margin-bottom:6px"><h2>${pair(r.label || name)} <span class="faint" style="font-size:14px">${esc(TF[r.tf] || "")}</span></h2>
        <small>${r.period ? esc(r.period[0]) + " → " + esc(r.period[1]) : ""}${r.speed?.device_name ? ` · ${esc(r.speed.device_name)}` : ""}</small></div>
      <div class="tabs" role="tablist">${Object.entries(tabs).filter(([, v]) => v).map(([k, v]) => `<button role="tab" data-tab="${k}" class="${k === tab ? "on" : ""}">${v}</button>`).join("")}</div>
      <div id="tabBody"></div></section>`;
    $$("[data-tab]").forEach((b) => b.onclick = () => { tab = b.dataset.tab; $$("[data-tab]").forEach((x) => x.classList.toggle("on", x === b)); renderTab(r); });
    renderTab(r);
  };

  const renderTab = (r) => {
    cur.charts.forEach((c) => c.remove()); cur.charts = [];
    const el = $("#tabBody"), mt = r.metrics || {}, q = r.quality || {}, o = r.optim;
    if (tab === "overview") {
      const g = o?.grade || r.grade || {};
      const best = o?.candidates?.[0];
      el.innerHTML = `
        <div class="verdict">${gradeBadge(g.letter, "xl")}
          <div><h2>${esc(GRADE_EN[g.letter] || "Not rated")}</h2>
            <p>${esc(GRADE_TXT[g.letter] || "")} ${o ? "Nilai ini untuk <b>setelan terbaik</b> hasil optimasi." : "Nilai ini untuk <b>setelanmu sekarang</b>. Centang Optimize untuk mencari yang lebih baik."}</p></div>
          <ul class="checks">${(g.checks || []).map((c) => `<li><i class="${c.ok ? "ok" : "no"}">${c.ok ? "✓" : "✕"}</i><span>${esc(c.text)}</span></li>`).join("")}</ul>
          ${(g.notes || []).map((n) => `<div class="notice warn" style="grid-column:1/-1">${esc(n)}</div>`).join("")}
        </div>
        <h3 style="margin:26px 0 10px;font:700 17px/1.2 var(--display)">${best ? "Setelanmu sekarang" : "Hasil robot"} di periode ini</h3>
        <div class="mgrid">
          <div><span>Bot return</span><b class="${tone(mt.return_pct)}">${pct(mt.return_pct)}</b><small>buy &amp; hold ${pct(mt.buyhold_pct)}</small></div>
          <div><span>Max drawdown</span><b class="${mt.max_dd_pct < 0 ? "down" : ""}">${pct(mt.max_dd_pct)}</b><small>turun terdalam</small></div>
          <div><span>Profit factor</span><b>${mt.profit_factor == null ? "–" : nf(Math.min(mt.profit_factor, 99), 2)}</b><small>bagus di atas 1,2</small></div>
          <div><span>Sharpe</span><b>${mt.sharpe == null ? "–" : nf(mt.sharpe, 2)}</b><small>untung per risiko, setahun</small></div>
          <div><span>Trades</span><b>${mt.trades ?? 0}</b><small>${r.venue === "forex" ? `buy ${mt.longs || 0} · sell ${mt.shorts || 0}` : `rata-rata ${nf(mt.avg_held || 0, 1)} candle`}</small></div>
          <div><span>Win rate</span><b>${mt.trades ? Math.round(mt.win_pct) + "%" : "–"}</b><small>untung ${pct(mt.avg_win_pct, 2)} · rugi ${pct(mt.avg_loss_pct, 2)}</small></div>
          <div><span>Losing streak</span><b>${mt.max_losing_streak ?? "–"}</b><small>rugi berturut-turut</small></div>
          <div><span>Time in market</span><b>${mt.exposure_pct == null ? "–" : nf(mt.exposure_pct, 0) + "%"}</b><small>dari semua candle</small></div>
        </div>
        <div class="chart md" id="btEq" style="margin-top:16px"></div>
        <div class="legend"><span><i style="background:var(--acc-text)"></i>Bot</span><span><i style="background:var(--ink-3)"></i>Buy &amp; hold</span></div>
        ${r.segments?.length ? `<h3 style="margin:24px 0 4px;font:700 17px/1.2 var(--display)">Per segmen waktu</h3>
          <p class="soft small" style="margin:0 0 12px">Periode dibagi ${r.segments.length} bagian. Setelan yang bagus untung di sebagian besar bagian, bukan cuma satu kali beruntung.</p>
          ${segBars(r.segments.map((x) => x.return_pct), r.segments.map((_, i) => `Seg ${i + 1}`))}` : ""}
        <h3 style="margin:24px 0 0;font:700 17px/1.2 var(--display)">Monte Carlo</h3>${mcBar(r.montecarlo)}`;
      if (r.equity?.length) {
        const c = makeChart($("#btEq"), "$"); cur.charts.push(c);
        c.addLineSeries({ color: cssv("--ink-3"), lineWidth: 1.5, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }).setData(r.buyhold);
        c.addLineSeries({ color: cssv("--acc-text"), lineWidth: 2.5, priceLineVisible: false }).setData(r.equity);
        c.timeScale().fitContent();
      }
    } else if (tab === "ai") {
      const sig = q.p_value != null && q.p_value < 0.05 && q.hit > 0.5;
      el.innerHTML = q.n ? `
        <p class="soft" style="margin-top:0">Dinilai dari ${nf(q.n, 0)} ramalan di periode ini, terlepas dari setelan robot. Ini jawaban jujur untuk pertanyaan "seberapa tepat AI di ${esc(r.label)}?"</p>
        <div class="mgrid">
          <div><span>Direction right</span><b class="${q.hit > 0.5 ? "up" : "down"}">${p0(q.hit)}</b><small>${sig ? "terbukti, bukan kebetulan" : `belum terbukti (p=${nf(q.p_value, 2)})`}</small></div>
          <div><span>Strong signals right</span><b>${q.conf_hit == null ? "–" : p0(q.conf_hit)}</b><small>${q.conf_n || 0} sinyal Up/Down</small></div>
          <div><span>Probability skill</span><b class="${tone(q.brier_skill)}">${pct(q.brier_skill * 100, 0)}</b><small>vs tebakan rata-rata</small></div>
          <div><span>Move size error</span><b>${nf(q.mae, 2)}%</b><small>${q.mae_skill >= 0 ? "lebih baik" : "lebih buruk"} dari menebak "tidak bergerak" (${nf(q.mae_naive, 2)}%)</small></div>
        </div>
        <h3 style="margin:24px 0 4px;font:700 17px/1.2 var(--display)">Kalibrasi peluang</h3>
        <p class="soft small" style="margin:0 0 14px">Kalau AI bilang "70% naik", apakah harga memang naik sekitar 70% dari waktu? Garis hitam = yang AI katakan, balok = yang benar-benar terjadi.</p>
        <div class="calib">${(q.calibration || []).map((b) => `<div class="calib-row"><span>AI ${Math.round(b.from * 100)}–${Math.round(Math.min(b.to, 1) * 100)}% naik</span>
          <div class="calib-bars"><i style="width:${b.actual * 100}%"></i><u style="left:${b.pred * 100}%"></u></div><b>${p0(b.actual)}</b></div>
          <div class="faint small" style="margin:-6px 0 0 142px">${b.n} kali</div>`).join("")}</div>
        <div class="notice" style="margin-top:16px">${sig ? `<b>AI punya keunggulan di pair ini.</b> Arah benar ${p0(q.hit)} dari ${q.n}, peluang ini terjadi cuma karena untung-untungan ${q.p_value < 0.001 ? "kurang dari 0,1%" : nf(q.p_value * 100, 1) + "%"}.`
          : `<b>Belum terbukti lebih baik dari lempar koin.</b> Coba history lebih panjang, timeframe lain, atau model AI yang lebih besar di Settings.`}</div>`
        : `<div class="empty">Belum ada ramalan yang bisa dinilai.</div>`;
    } else if (tab === "settings" && o) {
      const wf = o.walk_forward || {};
      const curO = o.current;
      const cand = (x, i) => `<div class="cand ${i === 1 ? "best" : ""}">
          <span class="rank">${i ? "#" + i : "Now"}</span>
          <div><div class="what">${esc(x.desc.entry)}. ${esc(x.desc.stop)}, ${esc(x.desc.trail)}, ${esc(x.desc.trend)}${x.desc.sides ? ", " + esc(x.desc.sides) : ""}.</div>
            <div class="nums"><span>Return <b class="${tone(x.full.return_pct)}">${pct(x.full.return_pct)}</b></span><span>${segDots(x.segments)} <b>${x.segments.filter((y) => y.return_pct > 0).length}/${x.segments.length}</b> segmen untung</span>
              <span>${x.full.trades} trade</span><span>PF <b>${nf(Math.min(x.full.profit_factor, 99), 2)}</b></span><span>DD <b class="down">${pct(x.full.max_dd_pct, 1)}</b></span>
              ${x.montecarlo ? `<span>peluang rugi <b class="${x.montecarlo.prob_loss > 0.35 ? "down" : "up"}">${p0(x.montecarlo.prob_loss)}</b></span>` : ""}</div></div>
          <div>${i ? `<button class="btn sm ${i === 1 ? "accent" : ""}" data-apply="${i}">Apply</button>` : `<span class="tag">current</span>`}</div></div>`;
      el.innerHTML = `
        <div class="grid halves" style="margin-bottom:8px">
          <div><div class="soft small">Walk-forward test</div><div class="verdict-word ${tone(wf.total_pct) === "up" ? "up" : "down"}" style="font-size:54px">${wf.total_pct == null ? "–" : pct(wf.total_pct, Math.abs(wf.total_pct) < 1 ? 2 : 1)}</div>
            <p class="soft small" style="margin:0">Untuk tiap segmen, setelan dipilih <b>hanya dari segmen sebelumnya</b> lalu dipakai di segmen itu, persis seperti memakai optimasi ini di dunia nyata. Ini perkiraan paling jujur.</p></div>
          <div>${segBars((wf.steps || []).map((x) => x.return_pct), (wf.steps || []).map((x) => `Seg ${x.segment + 1}`), "wf")}</div>
        </div>
        <h3 style="margin:22px 0 2px;font:700 17px/1.2 var(--display)">Setelan paling konsisten</h3>
        <p class="soft small" style="margin:0 0 6px">${o.valid} dari ${o.combos} kombinasi layak dinilai. Diurutkan dari hasil rata-rata per segmen, dikurangi ketidakstabilan dan drawdown, bukan dari untung total saja.</p>
        ${cand(curO, 0)}${o.candidates.map((x, i) => cand(x, i + 1)).join("")}`;
      $$("[data-apply]").forEach((b) => b.onclick = async () => {
        const k = Number(b.dataset.apply), x = o.candidates[k - 1];
        const bad = (wf.total_pct ?? 0) <= 0 || x.consistency < 0.5;
        const ok = await modal({ title: `Apply option #${k}?`, confirm: "Apply settings",
          body: `<p>${esc(x.desc.entry)}. ${esc(x.desc.stop)}, ${esc(x.desc.trail)}, ${esc(x.desc.trend)}${x.desc.sides ? ", " + esc(x.desc.sides) : ""}. Berlaku untuk semua pair ${MKT[m]}.</p>${bad ? `<div class="notice err">Hasil walk-forward atau konsistensinya lemah. Lebih aman dicoba di Simulation dulu.</div>` : ""}` });
        if (!ok) return;
        try { const res = await api("/api/backtest/apply", { name: selected, k }); toast(res.restarted ? "Settings applied. Bot restarted." : "Settings applied."); } catch (e) { toast(e.message, "err"); }
      });
    } else if (tab === "trades") {
      el.innerHTML = r.trades?.length ? `<div class="table-wrap" style="max-height:520px;overflow:auto"><table><thead><tr><th>Opened</th><th>Side</th><th class="r">Entry</th><th>Closed</th><th class="r">Exit</th><th class="r">P&amp;L</th><th>Reason</th></tr></thead><tbody>
        ${r.trades.map((t) => `<tr><td class="faint">${esc(String(t.entry_time).slice(5, 16))}</td><td>${sideTag(t.side)}</td><td class="r">${price(t.entry_price, r.symbol)}</td><td class="faint">${esc(String(t.exit_time).slice(5, 16))}</td><td class="r">${price(t.exit_price, r.symbol)}</td><td class="r ${tone(t.pnl)}">${sMoney(t.pnl)}</td><td class="soft">${esc(t.exit_reason)}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="empty">Tidak ada trade dengan setelan sekarang.</div>`;
    }
  };
  loadList();
  every(2500, poll);
};

/* ===================================================================== SETTINGS (per market) */
const PRESETS = {
  crypto: { careful: [1.2, 0.75], balanced: [0.8, 0.65], active: [0.4, 0.55] },
  forex: { careful: [0.2, 0.75], balanced: [0.1, 0.65], active: [0.05, 0.55] },
};
const PRESET_TXT = { careful: ["Careful", "jarang buka posisi, sinyal harus sangat kuat"], balanced: ["Balanced", "seimbang, disarankan"], active: ["Active", "lebih sering trading, risikonya lebih besar"], custom: ["Custom", "atur angkanya sendiri"] };
const MODELS = { light: ["Light", "paling cepat, cocok untuk laptop biasa"], balanced: ["Balanced", "seimbang, disarankan"], accurate: ["Accurate", "paling teliti, butuh komputer kuat"] };

PAGES.settings = async (view) => {
  const m = M;
  view.innerHTML = `<div class="head"><div><h1>${MKT[m]} settings</h1></div></div><div class="card"><div class="empty"><span class="spinner"></span></div></div>`;
  let saved, acct, sys;
  try { [saved, acct, sys] = await Promise.all([api(`/api/${m}/config`), api("/api/account"), api("/api/system").catch(() => ({}))]); } catch (e) { view.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; return; }
  const d = structuredClone(saved);
  const presetOf = () => Object.keys(PRESETS[m]).find((k) => PRESETS[m][k][0] === d.strategy.min_expected_return_pct && PRESETS[m][k][1] === d.strategy.min_prob_up) || "custom";
  let presetKey = presetOf();
  const num = (path, { label, unit = "", step = "any", min = 0, max, hint = "" }) => `
    <div class="field"><label for="f-${path}">${label}</label><div class="unit-wrap"><input class="input" id="f-${path}" type="number" inputmode="decimal" step="${step}" min="${min}" ${max != null ? `max="${max}"` : ""} data-path="${path}">${unit ? `<span class="unit">${unit}</span>` : ""}</div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
  const sw = (path, label, hint) => `<label class="check"><input type="checkbox" data-path="${path}"><span class="box"></span><span class="t"><b>${label}</b><span>${hint}</span></span></label>`;
  const fx = m === "forex";
  const connected = fx ? acct.mt5.enabled && acct.mt5.installed : acct.has_keys;

  view.innerHTML = `
    <div class="head"><div><h1>${MKT[m]} settings</h1><p>Setelan ini hanya untuk robot ${MKT[m]}. Kalau robot sedang berjalan, ia otomatis di-restart setelah kamu menyimpan.</p></div></div>
    <div class="card">
      <div class="group"><div><h3>Trading mode</h3><div class="desc">Simulation memakai uang virtual dengan harga asli. Live memakai akun ${fx ? "MetaTrader 5" : "Tokocrypto"} kamu.</div></div>
        <div class="stack" style="gap:12px">
          <div class="modecards"><button type="button" class="modecard ${d.mode === "paper" ? "on" : ""}" data-mode="paper"><b>Simulation</b><span>Aman untuk mencoba. Saldo virtual ${money(d.paper_balance)}.</span></button>
            <button type="button" class="modecard ${d.mode === "live" ? "on" : ""}" data-mode="live"><b>Live ${d.mode === "live" ? `<span class="tag live">ON</span>` : ""}</b><span>Uang sungguhan. ${connected ? "Akun sudah tersambung." : "Sambungkan akun dulu di Account."}</span></button></div>
          ${fx ? `<div class="notice">Tip: pakai <b>akun demo MT5</b> + mode Live untuk mencoba eksekusi sungguhan tanpa risiko uang.</div>` : ""}</div></div>

      <div class="group"><div><h3>Pairs &amp; timeframe</h3><div class="desc">Pair yang di-trade robot. Tambah atau kurangi lewat tombol Auto di halaman Markets.</div></div>
        <div class="stack" style="gap:14px">
          <div class="chips">${d.symbols.map((s) => `<span class="chip" style="padding-right:12px">${esc(labelOf(s))}</span>`).join("")}<a class="btn sm" href="#/${m}/markets">Manage in Markets</a></div>
          <div class="field"><span class="label">Bot checks the market every</span><div id="tfSeg"></div></div></div></div>

      <div class="group"><div><h3>Position size</h3><div class="desc">${fx ? "Ukuran lot dihitung dari risiko per posisi dan jarak stop-loss." : "Modal tetap per posisi dalam USDT."}</div></div>
        <div class="stack" style="gap:14px"><div class="fields">
          ${fx ? num("risk.risk_pct", { label: "Risk per trade", unit: "% equity", step: 0.1, min: 0.1, max: 10, hint: "kerugian maksimal kalau kena stop-loss" }) + num("risk.max_lots", { label: "Max lot per trade", unit: "lot", step: 0.01, min: 0.01 })
               : num("risk.order_size_quote", { label: "Size per trade", unit: "USDT", step: 1, min: 1 })}
          ${num("risk.max_open_positions", { label: "Max open positions", unit: "positions", step: 1, min: 1, max: 50 })}
          ${num("risk.max_daily_loss_quote", { label: "Daily loss limit", unit: "USD", step: 1, hint: "berhenti membuka posisi kalau rugi hari ini mencapai ini" })}
        </div><div class="notice" id="capNote"></div></div></div>

      <div class="group"><div><h3>Entry rules</h3><div class="desc">Seberapa yakin AI harus sebelum robot membuka posisi.</div></div>
        <div class="stack" style="gap:16px">
          <div class="choices" id="presets">${Object.entries(PRESET_TXT).map(([k, t]) => `<button type="button" class="choice" data-preset="${k}"><b>${t[0]}</b><span>${t[1]}</span></button>`).join("")}</div>
          <div class="fields" id="customBox">
            ${num("strategy.min_expected_return_pct", { label: "Min forecast move", unit: "%", step: 0.01 })}
            <div class="field"><label for="f-prob">Min probability</label><div class="range-row"><input id="f-prob" type="range" min="0.5" max="0.95" step="0.05" data-path="strategy.min_prob_up"><output id="probOut"></output></div></div></div>
          <div class="fields">
            ${fx ? sw("strategy.allow_short", "Allow Sell (short)", "robot boleh untung saat harga turun") : ""}
            ${sw("strategy.trend_filter", "Follow the trend", "Buy hanya saat tren naik" + (fx ? ", Sell hanya saat tren turun" : ""))}
            <div class="field"><label for="f-rsi">Skip if RSI above</label><div class="range-row"><input id="f-rsi" type="range" min="55" max="100" step="1" data-path="strategy.rsi_max"><output id="rsiOut"></output></div><div class="hint">jangan mengejar harga yang sudah naik terlalu cepat · 100 = off</div></div>
            ${num("strategy.min_rr", { label: "Min reward : risk", unit: "×", step: 0.1, hint: "0 = off" })}</div></div></div>

      <div class="group"><div><h3>Exit rules</h3><div class="desc">Kapan robot menutup posisi.</div></div>
        <div class="stack" style="gap:16px">
          <div class="field"><span class="label">Stop-loss &amp; take-profit</span><div id="slSeg"></div></div>
          <div class="fields" id="pctBox">${num("strategy.stop_loss_pct", { label: "Stop-loss", unit: "%", step: 0.05, min: 0.05 })}${num("strategy.take_profit_pct", { label: "Take-profit", unit: "%", step: 0.05, min: 0.05 })}</div>
          <div class="fields" id="atrBox">${num("strategy.sl_atr_mult", { label: "Stop-loss", unit: "× ATR", step: 0.5, min: 0.5 })}${num("strategy.tp_atr_mult", { label: "Take-profit", unit: "× ATR", step: 0.5, min: 0.5 })}</div>
          <div class="fields">
            ${sw("strategy.trailing_on", "Trailing stop", "stop-loss ikut naik supaya untung tidak hilang lagi")}
            ${num("strategy.trail_activate_pct", { label: "Activate after profit", unit: "%", step: 0.05, min: 0.05 })}
            ${num("strategy.trail_pct", { label: "Trail distance", unit: "%", step: 0.05, min: 0.05 })}
            ${num("strategy.max_hold_candles", { label: "Max holding time", unit: "candles", step: 1, min: 1 })}</div>
          <div class="notice" id="exitNote"></div></div></div>

      <div class="group"><div><h3>Accuracy filter</h3><div class="desc">Robot hanya trading di pair yang ramalannya terbukti cukup tepat.</div></div>
        <div class="fields">
          <div class="field"><label for="f-acc">Min accuracy</label><div class="range-row"><input id="f-acc" type="range" min="0" max="0.7" step="0.01" data-path="strategy.min_accuracy"><output id="accOut"></output></div><div class="hint">50% sama dengan lempar koin · 0 = off</div></div>
          ${num("strategy.min_accuracy_n", { label: "Rated after", unit: "forecasts", step: 5, min: 5 })}
          ${sw("strategy.require_proof", "Require proof first", "jangan trading sebelum jumlah ramalan di atas tercapai")}</div></div>

      <div class="group"><div><h3>AI model &amp; compute</h3><div class="desc">Dipakai robot Crypto dan Forex. Model lebih besar dan lebih banyak skenario biasanya lebih teliti, tapi lebih berat. Dengan GPU, Accurate tetap cepat.</div></div>
        <div class="stack" style="gap:16px">
          <div class="choices" id="models">${Object.entries(MODELS).map(([k, t]) => `<button type="button" class="choice" data-model="${k}"><b>${t[0]}</b><span>${t[1]}</span></button>`).join("")}</div>
          <div class="field"><span class="label">Run the AI on</span><div id="devSeg"></div>
            <div class="hint">${sys.gpu ? `Terdeteksi: <b>${esc(sys.gpu)}</b>${sys.vram_gb ? ` (${nf(sys.vram_gb, 0)} GB)` : ""}.` : sys.gpu_unused ? "Kartu grafis NVIDIA terdeteksi tapi PyTorch versi CPU. Tutup panel lalu jalankan MULAI lagi untuk memasang versi GPU." : "Tidak ada GPU yang bisa dipakai. Robot memakai CPU."}</div></div>
          <div class="fields">
            ${num("model.n_paths", { label: "Forecast scenarios", unit: "paths", step: 1, min: 2, max: 100, hint: "makin banyak, peluang naik/turun makin stabil. GPU: 30–50" })}
            ${num("model.lookback", { label: "History the AI reads", unit: "candles", step: 16, min: 64, max: 2048, hint: "Light: s/d 2048 · lainnya s/d 512" })}
            ${num("model.pred_len", { label: "Forecast horizon", unit: "candles", step: 1, min: 2, max: 120 })}</div>
          <div class="notice">Setelah mengganti model atau jumlah skenario, jalankan Backtest lagi supaya rapor akurasinya sesuai.</div></div></div>

      <div class="group"><div><h3>Advanced</h3><div class="desc">Biarkan saja kalau ragu.</div></div>
        <div class="fields">
          ${num("strategy.fee_pct", { label: fx ? "Spread" : "Trading fee", unit: "%", step: fx ? 0.005 : 0.01, hint: fx ? "0,02% kira-kira 2 pip EUR/USD" : "biaya per transaksi Tokocrypto" })}
          ${num("paper_balance", { label: "Simulation balance", unit: "USD", step: 100, min: 1 })}
          ${fx ? num("risk.leverage", { label: "Simulation leverage", unit: "×", step: 1, min: 1 }) : num("risk.max_order_size_quote", { label: "Hard cap per order", unit: "USDT", step: 1, min: 1 })}
          ${num("strategy.cooldown_candles", { label: "Cooldown after close", unit: "candles", step: 1 })}
          ${fx ? `<div class="field"><span class="label">Forex data source</span><div id="srcSeg"></div></div>` : ""}</div></div>

      <div class="group"><div><h3>Reset simulation</h3><div class="desc">Hapus riwayat dan saldo virtual ${MKT[m]}. Rapor akurasi tidak terhapus.</div></div>
        <div><button class="btn danger" id="resetBtn" data-busy="Resetting…">Reset ${MKT[m]} simulation</button></div></div>
    </div>
    <div class="savebar" id="savebar" hidden><span>Unsaved changes</span><span style="display:flex;gap:6px"><button class="btn ghost" id="revert">Discard</button><button class="btn light" id="save" data-busy="Saving…">Save changes</button></span></div>`;

  const getP = (p) => p.split(".").reduce((o, k) => o?.[k], d);
  const setP = (p, v) => { const ks = p.split("."); const last = ks.pop(); ks.reduce((o, k) => o[k], d)[last] = v; };
  const fill = () => $$("[data-path]").forEach((el) => { const v = getP(el.dataset.path); if (el.type === "checkbox") el.checked = !!v; else el.value = v ?? ""; });
  const derived = () => {
    if (!$("#capNote")) return;
    const s = d.strategy, r = d.risk;
    $("#capNote").innerHTML = fx ? `Kalau kena stop-loss, rugi sekitar <b>${nf(r.risk_pct, 1)}%</b> dari equity per posisi. Maksimal <b>${r.max_open_positions}</b> posisi sekaligus.`
      : `Tiap posisi memakai <b>${nf(r.order_size_quote, 0)} USDT</b>. Maksimal <b>${r.max_open_positions}</b> posisi, jadi modal terpakai paling banyak <b>${nf(r.order_size_quote * r.max_open_positions, 0)} USDT</b>.`;
    $("#probOut").textContent = p0(s.min_prob_up);
    $("#rsiOut").textContent = s.rsi_max >= 100 ? "off" : Math.round(s.rsi_max);
    $("#accOut").textContent = s.min_accuracy > 0 ? p0(s.min_accuracy) : "off";
    $("#customBox").hidden = presetKey !== "custom";
    $$("[data-preset]").forEach((b) => b.classList.toggle("on", b.dataset.preset === presetKey));
    $$("[data-model]").forEach((b) => b.classList.toggle("on", b.dataset.model === d.model.size));
    $("#pctBox").hidden = s.sl_mode === "atr"; $("#atrBox").hidden = s.sl_mode !== "atr";
    ["strategy.trail_activate_pct", "strategy.trail_pct"].forEach((p) => { $(`[data-path="${p}"]`).disabled = !s.trailing_on; });
    const hrs = (s.max_hold_candles * TF_SEC[d.timeframe]) / 3600;
    $("#exitNote").innerHTML = (s.sl_mode === "atr"
      ? `Batas ikut volatilitas: kalau harga biasanya bergerak 1% per candle, stop-loss di <b class="down">−${nf(s.sl_atr_mult, 1)}%</b> dan take-profit di <b class="up">+${nf(s.tp_atr_mult, 1)}%</b>.`
      : `Contoh Buy di 100: ditutup di <b class="down">${nf(100 * (1 - s.stop_loss_pct / 100), 2)}</b> (rugi) atau <b class="up">${nf(100 * (1 + s.take_profit_pct / 100), 2)}</b> (untung).`)
      + ` Posisi ditutup paksa setelah ${s.max_hold_candles} candle (±${hrs >= 48 ? nf(hrs / 24, 1) + " hari" : nf(hrs, 0) + " jam"}).`;
    $("#savebar").hidden = JSON.stringify(d) === JSON.stringify(saved);
  };
  view.addEventListener("input", (e) => {
    const el = e.target.closest("[data-path]"); if (!el) return;
    const v = el.type === "checkbox" ? el.checked : (el.type === "number" || el.type === "range") ? parseFloat(el.value) : el.value;
    if (typeof v === "number" && isNaN(v)) return;
    setP(el.dataset.path, v);
    if (el.dataset.path.startsWith("strategy.min_")) presetKey = presetOf();
    derived();
  });
  view.addEventListener("change", (e) => { if (e.target.type === "checkbox") e.target.dispatchEvent(new Event("input", { bubbles: true })); });
  $("#presets").onclick = (e) => {
    const b = e.target.closest("[data-preset]"); if (!b) return;
    presetKey = b.dataset.preset;
    if (PRESETS[m][presetKey]) [d.strategy.min_expected_return_pct, d.strategy.min_prob_up] = PRESETS[m][presetKey];
    fill(); derived();
  };
  $("#models").onclick = (e) => { const b = e.target.closest("[data-model]"); if (b) { d.model.size = b.dataset.model; derived(); } };
  seg($("#devSeg"), { auto: "Auto", gpu: sys.gpu ? `GPU · ${sys.gpu}` : "GPU", cpu: "CPU" }, d.model.device || "auto", (v) => { d.model.device = v; derived(); });
  seg($("#slSeg"), { persen: "Fixed %", atr: "Follow volatility (ATR)" }, d.strategy.sl_mode, (v) => { d.strategy.sl_mode = v; derived(); });
  seg($("#tfSeg"), TF_LONG, d.timeframe, (v) => { d.timeframe = v; derived(); });
  if (fx) seg($("#srcSeg"), { auto: "Auto", mt5: "MetaTrader 5", yahoo: "Yahoo Finance" }, d.source || "auto", (v) => { d.source = v; derived(); });
  $$("[data-mode]").forEach((b) => b.onclick = async () => {
    const want = b.dataset.mode;
    if (want === d.mode) return;
    if (want === "live") {
      if (!connected) { toast(`Sambungkan ${fx ? "MetaTrader 5" : "Tokocrypto"} dulu di Account.`, "err"); return; }
      const typed = await modal({ title: `Switch ${MKT[m]} to Live?`, confirm: "Switch to Live", danger: true,
        body: `<p>Robot ${MKT[m]} akan trading memakai <b>uang sungguhan</b> dan bisa rugi. Sebaiknya jalankan Simulation 1–2 minggu dulu, lalu mulai dengan modal kecil.</p>`,
        input: { label: `Ketik <b>${esc(acct.confirm_text)}</b>`, placeholder: acct.confirm_text } });
      if (typed == null) return;
      try { const r = await api(`/api/${m}/mode`, { mode: "live", confirm: typed }); toast(r.restarted ? "Live mode on, bot restarted." : "Live mode on."); } catch (e) { toast(e.message, "err", 6000); return; }
    } else {
      if (!(await modal({ title: "Back to Simulation?", body: "<p>Posisi live yang masih terbuka tetap ada di akunmu dan tidak lagi dijaga robot.</p>", confirm: "Switch to Simulation" }))) return;
      try { await api(`/api/${m}/mode`, { mode: "paper" }); toast("Simulation mode on."); } catch (e) { toast(e.message, "err"); return; }
    }
    await refreshStatus(); route();
  });
  $("#resetBtn").onclick = async (e) => {
    const btn = e.currentTarget;
    if (!(await modal({ title: `Reset ${MKT[m]} simulation?`, body: "<p>Riwayat trade dan saldo virtual dihapus.</p>", confirm: "Reset", danger: true }))) return;
    busy(btn, async () => { try { await api(`/api/${m}/reset-paper`, {}); toast("Simulation reset."); } catch (err) { toast(err.message, "err"); } });
  };
  $("#revert").onclick = () => route();
  $("#save").onclick = (e) => busy(e.currentTarget, async () => {
    try {
      const r = await api(`/api/${m}/config`, { timeframe: d.timeframe, strategy: d.strategy, risk: d.risk, paper_balance: d.paper_balance, source: d.source, model: d.model });
      saved = structuredClone(d); toast(r.restarted ? "Saved. Bot restarted." : "Saved."); derived(); refreshStatus();
    } catch (err) { toast(err.message, "err"); }
  });
  fill(); derived();
};

/* ===================================================================== ACCOUNT (global) */
PAGES.account = async (view) => {
  const render = async () => {
    let a;
    try { a = await api("/api/account"); } catch (e) { view.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; return; }
    const m5 = a.mt5;
    const theme = document.documentElement.dataset.theme || "system";
    view.innerHTML = `
      <div class="head"><div><h1>Account</h1><p>Sambungkan akun broker. Mode Simulation atau Live diatur per market di halaman Settings masing-masing.</p></div><div id="themeSeg"></div></div>
      <div class="grid halves">
        <section class="card"><div class="card-head"><h2>Tokocrypto <span class="tag">Crypto</span></h2><span class="tag ${a.has_keys ? "long" : ""}">${a.has_keys ? "Connected" : "Not connected"}</span></div>
          <p class="soft small" style="margin-top:0">Diperlukan untuk trading kripto Live. Simulasi tidak perlu.</p>
          <ol class="ol"><li>Di Tokocrypto buka <b>Manajemen API</b>, lalu buat API key baru.</li><li>Aktifkan izin <b>baca</b> dan <b>spot trading</b> saja. <b>Jangan aktifkan withdraw.</b></li><li>Tempel di bawah, lalu simpan.</li></ol>
          <form id="tkForm" class="stack" style="gap:12px" autocomplete="off">
            <div class="field"><label for="k1">API key</label><input class="input" id="k1" type="password" placeholder="${esc(a.key || "paste API key")}"></div>
            <div class="field"><label for="k2">Secret key</label><input class="input" id="k2" type="password" placeholder="${esc(a.secret || "paste secret key")}"></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn dark" type="submit" data-busy="Saving…">Save</button><button class="btn" type="button" id="tkTest" data-busy="Testing…" ${a.has_keys ? "" : "disabled"}>Test connection</button></div>
            <div id="tkOut"></div></form></section>
        <section class="card"><div class="card-head"><h2>MetaTrader 5 <span class="tag">Forex</span></h2><span class="tag ${m5.enabled ? "long" : ""}">${m5.enabled ? "Enabled" : "Off"}</span></div>
          <p class="soft small" style="margin-top:0">Untuk data dan order forex. Hampir semua broker forex di Indonesia memakai MT5, dan kebanyakan punya <b>akun demo gratis</b>. Tanpa MT5, forex tetap bisa dianalisa dan disimulasikan dengan data Yahoo Finance.</p>
          ${!m5.installed ? `<div class="notice" style="margin-bottom:12px">${m5.windows ? "Library MetaTrader5 belum terpasang. Tutup panel lalu jalankan MULAI lagi." : "MT5 hanya bisa disambungkan di Windows. Di komputer ini forex memakai data Yahoo Finance."}</div>` : ""}
          <ol class="ol"><li>Install aplikasi <b>MetaTrader 5</b> dari broker kamu, lalu login (akun demo juga bisa).</li><li>Di MT5 nyalakan tombol <b>Algo Trading</b> sampai hijau.</li><li>Isi di bawah. Kalau MT5 sudah login, login/password/server boleh dikosongkan.</li></ol>
          <form id="mtForm" class="stack" style="gap:12px" autocomplete="off">
            <label class="check"><input type="checkbox" id="mtOn" ${m5.enabled ? "checked" : ""}><span class="box"></span><span class="t"><b>Use MetaTrader 5 for Forex</b><span>data dan order forex lewat MT5</span></span></label>
            <div class="fields"><div class="field"><label for="m1">Login</label><input class="input" id="m1" inputmode="numeric" value="${esc(m5.login)}" placeholder="e.g. 51234567"></div>
              <div class="field"><label for="m2">Password</label><input class="input" id="m2" type="password" placeholder="${m5.has_password ? "saved" : "MT5 password"}"></div>
              <div class="field"><label for="m3">Server</label><input class="input" id="m3" value="${esc(m5.server)}" placeholder="e.g. Broker-Demo"></div>
              <div class="field"><label for="m4">terminal64.exe <span class="faint">(optional)</span></label><input class="input" id="m4" value="${esc(m5.path)}" placeholder="C:\\Program Files\\MetaTrader 5\\terminal64.exe"></div></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn dark" type="submit" data-busy="Saving…">Save</button><button class="btn" type="button" id="mtTest" data-busy="Connecting…" ${m5.installed ? "" : "disabled"}>Test connection</button></div>
            <div id="mtOut"></div></form></section>
      </div>`;
    seg($("#themeSeg"), { system: "System", light: "Light", dark: "Dark" }, theme, (v) => { applyTheme(v); });
    $("#tkForm").onsubmit = (e) => { e.preventDefault(); busy(e.submitter, async () => { try { await api("/api/account/keys", { key: $("#k1").value, secret: $("#k2").value }); toast("Keys saved."); render(); } catch (err) { toast(err.message, "err"); } }); };
    $("#tkTest").onclick = (e) => busy(e.currentTarget, async () => {
      try { const r = await api("/api/account/test", {}); $("#tkOut").innerHTML = `<div class="notice ok"><span><b>Connected to Tokocrypto.</b> Saldo USDT bebas: ${nf(r.usdt, 2)}</span></div>`; }
      catch (err) { $("#tkOut").innerHTML = `<div class="notice err">${esc(err.message)}</div>`; }
    });
    $("#mtForm").onsubmit = (e) => {
      e.preventDefault();
      busy(e.submitter, async () => {
        try { await api("/api/mt5", { enabled: $("#mtOn").checked, login: $("#m1").value, password: $("#m2").value, server: $("#m3").value, path: $("#m4").value }); toast("MT5 settings saved."); S.pairs = {}; refreshStatus(); render(); }
        catch (err) { toast(err.message, "err"); }
      });
    };
    $("#mtTest").onclick = (e) => busy(e.currentTarget, async () => {
      try {
        const r = await api("/api/mt5/test", {});
        $("#mtOut").innerHTML = `<div class="notice ok"><span><b>Connected to MT5 ${r.demo ? "(demo account)" : "(real account)"}.</b> ${esc(r.name || "")} @ ${esc(r.server)}, saldo ${nf(r.balance, 2)} ${esc(r.currency)}, leverage 1:${r.leverage}.${r.trade_allowed ? "" : " <b class='down'>Algo Trading belum aktif.</b>"}</span></div>`;
      } catch (err) { $("#mtOut").innerHTML = `<div class="notice err">${esc(err.message)}</div>`; }
    });
  };
  render();
};

/* ===================================================================== mulai */
refreshStatus().then((s) => {
  if (s && !s.setup_ok) toast("Setup belum selesai: folder Kronos belum ada. Tutup panel lalu jalankan MULAI lagi.", "err", 12000);
  route();
});
setInterval(refreshStatus, 8000);
