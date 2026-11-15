/* "Show the work" drawer for the Homepage (same /steps data and look as the Globe's drawer).
   window.DomeDrawer.open(caseId, agent). Uses Chart.js, Cytoscape and Leaflet already on the page. */
(() => {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const PALETTE = ["#828fff", "#5ad1e6", "#4cc38a", "#f2b45a", "#c38cff", "#ff8a8a", "#9aa0ad", "#ffd36b"];
  const AGENTS = ["spotter", "linker", "money", "zoner", "lister", "locator", "geo", "window", "briefer", "complex"];
  const W = { caseId: null, agent: null, steps: [], i: 0, chart: null, map: null, cy: null, timer: null };
  let el = null;

  function mount() {
    if (el) return el;
    el = document.createElement("section");
    el.className = "drawer"; el.hidden = true; el.setAttribute("aria-label", "Show the work");
    el.innerHTML = `<header><div><div class="eyebrow">Show the work</div><h2 data-d="title"></h2></div>
      <div class="drawer-tabs" data-d="tabs"></div><button class="btn" data-d="close" type="button">Close</button></header>
      <div class="drawer-body"><h3 data-d="stitle"></h3><div class="step-view" data-d="view"></div>
      <p class="step-cap" data-d="cap"></p><p class="step-src">read from: <code data-d="src"></code></p></div>
      <footer><button class="btn" data-d="prev" type="button">← Prev</button><span data-d="count"></span>
      <button class="btn primary" data-d="next" type="button">Next →</button></footer>`;
    document.body.appendChild(el);
    q("close").onclick = close; q("prev").onclick = () => show(W.i - 1); q("next").onclick = () => show(W.i + 1);
    q("tabs").onclick = (e) => { const b = e.target.closest("[data-agent]"); if (b) open(W.caseId, b.dataset.agent); };
    document.addEventListener("keydown", (e) => {
      if (el.hidden) return;
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") { e.preventDefault(); e.stopPropagation(); show(W.i + 1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); show(W.i - 1); }
    }, true);
    return el;
  }
  const q = (k) => el.querySelector(`[data-d="${k}"]`);
  function clear() { W.chart?.destroy(); W.chart = null; W.map?.remove(); W.map = null; W.cy?.destroy(); W.cy = null; q("view").innerHTML = ""; }
  function close() { clearTimeout(W.timer); if (el) { clear(); el.hidden = true; } }

  async function open(caseId, agent) {
    mount();
    const r = await fetch(`/steps?case=${encodeURIComponent(caseId)}&agent=${encodeURIComponent(agent)}`);
    if (!r.ok) { el.hidden = false; q("title").textContent = "Show the work is off (DOME_STEPS)"; return; }
    const j = await r.json();
    Object.assign(W, { caseId, agent, steps: j.steps || [] });
    q("title").textContent = j.title;
    q("tabs").innerHTML = AGENTS.map((k) => `<button data-agent="${k}" class="${k === agent ? "on" : ""}">${k}</button>`).join("");
    el.hidden = false; show(0);
  }

  function show(i) {
    if (!W.steps.length) return;
    i = Math.max(0, Math.min(W.steps.length - 1, i)); W.i = i;
    const st = W.steps[i], d = st.data || {}, v = q("view");
    clear();
    q("stitle").textContent = st.title; q("cap").textContent = st.caption || ""; q("src").textContent = st.source || "—";
    q("count").textContent = `${i + 1} / ${W.steps.length}`; q("prev").disabled = i === 0; q("next").disabled = i === W.steps.length - 1;
    if (st.kind === "text") {
      v.innerHTML = `<div class="bigtext">${esc(d.text || "")}</div>${(d.bullets || []).length ? `<ul>${d.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}${d.note ? `<p class="note">${esc(d.note)}</p>` : ""}`;
    } else if (st.kind === "image") {
      v.innerHTML = (d.images || []).slice(0, 8).map((im) => `<figure style="margin:0 0 10px"><img src="${esc(im.src)}" alt="${esc(im.label || st.title)}" loading="lazy"><figcaption class="muted">${esc(im.label || "")}</figcaption></figure>`).join("")
        + ((d.list || []).length ? `<div class="glist">${d.list.map((x) => `<div>${esc(x)}</div>`).join("")}</div>` : "");
    } else if (st.kind === "table") {
      const hi = new Set(d.highlight || []);
      v.innerHTML = `<div style="max-height:460px;overflow:auto"><table><thead><tr>${(d.columns || []).map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${(d.rows || []).map((r, k) => `<tr class="${hi.has(k) ? "hi" : ""}">${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    } else if (st.kind === "chart" && window.Chart) {
      v.innerHTML = `<div style="height:440px"><canvas></canvas></div>`;
      const hi = new Set(d.highlight || []);
      const ds = (d.datasets || []).map((x, k) => {
        const base = PALETTE[k % PALETTE.length];
        const col = (d.datasets.length === 1 && hi.size) ? x.data.map((_, j) => hi.has(j) ? "#ef5f5f" : base) : (x.highlight ? "#ef5f5f" : base);
        return { label: x.label, data: x.data, backgroundColor: col, borderColor: col };
      });
      if (d.threshold && d.threshold.value != null) ds.push({ type: "line", label: d.threshold.label || "threshold", data: (d.labels || []).map(() => d.threshold.value), borderColor: "#f2b45a", borderDash: [6, 4], pointRadius: 0, borderWidth: 2, fill: false });
      W.chart = new Chart(v.querySelector("canvas"), { type: d.type || "bar", data: { labels: d.labels, datasets: ds },
        options: { indexAxis: d.horizontal ? "y" : "x", responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: "#c9cdd6" } } },
          scales: { x: { stacked: !!d.stacked, ticks: { color: "#9aa0ad", autoSkip: false, maxRotation: 70, font: { size: 10 } }, grid: { color: "rgba(255,255,255,.06)" } },
                    y: { stacked: !!d.stacked, ticks: { color: "#9aa0ad", font: { size: 10 } }, grid: { color: "rgba(255,255,255,.06)" } } } } });
    } else if (st.kind === "graph" && window.cytoscape) {
      v.innerHTML = `<div class="dgraph" style="height:440px;border:1px solid rgba(255,255,255,.09);border-radius:10px"></div>`;
      W.cy = cytoscape({ container: v.querySelector(".dgraph"),
        elements: [...(d.nodes || []).map((n) => ({ data: { ...n, color: PALETTE[(n.group || 0) % PALETTE.length] } })), ...(d.edges || []).map((e, k) => ({ data: { id: "de" + k, ...e } }))],
        style: [{ selector: "node", style: { "background-color": "data(color)", label: "data(label)", color: "#c9cdd6", "font-size": 9, width: 14, height: 14, "text-valign": "bottom" } },
                { selector: "edge", style: { width: 1.4, "line-color": "#4a5068", "curve-style": "haystack" } },
                { selector: "edge[style='dashed']", style: { "line-style": "dashed", "line-color": "#f2b45a" } },
                { selector: "edge[style='strong']", style: { width: 2.5, "line-color": "#828fff" } }],
        layout: { name: "cose", animate: false } });
    } else if (st.kind === "map" && window.L) {
      v.innerHTML = `<div class="dmap" style="height:420px;border-radius:10px"></div>`;
      W.map = L.map(v.querySelector(".dmap"), { zoomControl: true, attributionControl: true });
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Imagery © Esri" }).addTo(W.map);
      if (d.image && d.image.src && d.image.bounds) { const [w, s, e, n] = d.image.bounds; L.imageOverlay(d.image.src, [[s, w], [n, e]]).addTo(W.map); }
      const layer = L.geoJSON(d.features, {
        style: (f) => ({ color: f.properties.chosen ? "#ef5f5f" : "#aab3ff", weight: 2, fillOpacity: .2, dashArray: f.geometry.type === "LineString" ? "4 4" : null }),
        pointToLayer: (f, ll) => L.circleMarker(ll, { radius: f.properties.top ? 9 : 5, color: "#0b0c10", weight: 1.5, fillOpacity: 1,
          fillColor: f.properties.color || (f.properties.top ? "#ef5f5f" : "#dfe2ea") }).bindTooltip(esc(f.properties.label || "")),
      }).addTo(W.map);
      const b = layer.getBounds();
      if (b.isValid()) W.map.fitBounds(b, { padding: [40, 40], maxZoom: d.zoom || 18 }); else W.map.setView([29.758, -95.37], 12);
      setTimeout(() => W.map && W.map.invalidateSize(), 50);
    }
    clearTimeout(W.timer);
    if (document.body.classList.contains("present") && i < W.steps.length - 1) W.timer = setTimeout(() => show(i + 1), 6000);
  }
  window.DomeDrawer = { open, close };
})();
