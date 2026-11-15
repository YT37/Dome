/* Dome globe flight (DOME_GLOBE=1). Read only: it shows files the agents wrote and the asset packs.
   No addresses reach the page; phones and wallets arrive masked. Synthetic case. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const qs = new URLSearchParams(location.search);
  let CASE = qs.get("case") || "demo-real-a";
  let F = null, P = null, step = -1, timer = null, pano = null, cy = null;
  let roughMarker = null, fixedMarker = null;
  let FLAGS = {}, LIVE_RUN = null;
  const STEP_AGENT = { globe: "linker", city: "zoner", zone: "zoner", cands: "lister", lead: "locator", ortho: "geo",
    oblique: "geo", costar: "geo", pin: "geo", inside: "locator", brief: "briefer" };
  const cap = (a) => String(a || "").charAt(0).toUpperCase() + String(a || "").slice(1);
  const sampleTag = (on) => on ? `<span class="sample-tag" title="Shared sample from samples/night/, not from this case">sample · not this case</span>` : "";
  const HOUSTON = [-95.37, 29.76];

  const map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      projection: { type: "globe" },
      sources: {
        esri: {
          type: "raster", tileSize: 256, maxzoom: 19,
          tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
          attribution: "Imagery © Esri, Maxar, Earthstar Geographics · Vexcel imagery and CoStar data under hackathon licence",
        },
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": "#010102" } },
        { id: "esri", type: "raster", source: "esri" },
      ],
      sky: { "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 6, 0.4, 9, 0] },
    },
    center: [-40, 25], zoom: 1.3, attributionControl: { compact: true },
  });
  let styleReady = false, onReady = null;
  map.on("load", () => { styleReady = true; if (onReady) { const f = onReady; onReady = null; f(); } });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");

  // --------------------------------------------------------------- steps
  const STEPS = [
    { id: "globe", t: "Case", run: sGlobe },
    { id: "city", t: "City", run: sCity },
    { id: "zone", t: "The dome", run: sZone },
    { id: "cands", t: "Candidates", run: sCands },
    { id: "lead", t: "#1 building", run: sLead },
    { id: "ortho", t: "Vexcel ortho", run: sOrtho },
    { id: "oblique", t: "Oblique + floor", run: sOblique },
    { id: "costar", t: "CoStar record", run: sCostar },
    { id: "pin", t: "Pin fix", run: sPin },
    { id: "inside", t: "Inside", run: sInside },
    { id: "brief", t: "Lead brief", run: sBrief },
  ];
  $("#steps").innerHTML = STEPS.map((s, i) => `<li data-i="${i}"><span class="n">${i + 1}</span>${esc(s.t)}</li>`).join("");
  $("#steps").addEventListener("click", (e) => { const li = e.target.closest("li"); if (li) go(+li.dataset.i); });

  function go(i) {
    if (!F) return;
    i = Math.max(0, Math.min(STEPS.length - 1, i));
    if (!styleReady) return;
    if (!map.getSource("zones")) addLayers();
    step = i;
    document.querySelectorAll("#steps li").forEach((li, j) => {
      li.classList.toggle("cur", j === i); li.classList.toggle("done", j < i);
    });
    if (STEPS[i].id !== "inside") closeInside();
    STEPS[i].run();
  }
  const card = (html) => {
    const ag = FLAGS.steps && STEPS[step] ? STEP_AGENT[STEPS[step].id] : null;
    const work = ag ? `<button class="btn ghost" data-work="${ag}" title="How the code got here">Show the work · ${esc(FLAGS.steps[ag] || ag)}</button>` : "";
    $("#card").innerHTML = html + work + `<div class="navrow"><button class="btn" data-nav="-1" ${step <= 0 ? "disabled" : ""}>← Back</button>
      <button class="btn primary" data-nav="1" ${step >= STEPS.length - 1 ? "disabled" : ""}>Next →</button></div>`;
  };
  $("#card").addEventListener("click", (e) => {
    const b = e.target.closest("[data-nav]"); if (b) { stopReplay(); go(step + +b.dataset.nav); }
    const a = e.target.closest("[data-approve]"); if (a) approve(a);
    const w = e.target.closest("[data-work]"); if (w) openWork(w.dataset.work);
  });

  const lead = () => F.lead || {};
  const ins = () => F.inside || {};
  const fixed = () => ins().fixed_pin || (F.best && F.best.geo) || null;
  const pct = (x) => (x == null ? "—" : Number(x).toFixed(2));

  function setVis(id, on) { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none"); }

  function sGlobe() {
    setVis("cands", false); setVis("zone-fill", false); setVis("zone-line", false);
    map.flyTo({ center: [-60, 28], zoom: 1.4, pitch: 0, bearing: 0, duration: 2500 });
    const r = F.ring || {};
    card(`<div class="eyebrow">Synthetic case · ${esc(F.case)}</div>
      <h2>One ring, one building to verify</h2>
      <p>The Linker joined flagged synthetic accounts into a ring only where content keys and connectivity agree.</p>
      <div class="stats"><div class="stat"><b>${r.members ?? "—"}</b><span>accounts in ring</span></div>
        <div class="stat"><b>${pct(r.confidence)}</b><span>ring confidence R</span></div>
        <div class="stat"><b>${(r.key_kinds || []).length}</b><span>key kinds shared</span></div></div>
      <p class="fine">Keys: ${esc((r.key_kinds || []).join(", "))}. Open the link chart to see why each account is in.</p>`);
  }

  function sCity() {
    setVis("zone-fill", false); setVis("zone-line", false); setVis("cands", false);
    map.flyTo({ center: HOUSTON, zoom: 10, pitch: 0, bearing: 0, duration: 4000, essential: true });
    card(`<div class="eyebrow">Zoner</div><h2>Houston</h2>
      <p>Place clues in the ads (stated areas, landmarks, area codes) point to one metro. Clues give an area, never an address.</p>`);
  }

  function zoneBounds() {
    const b = new maplibregl.LngLatBounds();
    F.zones.forEach((z) => z.polygon.forEach(([la, lo]) => b.extend([lo, la])));
    return b;
  }
  function sZone() {
    setVis("zone-fill", true); setVis("zone-line", true); setVis("cands", false);
    if (F.zones.length) map.fitBounds(zoneBounds(), { padding: { top: 120, bottom: 90, left: 260, right: 440 }, duration: 2500, pitch: 0 });
    const z = F.zones[0] || {};
    card(`<div class="eyebrow">Zoner · the dome</div><h2>${esc(z.zone_id || "Zone")}</h2>
      <div class="stats"><div class="stat"><b>${z.area_km2 ?? "—"}</b><span>km²</span></div>
        <div class="stat"><b>${z.weight_share != null ? Math.round(z.weight_share * 100) + "%" : "—"}</b><span>of clue weight</span></div>
        <div class="stat"><b>${pct(z.confidence)}</b><span>zone confidence Z</span></div></div>
      <ul>${(z.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      ${F.zones.length > 1 ? `<p class="fine">${F.zones.length} zones; Lister and Locator ran once per zone.</p>` : ""}`);
  }

  function sCands() {
    setVis("zone-fill", true); setVis("zone-line", true); setVis("cands", true);
    if (F.zones.length) map.fitBounds(zoneBounds(), { padding: { top: 120, bottom: 90, left: 260, right: 440 }, duration: 1500 });
    const scanned = F.candidates.filter((c) => c.has_scan).length;
    card(`<div class="eyebrow">Lister</div><h2>${F.candidates.length} buildings fit</h2>
      <p>CoStar buildings inside the dome, rated against what the ring's photos show. Pins carry no addresses.</p>
      <div class="stats"><div class="stat"><b>${F.total_in_zone || F.candidates.length}</b><span>in the zone</span></div>
        <div class="stat"><b>${scanned}</b><span>with a 3D scan</span></div>
        <div class="stat"><b>1</b><span>matched the photos</span></div></div>
      <p class="fine">Red pin: the building the Locator matched. Grey: scanned candidates. Dim: no scan.</p>`);
  }

  function sLead() {
    setVis("cands", true); clearPins();
    const p = fixed(); if (!p) return card("<h2>No building matched</h2>");
    map.flyTo({ center: [p.lon, p.lat], zoom: 17.6, pitch: 55, bearing: -20, duration: 5000, essential: true });
    setVis("footprint-line", true);
    const L = lead(), b = F.best || {};
    card(`<div class="eyebrow">Locator · #1 building</div><h2>${esc(ins().display_name || L.display_name || b.property_id)}</h2>
      <p><span class="tier ${esc(L.tier)}">${esc(L.tier || "—")}</span> &nbsp;score ${esc(L.score ?? "—")}</p>
      <div class="stats"><div class="stat"><b>${pct(b.P)}</b><span>room match P</span></div>
        <div class="stat"><b>${pct(b.W)}</b><span>window W</span></div>
        <div class="stat"><b>${(F.best_zone || {}).photos_used ?? "—"}</b><span>photos used</span></div></div>
      <p class="fine">Lead for human verification. ${esc((L.caps || [])[0] || "")}</p>`);
  }

  function sOrtho() {
    setVis("ortho", true); setVis("footprint-line", true);
    const p = fixed(); if (p) map.easeTo({ center: [p.lon, p.lat], zoom: 18.6, pitch: 0, bearing: 0, duration: 2200 });
    const o = ins().ortho;
    card(`<div class="eyebrow">Vexcel · ortho</div><h2>Straight down, this season</h2>
      <p>Vexcel's orthomosaic laid over the base map; the outline is Vexcel's building footprint.</p>
      ${o ? "" : `<p class="fine">No ortho in this asset pack.</p>`}`);
  }

  function sOblique() {
    setVis("ortho", true);
    const obs = ins().obliques || [];
    const o = obs.find((x) => x.floor_band) || obs[0];
    const p = fixed(); if (p) map.easeTo({ center: [p.lon, p.lat], zoom: 18.2, pitch: 60, bearing: 70, duration: 2500 });
    card(`<div class="eyebrow">Vexcel · oblique</div><h2>The side of the building</h2>
      ${o ? `<div class="oblique-box"><img src="${esc(o.img)}" alt="Vexcel oblique view of the building">
        ${o.floor_band ? `<span class="band-chip">Floor ${esc(ins().floor ?? "")} band · ${o.floor_band[0]}–${o.floor_band[1]} m</span>` : ""}</div>
        <p class="fine">${esc(o.direction || "")}${o.capture_date ? " · captured " + new Date(o.capture_date).toISOString().slice(0, 10) : ""}.
        The floor band is the height range of the matched floor above ground.</p>` : "<p>No oblique in this asset pack.</p>"}`);
  }

  function sCostar() {
    const c = ins().costar || {};
    card(`<div class="eyebrow">CoStar · building record</div><h2>${esc(ins().display_name || "Building")}</h2>
      <dl class="kv"><dt>Type</dt><dd>${esc(c.type || "—")}</dd><dt>Floors</dt><dd>${esc(c.floors ?? "—")}</dd>
        <dt>Units</dt><dd>${esc(c.units ?? "—")}</dd><dt>Built</dt><dd>${esc(c.year_built ?? "—")}</dd>
        <dt>Matched floor</dt><dd>${esc(ins().floor ?? "—")}</dd><dt>Floor from</dt><dd>${esc(ins().floor_source || "—")}</dd></dl>
      <p class="fine">CoStar records describe buildings, not tenants. Residents are never looked up. The street address stays on the server.</p>`);
  }

  function clearPins() { roughMarker?.remove(); fixedMarker?.remove(); roughMarker = fixedMarker = null;
    if (map.getSource("pinline")) map.getSource("pinline").setData({ type: "FeatureCollection", features: [] }); }
  function pinEl(cls) { const d = document.createElement("div"); d.className = "pin " + cls; return d; }
  function sPin() {
    clearPins();
    const r = ins().rough_pin, f = ins().fixed_pin;
    if (!r || !f) return card("<h2>No pin fix in this pack</h2>");
    map.easeTo({ center: [(r.lon + f.lon) / 2, (r.lat + f.lat) / 2], zoom: 19, pitch: 0, bearing: 0, duration: 1800 });
    roughMarker = new maplibregl.Marker({ element: pinEl("rough") }).setLngLat([r.lon, r.lat]).addTo(map);
    const moving = new maplibregl.Marker({ element: pinEl("fixed") }).setLngLat([r.lon, r.lat]).addTo(map);
    fixedMarker = moving;
    const t0 = performance.now(), dur = 2600;
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / dur), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      const lon = r.lon + (f.lon - r.lon) * e, lat = r.lat + (f.lat - r.lat) * e;
      moving.setLngLat([lon, lat]);
      map.getSource("pinline")?.setData({ type: "Feature", geometry: { type: "LineString", coordinates: [[r.lon, r.lat], [lon, lat]] } });
      const el = document.getElementById("movedM"); if (el) el.textContent = (f.moved_m * e).toFixed(1);
      if (k < 1 && fixedMarker === moving) requestAnimationFrame(tick);
    };
    setTimeout(() => requestAnimationFrame(tick), 1200);
    card(`<div class="eyebrow">geo.fix_scan_location</div><h2>Pin moved <span id="movedM">0.0</span> m</h2>
      <p>The listing pin (grey) is where the record says the building is. Matching the scan's rooms and views to Vexcel imagery moves it onto the real footprint (red).</p>
      <dl class="kv"><dt>From</dt><dd>${esc(r.source || "listing coordinates")}</dd><dt>Error</dt><dd>±${esc(f.error_estimate_m)} m</dd>
        <dt>Scan heading</dt><dd>${esc(f.heading_deg)}° to true north</dd></dl>`);
  }

  // --------------------------------------------------------------- inside
  function sInside() {
    const s = ins().sweep;
    if (!s || !s.faces || s.faces.length !== 6) return card("<h2>No 360 view in this pack</h2><p>Showing the match image instead.</p>");
    $("#inside").hidden = false;
    // Matterport skybox order is up, side 1..4, down; Pannellum wants front, right, back, left, up, down.
    const f = s.faces;
    if (pano) { pano.destroy(); pano = null; }
    const mpUrl = ins().matterport_url;   // built server-side, always title=0&mls=2 (the splash shows the address)
    const useMp = !!mpUrl && insideMode !== "cube";
    $("#mp").hidden = !useMp;
    if (useMp) { if ($("#mp").getAttribute("src") !== mpUrl) $("#mp").setAttribute("src", mpUrl); }
    else $("#mp").removeAttribute("src");
    const yaw = ((s.heading_deg ?? 0) + 180) % 360 - 180;
    if (!useMp) pano = pannellum.viewer("pano", {
      type: "cubemap", cubeMap: [f[1], f[2], f[3], f[4], f[0], f[5]], autoLoad: true, showControls: true,
      yaw, pitch: -4, hfov: 100, compass: false, showFullscreenCtrl: false,
    });
    $("#panoTag").innerHTML = `<b>Inside the matched unit</b><br><span class="fine">Matterport sweep ${esc((s.sweep_id || "").slice(0, 8))}… turned to the ad photo's heading (${esc(s.heading_deg)}°). Drag to look around.</span>
      ${mpUrl ? `<div class="navrow"><button class="btn" data-imode="${useMp ? "cube" : "mp"}">${useMp ? "Cube-face viewer (offline)" : "Matterport 3D tour"}</button></div>` : ""}
      <div class="navrow"><button class="btn" data-inav="-1">← Back to the map</button><button class="btn primary" data-inav="1">Lead brief →</button></div>`;
    const ms = ins().matches || [];
    $("#matchThumbs").innerHTML = ms.map((m, i) => `<button data-m="${i}" class="${i ? "" : "on"}">${esc(m.photo)} · ${esc(m.inliers)}</button>`).join("");
    if (ms[0]) $("#matchImg").src = ms[0].match_img;
    $("#planImg").src = s.floorplan_img || "";
    $("#planCap").textContent = `Floor plan · floor ${ins().floor ?? "?"} · red dot is the matched sweep`;
    card(`<div class="eyebrow">Locator · room match</div><h2>Inside: the room matches</h2>
      <p>${ms.length} ad photos matched this scan. Each pair shows the ad photo and the scan view with the matched points drawn between them.</p>
      <p class="fine">Press <kbd>Esc</kbd> or Next to leave the room.</p>`);
  }
  $("#matchThumbs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-m]"); if (!b) return;
    const m = (ins().matches || [])[+b.dataset.m]; if (m) $("#matchImg").src = m.match_img;
    document.querySelectorAll("#matchThumbs button").forEach((x) => x.classList.toggle("on", x === b));
  });
  let insideMode = "mp";
  $("#panoTag").addEventListener("click", (e) => {
    const b = e.target.closest("[data-inav]"); if (b) { stopReplay(); go(step + +b.dataset.inav); }
    const m = e.target.closest("[data-imode]"); if (m) { insideMode = m.dataset.imode; sInside(); }
  });
  function closeInside() { $("#inside").hidden = true; $("#mp").removeAttribute("src"); $("#mp").hidden = true; if (pano) { pano.destroy(); pano = null; } }

  function sBrief() {
    const L = lead();
    const approved = (P?.actions || []).some((a) => a.action === "approve_for_report");
    card(`<div class="eyebrow">Briefer</div><h2>${esc(ins().display_name || L.display_name || "Lead")}</h2>
      <p><span class="tier ${esc(L.tier)}">${esc(L.tier || "—")}</span> &nbsp;score ${esc(L.score ?? "—")}</p>
      <ul>${(L.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      ${(L.caps || []).length ? `<p class="fine">${(L.caps || []).map(esc).join("<br>")}</p>` : ""}
      ${(L.verify_next || []).length ? `<p><b>Verify next</b></p><ul>${L.verify_next.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      <button class="btn primary" data-approve ${approved ? "disabled" : ""}>${approved ? "Approved for report ✓" : "Approve for report"}</button>
      <p class="fine">Approval is recorded in the case log only. Dome contacts, dispatches and publishes nothing.</p>
      <p class="fine">${esc(F.footer || "")}</p>`);
  }
  async function approve(btn) {
    btn.disabled = true;
    await fetch("/approve", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case: CASE, property_id: (F.best || {}).property_id, run: LIVE_RUN }) });
    if (LIVE_RUN) streamEvents(LIVE_RUN, true);
    btn.textContent = "Approved for report ✓";
    P = await (await fetch(`/panels?case=${encodeURIComponent(CASE)}`)).json();
  }

  // --------------------------------------------------------------- map layers
  function addLayers() {
    const zoneFC = { type: "FeatureCollection", features: F.zones.map((z) => ({ type: "Feature", properties: { id: z.zone_id },
      geometry: { type: "Polygon", coordinates: [z.polygon.map(([la, lo]) => [lo, la])] } })) };
    const candFC = { type: "FeatureCollection", features: F.candidates.filter((c) => c.lat != null).map((c) => ({ type: "Feature",
      properties: { top: c.top ? 1 : 0, scan: c.has_scan ? 1 : 0, id: c.property_id }, geometry: { type: "Point", coordinates: [c.lon, c.lat] } })) };
    for (const id of ["cands", "zone-fill", "zone-line", "ortho", "footprint-line", "pinline"]) if (map.getLayer(id)) map.removeLayer(id);
    for (const id of ["zones", "cands", "ortho", "footprint", "pinline"]) if (map.getSource(id)) map.removeSource(id);
    map.addSource("zones", { type: "geojson", data: zoneFC });
    map.addLayer({ id: "zone-fill", type: "fill", source: "zones", layout: { visibility: "none" }, paint: { "fill-color": "#828fff", "fill-opacity": 0.16 } });
    map.addLayer({ id: "zone-line", type: "line", source: "zones", layout: { visibility: "none" }, paint: { "line-color": "#aab3ff", "line-width": 2.5 } });
    const o = ins().ortho;
    if (o && o.bounds) {
      const [w, s, e, n] = o.bounds;
      map.addSource("ortho", { type: "image", url: o.img, coordinates: [[w, n], [e, n], [e, s], [w, s]] });
      map.addLayer({ id: "ortho", type: "raster", source: "ortho", layout: { visibility: "none" }, paint: { "raster-fade-duration": 400 } });
    }
    if (ins().footprint) {
      map.addSource("footprint", { type: "geojson", data: ins().footprint });
      map.addLayer({ id: "footprint-line", type: "line", source: "footprint", layout: { visibility: "none" }, paint: { "line-color": "#ef5f5f", "line-width": 3 } });
    }
    map.addSource("cands", { type: "geojson", data: candFC });
    map.addLayer({ id: "cands", type: "circle", source: "cands", layout: { visibility: "none" }, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, ["case", ["==", ["get", "top"], 1], 8, 4], 16, ["case", ["==", ["get", "top"], 1], 13, 7]],
      "circle-color": ["case", ["==", ["get", "top"], 1], "#ef5f5f", ["==", ["get", "scan"], 1], "#dfe2ea", "#7d8291"],
      "circle-opacity": ["case", ["==", ["get", "top"], 1], 1, ["==", ["get", "scan"], 1], 0.85, 0.45],
      "circle-stroke-color": "#0b0c10", "circle-stroke-width": 1 } });
    map.addSource("pinline", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "pinline", type: "line", source: "pinline", paint: { "line-color": "#fff", "line-width": 2, "line-dasharray": [2, 2] } });
  }

  // --------------------------------------------------------------- panels
  const ROLE_COLORS = { member: "#828fff", recruiter: "#ef5f5f", "shared key": "#4cc38a", "ad photo": "#f2b45a", "scan room": "#5ad1e6",
    lead: "#ffffff", "area clue": "#9aa0ad", "wallet cluster": "#f2b45a", "cash-out": "#ff8a3d" };
  const TYPE_SHAPE = { account: "ellipse", phone: "round-rectangle", script: "round-rectangle", photo: "rectangle", room: "hexagon",
    building: "star", wallet_cluster: "diamond", service: "triangle", place: "round-tag" };
  const colorFor = (n) => ROLE_COLORS[n.role] || (n.layer === "money" ? "#f2b45a" : n.type === "account" ? "#828fff" : "#9aa0ad");

  function openSheet(title, html) {
    $("#sheetTitle").textContent = title; $("#sheetBody").innerHTML = html; $("#sheet").hidden = false;
  }
  $("#sheetClose").addEventListener("click", () => closeSheet());
  function closeSheet() { $("#sheet").hidden = true; document.querySelectorAll(".dock button").forEach((b) => b.classList.remove("on")); if (cy) { cy.destroy(); cy = null; } }

  const HAS_FCOSE = () => { try { cytoscape({ headless: true }).layout({ name: "fcose" }); return true; } catch (e) { return false; } };
  async function showGraph() {
    const g = await (await fetch(`/graph?case=${encodeURIComponent(CASE)}`)).json();
    const layers = [...new Set(g.edges.map((e) => e.layer).concat(g.nodes.map((n) => n.layer)))].filter(Boolean);
    openSheet(`Link chart · ${g.source}`, `<div class="graph-wrap"><div id="cy"></div><div class="graph-side">
      <b>Layers</b>${layers.map((l) => `<label><input type="checkbox" data-layer="${esc(l)}" checked> ${esc(l)}</label>`).join("")}
      <div class="legend">${Object.entries(ROLE_COLORS).filter(([r]) => g.nodes.some((n) => n.role === r)).map(([r, c]) => `<i style="background:${c}"></i><span>${esc(r)}</span>`).join("")}</div>
      <div class="why" id="why">Click a node or a link to see why it is there.</div>
      <p class="fine">${g.nodes.length} nodes · ${g.edges.length} links. Labels are masked; no addresses.</p></div></div>`);
    cy = cytoscape({
      container: $("#cy"),
      elements: [
        ...g.nodes.map((n) => ({ data: { ...n, color: colorFor(n), shape: TYPE_SHAPE[n.type] || "ellipse" } })),
        ...g.edges.map((e, i) => ({ data: { id: "e" + i, ...e } })),
      ],
      style: [
        { selector: "node", style: { "background-color": "data(color)", shape: "data(shape)", label: "data(label)", color: "#c9cdd6",
          "font-size": 9, "font-family": "Geist Mono", "text-valign": "bottom", "text-margin-y": 3, width: 16, height: 16,
          "border-width": 1, "border-color": "#0b0c10" } },
        { selector: "node[type='building']", style: { width: 30, height: 30, "font-size": 11, color: "#fff" } },
        { selector: "node[type='account']", style: { width: 20, height: 20 } },
        { selector: "edge", style: { width: 1.2, "line-color": "#3a3f52", "curve-style": "haystack", opacity: 0.8 } },
        { selector: "edge[layer='network']", style: { "line-color": "#828fff", width: 2 } },
        { selector: "edge[layer='money']", style: { "line-color": "#f2b45a", width: 2 } },
        { selector: "edge[layer='place']", style: { "line-color": "#5ad1e6" } },
        { selector: ":selected", style: { "border-color": "#fff", "border-width": 3, "line-color": "#fff" } },
      ],
      layout: { name: HAS_FCOSE() ? "fcose" : "cose", animate: false, nodeRepulsion: 6000, idealEdgeLength: 60 },
      wheelSensitivity: 0.3,
    });
    cy.on("tap", "node,edge", (ev) => {
      const d = ev.target.data();
      $("#why").innerHTML = ev.target.isNode()
        ? `<b>${esc(d.label)}</b><br><span class="fine">${esc(d.type)} · ${esc(d.role || "")} · ${esc(d.layer)}${d.score != null ? " · score " + esc(d.score) : ""}</span><p>${esc(d.reason || "—")}</p>`
        : `<b>${esc(d.type)}</b> <span class="fine">(${esc(d.layer)})</span><p>${esc(d.reason || "—")}</p>`;
    });
    $("#sheetBody").addEventListener("change", (e) => {
      const l = e.target.dataset.layer; if (!l || !cy) return;
      cy.elements(`[layer='${l}']`).style("display", e.target.checked ? "element" : "none");
    });
  }

  function showSpotter() {
    const sp = P.spotter || {}, q = sp.queue || [];
    openSheet("Spotter queue", `<div class="list">${sampleTag(sp.sample)}
      ${sp.flag_rule ? `<p class="fine">Rule: ${esc(sp.flag_rule)}</p>` : ""}
      ${q.map((r) => `<div class="row"><div><b>#${esc(r.rank)} ${esc(r.account)}</b> · score ${esc(r.score)}${r.model != null ? ` · model ${esc(r.model)}` : ""}
      <div class="sig">${(r.signals || []).map((s) => `${esc(s.kind)}: ${esc(s.reason)}`).join("<br>")}</div></div>
      <div><button class="btn" data-choose="${esc(r.account)}">Start case from this account</button></div></div>`).join("")}
      <p class="fine">${P.live ? `Starts a live run (assistant: ${esc(P.assistant || "default")}).` : "Starts the replay."} Nothing is contacted or dispatched.
      ${sp.model_name ? `Model column: ${esc(sp.model_name)}.` : ""}</p>
      ${FLAGS.steps ? `<button class="btn ghost" data-work="spotter">Show the work · ${esc(FLAGS.steps.spotter)}</button>` : ""}</div>`);
  }
  $("#sheetBody").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-choose]");
    if (b) {
      b.disabled = true;
      const r = await (await fetch("/spotter/choose", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case: CASE, account: b.dataset.choose }) })).json();
      b.textContent = r.live ? "Live run started ✓" : "Recorded ✓ · replaying";
      closeSheet();
      if (r.live) { LIVE_RUN = r.run; LIVE_CASE = r.case_id; $("#ticker").innerHTML = ""; streamEvents(r.run, true); }
      else replay();
    }
    const w = e.target.closest("[data-work]"); if (w) { closeSheet(); openWork(w.dataset.work); }
    const c = e.target.closest("[data-cell]");
    if (c) $("#cellWhy").innerHTML = `<b>${esc(c.dataset.label)}</b><p>${esc(c.dataset.reason || "—")}</p>`;
  });

  function showTopology() {
    const t = P.topology;
    const names = { 0: "Rank 0 · accounts and identifiers", 1: "Rank 1 · shared keys (pairs)", 2: "Rank 2 · groups", 3: "Rank 3 · the ring" };
    openSheet("Topology · combinatorial complex", `<div class="list">${sampleTag(t.sample)}${t.model ? `<p class="fine">Model: ${esc(t.model)}</p>` : ""}
      ${FLAGS.steps ? `<button class="btn ghost" data-work="complex">Show the work · ${esc(FLAGS.steps.complex)}</button>` : ""}${Object.keys(t.ranks).sort().map((r) => `<b>${esc(names[r] || "Rank " + r)}</b> <span class="fine">${t.ranks[r].length} cells</span>
      <div class="cells">${t.ranks[r].slice(0, 120).map((c) => `<button data-cell data-label="${esc(c.label)}" data-reason="${esc(c.reason || "")}">${esc(c.label)}${c.score != null ? " · " + Number(c.score).toFixed(2) : ""}</button>`).join("")}</div>`).join("")}
      <div class="why" id="cellWhy">Click a cell for its reason.</div></div>`);
  }

  function showMoney() {
    const m = P.money || {};
    const cid = (w) => w.cluster_id || w.id;
    const lab = Object.fromEntries((m.wallet_clusters || []).map((w) => [String(cid(w)), w.masked_label || cid(w)]));
    const nm = (x) => lab[String(x)] || x || "";
    const ptp = m.payment_then_post || [];
    const mins = (a, b) => Math.round((new Date(b) - new Date(a)) / 60000);
    openSheet("Money · payment then post", `<div class="list">${sampleTag(m.sample)}
      ${m.attribution_confidence != null ? `<p>Attribution confidence <b>${esc(m.attribution_confidence)}</b></p>` : ""}
      <b>Payment, then post</b><div class="timeline">${ptp.map((e) => `<div class="ev money"><small>${esc(e.paid_at)}</small><br>${esc(nm(e.wallet))} pays the ad platform</div>
        <div class="ev post"><small>${esc(e.post_at)} · +${mins(e.paid_at, e.post_at)} min</small><br>${esc(e.account)} posts</div>`).join("") || "<p class='fine'>None recorded.</p>"}</div>
      <b>Clusters and roles</b>${(m.wallet_clusters || []).map((w) => `<div class="row"><div><b>${esc(nm(cid(w)))}</b> · ${esc(w.role || "")}${w.addresses != null ? ` · ${esc(w.addresses)} addresses` : ""}${w.confidence != null ? ` · conf ${esc(w.confidence)}` : ""}
        <div class="sig">${esc((w.reasons || [w.reason]).filter(Boolean).join("; "))}</div></div></div>`).join("") || "<p class='fine'>None.</p>"}
      <b>Consolidation</b>${(m.flows || []).map((f) => `<div class="row"><div>${esc(nm(f.from))} → ${esc(nm(f.to))}<div class="sig">${f.btc != null ? `${esc(f.btc)} BTC in ${esc(f.txs)} txs` : esc(f.reason || f.kind || "")}</div></div></div>`).join("") || "<p class='fine'>None.</p>"}
      <b>Cash-out</b>${(m.cash_out || []).map((c) => `<div class="row"><div><b>${esc(nm(c.cluster_id || c.cluster))} → ${esc(c.masked_label || c.service || "")}</b><div class="sig">${c.times != null ? `${esc(c.times)} times` : esc(c.reason || "")}</div></div></div>`).join("") || "<p class='fine'>None.</p>"}
      ${FLAGS.steps ? `<button class="btn ghost" data-work="money">Show the work · ${esc(FLAGS.steps.money)}</button>` : ""}
      <p class="fine">Public ledger data, synthetic case. Wallet strings are masked.</p></div>`);
  }

  document.querySelector(".dock").addEventListener("click", (e) => {
    const b = e.target.closest("[data-panel]"); if (!b) return;
    const was = b.classList.contains("on"); closeSheet(); if (was) return;
    b.classList.add("on");
    if (b.dataset.panel === "steps") { b.classList.remove("on"); return openWork(STEPS[step] ? STEP_AGENT[STEPS[step].id] : "locator"); }
    ({ graph: showGraph, spotter: showSpotter, topology: showTopology, money: showMoney })[b.dataset.panel]();
  });

  // --------------------------------------------------------------- replay, presenter, events
  const DWELL = [5, 5, 5, 5, 7, 5, 6, 6, 6, 9, 8];
  function stopReplay() { clearTimeout(timer); timer = null; $("#replayBtn").classList.remove("on"); $("#replayBtn").textContent = "Replay"; }
  function replay() {
    if (timer) return stopReplay();
    $("#replayBtn").classList.add("on"); $("#replayBtn").textContent = "Stop";
    $("#ticker").innerHTML = ""; streamEvents(null, false);
    const next = (i) => { go(i); if (i < STEPS.length - 1) timer = setTimeout(() => next(i + 1), DWELL[i] * 1000); else stopReplay(); };
    next(0);
  }
  let es = null, LIVE_CASE = null;
  function streamEvents(run, live) {
    es?.close();
    es = new EventSource(live ? `/events?run=${encodeURIComponent(run)}` : `/events?case=${encodeURIComponent(CASE)}&pace=2.5&speed=1`);
    es.onmessage = (m) => {
      const e = JSON.parse(m.data);
      const d = document.createElement("div");
      d.className = (e.phase === "decision" || e.phase === "interrupt" ? "decision" : "") + (e.sample ? " sample" : "");
      d.dataset.agent = String(e.agent || "").toLowerCase();
      d.title = FLAGS.steps ? "Show the work" : "";
      d.textContent = `${cap(e.agent)} · ${e.phase}: ${e.message}${e.sample ? " (sample)" : ""}`;
      $("#ticker").appendChild(d); while ($("#ticker").children.length > 5) $("#ticker").firstChild.remove();
      if (e.phase === "interrupt" && live) { LIVE_RUN = run; go(STEPS.length - 1); }
    };
    es.addEventListener("end", () => { es.close(); if (live && LIVE_CASE) refreshAfterLive(); });
    es.onerror = () => es.close();
  }
  async function refreshAfterLive() {
    const cases = await (await fetch("/cases")).json();
    if (cases.some((c) => c.case === LIVE_CASE)) { const sel = $("#caseSel");
      if (![...sel.options].some((o) => o.value === LIVE_CASE)) sel.add(new Option(`${LIVE_CASE} (live)`, LIVE_CASE));
      sel.value = LIVE_CASE; const keep = LIVE_RUN; await load(LIVE_CASE); LIVE_RUN = keep; }
  }
  $("#ticker").addEventListener("click", (e) => {
    const d = e.target.closest("[data-agent]"); if (!d || !FLAGS.steps) return;
    const a = d.dataset.agent; openWork(FLAGS.steps[a] ? a : ({ supervisor: "briefer" })[a] || "locator");
  });

  // --------------------------------------------------------------- show the work (DOME_STEPS=1)
  let W = { agent: null, steps: [], i: 0, chart: null, map: null, cy: null, timer: null };
  function clearStepView() {
    W.chart?.destroy(); W.chart = null; W.map?.remove(); W.map = null; W.cy?.destroy(); W.cy = null;
    $("#stepView").innerHTML = "";
  }
  function closeWork() { clearTimeout(W.timer); clearStepView(); $("#drawer").hidden = true; }
  $("#drawerClose").addEventListener("click", closeWork);
  $("#stepPrev").addEventListener("click", () => showStep(W.i - 1));
  $("#stepNext").addEventListener("click", () => showStep(W.i + 1));
  $("#drawerTabs").addEventListener("click", (e) => { const b = e.target.closest("[data-agent]"); if (b) openWork(b.dataset.agent); });
  async function openWork(agent) {
    if (!FLAGS.steps) return;
    closeSheet();
    const r = await fetch(`/steps?case=${encodeURIComponent(CASE)}&agent=${encodeURIComponent(agent)}`);
    if (!r.ok) return;
    const j = await r.json();
    W.agent = agent; W.steps = j.steps || [];
    $("#drawerTitle").textContent = j.title;
    $("#drawerTabs").innerHTML = Object.entries(FLAGS.steps).map(([k, t]) => `<button data-agent="${esc(k)}" class="${k === agent ? "on" : ""}" title="${esc(t)}">${esc(k)}</button>`).join("");
    $("#drawer").hidden = false;
    showStep(0);
  }
  const PALETTE = ["#828fff", "#5ad1e6", "#4cc38a", "#f2b45a", "#c38cff", "#ff8a8a", "#9aa0ad", "#ffd36b"];
  function showStep(i) {
    if (!W.steps.length) { clearStepView(); $("#stepTitle").textContent = "Nothing recorded"; return; }
    i = Math.max(0, Math.min(W.steps.length - 1, i)); W.i = i;
    const st = W.steps[i];
    clearStepView();
    $("#stepTitle").textContent = st.title;
    $("#stepCap").textContent = st.caption || "";
    $("#stepSrc").textContent = st.source || "—";
    $("#stepCount").textContent = `${i + 1} / ${W.steps.length}`;
    $("#stepPrev").disabled = i === 0; $("#stepNext").disabled = i === W.steps.length - 1;
    const v = $("#stepView"), d = st.data || {};
    if (st.kind === "text") {
      v.innerHTML = `<div class="bigtext">${esc(d.text || "")}</div>${(d.bullets || []).length ? `<ul>${d.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}${d.note ? `<p class="note">${esc(d.note)}</p>` : ""}`;
    } else if (st.kind === "image") {
      v.innerHTML = (d.images || []).slice(0, 8).map((im) => `<figure style="margin:0 0 10px"><img src="${esc(im.src)}" alt="${esc(im.label || st.title)}" loading="lazy"><figcaption class="fine">${esc(im.label || "")}</figcaption></figure>`).join("")
        + ((d.list || []).length ? `<div class="glist">${d.list.map((x) => `<div>${esc(x)}</div>`).join("")}</div>` : "");
    } else if (st.kind === "table") {
      const hi = new Set(d.highlight || []);
      v.innerHTML = `<div style="max-height:460px;overflow:auto"><table><thead><tr>${(d.columns || []).map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${(d.rows || []).map((r, k) => `<tr class="${hi.has(k) ? "hi" : ""}">${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    } else if (st.kind === "chart") {
      v.innerHTML = `<canvas id="stepChart"></canvas>`;
      const hi = new Set(d.highlight || []);
      const ds = (d.datasets || []).map((x, k) => {
        const base = x.color || PALETTE[k % PALETTE.length];
        const col = (d.datasets.length === 1 && hi.size) ? x.data.map((_, j) => hi.has(j) ? "#ef5f5f" : base) : (x.highlight ? "#ef5f5f" : base);
        return { label: x.label, data: x.data, backgroundColor: col, borderColor: col, stack: d.stacked ? "s" : undefined };
      });
      if (d.threshold && d.threshold.value != null) ds.push({ type: "line", label: d.threshold.label || "threshold",
        data: (d.labels || []).map(() => d.threshold.value), borderColor: "#f2b45a", borderDash: [6, 4], pointRadius: 0, borderWidth: 2, fill: false });
      W.chart = new Chart($("#stepChart"), {
        type: d.type || "bar", data: { labels: d.labels, datasets: ds },
        options: { indexAxis: d.horizontal ? "y" : "x", animation: { duration: 500 }, responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { color: "#c9cdd6" } } },
          scales: { x: { stacked: !!d.stacked, ticks: { color: "#9aa0ad", autoSkip: false, maxRotation: 70, font: { size: 10 } }, grid: { color: "rgba(255,255,255,.06)" }, title: { display: !!d.x, text: d.x || "", color: "#9aa0ad" } },
                    y: { stacked: !!d.stacked, ticks: { color: "#9aa0ad", font: { size: 10 } }, grid: { color: "rgba(255,255,255,.06)" }, title: { display: !!d.y, text: d.y || "", color: "#9aa0ad" } } } },
      });
      $("#stepChart").parentElement.style.height = "440px";
    } else if (st.kind === "graph") {
      v.innerHTML = `<div id="scy"></div>`;
      W.cy = cytoscape({ container: $("#scy"),
        elements: [...(d.nodes || []).map((n) => ({ data: { ...n, color: n.color || PALETTE[(n.group || 0) % PALETTE.length] } })),
                   ...(d.edges || []).map((e, k) => ({ data: { id: "se" + k, ...e } }))],
        style: [{ selector: "node", style: { "background-color": "data(color)", label: "data(label)", color: "#c9cdd6", "font-size": 9, width: 14, height: 14, "text-valign": "bottom" } },
                { selector: "edge", style: { width: 1.4, "line-color": "#4a5068", "curve-style": "haystack" } },
                { selector: "edge[style='dashed']", style: { "line-style": "dashed", "line-color": "#f2b45a" } },
                { selector: "edge[style='strong']", style: { width: 2.5, "line-color": "#828fff" } }],
        layout: { name: HAS_FCOSE() ? "fcose" : "cose", animate: false } });
    } else if (st.kind === "map") {
      v.innerHTML = `<div class="smap" id="smap"></div>`;
      const fc = d.features || { type: "FeatureCollection", features: [] };
      const b = new maplibregl.LngLatBounds();
      const walk = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(walk));
      fc.features.forEach((f) => f.geometry && walk(f.geometry.coordinates));
      W.map = new maplibregl.Map({ container: "smap", attributionControl: { compact: true },
        style: { version: 8, sources: { esri: { type: "raster", tileSize: 256, maxzoom: 19, attribution: "Imagery © Esri",
          tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"] } },
          layers: [{ id: "esri", type: "raster", source: "esri" }] },
        bounds: b.isEmpty() ? undefined : b, fitBoundsOptions: { padding: 50, maxZoom: d.zoom || 18 } });
      W.map.on("load", () => {
        if (d.image && d.image.src && d.image.bounds) { const [w, s2, e2, n] = d.image.bounds;
          W.map.addSource("img", { type: "image", url: d.image.src, coordinates: [[w, n], [e2, n], [e2, s2], [w, s2]] });
          W.map.addLayer({ id: "img", type: "raster", source: "img" }); }
        W.map.addSource("f", { type: "geojson", data: fc });
        W.map.addLayer({ id: "poly", type: "fill", source: "f", filter: ["==", "$type", "Polygon"], paint: { "fill-color": ["case", ["boolean", ["get", "chosen"], false], "#ef5f5f", "#828fff"], "fill-opacity": 0.22 } });
        W.map.addLayer({ id: "poly-l", type: "line", source: "f", filter: ["==", "$type", "Polygon"], paint: { "line-color": ["case", ["boolean", ["get", "chosen"], false], "#ef5f5f", "#aab3ff"], "line-width": 2 } });
        W.map.addLayer({ id: "line", type: "line", source: "f", filter: ["==", "$type", "LineString"], paint: { "line-color": "#fff", "line-width": 2, "line-dasharray": [2, 2] } });
        W.map.addLayer({ id: "pts", type: "circle", source: "f", filter: ["==", "$type", "Point"], paint: {
          "circle-radius": ["case", ["boolean", ["get", "top"], false], 9, 5],
          "circle-color": ["coalesce", ["get", "color"], ["case", ["boolean", ["get", "top"], false], "#ef5f5f", "#dfe2ea"]],
          "circle-stroke-color": "#0b0c10", "circle-stroke-width": 1.5 } });
      });
    }
    clearTimeout(W.timer);
    if (document.body.classList.contains("present") && i < W.steps.length - 1) W.timer = setTimeout(() => showStep(i + 1), 6000);
  }
  $("#replayBtn").addEventListener("click", replay);
  $("#presentBtn").addEventListener("click", () => { document.body.classList.toggle("present"); $("#presentBtn").classList.toggle("on"); });
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select, textarea")) return;
    if (!$("#drawer").hidden && (e.key === "ArrowRight" || e.key === "ArrowLeft")) { e.preventDefault(); showStep(W.i + (e.key === "ArrowRight" ? 1 : -1)); }
    else if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") { e.preventDefault(); stopReplay(); go(step + 1); }
    else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); stopReplay(); go(step - 1); }
    else if (e.key === "Escape") { if (!$("#drawer").hidden) closeWork(); else if (!$("#sheet").hidden) closeSheet(); else if (!$("#inside").hidden) go(step + 1); }
    else if (e.key.toLowerCase() === "p") $("#presentBtn").click();
    else if (e.key.toLowerCase() === "r") replay();
  });

  // --------------------------------------------------------------- load
  async function load(caseId) {
    CASE = caseId; stopReplay(); closeSheet(); closeInside(); clearPins();
    $("#caseLabel").textContent = caseId;
    const r = await fetch(`/flight?case=${encodeURIComponent(caseId)}`);
    if (!r.ok) { card(`<h2>Case not found</h2><p>${esc(caseId)}</p>`); return; }
    F = await r.json();
    P = await (await fetch(`/panels?case=${encodeURIComponent(caseId)}`)).json();
    for (const k of ["spotter", "topology", "money"]) { const btn = document.querySelector(`[data-panel=${k}]`);
      btn.hidden = !P[k]; btn.dataset.sample = P[k] && P[k].sample ? "1" : "0";
      btn.title = P[k] && P[k].sample ? "Shared sample, not from this case (hidden in presenter mode)" : ""; }
    document.querySelector("[data-panel=steps]").hidden = !FLAGS.steps;
    const ready = () => { addLayers(); go(0); };
    if (styleReady) ready(); else onReady = ready;
  }
  (async () => {
    FLAGS = await (await fetch("/ui-flags")).json();
    const cases = await (await fetch("/cases")).json();
    const sel = $("#caseSel");
    sel.innerHTML = cases.map((c) => `<option value="${esc(c.case)}">${esc(c.case)} (${esc(c.kind)})</option>`).join("");
    if (!cases.some((c) => c.case === CASE) && cases.length) CASE = (cases.find((c) => c.case === "demo-real-a") || cases[0]).case;
    sel.value = CASE;
    sel.addEventListener("change", () => { history.replaceState(null, "", `?case=${sel.value}`); load(sel.value); });
    load(CASE);
  })();
})();
