/* Dome homepage. Reads what the agents wrote; never computes a tier or a score. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const fmt = new Intl.NumberFormat("en-US");
const f2 = (v) => (v == null ? "–" : Number(v).toFixed(2));

// No phone numbers on screen (ISO dates are fine).
const PHONE = /(?:\d[\s\-.()]{0,3}){6,10}\d/g;
const SPELLED = /five\s*5\s*five[\s\-.]*\S+/gi;
const scrub = (s) => String(s ?? "")
  .replace(PHONE, (m) => (/^\d{4}-\d{2}-\d{2}$/.test(m.trim()) ? m : "[phone]"))
  .replace(SPELLED, "[phone]");

const STEPS = ["spotter", "linker", "zoner", "lister", "locator", "briefer"];
let UI_FLAGS = {};
const FILES = ["rings.json", "zones.json", "candidates.json", "matches.json", "brief.json"];
const KIND_LABEL = {
  contact: "Same phone in ads", text: "Same ad script", photo: "Same photo", interaction: "Reposts & replies",
  place: "Same stated place", time: "Posting time", style: "Same writing style", heartbeat: "Shared rhythm",
  room: "Same room", route: "Same route", device: "Same device",
};
const kindLabel = (k) => KIND_LABEL[k] || (k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " "));
const COLORS = { ring: "#4cc9f0", rec: "#f5b14c", node: "#3a3f48", edge: "#23252a", dome: "#828fff",
                 High: "#ef5f5f", Medium: "#e0a84a", Low: "#62666d" };

const S = {
  presets: {}, preset: "ring_a", caseId: null, mode: "idle", next: 0, rows: [], files: {},
  graph: null, complex: null, ring: null, timer: null, polls: 0, logFilter: "all", colorBy: "role",
  view: "overview", started: 0,
};

// ------------------------------------------------------------------------- utils
async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw Object.assign(new Error(`${r.status} ${url}`), { status: r.status });
  return r.json();
}
const announce = (t) => { $("#live").textContent = t; };
const clock = (ts) => (ts || "").slice(11, 19);
const setKpi = (id, html, cls) => {
  const el = $(id); const b = $("b", el);
  b.innerHTML = html; el.classList.remove("arrive"); void el.offsetWidth; el.classList.add("arrive");
  el.classList.toggle("hl", cls === "hl");
};
const tip = $("#tip");
function showTip(html, x, y) { tip.innerHTML = html; tip.style.left = `${x + 14}px`; tip.style.top = `${y + 12}px`; tip.classList.add("on"); }
const hideTip = () => tip.classList.remove("on");

// ------------------------------------------------------------------------- views
function setView(name, push = true) {
  S.view = name;
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === `view-${name}`));
  $$(".rail a").forEach((a) => (a.dataset.view === name ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  if (push) { const u = new URL(location); u.searchParams.set("view", name); history.replaceState(null, "", u); }
  requestAnimationFrame(() => {
    MAPS.forEach((m) => {
      m.map.invalidateSize();
      if (m.pending && m.map.getSize().x) { const [fn, args] = m.pending; m.pending = null; m.map[fn](...args); }
    });
    // once the view has settled, frame the map on what matters now (lead pin, else the dome)
    clearTimeout(S.refitT);
    S.refitT = setTimeout(() => MAPS.forEach(refitMap), 380);
    refitGraphs();
  });
}
function refitGraphs() {
  // keep the ring in frame once it exists (unless the user asked for everything on the big graph)
  if (CY.topo) { CY.topo.resize(); CY.topo.fit(undefined, 24); }
  for (const [k, c] of [["mini", CY.mini], ["big", CY.big]]) {
    if (!c) continue;
    c.resize();
    const wantAll = k === "big" && $("#focusBtn")?.textContent === "Focus Ring";
    if (S.ring && !wantAll) { const a = ringArea(c); if (a.length) { c.fit(a, 36); continue; } }
    c.fit(undefined, 24);
  }
}
$$(".rail a").forEach((a) => a.addEventListener("click", (e) => {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;   // let new-tab clicks through
  e.preventDefault(); setView(a.dataset.view);
}));
document.addEventListener("click", (e) => {
  const h = e.target.closest("[data-guide]");
  if (!h) return;
  setView("guide");
  setTimeout(() => $(`#g-${h.dataset.guide}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
});

// ------------------------------------------------------------------------- stepper
function resetSteps() {
  $$(".step").forEach((s) => {
    s.classList.remove("active", "done", "failed");
    const sub = $(".t span", s); if (sub.dataset.orig) sub.textContent = sub.dataset.orig;
  });
  syncFlow();
}
// ---- How it works: the six agents as a data flow; numbers come from /flow (read from the case files)
let FLOW = null;
async function renderFlow(caseId) {
  try { FLOW = await getJSON(`/flow?case=${encodeURIComponent(caseId)}`); } catch { FLOW = null; $("#flowRow").innerHTML = ""; return; }
  $("#flowRow").innerHTML = FLOW.stages.map((s, i) => `<button type="button" class="flowstage" data-step="${esc(s.step)}" data-work="${esc(s.work)}" title="Show the work">
    <div class="ag"><i>${i + 1}</i>${esc(s.agent)}</div>
    <div class="io">in: ${esc(s.input)}<br>did: ${esc(s.did || "")}<br>out: <code>${esc(s.output)}</code></div>
    <div class="key" data-key="${esc(s.key || "")}">${esc(s.key || "–")}</div>${FLOW.steps ? `<div class="more">Show the work →</div>` : ""}</button>`).join("");
  syncFlow();
}
function syncFlow() {
  $$(".flowstage").forEach((f) => {
    const st = $(`.step[data-step="${f.dataset.step}"]`);
    const done = st?.classList.contains("done"), active = st?.classList.contains("active");
    f.classList.toggle("done", !!done); f.classList.toggle("active", !!active);
    const k = $(".key", f); k.textContent = done ? (k.dataset.key || "–") : (active ? "working…" : "–");
  });
}
$("#presentBtn")?.addEventListener("click", () => { document.body.classList.toggle("present"); $("#presentBtn").classList.toggle("primary"); });
document.addEventListener("click", (e) => {
  const f = e.target.closest(".flowstage"); if (f && window.DomeDrawer && FLOW?.steps) DomeDrawer.open(S.caseId, f.dataset.work);
  const w = e.target.closest("[data-why]"); if (w && window.DomeDrawer) DomeDrawer.open(S.caseId, "linker", w.dataset.why);
  const g = e.target.closest("[data-globe]"); if (g) location.href = `/globe?case=${encodeURIComponent(S.caseId)}&step=5`;
});
function stepEvent(row) {
  let base = (row.step || "").split(":")[0];
  if (base === "brief_text") base = "briefer";
  if (!STEPS.includes(base)) return;
  const el = $(`.step[data-step="${base}"]`);
  if (row.event === "tool_call") {
    $$(".step.active").forEach((s) => { if (s !== el) s.classList.remove("active"); });
    el.classList.remove("done", "failed"); el.classList.add("active");
    const sub = $(".t span", el); sub.dataset.orig ??= sub.textContent;
    if (row.step.includes(":")) sub.textContent = `Zone ${row.step.split(":")[1]}`;
    announce(`${base} running`);
  } else if (row.event === "tool_result") {
    el.classList.remove("active", "failed"); el.classList.add("done");
    STEPS.slice(0, STEPS.indexOf(base)).forEach((p) => $(`.step[data-step="${p}"]`).classList.add("done"));
    announce(`${base} done`);
  } else if (row.event === "step_failed") {
    el.classList.remove("active"); el.classList.add("failed"); announce(`${base} failed`);
  }
  syncFlow();
}

// ------------------------------------------------------------------------- log
function logRow(row) {
  const bad = row.event === "step_failed" || row.event === "refused" || row.event === "validation_failed";
  const isDecision = row.event === "decision";
  const msg = scrub(row.message || row.event);
  const head = `<span class="ts">${esc(clock(row.ts))}</span><span class="actor">${esc(row.actor)}</span>`
    + `<span class="step-n">${esc(row.step || "–")}</span>`;
  if (isDecision) {
    const ev = Object.entries(row.evidence || {}).map(([k, v]) =>
      `<div><span>${esc(k)}</span><span>${esc(scrub(typeof v === "object" ? JSON.stringify(v) : v))}</span></div>`).join("");
    const d = document.createElement("details");
    d.className = "drow"; d.dataset.kind = "decision";
    d.innerHTML = `<summary class="row decision">${head}<span class="msg"><span class="tag">${esc(row.decision)}</span>${esc(msg)}</span></summary>`
      + `<div class="ev">${ev || "<div><span>evidence</span><span>none</span></div>"}</div>`;
    return d;
  }
  const div = document.createElement("div");
  div.className = `row${bad ? " bad" : ""}`; div.dataset.kind = bad ? "bad" : "other";
  div.innerHTML = `${head}<span class="msg">${esc(msg)}</span>`;
  return div;
}
function appendLog(row) {
  for (const id of ["#logMini", "#logBig"]) {
    const box = $(id); const el = logRow(row);
    if (id === "#logBig") applyFilter(el);
    const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.appendChild(el);
    if (stick) box.scrollTop = box.scrollHeight;
  }
  $("#logEmpty").hidden = true;
}
function applyFilter(el) {
  const f = S.logFilter;
  el.hidden = !(f === "all" || el.dataset.kind === f);
}
$("#logSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  S.logFilter = b.dataset.f;
  $$("#logSeg button").forEach((x) => x.setAttribute("aria-pressed", x === b));
  $$("#logBig > *").forEach(applyFilter);
});

// ------------------------------------------------------------------------- graph (Cytoscape)
const CY = { mini: null, big: null, topo: null, pos: null };
const GRAPH_STYLE = [
  { selector: "node", style: { "background-color": COLORS.node, width: 11, height: 11, "border-width": 0,
      "transition-property": "background-color, width, height, border-width, opacity", "transition-duration": "450ms" } },
  { selector: "edge", style: { width: 0.7, "line-color": "#2b2f36", opacity: 0.55, "curve-style": "haystack" } },
  { selector: "node.member", style: { "background-color": COLORS.ring, width: 20, height: 20,
      "underlay-color": COLORS.ring, "underlay-padding": 6, "underlay-opacity": 0.18, "underlay-shape": "ellipse" } },
  { selector: "node.recruiter", style: { "border-width": 3, "border-color": COLORS.rec, width: 14, height: 14, "background-color": "#1d1f24" } },
  { selector: "node.seed", style: { "border-width": 2, "border-color": "#ffffff" } },
  { selector: "edge.ringlink", style: { width: 2.6, "line-color": COLORS.ring, opacity: 0.85, "curve-style": "straight" } },
  { selector: "edge.hint", style: { width: 1.2, "line-color": "#8a8f98", "line-style": "dashed", opacity: 0.6, "curve-style": "straight" } },
  { selector: ".faded", style: { opacity: 0.12 } },
  { selector: "node.hl", style: { "border-width": 2, "border-color": "#fff" } },
  { selector: "node:hidden", style: {} },
];

function graphElements(g) {
  const nodes = g.nodes.map((n) => ({ data: { id: n.id, handle: n.handle, posts: n.posts, created: n.created, flags: n.flags } }));
  const edges = g.edges.map((e, i) => ({ data: { id: `e${i}`, source: e.a, target: e.b, count: e.count, kinds: e.kinds } }));
  return [...nodes, ...edges];
}
function layoutOnce(g) {
  // Linked accounts get a force layout; unlinked ones are scattered on a ring around them, so
  // nothing jumps when the ring lights up (positions are frozen after this).
  const cy = cytoscape({ headless: true, elements: graphElements(g) });
  const linked = cy.nodes().filter((n) => n.degree(false) > 0);
  const pos = {};
  if (linked.length) {
    linked.union(linked.connectedEdges()).layout({ name: "cose", animate: false, randomize: true, nodeRepulsion: () => 12000,
      idealEdgeLength: () => 42, gravity: 0.9, componentSpacing: 60, numIter: 1200, boundingBox: { x1: 0, y1: 0, w: 900, h: 640 } }).run();
    // stretch the linked core to fill the centre, whatever scale cose settled on
    const bb = linked.boundingBox();
    const k = Math.min(760 / Math.max(bb.w, 1), 560 / Math.max(bb.h, 1));
    linked.forEach((n) => { const p = n.position(); pos[n.id()] = { x: 450 + (p.x - (bb.x1 + bb.w / 2)) * k, y: 320 + (p.y - (bb.y1 + bb.h / 2)) * k }; });
  }
  const loose = cy.nodes().filter((n) => n.degree(false) === 0);
  let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  loose.forEach((n, i) => {
    const a = (i / loose.length) * Math.PI * 2 + rnd() * 0.15; const r = 1 + rnd() * 0.22;
    pos[n.id()] = { x: 450 + Math.cos(a) * 560 * r, y: 320 + Math.sin(a) * 420 * r };
  });
  cy.destroy(); return pos;
}
function mountGraph(id, g) {
  const els = graphElements(g).map((el) => (el.data.source ? el : { ...el, position: CY.pos[el.data.id] }));
  const cy = cytoscape({ container: $(id), elements: els, style: GRAPH_STYLE, layout: { name: "preset", fit: true, padding: 20 },
                         minZoom: 0.2, maxZoom: 4, autoungrabify: true, boxSelectionEnabled: false });
  cy.on("mouseover", "node", (e) => {
    const n = e.target; const r = roleOf(n.id());
    const cells = S.complex?.byAcct?.[n.id()];
    showTip(`<b>${esc(n.data("handle"))}</b>${esc(r.label)}${cells ? `<br><span class="muted">${cells.cells} shared-key cells</span>` : ""}`,
            e.originalEvent.clientX, e.originalEvent.clientY);
  });
  cy.on("mouseover", "edge", (e) => {
    const d = e.target.data();
    const html = d.reason ? `<b>${esc((d.kindsList || []).map(kindLabel).join(" + "))}</b>${esc(scrub(d.reason))}`
      : `<b>${esc(Object.entries(d.kinds || {}).map(([k, v]) => `${v} ${k}${v > 1 ? "s" : ""}`).join(", "))}</b>between flagged accounts`;
    showTip(html, e.originalEvent.clientX, e.originalEvent.clientY);
  });
  cy.on("mouseout", hideTip);
  cy.on("tap", "node, edge", (e) => inspect(e.target));
  cy.on("tap", (e) => {
    if (e.target !== cy) return;
    const p = e.renderedPosition; let best = null, bd = 16;
    cy.nodes(":visible").forEach((n) => {
      const q = n.renderedPosition(); const d = Math.hypot(q.x - p.x, q.y - p.y) - n.renderedWidth() / 2;
      if (d < bd) { bd = d; best = n; }
    });
    if (best) { cy.nodes().removeClass("hl"); best.addClass("hl"); inspect(best); }
  });
  return cy;
}
function roleOf(id) {
  const r = S.ring;
  if (!r) return { role: "account", label: "flagged account" };
  if (r.members.includes(id)) return { role: "member", label: "ring member" };
  if ((r.recruiters || []).some((x) => x.account === id)) return { role: "recruiter", label: "likely recruiter" };
  return { role: "none", label: "not linked to the ring" };
}
function inspect(t) {
  const box = $("#inspect");
  if (t.isNode()) {
    const id = t.id(); const r = roleOf(id); const c = S.complex?.byAcct?.[id];
    const kinds = c ? Object.entries(c.kinds).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<span>${esc(kindLabel(k))}</span><span>${v}</span>`).join("") : "";
    box.innerHTML = `<h3>${esc(t.data("handle"))}</h3><p>${esc(r.label)}</p><div class="kv">`
      + `<span>Posts</span><span>${t.data("posts") ?? "–"}</span><span>Created</span><span>${esc(t.data("created") || "–")}</span>`
      + `<span>Topo P(in a ring)</span><span>${c?.p != null ? f2(c.p) : "–"}</span>${kinds}</div>`;
  } else {
    const d = t.data();
    box.innerHTML = d.reason
      ? `<h3>Ring link</h3><p>${esc((d.kindsList || []).map(kindLabel).join(" + "))}</p><p class="muted">${esc(scrub(d.reason))}</p>`
      : `<h3>Interaction</h3><p class="muted">${esc(Object.entries(d.kinds || {}).map(([k, v]) => `${v} × ${k}`).join(", "))}</p>`;
  }
}
async function loadGraph() {
  const data = S.presets[S.preset]?.data || "synth";
  try {
    const g = await getJSON(`/graph?data=${encodeURIComponent(data)}`);
    S.graph = g; CY.pos = layoutOnce(g);
    for (const k of ["mini", "big"]) { CY[k]?.destroy(); CY[k] = mountGraph(k === "mini" ? "#cyMini" : "#cyBig", g); }
    setKpi("#kFlag", fmt.format(g.nodes.length));
    $("#gSub").textContent = `${g.nodes.length} flagged accounts · ${fmt.format(g.edges.length)} interaction pairs`;
    if (S.ring) paintRing();
    paintColorMode();
  } catch (e) { console.warn(e); }
}
function paintRing() {
  const r = S.ring; if (!r) return;
  const members = new Set(r.members); const recs = new Set((r.recruiters || []).map((x) => x.account));
  for (const cy of [CY.mini, CY.big]) {
    if (!cy) continue;
    cy.batch(() => {
      cy.elements(".ringlink, .hint").remove();
      const cx = cy.nodes().length ? cy.nodes().boundingBox() : { x1: 0, y1: 0, w: 400, h: 300 };
      [...members, ...recs].forEach((id, i) => {
        if (cy.getElementById(id).empty()) cy.add({ data: { id, handle: id, posts: null }, position: { x: cx.x1 + cx.w / 2 + 40 * Math.cos(i), y: cx.y1 + cx.h / 2 + 40 * Math.sin(i) } });
      });
      cy.nodes().removeClass("member recruiter faded");
      cy.nodes().forEach((n) => { if (members.has(n.id())) n.addClass("member"); else if (recs.has(n.id())) n.addClass("recruiter"); });
      (r.links || []).forEach((l, i) => {
        if (!cy.getElementById(l.a).empty() && !cy.getElementById(l.b).empty())
          cy.add({ data: { id: `rl${i}`, source: l.a, target: l.b, reason: l.reason, kindsList: l.kinds }, classes: "ringlink" });
      });
      (S.files.rings?.weak_hints || []).filter((h) => members.has(h.a) || members.has(h.b)).slice(0, 40).forEach((h, i) => {
        if (!cy.getElementById(h.a).empty() && !cy.getElementById(h.b).empty())
          cy.add({ data: { id: `wh${i}`, source: h.a, target: h.b, reason: h.reason, kindsList: h.kinds }, classes: "hint" });
      });
    });
  }
  applyHide();
  focusRing(CY.mini, 900); focusRing(CY.big, 900);
  $("#focusBtn").textContent = "Show All";
}
function ringArea(cy) {
  return cy.nodes(".member, .recruiter").closedNeighborhood().nodes().filter((n) => n.style("display") !== "none");
}
function focusRing(cy, ms = 600) {
  if (!cy || !S.ring) return;
  const area = ringArea(cy); if (!area.length) return;
  cy.stop(); cy.animate({ fit: { eles: area, padding: 36 } }, { duration: ms, easing: "ease-in-out-cubic" });
}
function showAll(cy, ms = 600) { if (cy) { cy.stop(); cy.animate({ fit: { eles: cy.elements(), padding: 20 } }, { duration: ms, easing: "ease-in-out-cubic" }); } }
function paintColorMode() {
  const cy = CY.big; if (!cy) return;
  const mode = S.colorBy; const leg = $("#bigLegend");
  cy.nodes().style({ "background-color": "" });
  if (mode === "role") {
    leg.innerHTML = '<span><i style="background:var(--ring)"></i>Ring</span><span><i style="background:transparent;border:2px solid var(--recruiter)"></i>Recruiter</span><span><i style="background:#3a3f48"></i>Not linked</span><span><i style="background:transparent;border:1px dashed #8a8f98;border-radius:0;height:0;width:14px"></i>Weak hint</span>';
    return;
  }
  const by = S.complex?.byAcct || {};
  if (mode === "topo" && !S.complex?.hasP) {
    leg.innerHTML = '<span>Topological model is not installed on this machine, so no P(in a ring). Showing roles.</span>';
    return;
  }
  const val = (id) => (mode === "topo" ? by[id]?.p : by[id]?.cells);
  const vals = cy.nodes().map((n) => val(n.id())).filter((v) => v != null);
  const max = Math.max(1, ...vals);
  cy.nodes().forEach((n) => {
    const v = val(n.id()); if (v == null) return;
    const t = mode === "topo" ? v : Math.min(1, v / max);
    n.style("background-color", mix("#2a2e36", mode === "topo" ? "#ef5f5f" : "#828fff", t));
  });
  leg.innerHTML = mode === "topo"
    ? '<span><i style="background:#2a2e36"></i>P = 0</span><span><i style="background:#ef5f5f"></i>P = 1 · topological model</span>'
    : `<span><i style="background:#2a2e36"></i>0 cells</span><span><i style="background:#828fff"></i>${max} shared-key cells</span>`;
}
function mix(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(",")})`;
}
function applyHide() {
  const on = $("#hideLonely").checked; const cy = CY.big; if (!cy) return;
  cy.nodes().forEach((n) => n.style("display", on && n.degree(false) === 0 && !n.hasClass("member") && !n.hasClass("recruiter") ? "none" : "element"));
}
$("#hideLonely").addEventListener("change", applyHide);
$("#colorSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  S.colorBy = b.dataset.color; $$("#colorSeg button").forEach((x) => x.setAttribute("aria-pressed", x === b));
  paintColorMode();
});

// ------------------------------------------------------------------------- topology
async function loadComplex() {
  const data = S.presets[S.preset]?.data || "synth";
  for (let i = 0; i < 120; i++) {
    let c;
    try { c = await getJSON(`/complex?data=${encodeURIComponent(data)}`); } catch { return; }
    if (c.status === "ready") {
      c.byAcct = Object.fromEntries(c.accounts.map((a) => [a.id, a]));
      c.hasP = c.accounts.some((a) => a.p != null);
      S.complex = c; renderTopology(); paintColorMode(); return;
    }
    if (c.status === "error") { $("#topoEmpty").innerHTML = `<div><b>Topology view unavailable</b>${esc(c.error)}</div>`; return; }
    await new Promise((r) => setTimeout(r, 1500));
  }
}
function renderTopology() {
  const c = S.complex; if (!c) return;
  const total = Object.values(c.kinds).reduce((a, b) => a + b, 0) || 1;
  $("#cellBars").innerHTML = Object.entries(c.kinds).sort((a, b) => b[1] - a[1]).map(([k, v]) => hbar(kindLabel(k), v / total, fmt.format(v))).join("");
  $("#tSub").textContent = `${fmt.format(c.accounts.length)} accounts (rank 0) · ${fmt.format(c.cells.length)} shared-key cells (rank 1)`;
  renderTopoScore();
  // graph: ring accounts + cells touching them + the biggest other cells for contrast
  const ring = new Set(S.ring?.members || c.rings?.[0]?.members || []);
  // Drawn: the evidence-bearing cells (posting-time and place cells tie everything together, so
  // they stay in the bars and the heatmap but are not drawn).
  const small = c.cells.filter((x) => x.size <= 25 && !["place", "time"].includes(x.kind));
  const bySize = (a, b) => b.size - a.size;
  const touching = small.filter((x) => x.members.some((m) => ring.has(m))).sort(bySize).slice(0, 34);
  const others = small.filter((x) => !x.members.some((m) => ring.has(m))).sort(bySize).slice(0, 9);
  const cells = [...touching, ...others];
  const accts = new Set(cells.flatMap((x) => x.members));
  const handle = Object.fromEntries((S.graph?.nodes || []).map((n) => [n.id, n.handle]));
  const els = [
    ...[...accts].map((a) => ({ data: { id: a, label: handle[a] || a, ring: ring.has(a) ? 1 : 0 } })),
    ...cells.map((x) => ({ data: { id: x.id, kind: x.kind, size: x.size, cell: 1, touch: x.members.some((m) => ring.has(m)) ? 1 : 0 } })),
    ...cells.flatMap((x) => x.members.map((m, j) => ({ data: { id: `${x.id}-${j}`, source: x.id, target: m, ring: ring.has(m) ? 1 : 0 } }))),
  ];
  CY.topo?.destroy();
  CY.topo = cytoscape({
    container: $("#cyTopo"), elements: els, autoungrabify: false,
    style: [
      { selector: "node", style: { width: 10, height: 10, "background-color": "#8a8f98" } },
      { selector: "node[ring = 1]", style: { "background-color": COLORS.ring, width: 15, height: 15, "underlay-color": COLORS.ring, "underlay-opacity": 0.15, "underlay-padding": 5 } },
      { selector: "node[cell = 1]", style: { shape: "round-rectangle", "background-color": COLORS.dome, "background-opacity": 0.85,
          width: "mapData(size, 2, 25, 12, 30)", height: "mapData(size, 2, 25, 12, 30)", label: "data(kind)", color: "#d0d6e0",
          "font-size": 8, "font-family": "Geist Mono", "text-valign": "bottom", "text-margin-y": 3 } },
      { selector: "edge", style: { width: 0.8, "line-color": "#34343a", "curve-style": "haystack", opacity: 0.8 } },
      { selector: "edge[ring = 1]", style: { "line-color": COLORS.ring, opacity: 0.55 } },
    ],
    // concentric: ring accounts at the centre, the cells that bind them around it,
    // other accounts further out, unrelated cells on the rim
    layout: { name: "concentric", animate: true, animationDuration: 900, padding: 24, minNodeSpacing: 8,
              startAngle: -Math.PI / 2, levelWidth: () => 1,
              concentric: (n) => { const d = n.data(); return d.ring ? 4 : d.cell && d.touch ? 3 : d.cell ? 1 : 2; } },
  });
  CY.topo.on("mouseover", "node", (e) => {
    const d = e.target.data();
    const html = d.cell ? `<b>${esc(kindLabel(d.kind))}</b>rank 1 cell · ${d.size} accounts share this key`
      : `<b>${esc(d.label)}</b>rank 0 account${d.ring ? " · ring member" : ""}${c.byAcct[d.id]?.p != null ? ` · P ${f2(c.byAcct[d.id].p)}` : ""}`;
    showTip(html, e.originalEvent.clientX, e.originalEvent.clientY);
  });
  CY.topo.on("mouseout", hideTip);
  CY.topo.one("layoutstop", () => { CY.topo.resize(); CY.topo.fit(undefined, 24); });
  $("#topoEmpty").hidden = true;
  renderHeat(ring, handle);
}
function renderTopoScore() {
  const box = $("#topoScore"); const r = S.ring;
  if (!r) { box.innerHTML = '<h3>Two opinions on the ring</h3><p class="muted">Appears when rings.json is written.</p>'; return; }
  const topo = r.topo_score ?? S.complex?.rings?.find((x) => x.members.join() === r.members.join())?.topo_score;
  box.innerHTML = `<h3>Two opinions on the ring</h3><div class="hbars">${hbar("Rules · R", r.confidence, f2(r.confidence))}`
    + (topo != null ? hbar("Topological model", topo, f2(topo)) : "") + "</div>"
    + (topo != null ? '<p class="muted" style="margin-top:8px;font-size:12px">The model is a second opinion. The rules make every link and every reason; the model never changes a tier.</p>'
      : '<p class="muted" style="margin-top:8px;font-size:12px">The topological model (TopoModelX) is not installed on this machine, so only the rule score is shown. The structure on the left is the same either way.</p>');
}
function renderHeat(ring, handle) {
  const c = S.complex;
  const kinds = Object.entries(c.kinds).sort((a, b) => b[1] - a[1]).map(([k]) => k).slice(0, 7);
  const members = c.accounts.filter((a) => ring.has(a.id)).sort((a, b) => b.cells - a.cells).slice(0, 10);
  const others = c.accounts.filter((a) => !ring.has(a.id)).sort((a, b) => b.cells - a.cells).slice(0, 6);
  const rows = [...members, ...others];
  const max = Math.max(1, ...rows.flatMap((a) => kinds.map((k) => a.kinds[k] || 0)));
  const h = $("#heat");
  h.style.gridTemplateColumns = `92px repeat(${kinds.length}, 1fr)`;
  h.innerHTML = `<span></span>${kinds.map((k) => `<span class="hh" title="${esc(kindLabel(k))}">${esc(k)}</span>`).join("")}`
    + rows.map((a) => `<span class="hr${ring.has(a.id) ? " ring" : ""}" title="${esc(handle[a.id] || a.id)}">${esc(handle[a.id] || a.id)}</span>`
      + kinds.map((k) => { const v = a.kinds[k] || 0; const t = v / max;
          return `<span class="hc" style="background:rgba(130,143,255,${(0.06 + t * 0.8).toFixed(2)})">${v || ""}</span>`; }).join("")).join("");
}
function hbar(label, frac, value, thr) {
  const w = Math.max(0, Math.min(1, frac || 0));
  return `<div class="hbar"><span class="lab" title="${esc(label)}">${esc(label)}</span><span class="tr"><i style="width:${(w * 100).toFixed(1)}%"></i>`
    + (thr != null ? `<span class="thr" style="left:${thr * 100}%"></span>` : "") + `</span><span class="v">${esc(value)}</span></div>`;
}

// ------------------------------------------------------------------------- maps (Leaflet)
const MAPS = [];
function go(m, method, ...args) {
  const size = m.map.getSize();
  if (!size.x || !size.y) { m.pending = [method, args]; return; }
  m.map[method](...args);
}
function makeMap(id) {
  const map = L.map(id, { zoomControl: true, attributionControl: true, preferCanvas: true }).setView([29.758, -95.37], 11);
  // Esri's dark grey canvas, base layer only: no street names, no labels (areas, not addresses)
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Tiles &copy; Esri", maxZoom: 14 }).addTo(map);
  map.setMaxZoom(14);   // closer than this the base map starts naming features
  const m = { map, zones: L.layerGroup().addTo(map), cands: L.layerGroup().addTo(map), pins: L.layerGroup().addTo(map), dots: {} };
  MAPS.push(m); return m;
}
function refitMap(m) {
  m.map.invalidateSize();
  if (!m.map.getSize().x) return;
  const top = S.files.brief?.leads?.[0] && coordsOf(S.files.brief.leads[0].property_id);
  if (top) { m.map.flyTo(top, 14, { duration: 0.9 }); return; }
  const zs = S.files.zones?.zones || [];
  if (zs.length) m.map.flyToBounds(zs.map((z) => L.latLngBounds(z.polygon)).reduce((x, y) => x.extend(y)), { padding: [24, 24], duration: 0.9 });
}
function caption(html) { $("#capMini").innerHTML = html; $("#capBig").innerHTML = html; }
function drawZones(z) {
  for (const m of MAPS) {
    m.zones.clearLayers();
    const all = [];
    for (const zone of z.zones || []) {
      L.polygon(zone.polygon, { color: COLORS.dome, weight: 7, opacity: 0.12, fill: false, interactive: false }).addTo(m.zones);
      const p = L.polygon(zone.polygon, { color: COLORS.dome, weight: 1.6, fillColor: "#5e6ad2", fillOpacity: 0.16, dashArray: zone.wide ? "6 6" : null })
        .bindPopup(`<b>${esc(zone.zone_id)}</b><br>${zone.area_km2} km² · confidence ${f2(zone.confidence)}<br><span class="muted">${esc(scrub(zone.reasons?.[0] || ""))}</span>`)
        .addTo(m.zones);
      all.push(p.getBounds());
    }
    if (all.length) go(m, "flyToBounds", all.reduce((a, b) => a.extend(b)), { padding: [24, 24], duration: 1.3 });
  }
  const zone = z.zones?.[0];
  if (zone) {
    $("#mSub").textContent = `${z.zones.length} zone${z.zones.length > 1 ? "s" : ""} · ${zone.area_km2} km²`;
    caption(`<b>The dome:</b> ${zone.area_km2} km² · ${esc(scrub(zone.reasons?.[0] || ""))}`);
    setKpi("#kZone", `${zone.area_km2}<small> km²${zone.wide ? " · wide" : ""}</small>`);
    $("#zoneCard").innerHTML = `<h3>The zone ${esc(zone.zone_id)}${zone.wide ? ' <span class="chip">wide</span>' : ""}</h3><div class="kv">`
      + `<span>Area</span><span>${zone.area_km2} km²</span><span>Weight share</span><span>${Math.round(zone.weight_share * 100)}%</span>`
      + `<span>Confidence Z</span><span>${f2(zone.confidence)}</span></div>`
      + `<ul class="reasons" style="margin-top:8px">${(zone.reasons || []).map((r) => `<li>${esc(scrub(r))}</li>`).join("")}</ul>`;
    $("#clueList").innerHTML = `<ul class="reasons">${(zone.reasons || []).map((r) => `<li>${esc(scrub(r))}</li>`).join("")}</ul>`;
  }
}
function drawCandidates(c) {
  const zones = c.zones || []; const cands = zones.flatMap((z) => z.candidates || []);
  const total = zones.reduce((a, z) => a + (z.total_in_zone || 0), 0);
  for (const m of MAPS) {
    m.cands.clearLayers(); m.dots = {};
    cands.forEach((x) => {
      m.dots[x.property_id] = L.circleMarker([x.lat, x.lon], { radius: 5, color: "#8a8f98", weight: 1, fillColor: "#62666d", fillOpacity: 0.9 })
        .bindTooltip(`${esc(x.type)}${x.floors ? ` · ${x.floors} floors` : ""} · fit ${f2(x.fit)}${x.has_scan ? " · 3D scan" : ""}`)
        .addTo(m.cands);
    });
  }
  caption(`<b>${fmt.format(total)}</b> buildings in the zone → <b>${cands.length}</b> fit the photos`);
  setKpi("#kCand", `${fmt.format(total)} <small>→</small> ${cands.length}`);
  renderFunnel(); renderTable();
}
function drawMatches(mt) {
  for (const mz of mt.zones || []) {
    for (const m of mz.matches || []) {
      for (const mp of MAPS) {
        const d = mp.dots[m.property_id]; if (!d) continue;
        if (m.P >= mz.threshold) d.setStyle({ color: "#fff", fillColor: COLORS.dome, radius: 7, fillOpacity: 1 });
        else d.setStyle({ fillOpacity: 0.2, opacity: 0.3 });
      }
    }
  }
  const all = (mt.zones || []).flatMap((z) => z.matches.map((m) => ({ ...m, thr: z.threshold })));
  const above = all.filter((m) => m.P >= m.thr).length;
  caption(`<b>${all.length}</b> scanned buildings photo-checked → <b>${above}</b> above the match threshold`);
  setKpi("#kCand", `${$("#kCand b").textContent.split("→")[0].trim()} <small>→</small> ${above}`);
  const thr = mt.zones?.[0]?.threshold ?? 0.4;
  $("#pBars").innerHTML = all.sort((a, b) => b.P - a.P).map((m) => hbar(leadName(m.property_id) || m.property_id, m.P, f2(m.P), thr)).join("") || '<p class="muted">No scanned building in the zone.</p>';
  renderFunnel(); renderTable();
}
function leadName(pid) { return S.files.brief?.leads?.find((l) => l.property_id === pid)?.display_name; }
function coordsOf(pid) {
  for (const z of S.files.candidates?.zones || []) for (const c of z.candidates || []) if (c.property_id === pid) return [c.lat, c.lon];
  for (const z of S.files.matches?.zones || []) for (const m of z.matches || []) if (m.property_id === pid && m.geo) return [m.geo.lat, m.geo.lon];
  return null;
}
function drawPins(b) {
  for (const m of MAPS) {
    m.pins.clearLayers();
    for (const l of b.leads || []) {
      const ll = coordsOf(l.property_id); if (!ll) continue;
      const icon = L.divIcon({ className: "", iconSize: [0, 0], html: `<div class="pin ${esc(l.tier)}"><i></i><span>${esc(l.display_name)} · ${esc(l.tier)} ${l.score}</span></div>` });
      L.marker(ll, { icon, keyboard: true, title: l.display_name }).bindPopup(
        `<b>${esc(l.display_name)}</b> · <span style="color:${COLORS[l.tier]}">${esc(l.tier)}</span> ${l.score}`
        + `<ul class="reasons">${l.reasons.slice(0, 3).map((r) => `<li>${esc(scrub(r))}</li>`).join("")}</ul>`).addTo(m.pins);
    }
    const top = b.leads?.[0] && coordsOf(b.leads[0].property_id);
    if (top) setTimeout(() => go(m, "flyTo", top, 14, { duration: 1.6 }), 400);
  }
  if (b.leads?.[0]) caption(`<b>${esc(b.leads[0].display_name)}</b> · ${esc(b.leads[0].tier)} ${b.leads[0].score} · a lead for human verification`);
}

// ------------------------------------------------------------------------- leads + evidence
function renderLeads(b) {
  const box = $("#leadsMini"); box.innerHTML = "";
  $("#leadsEmpty").hidden = (b.leads || []).length > 0;
  if (!(b.leads || []).length) $("#leadsEmpty").innerHTML = `<div><b>${b.status === "weak_ring_zone_only" ? "Weak ring: the zone is the only output" : "No building lead"}</b>A building needs a photo match to become a lead.</div>`;
  for (const l of b.leads || []) {
    const fs = ["R", "Z", "F", "P", "W"].map((k) => {
      const v = l.factors[k];
      return `<div class="f${v == null ? " skipped" : ""}"><b>${k}</b> ${v == null ? "skipped" : f2(v)}<div class="bar"><i style="width:${v == null ? 100 : v * 100}%"></i></div></div>`;
    }).join("");
    const el = document.createElement("article");
    el.className = `lead ${l.tier}`;
    el.innerHTML = `<div class="lead-top"><span class="rank">#${l.rank}</span><h3>${esc(String(l.display_name).replace(/ *[(]synthetic case[)]/, ""))}</h3>${UI_FLAGS.globe ? `<button class="btn" data-globe type="button" title="Open this building in the Globe">Open in Globe</button>` : ""}<span class="tier ${esc(l.tier)}">${esc(l.tier)}</span>`
      + `<span class="score num">${l.score}<small>/100</small></span></div><div class="factors">${fs}</div>`
      + `<ul class="reasons">${l.reasons.map((r) => `<li>${esc(scrub(r))}</li>`).join("")}${(l.caps || []).map((c) => `<li class="cap">${esc(scrub(c))}</li>`).join("")}</ul>`
      + `<details class="verify"><summary><b>Verify next</b> · ${(l.verify_next || []).length} checks for a human</summary><ul>${(l.verify_next || []).map((v) => `<li>${esc(scrub(v))}</li>`).join("")}</ul></details>`;
    box.appendChild(el);
  }
  const foot = document.createElement("p"); foot.className = "footer-note"; foot.textContent = b.footer || ""; box.appendChild(foot);
  const top = b.leads?.[0];
  setKpi("#kLead", top ? `<span style="color:${COLORS[top.tier]}">${esc(top.tier)}</span> ${top.score}` : "none", top?.tier === "High" ? "hl" : "");
  if (top) {
    $("#factorBars").innerHTML = ["R", "Z", "F", "P", "W"].map((k) => hbar(`${k} · ${({ R: "ring", Z: "zone", F: "fit", P: "photo", W: "window" })[k]}`, top.factors[k], top.factors[k] == null ? "skipped" : f2(top.factors[k]), k === "P" || k === "W" || k === "R" ? 0.6 : null)).join("")
      + `<p style="margin:10px 0 0;font-size:12.5px">${esc(top.display_name)} · <b style="color:${COLORS[top.tier]}">${esc(top.tier)}</b> · score ${top.score}</p>`;
  }
  const link = $("#sumLink"); link.href = `/case/${encodeURIComponent(S.caseId)}/summary`; link.hidden = false;
  renderFunnel(); renderTable();
}
function renderFunnel() {
  const c = S.files.candidates, m = S.files.matches, b = S.files.brief, z = S.files.zones;
  const steps = [];
  if (z) steps.push(["Dome area", `${z.zones?.[0]?.area_km2 ?? "–"} km²`, 1]);
  if (c) {
    const total = c.zones.reduce((a, x) => a + (x.total_in_zone || 0), 0); const n = c.zones.reduce((a, x) => a + x.candidates.length, 0);
    steps.push(["Buildings in the zone", fmt.format(total), 0.85], ["Fit the photos", n, 0.6], ["Have a 3D scan", c.zones.flatMap((x) => x.candidates).filter((x) => x.has_scan).length, 0.45]);
  }
  if (m) steps.push(["Photo match ≥ threshold", m.zones.flatMap((x) => x.matches.filter((y) => y.P >= x.threshold)).length, 0.3]);
  if (b) steps.push(["Leads", (b.leads || []).length, 0.18]);
  if (steps.length) $("#funnel").innerHTML = steps.map(([k, v, w]) => `<div class="fun"><i style="width:${w * 100}%"></i><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("");
}
function renderTable() {
  const c = S.files.candidates; if (!c) return;
  const ms = {}; let thr = 0.4;
  for (const z of S.files.matches?.zones || []) { thr = z.threshold; for (const m of z.matches) ms[m.property_id] = m; }
  const leads = Object.fromEntries((S.files.brief?.leads || []).map((l) => [l.property_id, l]));
  const rows = c.zones.flatMap((z) => z.candidates).sort((a, b) => (ms[b.property_id]?.P ?? -1) - (ms[a.property_id]?.P ?? -1) || b.fit - a.fit);
  $("#candTable tbody").innerHTML = rows.map((x) => {
    const m = ms[x.property_id]; const l = leads[x.property_id];
    const result = l ? `<span class="tier ${esc(l.tier)}">${esc(l.tier)} ${l.score}</span>` : !x.has_scan ? "No reference photos"
      : m ? (m.P >= thr ? "Matched" : "Below threshold") : "Not checked yet";
    return `<tr class="${l ? "" : "dim"}"><td>${esc(l?.display_name || x.property_id)}</td><td>${esc(x.type)}</td><td class="num">${x.floors ?? "–"}</td>`
      + `<td class="num">${f2(x.fit)}</td><td>${x.has_scan ? "yes" : "no"}</td><td class="num">${m ? f2(m.P) : "–"}</td>`
      + `<td class="num">${m ? (m.W == null ? "skipped" : f2(m.W)) : "–"}</td><td>${result}</td></tr>`;
  }).join("");
}
function renderKinds(r) {
  const counts = {};
  (r.links || []).forEach((l) => (l.kinds || []).forEach((k) => { counts[k] = (counts[k] || 0) + 1; }));
  const max = Math.max(1, ...Object.values(counts));
  $("#kindBars").innerHTML = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => hbar(kindLabel(k), v / max, `${v}`)).join("")
    || `<p class="muted">Key kinds: ${esc((r.key_kinds || []).map(kindLabel).join(", "))}</p>`;
}

// ------------------------------------------------------------------------- files
async function onFile(name) {
  let data;
  try { data = await getJSON(`/case/${encodeURIComponent(S.caseId)}/file/${name}`); } catch { return; }
  const key = name.replace(".json", ""); S.files[key] = data;
  if (key === "brief" && FLOW) renderFlow(S.caseId);
  if (S.mode !== "idle" && $("#tour").checked) tour(key);
  if (key === "rings") {
    const seed = S.presets[S.preset]?.seed;
    const rings = data.rings || [];
    S.ring = rings.find((r) => seed && r.members.includes(seed)) || [...rings].sort((a, b) => b.confidence - a.confidence)[0] || null;
    $("#publicChip").hidden = data.private_layers !== false;
    if (S.ring) {
      setKpi("#kRing", `${S.ring.members.length}<small> + ${(S.ring.recruiters || []).length} recruiters · R ${f2(S.ring.confidence)}</small>`);
      paintRing(); renderKinds(S.ring); renderTopoScore(); if (S.complex) renderTopology();
      $("#nSub").textContent = `${S.ring.ring_id}: ${S.ring.members.length} accounts linked by ${(S.ring.key_kinds || []).filter((k) => k !== "place" && k !== "time").map(kindLabel).join(", ")}`;
    }
  }
  if (key === "zones") drawZones(data);
  if (key === "candidates") drawCandidates(data);
  if (key === "matches") drawMatches(data);
  if (key === "brief") {
    if (data.ring_id && S.files.rings) { const r = S.files.rings.rings.find((x) => x.ring_id === data.ring_id); if (r && r !== S.ring) { S.ring = r; paintRing(); renderKinds(r); } }
    renderLeads(data); drawPins(data); renderTable();
  }
}
let tourT;
function tour(key) {
  clearTimeout(tourT);
  const go = { rings: "network", zones: "map", brief: "map" }[key];
  if (go && S.view !== go) setView(go);
  if (key === "brief") tourT = setTimeout(() => setView("overview"), 3200);   // end on the full story
}
function handleRow(row) {
  S.rows.push(row); appendLog(row); stepEvent(row);
  if (row.event === "tool_result" && FILES.includes(row.output_file)) onFile(row.output_file);
}

// ------------------------------------------------------------------------- run / replay / load
function resetCase(caseId) {
  clearTimeout(S.timer); S.caseId = caseId; renderFlow(caseId); S.next = 0; S.rows = []; S.files = {}; S.ring = null;
  resetSteps(); ["#logMini", "#logBig", "#leadsMini"].forEach((id) => { $(id).innerHTML = ""; });
  $("#logEmpty").hidden = false; $("#leadsEmpty").hidden = false;
  $("#leadsEmpty").innerHTML = "<div><b>No leads yet</b>A building needs a photo match to become a lead.</div>";
  for (const m of MAPS) { m.zones.clearLayers(); m.cands.clearLayers(); m.pins.clearLayers(); go(m, "setView", [29.758, -95.37], 11); }
  caption(""); ["#kRing", "#kZone", "#kCand", "#kLead"].forEach((k) => { $(`${k} b`).textContent = "–"; $(k).classList.remove("hl"); });
  $("#sumLink").hidden = true; $("#publicChip").hidden = true;
  const raw = $("#rawLog"); raw.href = `/case/${encodeURIComponent(caseId)}/log.jsonl`; raw.hidden = false;
  if (CY.mini) paintRing();
  showAll(CY.mini, 400); showAll(CY.big, 400); if ($("#focusBtn")) $("#focusBtn").textContent = "Focus Ring";
  [CY.mini, CY.big].forEach((cy) => cy && cy.batch(() => { cy.elements(".ringlink, .hint").remove(); cy.nodes().removeClass("member recruiter"); }));
}
function busy(on, label) {
  $("#runBtn").disabled = on; $("#replaySel").disabled = on;
  $$("#presetSeg button").forEach((b) => { b.disabled = on; });
  $("#runBtn span").textContent = on ? (label || "Running…") : "Run Case";
}
async function runCase() {
  const scripted = $("#scripted").checked;
  let res;
  try { res = await getJSON("/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ preset: S.preset, scripted }) }); }
  catch (e) { announce(e.status === 409 ? "A run is already going." : "Could not start the run."); return; }
  resetCase(res.case); S.mode = "live"; S.started = Date.now(); busy(true);
  $("#caseTitle").textContent = `Running ${S.presets[S.preset].label.split(" · ")[0]}…`;
  setUrl({ replay: null });
  poll();
}
async function poll() {
  try {
    const lg = await getJSON(`/case/${encodeURIComponent(S.caseId)}/log?since=${S.next}`);
    lg.rows.forEach(handleRow); S.next = lg.next;
    const st = await getJSON("/status");
    const secs = Math.round((Date.now() - S.started) / 1000);
    if (st.running) {
      $("#caseTitle").textContent = `Running ${S.presets[S.preset].label.split(" · ")[0]}… ${secs}s`;
      S.timer = setTimeout(poll, 700); return;
    }
    const tail = await getJSON(`/case/${encodeURIComponent(S.caseId)}/log?since=${S.next}`);
    tail.rows.forEach(handleRow); S.next = tail.next;
    for (const f of FILES) if (!S.files[f.replace(".json", "")]) await onFile(f);
    finish(st.returncode === 0 ? `complete in ${secs}s` : "stopped with an error (see run.out)");
  } catch (e) { console.warn(e); S.timer = setTimeout(poll, 1500); }
}
function finish(msg) {
  S.mode = "idle"; busy(false);
  $("#caseTitle").textContent = `${S.presets[S.preset]?.label.split(" · ")[0] || S.caseId} · ${msg}`;
  $$(".step.active").forEach((s) => { s.classList.remove("active"); s.classList.add("done"); });
  announce(`Case ${msg}`); refreshCases();
}
async function replay(caseId) {
  resetCase(caseId); S.mode = "replay"; busy(true, "Replaying…");
  const presetKey = Object.keys(S.presets).find((k) => S.presets[k].case === caseId);
  if (presetKey && presetKey !== S.preset) await choosePreset(presetKey, false);
  $("#caseTitle").textContent = `Replaying ${caseId}`;
  let all;
  try { all = await getJSON(`/case/${encodeURIComponent(caseId)}/log?since=0`); } catch { finish("not found"); return; }
  const rows = all.rows; let i = 0;
  const tick = () => {
    if (i >= rows.length) { finish("replayed"); return; }
    handleRow(rows[i++]); S.timer = setTimeout(tick, 400);
  };
  tick();
}
async function loadFinished(caseId) {
  // show the last finished run instantly (no animation) so the page is never empty
  try { await getJSON(`/case/${encodeURIComponent(caseId)}/file/brief.json`); } catch { return false; }
  resetCase(caseId);
  const all = await getJSON(`/case/${encodeURIComponent(caseId)}/log?since=0`);
  all.rows.forEach((r) => { S.rows.push(r); appendLog(r); stepEvent(r); });
  $$(".step.active").forEach((s) => { s.classList.remove("active"); s.classList.add("done"); });
  for (const f of FILES) await onFile(f);
  $("#caseTitle").textContent = `${S.presets[S.preset]?.label.split(" · ")[0]} · last run`;
  return true;
}
function setUrl(params) {
  const u = new URL(location);
  for (const [k, v] of Object.entries(params)) (v == null ? u.searchParams.delete(k) : u.searchParams.set(k, v));
  history.replaceState(null, "", u);
}
async function refreshCases() {
  try {
    const cs = await getJSON("/cases"); const sel = $("#replaySel");
    sel.innerHTML = '<option value="">Replay…</option>' + cs.filter((c) => c.complete).map((c) => `<option value="${esc(c.case)}">${esc(c.case)}${c.kind === "recorded" ? " (recorded)" : ""}</option>`).join("");
  } catch {}
}
$("#replaySel").addEventListener("change", (e) => { const v = e.target.value; e.target.value = ""; if (v) { setUrl({ replay: v }); replay(v); } });
$("#runBtn").addEventListener("click", runCase);

async function choosePreset(key, load = true) {
  S.preset = key; setUrl({ preset: key });
  $$("#presetSeg button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.preset === key));
  $("#caseNote").textContent = S.presets[key].note;
  S.complex = null; $("#topoEmpty").hidden = false;
  $("#topoEmpty").innerHTML = "<div><b>Building the complex…</b>The Linker's public keys, grouped into cells.</div>";
  await loadGraph(); loadComplex();
  const pk = S.presets[key];
  if (load && S.mode === "idle") { if (!(await loadFinished(pk.case)) && !(pk.replay && await loadFinished(pk.replay))) resetCase(pk.case); }
}

$("#focusBtn").addEventListener("click", () => {
  const b = $("#focusBtn");
  if (b.textContent === "Show All") { showAll(CY.big); b.textContent = "Focus Ring"; } else { focusRing(CY.big); b.textContent = "Show All"; }
});
try { $("#tour").checked = localStorage.getItem("dome-tour") === "1"; } catch {}
$("#tour").addEventListener("change", (e) => { try { localStorage.setItem("dome-tour", e.target.checked ? "1" : "0"); } catch {} });

// ------------------------------------------------------------------------- intro
function intro() {
  let seen = false;
  try { seen = localStorage.getItem("dome-intro") === "1"; } catch {}
  const box = $("#intro"); if (seen) return;
  box.hidden = false; $("#introRun").focus();
  const close = () => { box.hidden = true; try { localStorage.setItem("dome-intro", "1"); } catch {} };
  $("#introRun").onclick = () => { close(); choosePreset("ring_a", false).then(runCase); };
  $("#introGuide").onclick = () => { close(); setView("guide"); };
  $("#introClose").onclick = close;
  box.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

// keep graphs and maps filling their panels when the window changes size
let resizeT;
window.addEventListener("resize", () => {
  clearTimeout(resizeT);
  resizeT = setTimeout(() => {
    MAPS.forEach((m) => m.map.invalidateSize());
    refitGraphs();
  }, 150);
});

// ------------------------------------------------------------------------- boot
(async function boot() {
  makeMap("mapMini"); makeMap("mapBig");
  S.presets = await getJSON("/presets");
  try {   // DOME_GLOBE=1: the Globe tab
    UI_FLAGS = await getJSON("/ui-flags");
    $("#globeTab").hidden = !UI_FLAGS.globe;
  } catch (e) { /* flag endpoint optional */ }
  $("#presetSeg").innerHTML = Object.entries(S.presets).map(([k, p]) => `<button type="button" data-preset="${esc(k)}" aria-pressed="false" title="${esc(p.note)}">${esc(p.label)}</button>`).join("");
  $("#presetSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b && S.mode === "idle") choosePreset(b.dataset.preset); });
  const q = new URLSearchParams(location.search);
  setView(q.get("view") || "overview", false);
  refreshCases();
  const rp = q.get("replay");
  const preset = S.presets[q.get("preset")] ? q.get("preset") : "ring_a";
  if (rp) { await choosePreset(preset, false); replay(rp); }
  else if (q.get("work")) { await choosePreset(preset); if (window.DomeDrawer) DomeDrawer.open(S.caseId, q.get("work"), q.get("wstep")); }
  else { await choosePreset(preset); intro(); }
})();
