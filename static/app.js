/* kronos — panel robot trading (vanilla JS, tanpa build) */
"use strict";

/* ===================================================================== utilitas */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TF = { "15m": "15 menit", "30m": "30 menit", "1h": "1 jam", "4h": "4 jam", "1d": "1 hari" };
const TF_SEC = { "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400 };
const VENUE = { crypto: "kripto", forex: "forex" };
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
function usd(v) { return v == null || isNaN(v) ? "–" : `${v < 0 ? "−" : ""}$${nf(Math.abs(v), 2)}`; }
function sUsd(v) { return v == null || isNaN(v) ? "–" : `${v >= 0 ? "+" : "−"}$${nf(Math.abs(v), 2)}`; }
function pct(v, d = 2) { return v == null || isNaN(v) ? "–" : `${v >= 0 ? "+" : "−"}${nf(Math.abs(v), d)}%`; }
function p0(v) { return v == null || isNaN(v) ? "–" : `${Math.round(v * 100)}%`; }
function tone(v) { return v == null || isNaN(v) ? "" : v >= 0 ? "up" : "down"; }
function hhmm(ms) { return new Date(ms).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }); }
function mkt(label) { const [b, q] = String(label).split("/"); return `<span class="mkt">${esc(b)}<small>/${esc(q || "")}</small></span>`; }
function venueTag(v) { return `<span class="tag venue">${VENUE[v] || esc(v)}</span>`; }
function sideTag(side) { return side === "short" ? `<span class="tag sell">sell</span>` : `<span class="tag buy">buy</span>`; }
const ARROWS = {
  NAIK: ["up", "naik", '<path d="M12 19V5M6 11l6-6 6 6"/>'],
  TURUN: ["down", "turun", '<path d="M12 5v14M6 13l6 6 6-6"/>'],
  SAMPING: ["flat", "datar", '<path d="M5 12h14M14 7l5 5-5 5"/>'],
};
function arrow(dir) { const a = ARROWS[dir] || ARROWS.SAMPING; return `<span class="arrow ${a[0]}"><svg viewBox="0 0 24 24">${a[2]}</svg>${a[1]}</span>`; }
const ACT = { BELI: ["buy", "buka buy"], JUAL: ["sell", "buka sell"], TAHAN: ["ai", "tahan"], TUTUP: ["", "tutup"], TUNGGU: ["", "nunggu"], LEWATI: ["", "lewati"], ERROR: ["sell", "gagal"] };
function actTag(a) { const x = ACT[a] || ["", String(a || "–").toLowerCase()]; return `<span class="tag ${x[0]}">${x[1]}</span>`; }

async function api(path, body, method) {
  const opt = { method: method || (body !== undefined ? "POST" : "GET"), headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opt); } catch { throw new Error("Panel nggak nyambung ke server. Pastikan jendela MULAI masih terbuka."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Gagal (${res.status})`);
  return data;
}
function toast(msg, kind = "ok", ms = 3800) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`; el.textContent = msg;
  $("#toasts").append(el); setTimeout(() => el.remove(), ms);
}
function modal({ title, body = "", confirm = "Lanjut", danger = false, input = null, cancel = "batal" }) {
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
  btn.innerHTML = `<span class="spinner"></span>${esc(btn.dataset.busy || "sebentar…")}`;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = html; }
}

/* ===================================================================== tema */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("kronos-theme", t); } catch { /* penyimpanan tidak tersedia */ }
  route();
}
$("#themeBtn").addEventListener("click", () => {
  const t = document.documentElement.dataset.theme;
  const dark = t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(dark ? "light" : "dark");
});

/* ===================================================================== grafik */
function makeChart(el, sym, extra = {}) {
  return LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, textColor: cssv("--ink-3"), fontFamily: cssv("--text") || "sans-serif", fontSize: 12 },
    grid: { vertLines: { color: hexA(cssv("--line"), 0.7) }, horzLines: { color: hexA(cssv("--line"), 0.7) } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 4 },
    crosshair: { mode: 1, vertLine: { color: cssv("--ink-3"), labelBackgroundColor: cssv("--ink") }, horzLine: { color: cssv("--ink-3"), labelBackgroundColor: cssv("--ink") } },
    localization: { locale: "id-ID", priceFormatter: (v) => (sym === "$" ? usd(v) : price(v, sym)) },
    ...extra,
  });
}

/* ===================================================================== router */
const S = { status: null, pairs: {} };
let cur = { timers: [], charts: [] };
function every(ms, fn) { fn(); const id = setInterval(fn, ms); cur.timers.push(id); return id; }
function teardown() {
  cur.timers.forEach(clearInterval);
  cur.charts.forEach((c) => { try { c.remove(); } catch { /* sudah dihapus */ } });
  cur = { timers: [], charts: [] };
}
const ROUTES = {};
function route() {
  const name = (location.hash.replace("#/", "") || "beranda").split("?")[0];
  const key = ROUTES[name] ? name : "beranda";
  teardown();
  $$(".nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === key));
  const view = $("#view"); view.innerHTML = "";
  ROUTES[key](view); view.focus({ preventScroll: true }); window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

async function refreshStatus() {
  try { S.status = await api("/api/status"); } catch { return null; }
  const s = S.status;
  const st = $("#modeSticker");
  st.hidden = false; st.className = `sticker ${s.mode === "live" ? "live" : ""}`;
  st.textContent = s.mode === "live" ? "live" : "simulasi";
  st.title = s.mode === "live" ? "Robot pakai uang sungguhan" : "Robot pakai uang virtual";
  $("#robotDot").className = `robot-dot ${s.crashed ? "warn" : s.running ? "on" : ""}`;
  $("#robotDot").title = s.crashed ? "robot berhenti karena masalah" : s.running ? "robot nyala" : "robot mati";
  return s;
}
async function loadPairs(venue) {
  if (S.pairs[venue]) return S.pairs[venue];
  const r = await api(`/api/pairs?venue=${venue}`).catch(() => ({ pairs: [] }));
  S.pairs[venue] = r.pairs || [];
  return S.pairs[venue];
}
function labelOf(sym) {
  if (!isFx(sym)) return sym;
  const c = String(sym).toUpperCase().replace(/[^A-Z]/g, "");
  return `${c.slice(0, 3)}/${c.slice(3, 6)}`;
}
const clean = (s) => String(s).toUpperCase().replace(/[^A-Z]/g, "");

/* pemilih pasar (kripto & forex, bisa diketik) */
function picker(el, { value = "", venue = null, onPick, placeholder = "cari pasar, mis. EURUSD atau BTC" }) {
  el.classList.add("picker");
  el.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>
    <input class="input" value="${esc(value ? labelOf(value) : "")}" placeholder="${esc(placeholder)}" aria-label="Pilih pasar" autocomplete="off" spellcheck="false"><div class="picker-list" hidden></div>`;
  const inp = $("input", el), list = $(".picker-list", el);
  let items = [], hl = 0;
  const show = async () => {
    const venues = venue ? [venue] : ["crypto", "forex"];
    const t = clean(inp.value);
    const groups = [];
    for (const v of venues) {
      const all = await loadPairs(v);
      const f = all.filter((p) => !t || clean(p.symbol).includes(t));
      if (t) f.sort((a, b) => (clean(b.symbol).startsWith(t) ? 1 : 0) - (clean(a.symbol).startsWith(t) ? 1 : 0));
      groups.push([v, f.slice(0, 40)]);
    }
    items = groups.flatMap(([, f]) => f.map((p) => p.symbol));
    const custom = !items.length && t.length >= 6 && (!venue || venue === "forex");   // simbol broker sendiri
    if (custom) items = [inp.value.trim().toUpperCase()];
    hl = 0;
    let i = 0;
    list.innerHTML = custom ? `<button type="button" data-p="${esc(items[0])}" class="hl">pakai “${esc(items[0])}” (simbol forex)</button>`
      : groups.map(([v, f]) => (f.length ? `<div class="grp">${VENUE[v]}</div>` + f.map((p) => `<button type="button" data-p="${esc(p.symbol)}" class="${i++ === 0 ? "hl" : ""}">${mkt(p.label)}</button>`).join("") : "")).join("")
        || `<div class="empty">nggak ketemu</div>`;
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
const ICON_POWER = '<svg viewBox="0 0 24 24"><path d="M12 4v7"/><path d="M7.5 7.2a7 7 0 1 0 9 0"/></svg>';

/* ===================================================================== BERANDA */
ROUTES.beranda = (view) => {
  view.innerHTML = `
    <div id="crash"></div>
    <section class="hero" id="hero"></section>
    <section id="steps"></section>
    <section class="stats" id="stats"></section>
    <div class="grid split">
      <div class="stack">
        <section class="card"><div class="card-head"><h2>posisi terbuka</h2><span id="closeAllWrap"></span></div><div id="positions"></div></section>
        <section class="card"><div class="card-head"><h2>perjalanan aset</h2><small id="eqNote"></small></div><div class="chart md" id="eqChart"></div><div id="eqEmpty"></div></section>
      </div>
      <div class="stack">
        <section class="card"><div class="card-head"><h2>kata robot</h2><small>keputusan terakhir</small></div><div class="rows" id="decisions"></div></section>
        <section class="card"><div class="card-head"><h2>rapor akurasi</h2><a class="faint" href="#/setelan" style="font-size:13px">atur batas</a></div><div id="acc"></div></section>
        <section class="card"><div class="card-head"><h2>aktivitas</h2></div><div class="feed" id="feed"></div></section>
      </div>
    </div>`;

  const chart = makeChart($("#eqChart"), "$");
  cur.charts.push(chart);
  const eqS = chart.addAreaSeries({ lineColor: cssv("--ink"), topColor: hexA(cssv("--ink"), 0.12), bottomColor: hexA(cssv("--ink"), 0), lineWidth: 2, priceLineVisible: false });
  let eqLen = -1;

  const renderHero = (s) => {
    if (!s) return;
    const n = s.symbols.length, live = s.mode === "live";
    let h = "robotnya lagi istirahat.";
    let p = `Nyalain buat mulai mantau ${n} pasar tiap ${TF[s.timeframe]}. Selama robot mati, posisi yang masih kebuka nggak dijaga stop-loss.`;
    if (s.running) {
      if (s.state === "memuat model") { h = "lagi nyiapin otak AI…"; p = "Pertama kali bisa beberapa menit karena modelnya diunduh dulu."; }
      else if (s.state === "meramal") { h = "lagi baca pasar…"; p = "Robot meramal tiap pasar, lalu memutuskan buka, tahan, atau tutup posisi."; }
      else {
        h = s.paused ? "robot cuma jaga posisi." : `robot lagi mantau ${n} pasar.`;
        const left = Math.max(0, (s.next_run || Date.now()) - Date.now());
        p = `Ramalan berikutnya jam ${s.next_run ? hhmm(s.next_run) : "–"}${left > 60000 ? ` (${Math.round(left / 60000)} menit lagi)` : ""}. Stop-loss, target, dan trailing stop dicek tiap menit.`;
        if (s.paused) p = "Robot nggak buka posisi baru dulu, tapi posisi yang ada tetap dijaga. " + p;
      }
    }
    if (live) p += " Mode live: ini uang sungguhan.";
    $("#hero").innerHTML = `
      <button class="toggle ${live ? "live" : ""} ${s.running && s.state !== "berjalan" ? "busy" : ""}" role="switch" aria-checked="${s.running}" id="power" aria-label="${s.running ? "Matikan robot" : "Nyalakan robot"}">
        <span class="lbl on">nyala</span><span class="lbl off">mati</span><span class="knob">${ICON_POWER}</span></button>
      <div><h1>${esc(h)}</h1><p>${esc(p)}</p>
        <div class="row"><label class="check"><input type="checkbox" id="pause" ${s.paused ? "checked" : ""}><span class="box"></span><span class="t"><b>jeda posisi baru</b><span>posisi yang ada tetap dijaga</span></span></label></div></div>`;
    $("#power").onclick = async (e) => {
      const btn = e.currentTarget;
      if (s.running) {
        const ok = await modal({ title: "matiin robot?", body: "<p>Posisi yang masih kebuka <b>nggak ikut ditutup</b> dan nggak dijaga robot selama mati. Khusus forex lewat MT5, stop-loss-nya tetap ada di server broker.</p>", confirm: "matiin", danger: true });
        if (!ok) return;
        btn.classList.add("busy");
        try { await api("/api/bot/stop", {}); toast("Robot dimatikan."); } catch (err) { toast(err.message, "err"); }
      } else {
        if (live) {
          const ok = await modal({ title: "nyalain di mode live?", body: "<p>Robot bakal buka dan tutup posisi pakai <b>uang sungguhan</b> di akun kamu.</p>", confirm: "nyalain", danger: true });
          if (!ok) return;
        }
        btn.classList.add("busy"); btn.setAttribute("aria-checked", "true");
        try { await api("/api/bot/start", {}); toast("Robot dinyalakan."); } catch (err) { toast(err.message, "err"); }
      }
      renderHero(await refreshStatus());
    };
    $("#pause").onchange = async (e) => {
      try { await api("/api/bot/pause", { value: e.target.checked }); toast(e.target.checked ? "Posisi baru dijeda." : "Robot boleh buka posisi lagi."); }
      catch (err) { toast(err.message, "err"); e.target.checked = !e.target.checked; }
    };
    $("#crash").innerHTML = s.crashed ? `<div class="err-box" style="margin-bottom:20px"><b>Robot berhenti karena ada masalah.</b> Baca pesannya, beresin penyebabnya, terus nyalain lagi.<pre class="log">${esc(s.crash_log || "(tidak ada pesan)")}</pre><button class="btn sm" id="dismiss" style="margin-top:10px">tutup pesan</button></div>` : "";
    $("#dismiss")?.addEventListener("click", async () => { await api("/api/bot/dismiss-crash", {}); renderHero(await refreshStatus()); });
    $("#steps").innerHTML = s.has_signals ? "" : `<div class="steps">
      <a class="step done" href="#/setelan"><span class="n">1</span><b>pilih pasar</b><span>${n} pasar dipilih. Tambah forex atau kripto di setelan.</span></a>
      <a class="step ${s.has_backtest ? "done" : ""}" href="#/uji"><span class="n">2</span><b>uji dulu</b><span>Lihat seberapa tepat ramalannya di data lama sebelum dipakai.</span></a>
      <a class="step" href="#/beranda" id="stepRun"><span class="n">3</span><b>nyalain robot</b><span>Mulai di mode simulasi: uangnya virtual, harganya asli.</span></a></div>`;
    $("#stepRun")?.addEventListener("click", (e) => { e.preventDefault(); $("#power").click(); });
  };

  const renderOverview = (o) => {
    $("#stats").innerHTML = `
      <div class="stat"><div class="k">total aset</div><div class="v">${usd(o.equity)}</div><div class="d ${tone(o.equity_change_pct)}">${o.equity_change_pct == null ? "belum ada catatan" : pct(o.equity_change_pct) + " sejak awal"}</div></div>
      <div class="stat"><div class="k">cuan hari ini</div><div class="v ${tone(o.pnl_today)}">${sUsd(o.pnl_today)}</div><div class="d">dari posisi yang sudah ditutup</div></div>
      <div class="stat"><div class="k">cuan total</div><div class="v ${tone(o.pnl_total)}">${sUsd(o.pnl_total)}</div><div class="d">${o.trades} trade</div></div>
      <div class="stat"><div class="k">posisi</div><div class="v">${o.positions.length}<span class="faint" style="font-size:.6em"> / ${o.max_positions}</span></div><div class="d">terbuka dari maksimal</div></div>
      <div class="stat"><div class="k">trade menang</div><div class="v">${o.win_pct == null ? "–" : Math.round(o.win_pct) + "%"}</div><div class="d">dari ${o.trades} trade</div></div>`;

    if (o.equity_series.length !== eqLen) { eqS.setData(o.equity_series); if (eqLen <= 0) chart.timeScale().fitContent(); eqLen = o.equity_series.length; }
    $("#eqChart").style.display = o.equity_series.length > 1 ? "" : "none";
    $("#eqEmpty").innerHTML = o.equity_series.length > 1 ? "" : `<div class="empty"><b>grafiknya masih kosong</b>Muncul setelah robot jalan beberapa candle.</div>`;
    $("#eqNote").textContent = o.mode === "live" ? "saldo akun + nilai posisi" : "saldo virtual + nilai posisi";

    $("#closeAllWrap").innerHTML = o.positions.length > 1 ? `<button class="btn sm danger" id="closeAll">tutup semua</button>` : "";
    $("#positions").innerHTML = o.positions.length ? o.positions.map((p) => {
      const frac = p.sl && p.tp && p.price_now ? Math.min(1, Math.max(0, (p.price_now - p.sl) / (p.tp - p.sl))) : null;
      return `<div class="pos">
        <div><div class="meta">${mkt(p.label)} ${sideTag(p.side)} ${venueTag(p.venue)}</div>
          <div class="soft" style="font-size:13px;margin-top:4px">${p.lots ? nf(p.lots, 2) + " lot" : "modal " + usd(p.cost)}, dibuka ${esc(String(p.entry_time).slice(5, 16))}</div></div>
        <div class="pnl"><b class="${tone(p.pnl_pct_now)}">${pct(p.pnl_pct_now)}</b><span class="${tone(p.pnl_now)}" style="font-size:13px">${sUsd(p.pnl_now)}</span></div>
        ${frac != null ? `<div class="lane" title="posisi harga di antara stop-loss (kiri) dan target (kanan)"><i style="left:${(frac * 100).toFixed(1)}%"></i></div>` : ""}
        <div class="levels"><div><span>stop-loss</span><b class="down">${price(p.sl, p.symbol)}</b></div><div><span>buka → sekarang</span>${price(p.entry_price, p.symbol)} → ${price(p.price_now, p.symbol)}</div><div style="text-align:right"><span>target</span><b class="up">${price(p.tp, p.symbol)}</b></div></div>
        <div style="grid-column:1/-1;text-align:right"><button class="btn sm" data-close="${p.id}" data-label="${esc(p.label)}">tutup posisi</button></div></div>`;
    }).join("") : `<div class="empty"><b>belum ada posisi</b>Robot buka posisi sendiri kalau ramalannya cukup kuat.</div>`;
    $$("[data-close]").forEach((b) => b.onclick = async () => {
      const ok = await modal({ title: `tutup ${b.dataset.label}?`, body: "<p>Posisi ditutup di harga pasar sekarang.</p>", confirm: "tutup sekarang", danger: true });
      if (ok) busy(b, async () => { try { toast((await api("/api/positions/close", { ids: [Number(b.dataset.close)] })).message); } catch (e) { toast(e.message, "err"); } load(); });
    });
    $("#closeAll")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const ok = await modal({ title: "tutup semua posisi?", body: `<p>${o.positions.length} posisi ditutup di harga pasar sekarang.</p>`, confirm: "tutup semua", danger: true });
      if (ok) busy(btn, async () => { try { toast((await api("/api/positions/close", { ids: ["ALL"] })).message); } catch (err) { toast(err.message, "err"); } load(); });
    });

    $("#decisions").innerHTML = o.decisions.length ? o.decisions.map((d) => `
      <div class="rowi"><a class="l" href="#/analisa?${encodeURIComponent(d.symbol)}">${mkt(d.label)} ${arrow(d.direction)}</a>
        <div class="r">${actTag(d.action)}</div>
        <div class="note">Ramalan <b class="${tone(d.exp_ret_pct)}">${pct(d.exp_ret_pct)}</b>, peluang naik ${p0(d.prob_up)}, turun ${p0(d.prob_down)}. ${esc(d.reason || "")}</div></div>`).join("")
      : `<div class="empty"><b>belum ada keputusan</b>Muncul setelah robot meramal pertama kali.</div>`;

    $("#feed").innerHTML = o.events.length ? o.events.map((e) => `<div><time>${esc(String(e.time).slice(11, 16))}</time><span class="${esc(e.level)}">${esc(e.message)}</span></div>`).join("")
      : `<div style="grid-template-columns:1fr" class="faint">Belum ada aktivitas.</div>`;
  };

  const renderAcc = (a) => {
    const rows = a.rows || [];
    $("#acc").innerHTML = rows.length ? rows.map((r) => {
      const cls = r.state === "lolos" ? "ok" : r.state === "kurang" ? "low" : "";
      return `<div class="acc"><span>${mkt(r.label)}</span>
        <span class="bar" title="garis tegak = batas minimal">${r.n ? `<i class="${cls}" style="width:${(r.hit || 0) * 100}%"></i>` : ""}${r.need ? `<u style="left:${r.need * 100}%"></u>` : ""}</span>
        <span class="v">${r.hit == null ? "–" : p0(r.hit)}<small>${r.n ? `dari ${r.n}` : "belum dinilai"}</small></span></div>`;
    }).join("") + `<p class="faint" style="font-size:13px;margin:12px 0 0">Seberapa sering arah ramalan AI benar, dari uji strategi dan ramalan robot yang sudah lewat waktunya.${rows.some((r) => r.blocking) ? " Pasar yang di bawah garis nggak akan dibuka posisinya." : ""}</p>`
      : `<div class="empty">Belum ada pasar.</div>`;
  };

  const load = async () => { try { renderOverview(await api("/api/overview")); } catch { /* koneksi sesaat */ } };
  every(4000, async () => renderHero(await refreshStatus()));
  every(7000, load);
  every(30000, async () => { try { renderAcc(await api("/api/accuracy")); } catch { /* abaikan */ } });
};

/* ===================================================================== ANALISA */
ROUTES.analisa = async (view) => {
  const st = S.status || (await refreshStatus()) || { symbols: [{ symbol: "BTC/USDT" }], timeframe: "1h" };
  const fromHash = decodeURIComponent(location.hash.split("?")[1] || "");
  const A = { sym: fromHash || st.symbols[0]?.symbol || "BTC/USDT", tf: st.timeframe, signal: null, fitted: false, scan: st.symbols.map((x) => x.symbol) };

  view.innerHTML = `
    <div class="head"><div><h1>analisa</h1><p>Harga live plus ke mana AI kira harga bakal jalan. Garis biru tebal itu perkiraan tengahnya, garis putus-putus batas atas dan bawah kemungkinannya.</p></div></div>
    <div class="toolbar" style="margin-bottom:18px"><div id="symPick"></div><div id="tfPick"></div><div class="grow"></div>
      <button class="btn" id="scanOpen"><svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h10M4 18h6"/></svg>bandingin beberapa pasar</button>
      <button class="btn ai" id="fcBtn" data-busy="AI lagi meramal…"><svg viewBox="0 0 24 24"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/></svg>ramal sekarang</button></div>
    <div class="grid split">
      <section class="card">
        <div class="price-line"><span id="phSym" style="font-size:18px"></span><span class="px" id="phPx">–</span><span id="phChg"></span><span class="faint" id="phTime" style="margin-left:auto;font-size:13px"></span></div>
        <div class="chart" id="mainChart"></div><div class="chart rsi" id="rsiChart"></div>
        <div class="legend"><span><i style="background:var(--ai)"></i>ramalan AI</span><span><i style="background:repeating-linear-gradient(90deg,var(--ai) 0 4px,transparent 4px 7px);opacity:.7"></i>batas atas & bawah kemungkinan</span><span><i style="background:var(--ink-3)"></i>tren cepat (EMA 50)</span><span><i style="background:var(--ink)"></i>tren besar (EMA 200)</span><span><i style="background:var(--ink-2);height:2px"></i>RSI</span></div>
      </section>
      <section class="card" id="verdict"></section>
    </div>
    <section class="card" id="scanCard" style="margin-top:18px" hidden></section>`;

  let step = TF_SEC[A.tf];
  const mkCharts = () => {
    cur.charts.forEach((c) => c.remove()); cur.charts = [];
    const main = makeChart($("#mainChart"), A.sym);
    const rsiC = makeChart($("#rsiChart"), A.sym, { timeScale: { visible: false }, localization: { locale: "id-ID", priceFormatter: (v) => Math.round(v) } });
    cur.charts.push(main, rsiC);
    const up = cssv("--up"), down = cssv("--down"), ai = cssv("--ai");
    const vol = main.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    main.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    const band = { color: hexA(ai, 0.55), lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
    const hi = main.addLineSeries(band);
    const lo = main.addLineSeries(band);
    const candles = main.addCandlestickSeries({ upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down });
    const e50 = main.addLineSeries({ color: cssv("--ink-3"), lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    const e200 = main.addLineSeries({ color: cssv("--ink"), lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    const fc = main.addLineSeries({ color: ai, lineWidth: 3, priceLineVisible: false, title: "AI" });
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
      step = d.step;
      C.candles.setData(d.candles);
      C.vol.setData(d.volume.map((v) => ({ time: v.time, value: v.value, color: hexA(v.up ? cssv("--up") : cssv("--down"), 0.22) })));
      C.e50.setData(d.ema50); C.e200.setData(d.ema200); C.rs.setData(d.rsi);
      drawForecast();
      if (!A.fitted) { C.main.timeScale().setVisibleLogicalRange({ from: d.candles.length - 110, to: d.candles.length + 16 }); A.fitted = true; }
      const chg = d.prev_close ? (d.last / d.prev_close - 1) * 100 : null;
      $("#phSym").innerHTML = mkt(d.label) + " " + venueTag(d.venue);
      $("#phPx").textContent = price(d.last, A.sym);
      $("#phChg").innerHTML = `<span class="${tone(chg)}">${pct(chg)}</span> <span class="faint">candle ini</span>`;
      const src = { mt5: "MetaTrader 5", yahoo: "Yahoo Finance", tokocrypto: "Tokocrypto" }[d.source] || d.source;
      $("#phTime").textContent = `data ${src}, ${new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    } catch (e) { $("#phTime").innerHTML = `<span class="down">${esc(e.message)}</span>`; }
  };

  const renderVerdict = () => {
    const s = A.signal, el = $("#verdict");
    if (!s) {
      el.innerHTML = `<div class="card-head"><h2>arahnya ke mana?</h2></div><div class="empty"><b>belum ada ramalan buat ${esc(labelOf(A.sym))}</b>Klik <b>ramal sekarang</b> biar AI kasih perkiraan arah harga berikutnya.<br><button class="btn ai" id="fcBtn2">ramal sekarang</button></div>`;
      $("#fcBtn2").onclick = () => $("#fcBtn").click();
      return;
    }
    const a = ARROWS[s.direction] || ARROWS.SAMPING;
    const hrs = (s.path.length * step) / 3600;
    const horizon = hrs >= 24 ? `${nf(hrs / 24, hrs % 24 ? 1 : 0)} hari` : `${nf(hrs, hrs % 1 ? 1 : 0)} jam`;
    const mid = Math.max(0, 1 - s.prob_up - s.prob_down);
    const note = s.would === "long" ? ["go", "kalau sekarang, robot bakal buy"] : s.would === "short" ? ["go-short", "kalau sekarang, robot bakal sell"] : ["wait", "robot nunggu dulu"];
    el.innerHTML = `
      <div class="card-head"><h2>arahnya ke mana?</h2><small>${esc(s.source)}</small></div>
      <div class="verdict-word ${a[0]}">${a[1]}</div>
      <div class="soft">AI kira harga ${s.exp_ret_pct >= 0 ? "naik" : "turun"} <b class="${tone(s.exp_ret_pct)}">${pct(s.exp_ret_pct)}</b> dalam ${horizon} ke depan.</div>
      <div class="tug" title="pembagian skenario AI"><i class="u" style="width:${s.prob_up * 100}%"></i><i class="m" style="width:${mid * 100}%"></i><i class="d" style="width:${s.prob_down * 100}%"></i></div>
      <div class="tug-l"><span>peluang naik <b class="up">${p0(s.prob_up)}</b></span><span>turun <b class="down">${p0(s.prob_down)}</b></span></div>
      <div class="facts">
        <div><span>bisa naik sampai</span><b class="up">${pct(s.upside_pct)}</b></div>
        <div><span>bisa turun sampai</span><b class="down">${pct(-s.downside_pct)}</b></div>
        <div><span>tren besar</span><b>${s.trend_up ? "naik" : s.trend_down ? "turun" : "datar"}</b></div>
        <div><span>RSI</span><b>${Math.round(s.rsi)}</b> <small class="faint">${s.rsi > 70 ? "kepanasan" : s.rsi < 30 ? "kedinginan" : "wajar"}</small></div>
        <div><span>gerak rata-rata per candle</span><b>${nf(s.atr_pct, 2)}%</b></div>
        <div><span>akurasi di pasar ini</span><b>${s.accuracy == null ? "–" : p0(s.accuracy)}</b> <small class="faint">${s.acc_n ? `dari ${s.acc_n}` : "belum dinilai"}</small></div>
      </div>
      <div class="verdict-note ${note[0]}"><b>${note[1]}</b><span class="soft">${esc(s.decision)}</span></div>
      <p class="faint" style="font-size:13px;margin:14px 0 0">Kisaran ramalan ${price(s.pred_low, A.sym)} sampai ${price(s.pred_high, A.sym)}. Ramalan itu perkiraan, bukan kepastian.</p>`;
  };
  const loadSignal = async () => {
    try { A.signal = (await api(`/api/signal?symbol=${encodeURIComponent(A.sym)}&tf=${A.tf}`)).signal; } catch { A.signal = null; }
    renderVerdict(); drawForecast();
  };
  const switchTo = () => {
    A.fitted = false; A.signal = null; C = mkCharts(); renderVerdict(); loadCandles(); loadSignal();
    history.replaceState(null, "", `#/analisa?${encodeURIComponent(A.sym)}`);
  };
  const pk = picker($("#symPick"), { value: A.sym, onPick: (p) => { A.sym = p; switchTo(); } });
  seg($("#tfPick"), TF, A.tf, (v) => { A.tf = v; switchTo(); });
  $("#fcBtn").onclick = (e) => busy(e.currentTarget, async () => {
    try { A.signal = (await api("/api/forecast", { symbol: A.sym, tf: A.tf })).signal; renderVerdict(); drawForecast(); toast(`Ramalan ${labelOf(A.sym)} siap.`); }
    catch (err) { toast(err.message, "err", 7000); }
  });

  /* bandingkan beberapa pasar */
  const card = $("#scanCard");
  const renderScan = (job) => {
    const rows = job?.rows || [];
    const running = job && !job.finished;
    card.innerHTML = `
      <div class="card-head"><h2>bandingin beberapa pasar</h2><small>diurutkan dari sinyal paling kuat</small></div>
      <div class="toolbar" style="margin-bottom:14px"><div id="scanAdd"></div>
        <div class="chips">${A.scan.map((p) => `<span class="chip">${esc(labelOf(p))}<button data-rm="${esc(p)}" aria-label="hapus ${esc(p)}">✕</button></span>`).join("")}</div>
        <div class="grow"></div><button class="btn dark" id="scanGo" ${running ? "disabled" : ""}>ramal ${A.scan.length} pasar</button></div>
      ${running ? `<div class="progress"><i style="width:${(job.done / job.total) * 100}%"></i></div><p class="faint" style="font-size:13px">Lagi meramal ${esc(job.current)}… (${job.done}/${job.total})</p>` : ""}
      ${rows.length ? `<div class="table-wrap"><table><thead><tr><th>pasar</th><th>arah</th><th class="r">perkiraan</th><th class="r">naik</th><th class="r">turun</th><th class="r">akurasi</th><th>robot</th><th></th></tr></thead><tbody>
        ${rows.map((r) => r.error ? `<tr><td>${mkt(r.label)}</td><td colspan="7" class="down">${esc(r.error)}</td></tr>` :
          `<tr><td>${mkt(r.label)} ${venueTag(r.venue)}</td><td>${arrow(r.direction)}</td><td class="r ${tone(r.exp_ret_pct)}">${pct(r.exp_ret_pct)}</td><td class="r">${p0(r.prob_up)}</td><td class="r">${p0(r.prob_down)}</td>
           <td class="r">${r.accuracy == null ? "–" : p0(r.accuracy)}</td><td>${r.would === "long" ? sideTag("long") : r.would === "short" ? sideTag("short") : `<span class="tag">nunggu</span>`}</td>
           <td class="r"><button class="btn sm" data-view="${esc(r.symbol)}">lihat</button></td></tr>`).join("")}</tbody></table></div>` : ""}`;
    picker($("#scanAdd"), { placeholder: "tambah pasar…", onPick: (p) => { if (!A.scan.includes(p)) A.scan.push(p); renderScan(job); } });
    $$("[data-rm]", card).forEach((b) => b.onclick = () => { A.scan = A.scan.filter((x) => x !== b.dataset.rm); renderScan(job); });
    $$("[data-view]", card).forEach((b) => b.onclick = () => { A.sym = b.dataset.view; pk.set(A.sym); switchTo(); window.scrollTo({ top: 0, behavior: "smooth" }); });
    $("#scanGo").onclick = async () => {
      if (!A.scan.length) return toast("Tambah minimal satu pasar.", "err");
      try {
        const { job: id } = await api("/api/scan", { symbols: A.scan, tf: A.tf });
        renderScan({ done: 0, total: A.scan.length, current: labelOf(A.scan[0]), rows: [], finished: false });
        const poll = setInterval(async () => {
          try { const j = await api(`/api/scan/${id}`); renderScan(j); if (j.finished) { clearInterval(poll); toast("Selesai dibandingin."); } } catch { clearInterval(poll); }
        }, 1500);
        cur.timers.push(poll);
      } catch (err) { toast(err.message, "err"); }
    };
  };
  $("#scanOpen").onclick = () => { card.hidden = false; renderScan(null); card.scrollIntoView({ behavior: "smooth" }); };

  renderVerdict(); loadSignal();
  every(10000, loadCandles);
  every(30000, loadSignal);
};

/* ===================================================================== RIWAYAT */
ROUTES.riwayat = async (view) => {
  let mode = S.status?.mode;
  const render = async () => {
    let h;
    try { h = await api(`/api/history${mode ? `?mode=${mode}` : ""}`); } catch (e) { view.innerHTML = `<div class="err-box">${esc(e.message)}</div>`; return; }
    mode = h.mode; const s = h.stats;
    teardown();
    view.innerHTML = `
      <div class="head"><div><h1>riwayat</h1><p>Semua trade yang sudah ditutup dan perjalanan aset robot.</p></div>${h.modes.length > 1 ? `<div id="modeSeg"></div>` : ""}</div>
      ${s.trades ? `<div class="versus"><div><span>cuan total</span><b class="${tone(s.pnl)}">${sUsd(s.pnl)}</b></div><div><span>trade menang</span><b>${Math.round(s.win_pct)}%</b> <small class="faint">dari ${s.trades}</small></div><div><span>trade terbaik</span><b class="up">${sUsd(s.best)}</b></div><div><span>trade terburuk</span><b class="down">${sUsd(s.worst)}</b></div></div>` : ""}
      <section class="card" style="margin-bottom:18px"><div class="card-head"><h2>perjalanan aset</h2></div>${h.equity.length > 1 ? `<div class="chart md" id="hEq"></div>` : `<div class="empty"><b>belum ada data</b>Nyalain robot buat mulai mencatat.</div>`}</section>
      <section class="card"><div class="card-head"><h2>trade selesai</h2><small>${h.trades.length} trade</small></div>
        ${h.trades.length ? `<div class="table-wrap"><table><thead><tr><th>pasar</th><th>arah</th><th>buka</th><th class="r">harga buka</th><th>tutup</th><th class="r">harga tutup</th><th class="r">hasil</th><th>alasan tutup</th></tr></thead><tbody>
        ${h.trades.map((t) => `<tr><td>${mkt(t.label)}</td><td>${sideTag(t.side)}</td><td class="faint">${esc(String(t.entry_time).slice(5, 16))}</td><td class="r">${price(t.entry_price, t.symbol)}</td><td class="faint">${esc(String(t.exit_time).slice(5, 16))}</td><td class="r">${price(t.exit_price, t.symbol)}</td><td class="r ${tone(t.pnl)}"><b>${sUsd(t.pnl)}</b> <small>${pct(t.pnl_pct)}</small></td><td class="soft">${esc(t.exit_reason)}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="empty"><b>belum ada trade selesai</b>Trade muncul di sini setelah robot menutup posisi.</div>`}</section>`;
    if (h.modes.length > 1) seg($("#modeSeg"), Object.fromEntries(h.modes.map((m) => [m, m === "live" ? "live" : "simulasi"])), mode, (v) => { mode = v; render(); });
    if (h.equity.length > 1) {
      const c = makeChart($("#hEq"), "$"); cur.charts.push(c);
      c.addAreaSeries({ lineColor: cssv("--ink"), topColor: hexA(cssv("--ink"), 0.12), bottomColor: hexA(cssv("--ink"), 0), lineWidth: 2 }).setData(h.equity);
      c.timeScale().fitContent();
    }
  };
  render();
};

/* ===================================================================== UJI STRATEGI */
ROUTES.uji = async (view) => {
  const st = S.status || (await refreshStatus()) || { symbols: [{ symbol: "BTC/USDT" }], timeframe: "1h" };
  const F = { sym: st.symbols[0]?.symbol || "BTC/USDT", tf: st.timeframe, speed: "3" };
  let selected = null, wasRunning = false;
  view.innerHTML = `
    <div class="head"><div><h1>uji strategi</h1><p>Robot pura-pura trading di data lama pakai setelan kamu, terus dibandingin sama kalau cuma beli dan didiamkan. Nggak ada order sungguhan. Akurasinya juga masuk ke rapor akurasi.</p></div></div>
    <section class="card" style="margin-bottom:18px">
      <div class="fields" style="align-items:end">
        <div class="field"><span class="label">pasar</span><div id="btSym"></div></div>
        <div class="field"><span class="label">timeframe</span><div id="btTf"></div></div>
        <div class="field"><label for="btN">berapa candle ke belakang</label><div class="unit-wrap"><input id="btN" class="input" type="number" min="100" max="3000" step="50" value="500"><span class="unit">candle</span></div></div>
        <div class="field"><span class="label">ketelitian</span><div id="btSpeed"></div></div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-top:20px">
        <label class="check"><input type="checkbox" id="btOpt" checked><span class="box"></span><span class="t"><b>sekalian cariin setelan terbaik</b><span>coba ratusan kombinasi, cuma nambah beberapa detik</span></span></label>
        <button class="btn dark lg" id="btGo" data-busy="memulai…">mulai uji</button></div>
      <div id="btRun" style="margin-top:16px"></div>
    </section>
    <div class="grid" style="grid-template-columns:minmax(220px,280px) minmax(0,1fr);align-items:start" id="btBody">
      <section class="card"><div class="card-head"><h2>hasil</h2></div><div class="results" id="btList"></div></section>
      <div id="btDetail" class="stack"></div></div>`;
  if (matchMedia("(max-width: 860px)").matches) $("#btBody").style.gridTemplateColumns = "1fr";
  picker($("#btSym"), { value: F.sym, onPick: (p) => (F.sym = p) });
  seg($("#btTf"), TF, F.tf, (v) => (F.tf = v));
  seg($("#btSpeed"), { "1": "teliti", "3": "sedang", "6": "cepat" }, F.speed, (v) => (F.speed = v));
  $("#btGo").onclick = (e) => busy(e.currentTarget, async () => {
    try { await api("/api/backtest/start", { symbol: F.sym, tf: F.tf, candles: Number($("#btN").value) || 500, speed: Number(F.speed), optimize: $("#btOpt").checked }); toast("Uji dimulai."); poll(); }
    catch (err) { toast(err.message, "err"); }
  });

  const poll = async () => {
    let s; try { s = await api("/api/backtest/status"); } catch { return; }
    if (!$("#btGo")) return;   // sudah pindah halaman
    $("#btGo").disabled = s.running;
    const el = $("#btRun");
    if (s.running) {
      el.innerHTML = `<div class="progress ${s.pct == null ? "indet" : ""}"><i style="width:${s.pct ?? 30}%"></i></div>
        <div style="display:flex;justify-content:space-between;gap:10px;margin-top:8px;font-size:13.5px"><span class="soft">${esc(s.phase)}</span><button class="btn sm ghost" id="btStop">batalin</button></div>
        <p class="faint" style="font-size:13px;margin:6px 0 0">Tanpa kartu grafis, 500 candle mode teliti bisa 20–40 menit. Ramalannya disimpan, jadi uji ulang berikutnya cepat.</p>`;
      $("#btStop").onclick = async () => { await api("/api/backtest/stop", {}); toast("Uji dibatalkan."); poll(); };
      wasRunning = true;
    } else {
      el.innerHTML = s.failed ? `<div class="err-box"><b>Uji terakhir gagal.</b><pre class="log">${esc(s.log)}</pre></div>` : "";
      if (wasRunning) { wasRunning = false; selected = null; loadList(); if (!s.failed) toast("Uji selesai."); }
    }
  };
  const loadList = async () => {
    const { results } = await api("/api/backtest/results").catch(() => ({ results: [] }));
    $("#btList").innerHTML = results.length ? results.map((r) => `<button data-r="${esc(r.name)}" class="${r.name === selected ? "on" : ""}">
        <span>${mkt(r.label)} <span class="faint" style="font-size:13px">${esc(TF[r.tf] || r.tf)}</span></span><b class="${tone(r.return_pct)}">${pct(r.return_pct)}</b>
        <small>${esc(r.updated)}${r.has_opt ? ", dengan optimasi" : ""}${r.dummy ? ", ramalan acak" : ""}</small></button>`).join("")
      : `<div class="empty"><b>belum ada hasil</b>Jalankan uji pertama di atas.</div>`;
    $$("[data-r]").forEach((b) => b.onclick = () => openResult(b.dataset.r));
    if (!selected && results.length) openResult(results[0].name);
    if (!results.length) $("#btDetail").innerHTML = "";
  };
  const openResult = async (name) => {
    selected = name;
    $$("[data-r]").forEach((b) => b.classList.toggle("on", b.dataset.r === name));
    cur.charts.forEach((c) => c.remove()); cur.charts = [];
    let r; try { r = await api(`/api/backtest/result/${encodeURIComponent(name)}`); } catch (e) { $("#btDetail").innerHTML = `<div class="err-box">${esc(e.message)}</div>`; return; }
    const m = r.metrics || {}, acc = r.accuracy || {}, o = r.optim;
    const beat = m.return_pct != null && m.return_pct > m.buyhold_pct;
    const fx = r.venue === "forex";
    $("#btDetail").innerHTML = `
      <section class="card">
        <div class="card-head"><h2>${mkt(r.label || name)} <span class="faint" style="font-size:15px">${esc(TF[r.tf] || "")}</span></h2><small>${r.period ? esc(r.period[0]) + " sampai " + esc(r.period[1]) : ""}</small></div>
        <div class="versus">
          <div><span>hasil robot</span><b class="${tone(m.return_pct)}">${pct(m.return_pct)}</b></div>
          <div><span>beli & diamkan</span><b class="${tone(m.buyhold_pct)}">${pct(m.buyhold_pct)}</b></div>
          <div><span>turun terdalam</span><b class="down">${pct(m.max_dd_pct)}</b></div>
          <div><span>trade, menang</span><b>${m.trades ?? 0}</b> <small class="faint">${m.trades ? Math.round(m.win_pct) + "%" : ""}</small></div></div>
        <div class="note-box" style="margin-bottom:16px">${beat ? "<b>Robot lebih bagus dari beli & diamkan</b> di periode ini." : "<b>Robot belum ngalahin beli & diamkan</b> di periode ini."}
          Arah ramalan AI benar <b>${acc.hit == null ? "–" : p0(acc.hit)}</b> dari ${acc.n || 0} ramalan.${fx ? ` Buy ${m.longs || 0}, sell ${m.shorts || 0}.` : ""}</div>
        <div class="chart md" id="btEq"></div>
        <div class="legend"><span><i style="background:var(--ai)"></i>robot</span><span><i style="background:var(--ink-3)"></i>beli & diamkan</span></div></section>
      ${o ? `<section class="card"><div class="card-head"><h2>setelan terbaik</h2><small>hasil optimasi</small></div>
        <p class="soft" style="margin-top:0;font-size:14px">Setelan dicari di periode latih (${esc(o.periode_latih[0].slice(0, 10))} – ${esc(o.periode_latih[1].slice(0, 10))}), terus dites di periode uji (${esc(o.periode_uji[0].slice(0, 10))} – ${esc(o.periode_uji[1].slice(0, 10))}) yang nggak dipakai waktu nyari. <b style="color:var(--ink)">Lihat kolom “hasil uji”</b>: kalau bagus di latih tapi rugi di uji, kemungkinan cuma kebetulan.</p>
        <div class="table-wrap"><table><thead><tr><th></th><th class="r">hasil latih</th><th class="r">hasil uji</th><th class="r">trade (uji)</th><th>setelannya</th><th></th></tr></thead><tbody>
          ${[["sekarang", o.setelan_sekarang, 0], ...o.terbaik.map((x, i) => [`kandidat ${i + 1}`, x, i + 1])].map(([n, x, k]) => `
          <tr class="${k === 0 ? "mark-row" : ""}"><td><b>${n}</b></td><td class="r ${tone(x.latih.return_pct)}">${pct(x.latih.return_pct)}</td><td class="r ${tone(x.uji.return_pct)}"><b>${pct(x.uji.return_pct)}</b></td>
            <td class="r">${x.uji.trades}, ${Math.round(x.uji.win_pct)}% menang</td><td class="wrap">${esc(x.desc.entry)}. ${esc(x.desc.stop)}, ${esc(x.desc.trail)}, ${esc(x.desc.trend)}${x.desc.sides ? ", " + esc(x.desc.sides) : ""}.</td>
            <td class="r">${k ? `<button class="btn sm ${x.uji.return_pct > 0 ? "dark" : ""}" data-apply="${k}">pakai</button>` : ""}</td></tr>`).join("")}
        </tbody></table></div></section>` : ""}
      ${r.trades?.length ? `<section class="card"><div class="card-head"><h2>daftar trade</h2><small>${r.trades.length} trade</small></div><div class="table-wrap" style="max-height:420px;overflow:auto"><table><thead><tr><th>buka</th><th>arah</th><th class="r">harga buka</th><th>tutup</th><th class="r">harga tutup</th><th class="r">hasil</th><th>alasan</th></tr></thead><tbody>
        ${r.trades.map((t) => `<tr><td class="faint">${esc(String(t.entry_time).slice(5, 16))}</td><td>${sideTag(t.side)}</td><td class="r">${price(t.entry_price, r.symbol)}</td><td class="faint">${esc(String(t.exit_time).slice(5, 16))}</td><td class="r">${price(t.exit_price, r.symbol)}</td><td class="r ${tone(t.pnl)}">${sUsd(t.pnl)}</td><td class="soft">${esc(t.exit_reason)}</td></tr>`).join("")}
        </tbody></table></div></section>` : ""}`;
    if (r.equity?.length) {
      const c = makeChart($("#btEq"), "$"); cur.charts.push(c);
      c.addLineSeries({ color: cssv("--ink-3"), lineWidth: 1.5, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }).setData(r.buyhold);
      c.addLineSeries({ color: cssv("--ai"), lineWidth: 2.5, priceLineVisible: false }).setData(r.equity);
      c.timeScale().fitContent();
    }
    $$("[data-apply]").forEach((b) => b.onclick = async () => {
      const k = Number(b.dataset.apply), x = o.terbaik[k - 1];
      const ok = await modal({ title: `pakai kandidat ${k}?`, confirm: "pakai setelan ini",
        body: `<p>${esc(x.desc.entry)}. ${esc(x.desc.stop)}, ${esc(x.desc.trail)}, ${esc(x.desc.trend)}${x.desc.sides ? ", " + esc(x.desc.sides) : ""}. Berlaku untuk semua pasar ${VENUE[r.venue]}.</p>${x.uji.return_pct <= 0 ? `<div class="err-box">Kandidat ini <b>rugi di periode uji</b>. Mending jangan dipakai.</div>` : ""}` });
      if (!ok) return;
      try { const res = await api("/api/backtest/apply", { name, k }); toast(res.restarted ? "Setelan dipakai, robot dinyalain ulang." : "Setelan dipakai."); } catch (e) { toast(e.message, "err"); }
    });
  };
  loadList();
  every(2500, poll);
};

/* ===================================================================== SETELAN */
const PRESETS = {
  crypto: { hati: [1.2, 0.75], normal: [0.8, 0.65], agresif: [0.4, 0.55] },
  forex: { hati: [0.2, 0.75], normal: [0.1, 0.65], agresif: [0.05, 0.55] },
};
const PRESET_TXT = { hati: ["hati-hati", "jarang buka posisi, sinyal harus kuat banget"], normal: ["normal", "seimbang"], agresif: ["agresif", "lebih sering, risikonya juga lebih gede"], kustom: ["atur sendiri", "tentuin angkanya"] };
const MODELS = { ringan: ["ringan", "paling cepat, cocok buat laptop biasa"], sedang: ["sedang", "seimbang, disarankan"], berat: ["berat", "paling teliti, butuh komputer kuat"] };
const SL_OPTS = { persen: "persen tetap", atr: "ikut liarnya pasar" };

ROUTES.setelan = async (view) => {
  view.innerHTML = `<div class="head"><div><h1>setelan</h1></div></div><div class="card"><div class="empty"><span class="spinner"></span></div></div>`;
  let saved;
  try { saved = await api("/api/config"); } catch (e) { view.innerHTML = `<div class="err-box">${esc(e.message)}</div>`; return; }
  const d = structuredClone(saved);
  let V = "crypto";   // pasar yang sedang diatur di bagian keputusan
  const SK = () => (V === "crypto" ? "strategy" : "strategy_forex");
  const presetOf = () => { const s = d[SK()]; return Object.keys(PRESETS[V]).find((k) => PRESETS[V][k][0] === s.min_expected_return_pct && PRESETS[V][k][1] === s.min_prob_up) || "kustom"; };

  const num = (path, { label, unit = "", step = "any", min = 0, max, hint = "" }) => `
    <div class="field"><label for="f-${path}">${label}</label><div class="unit-wrap"><input class="input" id="f-${path}" type="number" inputmode="decimal" step="${step}" min="${min}" ${max != null ? `max="${max}"` : ""} data-path="${path}">${unit ? `<span class="unit">${unit}</span>` : ""}</div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
  const sw = (path, label, hint) => `<label class="check"><input type="checkbox" data-path="${path}"><span class="box"></span><span class="t"><b>${label}</b><span>${hint}</span></span></label>`;

  view.innerHTML = `
    <div class="head"><div><h1>setelan</h1><p>Atur pasar, modal, dan cara robot ambil keputusan. Kalau robot lagi nyala, dia otomatis dinyalain ulang setelah kamu simpan.</p></div></div>
    <div class="card">
      <div class="group"><div><h3>pasar & waktu</h3><div class="desc">Pasar yang dipantau dan seberapa sering robot mikir.</div></div>
        <div class="stack" style="gap:16px">
          <div class="field"><span class="label">pasar yang dipantau</span><div class="toolbar"><div id="symAdd"></div></div><div id="symChips" class="stack" style="gap:10px;margin-top:6px"></div>
            <div class="hint">Kripto lewat Tokocrypto (cuma buy). Forex lewat MetaTrader 5 atau data Yahoo Finance (bisa buy dan sell). Makin banyak pasar, makin lama robot meramal.</div></div>
          <div class="field"><span class="label">robot ambil keputusan tiap</span><div id="tfSeg"></div></div></div></div>

      <div class="group"><div><h3>modal & risiko</h3><div class="desc">Berapa uang yang dipakai tiap posisi dan kapan robot berhenti.</div></div>
        <div class="stack" style="gap:16px"><div class="fields">
          ${num("risk.order_size_quote", { label: "modal per posisi kripto", unit: "USDT", step: 1, min: 1 })}
          ${num("forex.risk_pct", { label: "risiko per posisi forex", unit: "% aset", step: 0.1, min: 0.1, max: 10, hint: "kalau kena stop-loss, rugi maksimal segini" })}
          ${num("forex.max_lots", { label: "lot maksimal per posisi forex", unit: "lot", step: 0.01, min: 0.01 })}
          ${num("risk.max_open_positions", { label: "posisi terbuka maksimal", unit: "posisi", step: 1, min: 1, max: 50 })}
          ${num("risk.max_daily_loss_quote", { label: "stop buka posisi kalau rugi hari ini", unit: "USD", step: 1 })}
        </div><div class="note-box" id="capNote"></div></div></div>

      <div class="group"><div><h3>cara ambil keputusan</h3><div class="desc">Kripto dan forex punya setelan sendiri karena geraknya beda jauh.</div><div id="vSeg" style="margin-top:14px"></div></div>
        <div class="stack" style="gap:18px">
          <div class="field"><span class="label">seberapa yakin sebelum buka posisi?</span><div class="choices" id="presets">${Object.entries(PRESET_TXT).map(([k, t]) => `<button type="button" class="choice" data-preset="${k}"><b>${t[0]}</b><span>${t[1]}</span></button>`).join("")}</div></div>
          <div class="fields" id="customBox">
            ${num("S.min_expected_return_pct", { label: "minimal ramalan bergerak", unit: "%", step: 0.01 })}
            <div class="field"><label for="f-prob">minimal peluang searah</label><div class="range-row"><input id="f-prob" type="range" min="0.5" max="0.95" step="0.05" data-path="S.min_prob_up"><output id="probOut"></output></div></div></div>
          <div class="fields">
            ${sw("S.trend_filter", "ikut tren besar", "buy cuma saat tren naik, sell cuma saat tren turun")}
            <div id="shortWrap">${sw("S.allow_short", "boleh sell (short)", "robot boleh untung saat harga turun")}</div>
            <div class="field"><label for="f-rsi">jangan kejar harga kalau RSI lewat</label><div class="range-row"><input id="f-rsi" type="range" min="55" max="100" step="1" data-path="S.rsi_max"><output id="rsiOut"></output></div><div class="hint">100 = abaikan</div></div>
            ${num("S.min_rr", { label: "minimal untung dibanding rugi", unit: "×", step: 0.1, hint: "0 = abaikan" })}
          </div>
          <div class="field"><span class="label">cara nentuin stop-loss & target</span><div id="slSeg"></div></div>
          <div class="fields" id="pctBox">${num("S.stop_loss_pct", { label: "stop-loss", unit: "%", step: 0.05, min: 0.05 })}${num("S.take_profit_pct", { label: "target untung", unit: "%", step: 0.05, min: 0.05 })}</div>
          <div class="fields" id="atrBox">${num("S.sl_atr_mult", { label: "stop-loss", unit: "× gerak", step: 0.5, min: 0.5 })}${num("S.tp_atr_mult", { label: "target untung", unit: "× gerak", step: 0.5, min: 0.5 })}</div>
          <div class="fields">
            ${sw("S.trailing_on", "trailing stop", "stop-loss ikut geser biar untung nggak balik hilang")}
            ${num("S.trail_activate_pct", { label: "aktif setelah untung", unit: "%", step: 0.05, min: 0.05 })}
            ${num("S.trail_pct", { label: "tutup kalau mundur dari puncak", unit: "%", step: 0.05, min: 0.05 })}
            ${num("S.max_hold_candles", { label: "tutup paksa setelah", unit: "candle", step: 1, min: 1 })}</div>
          <div class="note-box" id="exitNote"></div></div></div>

      <div class="group"><div><h3>akurasi</h3><div class="desc">Biar robot cuma trading di pasar yang ramalannya terbukti cukup tepat.</div></div>
        <div class="stack" style="gap:16px"><div class="fields">
          <div class="field"><label for="f-acc">akurasi arah minimal</label><div class="range-row"><input id="f-acc" type="range" min="0" max="0.7" step="0.01" data-path="ACC.min_accuracy"><output id="accOut"></output></div><div class="hint">0 = abaikan. 50% itu sama aja kayak lempar koin.</div></div>
          ${num("ACC.min_accuracy_n", { label: "dinilai setelah", unit: "ramalan", step: 5, min: 5 })}
          ${sw("ACC.require_proof", "wajib terbukti dulu", "jangan trading sebelum jumlah ramalan di atas tercapai")}
        </div><div class="note-box">Akurasi dihitung dari <b>uji strategi</b> dan ramalan robot yang sudah lewat waktunya. Cara paling cepat ngisi rapor: jalankan uji di tiap pasar.</div></div></div>

      <div class="group"><div><h3>otak AI</h3><div class="desc">Model Kronos yang lebih gede lebih teliti tapi lebih lambat.</div></div>
        <div class="choices" id="models">${Object.entries(MODELS).map(([k, m]) => `<button type="button" class="choice" data-model="${k}"><b>${m[0]}</b><span>${m[1]}</span></button>`).join("")}</div></div>

      <div class="group"><div><h3>lanjutan</h3><div class="desc">Biarin aja kalau ragu.</div></div>
        <div class="fields">
          ${num("strategy.fee_pct", { label: "biaya trading kripto", unit: "%", step: 0.01 })}
          ${num("strategy_forex.fee_pct", { label: "spread forex", unit: "%", step: 0.005, hint: "selisih harga buy-sell, 0,02% kira-kira 2 pip EUR/USD" })}
          ${num("paper.starting_balance", { label: "saldo awal simulasi", unit: "USD", step: 100, min: 1 })}
          ${num("forex.leverage", { label: "leverage simulasi forex", unit: "×", step: 1, min: 1 })}
          ${num("risk.max_order_size_quote", { label: "batas keras per order kripto", unit: "USDT", step: 1, min: 1 })}
          ${num("model.n_paths", { label: "jumlah skenario ramalan", unit: "skenario", step: 1, min: 2, max: 50 })}
          ${num("model.pred_len", { label: "ramal ke depan", unit: "candle", step: 1, min: 2, max: 120 })}
          <div class="field"><span class="label">sumber data forex</span><div id="srcSeg"></div></div>
        </div></div>
    </div>
    <div class="savebar" id="savebar" hidden><span>ada perubahan yang belum disimpan</span><span style="display:flex;gap:6px"><button class="btn ghost" id="revert">batal</button><button class="btn light" id="save" data-busy="nyimpen…">simpan</button></span></div>`;

  const getP = (p) => {
    if (p.startsWith("S.")) return d[SK()][p.slice(2)];
    if (p.startsWith("ACC.")) return d.strategy[p.slice(4)];
    return p.split(".").reduce((o, k) => o?.[k], d);
  };
  const setP = (p, v) => {
    if (p.startsWith("S.")) { d[SK()][p.slice(2)] = v; return; }
    if (p.startsWith("ACC.")) { d.strategy[p.slice(4)] = v; d.strategy_forex[p.slice(4)] = v; return; }
    const ks = p.split("."); const last = ks.pop(); ks.reduce((o, k) => o[k], d)[last] = v;
  };
  const fill = () => $$("[data-path]").forEach((el) => { const v = getP(el.dataset.path); if (el.type === "checkbox") el.checked = !!v; else el.value = v ?? ""; });
  let presetKey = presetOf();

  const derived = () => {
    if (!$("#capNote")) return;   // sudah pindah halaman
    const s = d[SK()];
    const cryptoN = d.symbols.filter((x) => !isFx(x)).length, fxN = d.symbols.filter(isFx).length;
    $("#capNote").innerHTML = [cryptoN ? `Kripto: tiap posisi pakai <b>${nf(d.risk.order_size_quote, 0)} USDT</b>.` : "",
      fxN ? `Forex: kalau kena stop-loss, rugi sekitar <b>${nf(d.forex.risk_pct, 1)}%</b> dari total aset per posisi.` : "",
      `Maksimal <b>${d.risk.max_open_positions} posisi</b> sekaligus.`].filter(Boolean).join(" ");
    $("#probOut").textContent = p0(s.min_prob_up);
    $("#rsiOut").textContent = s.rsi_max >= 100 ? "abaikan" : Math.round(s.rsi_max);
    $("#accOut").textContent = d.strategy.min_accuracy > 0 ? p0(d.strategy.min_accuracy) : "abaikan";
    $("#customBox").hidden = presetKey !== "kustom";
    $$("[data-preset]").forEach((b) => b.classList.toggle("on", b.dataset.preset === presetKey));
    $$("[data-model]").forEach((b) => b.classList.toggle("on", b.dataset.model === d.model.size));
    $("#shortWrap").hidden = V !== "forex";
    $("#pctBox").hidden = s.sl_mode === "atr"; $("#atrBox").hidden = s.sl_mode !== "atr";
    ["S.trail_activate_pct", "S.trail_pct"].forEach((p) => { $(`[data-path="${p}"]`).disabled = !s.trailing_on; });
    const hrs = (s.max_hold_candles * TF_SEC[d.timeframe]) / 3600;
    $("#exitNote").innerHTML = (s.sl_mode === "atr"
      ? `Batasnya ngikutin seberapa liar pasar. Kalau harga biasanya gerak 1% per candle, stop-loss di <b class="down">−${nf(s.sl_atr_mult, 1)}%</b> dan target di <b class="up">+${nf(s.tp_atr_mult, 1)}%</b>.`
      : `Contoh buy di 100: ditutup otomatis di <b class="down">${nf(100 * (1 - s.stop_loss_pct / 100), 2)}</b> (rugi) atau <b class="up">${nf(100 * (1 + s.take_profit_pct / 100), 2)}</b> (untung).`)
      + ` Posisi ditutup paksa setelah ${s.max_hold_candles} candle (sekitar ${hrs >= 48 ? nf(hrs / 24, 1) + " hari" : nf(hrs, 0) + " jam"}).`;
    const groups = { crypto: d.symbols.filter((x) => !isFx(x)), forex: d.symbols.filter(isFx) };
    $("#symChips").innerHTML = Object.entries(groups).filter(([, l]) => l.length).map(([v, l]) => `<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><span class="faint" style="width:52px;font-size:13px">${VENUE[v]}</span><div class="chips">${l.map((p) => `<span class="chip">${esc(labelOf(p))}<button data-rm="${esc(p)}" aria-label="hapus ${esc(p)}">✕</button></span>`).join("")}</div></div>`).join("");
    $$("#symChips [data-rm]").forEach((b) => b.onclick = () => { if (d.symbols.length === 1) return toast("Minimal satu pasar.", "err"); d.symbols = d.symbols.filter((x) => x !== b.dataset.rm); derived(); });
    $("#savebar").hidden = JSON.stringify(d) === JSON.stringify(saved);
  };

  view.addEventListener("input", (e) => {
    const el = e.target.closest("[data-path]"); if (!el) return;
    const v = el.type === "checkbox" ? el.checked : (el.type === "number" || el.type === "range") ? parseFloat(el.value) : el.value;
    if (typeof v === "number" && isNaN(v)) return;
    setP(el.dataset.path, v);
    if (el.dataset.path.startsWith("S.min_")) presetKey = presetOf();
    derived();
  });
  view.addEventListener("change", (e) => { if (e.target.type === "checkbox") e.target.dispatchEvent(new Event("input", { bubbles: true })); });
  $("#presets").onclick = (e) => {
    const b = e.target.closest("[data-preset]"); if (!b) return;
    presetKey = b.dataset.preset;
    if (PRESETS[V][presetKey]) [d[SK()].min_expected_return_pct, d[SK()].min_prob_up] = PRESETS[V][presetKey];
    fill(); derived();
  };
  $("#models").onclick = (e) => { const b = e.target.closest("[data-model]"); if (b) { d.model.size = b.dataset.model; derived(); } };
  const onSl = (v) => { d[SK()].sl_mode = v; derived(); };
  seg($("#slSeg"), SL_OPTS, d[SK()].sl_mode, onSl);
  seg($("#vSeg"), { crypto: "kripto", forex: "forex" }, V, (v) => { V = v; presetKey = presetOf(); seg($("#slSeg"), SL_OPTS, d[SK()].sl_mode, onSl); fill(); derived(); });
  seg($("#tfSeg"), TF, d.timeframe, (v) => { d.timeframe = v; derived(); });
  seg($("#srcSeg"), { auto: "otomatis", mt5: "MetaTrader 5", yahoo: "Yahoo Finance" }, d.forex.source || "auto", (v) => { d.forex.source = v; derived(); });
  const add = picker($("#symAdd"), { placeholder: "tambah pasar, mis. EURUSD", onPick: (p) => { if (!d.symbols.includes(p)) d.symbols.push(p); add.clear(); derived(); } });
  $("#revert").onclick = () => route();
  $("#save").onclick = (e) => busy(e.currentTarget, async () => {
    try {
      const r = await api("/api/config", d);
      saved = structuredClone(d);
      toast(r.restarted ? "Tersimpan. Robot dinyalain ulang." : "Tersimpan.");
      derived(); refreshStatus();
    } catch (err) { toast(err.message, "err"); }
  });
  fill(); derived();
};

/* ===================================================================== AKUN */
ROUTES.akun = async (view) => {
  const render = async () => {
    let a;
    try { a = await api("/api/account"); } catch (e) { view.innerHTML = `<div class="err-box">${esc(e.message)}</div>`; return; }
    const m5 = a.mt5;
    view.innerHTML = `
      <div class="head"><div><h1>akun</h1><p>Pilih robot main pakai uang virtual atau uang beneran, dan sambungin akun broker kamu.</p></div></div>
      <div class="stack">
        <div class="modes">
          <button class="mode ${a.mode === "paper" ? "on" : ""}" data-mode="paper"><h3>simulasi <span class="sticker">aman</span></h3><p>Harga asli, uang virtual. Pakai ini dulu buat kenalan sama robotnya.</p></button>
          <button class="mode ${a.mode === "live" ? "on" : ""}" data-mode="live"><h3>live</h3><p>Robot buka dan tutup posisi pakai uang sungguhan di akun kamu.</p></button></div>
        <div class="grid halves">
          <section class="card"><div class="card-head"><h2>Tokocrypto</h2><span class="tag ${a.has_keys ? "buy" : ""}">${a.has_keys ? "tersambung" : "belum"}</span></div>
            <p class="soft" style="margin-top:0;font-size:14px">Buat trading kripto beneran. Buat simulasi nggak perlu.</p>
            <ol class="ol"><li>Di Tokocrypto buka <b>Manajemen API</b>, bikin API key baru.</li><li>Nyalain izin <b>baca</b> dan <b>spot trading</b> aja. <b>Jangan nyalain withdraw.</b></li><li>Tempel di bawah, terus simpan.</li></ol>
            <form id="tkForm" class="stack" style="gap:12px" autocomplete="off">
              <div class="field"><label for="k1">API key</label><input class="input" id="k1" type="password" placeholder="${esc(a.key || "tempel API key")}"></div>
              <div class="field"><label for="k2">secret key</label><input class="input" id="k2" type="password" placeholder="${esc(a.secret || "tempel secret key")}"></div>
              <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn dark" type="submit" data-busy="nyimpen…">simpan</button><button class="btn" type="button" id="tkTest" data-busy="ngecek…" ${a.has_keys ? "" : "disabled"}>cek koneksi</button></div>
              <div id="tkOut"></div></form></section>

          <section class="card"><div class="card-head"><h2>MetaTrader 5</h2><span class="tag ${m5.enabled ? "buy" : ""}">${m5.enabled ? "dipakai" : "nggak dipakai"}</span></div>
            <p class="soft" style="margin-top:0;font-size:14px">Buat forex. Hampir semua broker forex di Indonesia pakai MT5, dan kebanyakan punya <b style="color:var(--ink)">akun demo gratis</b>. Tanpa MT5, forex tetap bisa dianalisa dan disimulasiin pakai data Yahoo Finance.</p>
            ${!m5.installed ? `<div class="note-box" style="margin-bottom:14px">${m5.windows ? "Library MetaTrader5 belum terpasang. Tutup panel lalu jalankan MULAI lagi." : "MT5 cuma bisa disambungin di Windows. Di komputer ini forex pakai data Yahoo Finance (buat analisa dan simulasi)."}</div>` : ""}
            <ol class="ol"><li>Install aplikasi <b>MetaTrader 5</b> dari broker kamu, terus login (akun demo juga bisa).</li><li>Di MT5 nyalain tombol <b>Algo Trading</b> sampai hijau.</li><li>Isi di bawah. Kalau MT5 sudah login, login/password/server boleh dikosongin.</li></ol>
            <form id="mtForm" class="stack" style="gap:12px" autocomplete="off">
              <label class="check"><input type="checkbox" id="mtOn" ${m5.enabled ? "checked" : ""}><span class="box"></span><span class="t"><b>pakai MT5 buat forex</b><span>data dan order forex lewat MT5</span></span></label>
              <div class="fields"><div class="field"><label for="m1">nomor login</label><input class="input" id="m1" inputmode="numeric" value="${esc(m5.login)}" placeholder="mis. 51234567"></div>
                <div class="field"><label for="m2">password</label><input class="input" id="m2" type="password" placeholder="${m5.has_password ? "tersimpan" : "password MT5"}"></div>
                <div class="field"><label for="m3">server</label><input class="input" id="m3" value="${esc(m5.server)}" placeholder="mis. NamaBroker-Demo"></div>
                <div class="field"><label for="m4">lokasi terminal64.exe <span class="faint">(opsional)</span></label><input class="input" id="m4" value="${esc(m5.path)}" placeholder="C:\\Program Files\\MetaTrader 5\\terminal64.exe"></div></div>
              <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn dark" type="submit" data-busy="nyimpen…">simpan</button><button class="btn" type="button" id="mtTest" data-busy="nyambungin…" ${m5.installed ? "" : "disabled"}>cek koneksi</button></div>
              <div id="mtOut"></div></form></section>
        </div>
        <section class="card"><div class="card-head"><h2>reset simulasi</h2></div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap"><p class="soft" style="margin:0">Hapus riwayat trade dan saldo virtual mode simulasi. Rapor akurasi dan data live nggak kesentuh.</p>
          <button class="btn danger" id="resetBtn" data-busy="mereset…">reset simulasi</button></div></section>
      </div>`;

    $$("[data-mode]").forEach((b) => b.onclick = async () => {
      const m = b.dataset.mode;
      if (m === a.mode) return;
      if (m === "live") {
        const typed = await modal({ title: "pindah ke live?", confirm: "aktifin live", danger: true,
          body: "<p>Robot bakal trading pakai <b>uang sungguhan</b> dan bisa rugi. Saran: jalanin simulasi minimal 1–2 minggu dulu, terus mulai dengan modal kecil.</p>",
          input: { label: `ketik <b>${esc(a.confirm_text)}</b>`, placeholder: a.confirm_text } });
        if (typed == null) return;
        try { const r = await api("/api/account/mode", { mode: "live", confirm: typed }); toast(r.restarted ? "Mode live aktif, robot dinyalain ulang." : "Mode live aktif."); } catch (e) { return toast(e.message, "err", 6000); }
      } else {
        const ok = await modal({ title: "balik ke simulasi?", body: "<p>Posisi live yang masih kebuka tetap ada di akun kamu dan nggak dijaga robot lagi.</p>", confirm: "balik ke simulasi" });
        if (!ok) return;
        try { await api("/api/account/mode", { mode: "paper" }); toast("Balik ke simulasi."); } catch (e) { return toast(e.message, "err"); }
      }
      refreshStatus(); render();
    });
    $("#tkForm").onsubmit = (e) => { e.preventDefault(); busy(e.submitter, async () => { try { await api("/api/account/keys", { key: $("#k1").value, secret: $("#k2").value }); toast("Kunci tersimpan."); render(); } catch (err) { toast(err.message, "err"); } }); };
    $("#tkTest").onclick = (e) => busy(e.currentTarget, async () => {
      try { const r = await api("/api/account/test", {}); $("#tkOut").innerHTML = `<div class="ok-box"><b>Nyambung ke Tokocrypto.</b>Saldo USDT bebas: ${nf(r.usdt, 2)}</div>`; }
      catch (err) { $("#tkOut").innerHTML = `<div class="err-box">${esc(err.message)}</div>`; }
    });
    $("#mtForm").onsubmit = (e) => {
      e.preventDefault();
      busy(e.submitter, async () => {
        try { await api("/api/mt5", { enabled: $("#mtOn").checked, login: $("#m1").value, password: $("#m2").value, server: $("#m3").value, path: $("#m4").value }); toast("Setelan MT5 tersimpan."); S.pairs = {}; refreshStatus(); render(); }
        catch (err) { toast(err.message, "err"); }
      });
    };
    $("#mtTest").onclick = (e) => busy(e.currentTarget, async () => {
      try {
        const r = await api("/api/mt5/test", {});
        $("#mtOut").innerHTML = `<div class="ok-box"><b>Nyambung ke MT5 ${r.demo ? "(akun demo)" : "(akun real)"}.</b>${esc(r.name || "")} di ${esc(r.server)}, saldo ${nf(r.balance, 2)} ${esc(r.currency)}, leverage 1:${r.leverage}.${r.trade_allowed ? "" : " <b class='down'>Algo Trading belum aktif.</b>"}</div>`;
      } catch (err) { $("#mtOut").innerHTML = `<div class="err-box">${esc(err.message)}</div>`; }
    });
    $("#resetBtn").onclick = async (e) => {
      const btn = e.currentTarget;
      const ok = await modal({ title: "reset simulasi?", body: "<p>Riwayat trade dan saldo virtual mode simulasi dihapus.</p>", confirm: "reset", danger: true });
      if (ok) busy(btn, async () => { try { await api("/api/account/reset-paper", {}); toast("Simulasi direset."); } catch (err) { toast(err.message, "err"); } });
    };
  };
  render();
};

/* ===================================================================== mulai */
refreshStatus().then((s) => {
  if (s && !s.setup_ok) toast("Setup belum selesai: folder Kronos belum ada. Tutup panel lalu jalankan MULAI lagi.", "err", 12000);
  route();
});
setInterval(refreshStatus, 8000);
