"use strict";

/* JoSAA predictor — fully client-side. Loads a SQLite snapshot via sql.js and
   runs the deterministic prediction + trend queries in the browser. No backend. */

const state = { exam: "jee_adv", gender: "male" };
const TYPE_ORDER = ["IIT", "NIT", "IIIT", "GFTI"];
const $ = (s, r = document) => r.querySelector(s);
const FEMALE_G = "Female-only (including Supernumerary)";

let DB = null;
let lastCandidates = [];
const filters = { type: "ALL", search: "", buckets: new Set(["green", "yellow", "red"]), sortKey: null, sortDir: 1 };

/* preference order (persisted) */
const prefKeyOf = (o) => `${o.institute}||${o.program}||${o.gender}||${o.quota}`;
let prefs = (() => { try { return JSON.parse(localStorage.getItem("josaa_prefs") || "[]"); } catch { return []; } })();
const savePrefs = () => localStorage.setItem("josaa_prefs", JSON.stringify(prefs));
let prefSortable = null;

// bucket thresholds (mirror josaa/predict/deterministic.py)
const GREEN_MIN = 1.20, YELLOW_MIN = 1.00, RED_MIN = 0.85;

/* ---- segmented controls ------------------------------------------------ */
document.querySelectorAll(".segmented").forEach((group) => {
  group.addEventListener("click", (e) => {
    const btn = e.target.closest(".seg");
    if (!btn) return;
    group.querySelectorAll(".seg").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    state[group.dataset.name] = btn.dataset.value;
  });
});

/* ---- sql.js data layer ------------------------------------------------- */
function rows(sql, params) {
  const res = DB.exec(sql, params || []);
  if (!res.length) return [];
  const { columns, values } = res[0];
  return values.map((v) => Object.fromEntries(columns.map((c, i) => [c, v[i]])));
}

async function initDB() {
  const SQL = await initSqlJs({ locateFile: (f) => `vendor/${f}` });
  const buf = await (await fetch("data/josaa.sqlite")).arrayBuffer();
  DB = new SQL.Database(new Uint8Array(buf));
}

function meta() {
  return {
    years: rows("SELECT DISTINCT year FROM cutoffs ORDER BY year DESC").map((r) => r.year),
    institutes: rows("SELECT COUNT(*) n FROM institutes")[0].n,
    cutoffs: rows("SELECT COUNT(*) n FROM cutoffs")[0].n,
  };
}

/* ---- prediction (ported from deterministic.py) ------------------------- */
function project(trend, latest) {
  const ys = Object.keys(trend).map(Number).sort((a, b) => a - b);
  if (ys.length >= 2) {
    const span = ys[ys.length - 1] - ys[0];
    const slope = span ? (trend[ys[ys.length - 1]] - trend[ys[0]]) / span : 0;
    const proj = trend[ys[ys.length - 1]] + slope;
    return Math.max(1, Math.round(0.5 * proj + 0.5 * latest));
  }
  return latest;
}
function seatPad(seats) {
  if (seats == null) return 0;
  if (seats <= 3) return 0.12;
  if (seats <= 8) return 0.05;
  return 0;
}
function bucketOf(rank, proj, seats) {
  const ratio = proj / rank, pad = seatPad(seats);
  if (ratio >= GREEN_MIN + pad) return "green";
  if (ratio >= YELLOW_MIN + pad) return "yellow";
  if (ratio >= RED_MIN) return "red";
  return null;
}

function predict(exam, rank, gender) {
  const types = exam === "jee_adv" ? ["IIT"] : ["NIT", "IIIT", "GFTI"];
  const genders = gender.toLowerCase().startsWith("f") ? ["Gender-Neutral", FEMALE_G] : ["Gender-Neutral"];
  const tList = types.map((t) => `'${t}'`).join(",");
  const gList = genders.map((g) => `'${g.replace(/'/g, "''")}'`).join(",");

  const cuts = rows(
    `SELECT i.name inst, i.type itype, p.name prog, c.quota, c.gender, c.year, c.round,
            c.opening_rank op, c.closing_rank cl
     FROM cutoffs c JOIN institutes i ON c.institute_id=i.id JOIN programs p ON c.program_id=p.id
     WHERE i.type IN (${tList}) AND c.gender IN (${gList}) AND c.closing_rank IS NOT NULL`);
  if (!cuts.length) return { candidates: [], counts: { green: 0, yellow: 0, red: 0 }, total: 0 };

  const latestYear = Math.max(...cuts.map((r) => r.year));
  const groups = new Map();
  for (const r of cuts) {
    const key = `${r.inst}|${r.prog}|${r.quota}|${r.gender}`;
    let g = groups.get(key);
    if (!g) { g = { inst: r.inst, itype: r.itype, prog: r.prog, quota: r.quota, gender: r.gender, perYear: {} }; groups.set(key, g); }
    const py = g.perYear[r.year];
    if (!py || r.round > py.round) g.perYear[r.year] = { round: r.round, cl: r.cl, op: r.op };
  }

  const seatMap = new Map();
  for (const s of rows(
    `SELECT i.name inst, p.name prog, s.gender, s.seats
     FROM seat_matrix s JOIN institutes i ON s.institute_id=i.id JOIN programs p ON s.program_id=p.id`))
    seatMap.set(`${s.inst}|${s.prog}|${s.gender}`, s.seats);

  const out = [];
  for (const g of groups.values()) {
    const ly = g.perYear[latestYear];
    if (!ly) continue;
    const trend = {};
    for (const y in g.perYear) trend[y] = g.perYear[y].cl;
    const proj = project(trend, ly.cl);
    const seats = seatMap.has(`${g.inst}|${g.prog}|${g.gender}`) ? seatMap.get(`${g.inst}|${g.prog}|${g.gender}`) : null;
    const b = bucketOf(rank, proj, seats);
    if (!b) continue;
    out.push({
      institute: g.inst, institute_type: g.itype, program: g.prog, quota: g.quota, gender: g.gender,
      year: latestYear, round: ly.round, closing_rank: ly.cl, projected_close: proj, opening_rank: ly.op,
      bucket: b, seats, trend,
    });
  }
  const order = { green: 0, yellow: 1, red: 2 };
  out.sort((a, b) => order[a.bucket] - order[b.bucket] || a.projected_close - b.projected_close);
  const counts = { green: 0, yellow: 0, red: 0 };
  out.forEach((c) => counts[c.bucket]++);
  return { candidates: out, counts, total: out.length };
}

function trendData(inst, prog, gender, quota) {
  const r = rows(
    `SELECT c.year, c.round, c.opening_rank op, c.closing_rank cl
     FROM cutoffs c JOIN institutes i ON c.institute_id=i.id JOIN programs p ON c.program_id=p.id
     WHERE i.name=? AND p.name=? AND c.gender=? AND c.quota=? AND c.closing_rank IS NOT NULL
     ORDER BY c.year, c.round`, [inst, prog, gender, quota]);
  const series = {};
  for (const x of r) (series[x.year] = series[x.year] || []).push({ round: x.round, opening: x.op, closing: x.cl });
  return { institute: inst, program: prog, gender, quota, series };
}

/* ---- helpers ----------------------------------------------------------- */
function splitProgram(name) {
  const m = name.match(/^(.*?)\s*\(([^)]*)\)\s*$/);
  return m ? { main: m[1], degree: m[2] } : { main: name, degree: "" };
}
const genderShort = (g) => g.replace(" (including Supernumerary)", " ✦");
function trendHTML(trend) {
  const years = Object.keys(trend).map(Number).sort((a, b) => a - b);
  if (!years.length) return '<span class="trend">—</span>';
  const vals = years.map((y) => trend[y]);
  const first = vals[0], last = vals[vals.length - 1];
  let dir = "flat", glyph = "→";
  if (last > first) { dir = "up"; glyph = "↑"; } else if (last < first) { dir = "down"; glyph = "↓"; }
  return `<span class="trend"><span class="trend__vals">${vals.join("·")}</span><span class="trend__arrow ${dir}">${glyph}</span></span>`;
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---- rendering --------------------------------------------------------- */
function renderTally(counts) {
  $("#tally").innerHTML = [
    ["green", "Safe", counts.green], ["yellow", "Moderate", counts.yellow], ["red", "Reach", counts.red],
  ].map(([k, label, n]) => `<span class="tally__chip ${k}">${label} <b>${n}</b></span>`).join("");
}

function buildTypeFilter(cands) {
  const types = TYPE_ORDER.filter((t) => cands.some((c) => c.institute_type === t));
  const el = $("#typeFilter");
  if (types.length <= 1) { el.hidden = true; el.innerHTML = ""; return; }
  const chip = (val, label, n) =>
    `<button class="chip ${filters.type === val ? "is-active" : ""}" data-type="${val}">${label} <b>${n}</b></button>`;
  el.hidden = false;
  el.innerHTML = chip("ALL", "All", cands.length) +
    types.map((t) => chip(t, t, cands.filter((c) => c.institute_type === t).length)).join("");
}
$("#typeFilter").addEventListener("click", (e) => {
  const b = e.target.closest(".chip");
  if (!b) return;
  filters.type = b.dataset.type;
  $("#typeFilter").querySelectorAll(".chip").forEach((c) => c.classList.toggle("is-active", c.dataset.type === filters.type));
  applyFilters();
});

/* ---- search + bucket toggles + column sort ----------------------------- */
function buildControls(cands) {
  $("#controls").hidden = false;
  $("#search").value = "";
  const counts = { green: 0, yellow: 0, red: 0 };
  cands.forEach((c) => counts[c.bucket]++);
  const lab = { green: "Safe", yellow: "Moderate", red: "Reach" };
  $("#bucketFilter").innerHTML = ["green", "yellow", "red"].map((k) =>
    `<button class="bchip ${k} ${filters.buckets.has(k) ? "" : "off"}" data-b="${k}">${lab[k]} ${counts[k]}</button>`).join("");
}
$("#search").addEventListener("input", (e) => { filters.search = e.target.value.trim().toLowerCase(); applyFilters(); });
$("#bucketFilter").addEventListener("click", (e) => {
  const b = e.target.closest(".bchip");
  if (!b) return;
  const k = b.dataset.b;
  if (filters.buckets.has(k)) filters.buckets.delete(k); else filters.buckets.add(k);
  b.classList.toggle("off", !filters.buckets.has(k));
  applyFilters();
});
// sortable column headers (delegated; headers are re-rendered each time)
$("#groups").addEventListener("click", (e) => {
  const th = e.target.closest("th.sortable");
  if (!th) return;
  const k = th.dataset.key;
  if (filters.sortKey === k) filters.sortDir *= -1;
  else { filters.sortKey = k; filters.sortDir = 1; }
  applyFilters();
});

function applyFilters() {
  let list = lastCandidates;
  if (filters.type !== "ALL") list = list.filter((c) => c.institute_type === filters.type);
  if (filters.search) list = list.filter((c) =>
    c.institute.toLowerCase().includes(filters.search) || c.program.toLowerCase().includes(filters.search));
  if (filters.buckets.size < 3) list = list.filter((c) => filters.buckets.has(c.bucket));
  if (filters.sortKey) {
    const k = filters.sortKey, d = filters.sortDir;
    list = [...list].sort((a, b) => {
      const A = a[k], B = b[k];
      if (typeof A === "string" || typeof B === "string")
        return String(A ?? "").localeCompare(String(B ?? "")) * d;
      return ((A ?? 0) - (B ?? 0)) * d;
    });
  }
  renderGroups(list);
}

function sortableTh(label, key, numeric = true) {
  const active = filters.sortKey === key;
  const arr = active ? (filters.sortDir > 0 ? "↑" : "↓") : "";
  return `<th class="${numeric ? "num " : ""}sortable" data-key="${key}">${label} <span class="arr">${arr}</span></th>`;
}

function renderGroups(candidates) {
  const byType = {};
  candidates.forEach((c) => (byType[c.institute_type] ??= []).push(c));
  const order = TYPE_ORDER.filter((t) => byType[t]).concat(Object.keys(byType).filter((t) => !TYPE_ORDER.includes(t)));
  const prefSet = new Set(prefs.map(prefKeyOf));

  $("#groups").innerHTML = order.map((type) => {
    const rws = byType[type].map((c) => {
      const p = splitProgram(c.program);
      const inst = esc(c.institute.replace(/\s+/g, " ").trim());
      const added = prefSet.has(prefKeyOf(c));
      return `<tr class="crow" data-institute="${esc(c.institute)}" data-program="${esc(c.program)}" data-gender="${esc(c.gender)}" data-quota="${esc(c.quota)}" data-bucket="${c.bucket}" data-closing="${c.closing_rank}" data-type="${c.institute_type}">
        <td><button type="button" class="addbtn ${added ? "added" : ""}" data-add title="Add to my choice order">${added ? "✓" : "＋"}</button><span class="bucket-tag ${c.bucket}">${c.bucket.toUpperCase()}</span></td>
        <td class="inst">${inst}</td>
        <td class="prog">${esc(p.main)}${p.degree ? `<small>${esc(p.degree)}</small>` : ""}</td>
        <td class="gender">${esc(genderShort(c.gender))}</td>
        <td class="num">${c.year}</td>
        <td class="num">R${c.round}</td>
        <td class="num" title="trend-projected: ${c.projected_close.toLocaleString()}">${c.closing_rank.toLocaleString()}</td>
        <td class="num">${c.seats ?? "—"}</td>
        <td>${trendHTML(c.trend)}</td>
        <td class="quota">${esc(c.quota)}</td>
      </tr>`;
    }).join("");
    return `
      <div class="group">
        <div class="group__head">
          <span class="group__type">${type}</span>
          <span class="group__count">${byType[type].length} option${byType[type].length > 1 ? "s" : ""}</span>
        </div>
        <div class="tbl-wrap">
          <table>
            <thead><tr>
              <th>Bucket</th>${sortableTh("Institute", "institute", false)}<th>Program</th><th>Gender</th>
              ${sortableTh("Year", "year")}<th class="num">Round</th>
              ${sortableTh("Closing", "closing_rank")}${sortableTh("Seats", "seats")}<th>Trend</th><th>Quota</th>
            </tr></thead>
            <tbody>${rws}</tbody>
          </table>
        </div>
      </div>`;
  }).join("");
}

function renderReportHead() {
  const examLabel = state.exam === "jee_adv" ? "JEE Advanced" : "JEE Main";
  const d = new Date().toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  $("#reportHead").innerHTML = `
    <h1>JoSAA Branch Prediction</h1>
    <div class="q">${examLabel} · rank <b>${Number($("#rank").value).toLocaleString()}</b> · ${state.gender} · generated ${d}</div>`;
}

/* ---- submit ------------------------------------------------------------ */
$("#form").addEventListener("submit", (e) => {
  e.preventDefault();
  const rank = parseInt($("#rank").value, 10);
  if (!rank || rank < 1 || !DB) return;

  const btn = $("#submitBtn");
  btn.disabled = true; btn.textContent = "Predicting…";
  $("#placeholder").hidden = true;
  try {
    const data = predict(state.exam, rank, state.gender);
    $("#results").hidden = false;
    if (!data.total) {
      $("#groups").innerHTML = `<div class="error">No reachable OPEN seats found for this rank — try a higher rank number.</div>`;
      $("#typeFilter").hidden = true; $("#controls").hidden = true; renderTally({ green: 0, yellow: 0, red: 0 });
    } else {
      lastCandidates = data.candidates;
      filters.type = "ALL"; filters.search = ""; filters.buckets = new Set(["green", "yellow", "red"]);
      filters.sortKey = "institute"; filters.sortDir = 1;   // default: alphabetical by institute
      renderTally(data.counts);
      buildTypeFilter(data.candidates);
      buildControls(data.candidates);
      applyFilters();
    }
    renderReportHead();
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    $("#results").hidden = false;
    $("#groups").innerHTML = `<div class="error">${esc(err.message)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "Predict";
  }
});

/* ---- export PDF -------------------------------------------------------- */
$("#exportBtn").addEventListener("click", () => { renderReportHead(); window.print(); });

/* ---- trends modal + interactive charts --------------------------------- */
const modal = $("#modal");
const YEAR_COLORS = { 0: "#c0492f", 1: "#c98a14", 2: "#195e4d", 3: "#5b6b8a" };
function openModal() { modal.hidden = false; document.body.style.overflow = "hidden"; }
function closeModal() { modal.hidden = true; document.body.style.overflow = ""; }
modal.addEventListener("click", (e) => { if ("close" in e.target.dataset) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeModal(); });

$("#groups").addEventListener("click", (e) => {
  if (e.target.closest(".addbtn")) return;   // add-to-prefs handled separately
  const tr = e.target.closest("tr.crow");
  if (tr) showTrend(tr.dataset);
});

/* ---- preference order builder ------------------------------------------ */
function syncAddButtons() {
  const set = new Set(prefs.map((p) => p.key));
  document.querySelectorAll("#groups .addbtn").forEach((btn) => {
    const d = btn.closest("tr.crow").dataset;
    const on = set.has(prefKeyOf(d));
    btn.classList.toggle("added", on);
    btn.textContent = on ? "✓" : "＋";
  });
}

$("#groups").addEventListener("click", (e) => {
  const btn = e.target.closest(".addbtn");
  if (!btn) return;
  const d = btn.closest("tr.crow").dataset;
  const key = prefKeyOf(d);
  if (prefs.some((p) => p.key === key)) {
    prefs = prefs.filter((p) => p.key !== key);
  } else {
    prefs.push({ key, institute: d.institute, program: d.program, gender: d.gender,
      quota: d.quota, bucket: d.bucket, closing: +d.closing, type: d.type });
  }
  savePrefs();
  renderPrefs();
  syncAddButtons();
});

$("#prefList").addEventListener("click", (e) => {
  const rm = e.target.closest(".pref__rm");
  if (!rm) return;
  const key = rm.closest(".pref").dataset.key;
  prefs = prefs.filter((p) => p.key !== key);
  savePrefs(); renderPrefs(); syncAddButtons(); markFinderAdded();
});

$("#prefClear").addEventListener("click", () => {
  if (!prefs.length) return;
  prefs = []; savePrefs(); renderPrefs(); syncAddButtons(); markFinderAdded();
});

/* export the choice order */
function csvCell(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
$("#prefCsv").addEventListener("click", () => {
  if (!prefs.length) return;
  const header = ["Preference", "Institute", "Program", "Gender", "Quota", "Bucket", "ClosingRank"];
  const rows = prefs.map((p, i) => [i + 1, p.institute.replace(/\s+/g, " ").trim(), p.program,
    p.gender, p.quota, p.bucket, p.closing]);
  const csv = [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8;" }));
  a.download = "josaa-choice-order.csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
$("#prefPdf").addEventListener("click", () => {
  if (!prefs.length) return;
  const d = new Date().toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  $("#prefPrintHead").innerHTML = `<h1>My JoSAA Choice Order</h1><div class="q">${prefs.length} choices · generated ${d}</div>`;
  document.body.classList.add("print-prefs");
  window.print();
});
window.addEventListener("afterprint", () => document.body.classList.remove("print-prefs"));

function updateTabBadge() {
  const b = $("#tabCount");
  if (!b) return;
  b.textContent = prefs.length;
  b.hidden = !prefs.length;
}

function renderPrefs() {
  const panel = $("#prefPanel"), list = $("#prefList"), empty = $("#prefEmpty");
  $("#prefCount").textContent = prefs.length ? `(${prefs.length})` : "";
  updateTabBadge();
  panel.hidden = false;   // panel lives in the Choice-list tab; only visible there
  if (!prefs.length) {
    if (empty) empty.hidden = false;
    list.innerHTML = "";
    if (prefSortable) { prefSortable.destroy(); prefSortable = null; }
    return;
  }
  if (empty) empty.hidden = true;
  list.innerHTML = prefs.map((p, i) => {
    const sub = [esc(genderShort(p.gender)), p.quota ? esc(p.quota) : null,
      p.closing ? `close ${p.closing.toLocaleString()}` : null].filter(Boolean).join(" · ");
    return `
    <li class="pref" data-key="${esc(p.key)}">
      <span class="pref__drag" title="drag to reorder">⠿</span>
      <span class="pref__rank">${i + 1}</span>
      <div class="pref__body">
        <div class="pref__title">${esc(p.institute.replace(/\s+/g, " ").trim())}${p.bucket ? `<span class="tag ${p.bucket}">${p.bucket.toUpperCase()}</span>` : ""}</div>
        <div class="pref__sub">${esc(splitProgram(p.program).main)} · ${sub}</div>
      </div>
      <button type="button" class="pref__rm" data-rm title="Remove">×</button>
    </li>`;
  }).join("");

  if (prefSortable) prefSortable.destroy();
  if (window.Sortable) {
    prefSortable = Sortable.create(list, {
      animation: 150, handle: ".pref__drag", ghostClass: "sortable-ghost", chosenClass: "sortable-chosen",
      onEnd: () => {
        const order = [...list.querySelectorAll(".pref")].map((li) => li.dataset.key);
        prefs.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
        savePrefs();
        list.querySelectorAll(".pref__rank").forEach((el, i) => (el.textContent = i + 1));
      },
    });
  }
}

const chartTip = document.createElement("div");
chartTip.className = "charttip"; chartTip.hidden = true;
document.body.appendChild(chartTip);
$("#m-body").addEventListener("mouseover", (e) => {
  const c = e.target.closest("circle[data-tip]");
  if (!c) return;
  chartTip.textContent = c.getAttribute("data-tip"); chartTip.hidden = false;
});
$("#m-body").addEventListener("mousemove", (e) => {
  if (chartTip.hidden) return;
  chartTip.style.left = (e.clientX + 14) + "px"; chartTip.style.top = (e.clientY + 14) + "px";
});
$("#m-body").addEventListener("mouseout", (e) => { if (e.target.closest("circle[data-tip]")) chartTip.hidden = true; });

function showTrend(d) {
  $("#m-title").textContent = d.institute.replace(/\s+/g, " ").trim();
  const pp = splitProgram(d.program);
  $("#m-sub").innerHTML = `${esc(pp.main)} · <span class="pool">${esc(genderShort(d.gender))} · ${esc(d.quota)}</span>`;
  $("#m-body").innerHTML = "";
  openModal();
  try {
    renderTrend(trendData(d.institute, d.program, d.gender, d.quota));
  } catch (err) {
    $("#m-body").innerHTML = `<div class="error">${esc(err.message)}</div>`;
  }
}

function svgChart(datasets, xLabels, { valueLabels = false } = {}) {
  const W = 760, H = 250, L = 52, R = 18, T = 18, B = 34;
  const plotW = W - L - R, plotH = H - T - B;
  const vals = datasets.flatMap((d) => d.points.map((p) => p[1]).filter((v) => v != null));
  if (!vals.length) return `<p class="modal__note">No data.</p>`;
  let yMin = Math.min(...vals), yMax = Math.max(...vals);
  if (yMin === yMax) { yMin -= 1; yMax += 1; }
  const pad = (yMax - yMin) * 0.12; yMin -= pad; yMax += pad;
  const n = xLabels.length;
  const xS = (i) => L + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const yS = (v) => T + ((v - yMin) / (yMax - yMin)) * plotH;

  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = yMin + (k / 4) * (yMax - yMin), y = yS(v);
    g += `<line class="grid" x1="${L}" y1="${y.toFixed(1)}" x2="${W - R}" y2="${y.toFixed(1)}"/>`;
    g += `<text class="tick" x="${L - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end">${Math.round(v).toLocaleString()}</text>`;
  }
  xLabels.forEach((lab, i) => { g += `<text class="tick" x="${xS(i).toFixed(1)}" y="${H - B + 16}" text-anchor="middle">${lab}</text>`; });
  g += `<line class="axis" x1="${L}" y1="${T}" x2="${L}" y2="${T + plotH}"/>`;
  g += `<line class="axis" x1="${L}" y1="${T + plotH}" x2="${W - R}" y2="${T + plotH}"/>`;

  for (const ds of datasets) {
    const pts = ds.points.filter((p) => p[1] != null);
    if (pts.length > 1) {
      const dpath = pts.map((p, i) => `${i ? "L" : "M"}${xS(p[0]).toFixed(1)},${yS(p[1]).toFixed(1)}`).join(" ");
      g += `<path d="${dpath}" fill="none" stroke="${ds.color}" stroke-width="2.2" stroke-linejoin="round"/>`;
    }
    for (const p of pts) {
      const tip = p[2] != null ? ` data-tip="${esc(String(p[2]))}"` : "";
      g += `<circle class="pt" cx="${xS(p[0]).toFixed(1)}" cy="${yS(p[1]).toFixed(1)}" r="3.6" stroke="${ds.color}"${tip}/>`;
      if (valueLabels) g += `<text class="ptval" x="${xS(p[0]).toFixed(1)}" y="${(yS(p[1]) - 8).toFixed(1)}" text-anchor="middle">${p[1].toLocaleString()}</text>`;
    }
  }
  const legend = datasets.length > 1
    ? `<div class="legend">${datasets.map((d) => `<span><i style="background:${d.color}"></i>${esc(d.name)}</span>`).join("")}</div>` : "";
  return `<svg viewBox="0 0 ${W} ${H}" role="img">${g}</svg>${legend}`;
}

function renderTrend(data) {
  const years = Object.keys(data.series).map(Number).sort((a, b) => a - b);
  if (!years.length) { $("#m-body").innerHTML = `<p class="modal__note">No historical data for this program.</p>`; return; }
  const finalClose = (rounds) => (rounds.length ? rounds[rounds.length - 1].closing : null);
  const maxRound = Math.max(...years.flatMap((y) => data.series[y].map((r) => r.round)));
  const roundLabels = Array.from({ length: maxRound }, (_, i) => "R" + (i + 1));

  const yearChart = svgChart(
    [{ name: "Final closing", color: "#195e4d",
       points: years.map((y, i) => { const v = finalClose(data.series[y]); return [i, v, v != null ? `${y}: closing ${v.toLocaleString()}` : null]; }) }],
    years.map(String), { valueLabels: true });

  const roundDatasets = years.map((y, idx) => ({
    name: String(y), color: YEAR_COLORS[idx] || "#888",
    points: data.series[y].map((r) => [r.round - 1, r.closing,
      r.closing != null ? `${y} · R${r.round}: closing ${r.closing.toLocaleString()}${r.opening ? ` (open ${r.opening.toLocaleString()})` : ""}` : null]),
  }));
  const roundChart = svgChart(roundDatasets, roundLabels);

  const head = `<tr><th>Year</th>${roundLabels.map((r) => `<th>${r}</th>`).join("")}</tr>`;
  const body = years.map((y) => {
    const byR = {}; data.series[y].forEach((r) => (byR[r.round] = r.closing));
    const cells = roundLabels.map((_, i) => `<td class="num">${byR[i + 1] != null ? byR[i + 1].toLocaleString() : "·"}</td>`).join("");
    return `<tr><td>${y}</td>${cells}</tr>`;
  }).join("");

  $("#m-body").innerHTML = `
    <div class="chart"><h4>Year-wise · final closing rank</h4>${yearChart}</div>
    <div class="chart"><h4>Round-wise · closing rank by round</h4>${roundChart}</div>
    <div><h4 style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);margin:0 0 8px">Closing rank — year × round</h4>
      <table class="mtable"><thead>${head}</thead><tbody>${body}</tbody></table></div>
    <p class="modal__note">Closing rank — lower is better, so points higher on the chart are stronger cutoffs. Quota: ${esc(data.quota || "—")}.</p>`;
}

/* ---- tabs --------------------------------------------------------------- */
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("is-active", x === t));
  const v = t.dataset.view;
  $("#view-predict").hidden = v !== "predict";
  $("#view-choices").hidden = v !== "choices";
  if (v === "choices") renderPrefs();
}));

/* ---- choice finder (rank-independent) ---------------------------------- */
let cType = "ALL", cQuery = "";
const finderKey = (inst, prog) => `${inst}||${prog}||Gender-Neutral||`;

function buildCFilter() {
  $("#cFilter").innerHTML = ["ALL", "IIT", "NIT", "IIIT", "GFTI"].map((t) =>
    `<button class="chip ${cType === t ? "is-active" : ""}" data-ctype="${t}">${t === "ALL" ? "All" : t}</button>`).join("");
}
$("#cFilter").addEventListener("click", (e) => {
  const b = e.target.closest(".chip"); if (!b) return;
  cType = b.dataset.ctype; buildCFilter(); runFinder();
});
$("#cSearch").addEventListener("input", (e) => { cQuery = e.target.value.trim(); runFinder(); });

function runFinder() {
  if (!DB) return;
  const out = $("#cResults"), hint = $("#cHint");
  if (cType === "ALL" && cQuery.length < 2) { out.innerHTML = ""; hint.hidden = false; return; }
  hint.hidden = true;
  const where = ["c.gender='Gender-Neutral'"], params = [];
  if (cType !== "ALL") { where.push("i.type=?"); params.push(cType); }
  // each typed word must appear in the institute OR program name (token AND)
  for (const tok of cQuery.split(/\s+/).filter(Boolean)) {
    where.push("(i.name LIKE ? OR p.name LIKE ?)");
    params.push(`%${tok}%`, `%${tok}%`);
  }
  const list = rows(`SELECT DISTINCT i.name inst, i.type itype, p.name prog
    FROM cutoffs c JOIN institutes i ON c.institute_id=i.id JOIN programs p ON c.program_id=p.id
    WHERE ${where.join(" AND ")} ORDER BY i.name, p.name LIMIT 300`, params);
  const set = new Set(prefs.map((p) => p.key));
  out.innerHTML = list.length ? list.map((o) => {
    const added = set.has(finderKey(o.inst, o.prog));
    return `<div class="fitem" data-inst="${esc(o.inst)}" data-prog="${esc(o.prog)}" data-type="${o.itype}">
      <span class="fitem__type">${o.itype}</span>
      <div class="fitem__body">
        <div class="fitem__inst">${esc(o.inst.replace(/\s+/g, " ").trim())}</div>
        <div class="fitem__prog">${esc(splitProgram(o.prog).main)}</div>
      </div>
      <button type="button" class="addbtn ${added ? "added" : ""}" data-fadd>${added ? "✓" : "＋"}</button>
    </div>`;
  }).join("") : `<p class="finder-hint">No matches${cQuery ? ` for “${esc(cQuery)}”` : ""}.</p>`;
}

function markFinderAdded() {
  const set = new Set(prefs.map((p) => p.key));
  document.querySelectorAll("#cResults .fitem").forEach((el) => {
    const btn = el.querySelector(".addbtn");
    const on = set.has(finderKey(el.dataset.inst, el.dataset.prog));
    btn.classList.toggle("added", on); btn.textContent = on ? "✓" : "＋";
  });
}

$("#cResults").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-fadd]"); if (!btn) return;
  const d = btn.closest(".fitem").dataset;
  const key = finderKey(d.inst, d.prog);
  if (prefs.some((p) => p.key === key)) {
    prefs = prefs.filter((p) => p.key !== key);
  } else {
    const m = rows(`SELECT closing_rank cl FROM cutoffs c JOIN institutes i ON c.institute_id=i.id JOIN programs p ON c.program_id=p.id
      WHERE i.name=? AND p.name=? AND c.gender='Gender-Neutral' ORDER BY year DESC, round DESC LIMIT 1`, [d.inst, d.prog]);
    prefs.push({ key, institute: d.inst, program: d.prog, gender: "Gender-Neutral", quota: "",
      bucket: "", closing: m.length ? m[0].cl : null, type: d.type });
  }
  savePrefs(); renderPrefs(); markFinderAdded();
});

/* ---- boot -------------------------------------------------------------- */
buildCFilter();
renderPrefs();   // restore any saved choice order immediately
(async () => {
  try {
    await initDB();
    const m = meta();
    $("#dbpill").classList.add("is-ok");
    $("#dbpill-text").textContent = `${m.cutoffs.toLocaleString()} cutoffs · ${m.institutes} institutes · ${m.years.join(", ")}`;
    $("#submitBtn").disabled = false;
    $("#form-note").textContent = "";
  } catch (e) {
    console.error(e);
    $("#dbpill-text").textContent = "failed to load data";
    $("#form-note").textContent = "Could not load data file.";
  }
})();
