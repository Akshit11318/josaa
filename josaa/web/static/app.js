"use strict";

const state = { exam: "jee_adv", gender: "male" };
const TYPE_ORDER = ["IIT", "NIT", "IIIT", "GFTI"];
const $ = (s, r = document) => r.querySelector(s);

let lastCandidates = [];
let typeFilter = "ALL";

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

/* ---- meta / db status -------------------------------------------------- */
async function loadMeta() {
  try {
    const m = await (await fetch("/api/meta")).json();
    const pill = $("#dbpill");
    pill.classList.add("is-ok");
    $("#dbpill-text").textContent =
      `${m.cutoffs.toLocaleString()} cutoffs · ${m.institutes} institutes · ${m.years.join(", ")}`;

    const ai = $("#ai"), hint = $("#ai-hint");
    if (!m.ai_available) {
      ai.disabled = true;
      hint.textContent = "(set ANTHROPIC_API_KEY to enable)";
    }
  } catch {
    $("#dbpill-text").textContent = "database unreachable";
  }
}

/* ---- helpers ----------------------------------------------------------- */
function splitProgram(name) {
  const m = name.match(/^(.*?)\s*\(([^)]*)\)\s*$/);
  return m ? { main: m[1], degree: m[2] } : { main: name, degree: "" };
}
function genderShort(g) {
  return g.replace(" (including Supernumerary)", " ✦");
}
function trendHTML(trend) {
  const years = Object.keys(trend).map(Number).sort((a, b) => a - b);
  if (!years.length) return '<span class="trend">—</span>';
  const vals = years.map((y) => trend[y]);
  const first = vals[0], last = vals[vals.length - 1];
  let dir = "flat", glyph = "→";
  if (last > first) { dir = "up"; glyph = "↑"; }
  else if (last < first) { dir = "down"; glyph = "↓"; }
  return `<span class="trend"><span class="trend__vals">${vals.join("·")}</span>` +
         `<span class="trend__arrow ${dir}">${glyph}</span></span>`;
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---- rendering --------------------------------------------------------- */
function renderTally(counts) {
  $("#tally").innerHTML = [
    ["green", "Safe", counts.green],
    ["yellow", "Moderate", counts.yellow],
    ["red", "Reach", counts.red],
  ].map(([k, label, n]) =>
    `<span class="tally__chip ${k}">${label} <b>${n}</b></span>`).join("");
}

function renderAI(ai) {
  const box = $("#ai-block");
  if (!ai) { box.innerHTML = ""; return; }
  const items = (ai.shortlist || []).map((p) => `
    <div class="ai__item">
      <span class="bucket-tag ${esc(p.label)}">${esc((p.label || "").toUpperCase())}</span>
      <div>
        <span class="where">${esc(p.institute)} <small>${esc(p.program)}</small></span>
        <span class="why">${esc(p.reason || "")}</span>
      </div>
    </div>`).join("");
  box.innerHTML = `
    <div class="ai">
      <h3 class="ai__title">Claude's shortlist</h3>
      <p class="ai__summary">${esc(ai.summary || "")}</p>
      <div class="ai__list">${items}</div>
    </div>`;
}

function renderGroups(candidates) {
  const byType = {};
  candidates.forEach((c) => (byType[c.institute_type] ??= []).push(c));
  const order = TYPE_ORDER.filter((t) => byType[t]).concat(
    Object.keys(byType).filter((t) => !TYPE_ORDER.includes(t)));

  $("#groups").innerHTML = order.map((type) => {
    const rows = byType[type].map((c) => {
      const p = splitProgram(c.program);
      const inst = esc(c.institute.replace(/\s+/g, " ").trim());
      return `<tr class="crow" data-institute="${esc(c.institute)}" data-program="${esc(c.program)}" data-gender="${esc(c.gender)}" data-quota="${esc(c.quota)}">
        <td><span class="bucket-tag ${c.bucket}">${c.bucket.toUpperCase()}</span></td>
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
              <th>Bucket</th><th>Institute</th><th>Program</th><th>Gender</th>
              <th class="num">Year</th><th class="num">Round</th>
              <th class="num">Closing</th><th class="num">Seats</th><th>Trend</th><th>Quota</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
  }).join("");
}

/* ---- institute-type filter (esp. JEE Main: NIT / IIIT / GFTI) ---------- */
function buildTypeFilter(cands) {
  const types = TYPE_ORDER.filter((t) => cands.some((c) => c.institute_type === t));
  const el = $("#typeFilter");
  if (types.length <= 1) { el.hidden = true; el.innerHTML = ""; return; }
  const chip = (val, label, n) =>
    `<button class="chip ${typeFilter === val ? "is-active" : ""}" data-type="${val}">${label} <b>${n}</b></button>`;
  el.hidden = false;
  el.innerHTML = chip("ALL", "All", cands.length) +
    types.map((t) => chip(t, t, cands.filter((c) => c.institute_type === t).length)).join("");
}

$("#typeFilter").addEventListener("click", (e) => {
  const b = e.target.closest(".chip");
  if (!b) return;
  typeFilter = b.dataset.type;
  $("#typeFilter").querySelectorAll(".chip").forEach((c) => c.classList.toggle("is-active", c.dataset.type === typeFilter));
  renderGroups(typeFilter === "ALL" ? lastCandidates : lastCandidates.filter((c) => c.institute_type === typeFilter));
});

function renderReportHead() {
  const examLabel = state.exam === "jee_adv" ? "JEE Advanced" : "JEE Main";
  const d = new Date().toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  $("#reportHead").innerHTML = `
    <h1>JoSAA Branch Prediction</h1>
    <div class="q">${examLabel} · rank <b>${Number($("#rank").value).toLocaleString()}</b>
      · ${state.gender} · generated ${d}</div>`;
}

/* ---- submit ------------------------------------------------------------ */
$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const rank = parseInt($("#rank").value, 10);
  if (!rank || rank < 1) return;

  const btn = $("#submitBtn");
  btn.disabled = true; btn.textContent = "Predicting…";
  $("#placeholder").hidden = true;

  try {
    const res = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exam: state.exam, rank, gender: state.gender,
        prefs: $("#prefs").value, ai: $("#ai").checked && !$("#ai").disabled,
      }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
    const data = await res.json();

    $("#results").hidden = false;
    if (!data.total) {
      $("#groups").innerHTML = `<div class="error">No reachable OPEN seats found for this rank.
        Try a higher rank number, or check that the crawler has populated the database.</div>`;
      $("#ai-block").innerHTML = ""; renderTally({ green: 0, yellow: 0, red: 0 });
    } else {
      lastCandidates = data.candidates;
      typeFilter = "ALL";
      renderTally(data.counts);
      renderAI(data.ai);
      buildTypeFilter(data.candidates);
      renderGroups(data.candidates);
    }
    renderReportHead();
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    $("#results").hidden = false;
    $("#groups").innerHTML = `<div class="error">${esc(err.message)}</div>`;
    $("#ai-block").innerHTML = ""; $("#tally").innerHTML = "";
  } finally {
    btn.disabled = false; btn.textContent = "Predict";
  }
});

/* ---- export PDF (native print → "Save as PDF" gives crisp vector text) -- */
$("#exportBtn").addEventListener("click", () => { renderReportHead(); window.print(); });

/* ---- trends modal ------------------------------------------------------ */
const modal = $("#modal");
const YEAR_COLORS = { 0: "#c0492f", 1: "#c98a14", 2: "#195e4d", 3: "#5b6b8a" };

function openModal() { modal.hidden = false; document.body.style.overflow = "hidden"; }
function closeModal() { modal.hidden = true; document.body.style.overflow = ""; }
modal.addEventListener("click", (e) => { if ("close" in e.target.dataset) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeModal(); });

$("#groups").addEventListener("click", (e) => {
  const tr = e.target.closest("tr.crow");
  if (tr) showTrend(tr.dataset);
});

// interactive chart tooltips
const chartTip = document.createElement("div");
chartTip.className = "charttip"; chartTip.hidden = true;
document.body.appendChild(chartTip);
$("#m-body").addEventListener("mouseover", (e) => {
  const c = e.target.closest("circle[data-tip]");
  if (!c) return;
  chartTip.textContent = c.getAttribute("data-tip");
  chartTip.hidden = false;
});
$("#m-body").addEventListener("mousemove", (e) => {
  if (chartTip.hidden) return;
  chartTip.style.left = (e.clientX + 14) + "px";
  chartTip.style.top = (e.clientY + 14) + "px";
});
$("#m-body").addEventListener("mouseout", (e) => {
  if (e.target.closest("circle[data-tip]")) chartTip.hidden = true;
});

async function showTrend(d) {
  $("#m-title").textContent = d.institute.replace(/\s+/g, " ").trim();
  const pp = splitProgram(d.program);
  $("#m-sub").innerHTML = `${esc(pp.main)} · <span class="pool">${esc(genderShort(d.gender))} · ${esc(d.quota)}</span>`;
  $("#m-body").innerHTML = `<p class="modal__note">Loading trend…</p>`;
  openModal();
  try {
    const qs = new URLSearchParams({ institute: d.institute, program: d.program, gender: d.gender, quota: d.quota });
    const data = await (await fetch("/api/trend?" + qs)).json();
    renderTrend(data);
  } catch (err) {
    $("#m-body").innerHTML = `<div class="error">${esc(err.message)}</div>`;
  }
}

// datasets: [{name, color, points:[[xIndex, value|null]]}], xLabels: string[]
function svgChart(datasets, xLabels, { valueLabels = false } = {}) {
  const W = 760, H = 250, L = 52, R = 18, T = 18, B = 34;
  const plotW = W - L - R, plotH = H - T - B;
  const vals = datasets.flatMap(d => d.points.map(p => p[1]).filter(v => v != null));
  if (!vals.length) return `<p class="modal__note">No data.</p>`;
  let yMin = Math.min(...vals), yMax = Math.max(...vals);
  if (yMin === yMax) { yMin -= 1; yMax += 1; }
  const pad = (yMax - yMin) * 0.12; yMin -= pad; yMax += pad;
  const n = xLabels.length;
  // lower rank = better -> plot smaller values HIGHER (reversed y)
  const xS = (i) => L + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const yS = (v) => T + ((v - yMin) / (yMax - yMin)) * plotH;

  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = yMin + (k / 4) * (yMax - yMin);
    const y = yS(v);
    g += `<line class="grid" x1="${L}" y1="${y.toFixed(1)}" x2="${W - R}" y2="${y.toFixed(1)}"/>`;
    g += `<text class="tick" x="${L - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end">${Math.round(v).toLocaleString()}</text>`;
  }
  xLabels.forEach((lab, i) => {
    g += `<text class="tick" x="${xS(i).toFixed(1)}" y="${H - B + 16}" text-anchor="middle">${lab}</text>`;
  });
  g += `<line class="axis" x1="${L}" y1="${T}" x2="${L}" y2="${T + plotH}"/>`;
  g += `<line class="axis" x1="${L}" y1="${T + plotH}" x2="${W - R}" y2="${T + plotH}"/>`;

  for (const ds of datasets) {
    const pts = ds.points.filter(p => p[1] != null);
    if (pts.length > 1) {
      const dpath = pts.map((p, i) => `${i ? "L" : "M"}${xS(p[0]).toFixed(1)},${yS(p[1]).toFixed(1)}`).join(" ");
      g += `<path d="${dpath}" fill="none" stroke="${ds.color}" stroke-width="2.2" stroke-linejoin="round"/>`;
    }
    for (const p of pts) {
      const tip = p[2] != null ? ` data-tip="${esc(String(p[2]))}"` : "";
      g += `<circle class="pt" cx="${xS(p[0]).toFixed(1)}" cy="${yS(p[1]).toFixed(1)}" r="3.6" stroke="${ds.color}"${tip}/>`;
      if (valueLabels)
        g += `<text class="ptval" x="${xS(p[0]).toFixed(1)}" y="${(yS(p[1]) - 8).toFixed(1)}" text-anchor="middle">${p[1].toLocaleString()}</text>`;
    }
  }
  const legend = datasets.length > 1
    ? `<div class="legend">${datasets.map(d => `<span><i style="background:${d.color}"></i>${esc(d.name)}</span>`).join("")}</div>`
    : "";
  return `<svg viewBox="0 0 ${W} ${H}" role="img">${g}</svg>${legend}`;
}

function renderTrend(data) {
  const years = Object.keys(data.series).map(Number).sort((a, b) => a - b);
  if (!years.length) { $("#m-body").innerHTML = `<p class="modal__note">No historical data for this program.</p>`; return; }

  const finalClose = (rounds) => rounds.length ? rounds[rounds.length - 1].closing : null;
  const maxRound = Math.max(...years.flatMap(y => data.series[y].map(r => r.round)));
  const roundLabels = Array.from({ length: maxRound }, (_, i) => "R" + (i + 1));

  // Year-wise: final-round closing rank per year
  const yearChart = svgChart(
    [{ name: "Final closing", color: "#195e4d",
       points: years.map((y, i) => {
         const v = finalClose(data.series[y]);
         return [i, v, v != null ? `${y}: closing ${v.toLocaleString()}` : null];
       }) }],
    years.map(String), { valueLabels: true });

  // Round-wise: one line per year across rounds
  const roundDatasets = years.map((y, idx) => ({
    name: String(y), color: YEAR_COLORS[idx] || "#888",
    points: data.series[y].map(r => [r.round - 1, r.closing,
      r.closing != null ? `${y} · R${r.round}: closing ${r.closing.toLocaleString()}${r.opening ? ` (open ${r.opening.toLocaleString()})` : ""}` : null]),
  }));
  const roundChart = svgChart(roundDatasets, roundLabels);

  // Raw table (closing rank by year × round)
  let head = `<tr><th>Year</th>${roundLabels.map(r => `<th>${r}</th>`).join("")}</tr>`;
  let body = years.map(y => {
    const byR = {}; data.series[y].forEach(r => byR[r.round] = r.closing);
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

loadMeta();
