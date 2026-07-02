"use strict";

// Ahupuaʻa Watershed Mapper — vanilla canvas front end.
// Every layer lives in one shared pixel space (the exported "web" pixels), so the
// canvas bitmap is sized to meta.web_size and drawing needs no projection math.
// Static layers (streams, boundaries, match fill) are stroked once per island into
// offscreen canvases; each frame just composites, keeping interaction smooth.

const COL = {
  stream: "#6fd0ff", streamCore: "#bfecff",
  haloDark: "rgba(0,0,0,0.9)", lineLight: "#ffffff",
  accent: "#ffc36e", basinOv: "#57e0ff", mismatch: "#c084fc",
};
// diverging match ramp: red (drainage splits) -> yellow -> green (single watershed)
const MATCH_STOPS = [[0, [215, 48, 31]], [0.5, [254, 196, 79]],
                     [0.85, [120, 198, 121]], [1, [35, 132, 67]]];
const TINY_COLOR = [107, 114, 128];

const state = {
  mode: "terrain",                 // "terrain" | "match"
  layers: { base: true, basins: true, streams: true, ahupuaa: true },
  opacity: 0.55,
  hover: null, pinned: null, mismatches: null,
  pulse: null,                     // {x,y,t0} search/pin animation
};

let manifest, meta, ahupuaa, basinById;
let canvas, ctx, baseImg, basinsImg, streamCanvas, ahupuaaCanvas, matchCanvas;

// --- boot ------------------------------------------------------------------
async function boot() {
  canvas = document.getElementById("map");
  ctx = canvas.getContext("2d");
  manifest = await fetch("../data/ahupuaa-watersheds/manifest.json").then(r => r.json());
  buildIslandSelect();
  buildViewMode();
  wireControls();
  wirePointer();
  wireSearchAndMismatch();
  const first = manifest.islands.find(i => i.slug === manifest.default)
             || manifest.islands.find(i => i.available);
  await loadIsland(first.slug);
}

function buildIslandSelect() {
  const sel = document.getElementById("island");
  for (const i of manifest.islands) {
    const o = document.createElement("option");
    o.value = i.slug;
    o.textContent = i.available ? i.name : i.name + " — not yet processed";
    o.disabled = !i.available;
    sel.appendChild(o);
  }
  sel.value = manifest.default;
  sel.addEventListener("change", () => loadIsland(sel.value));
}

// --- load one island -------------------------------------------------------
async function loadIsland(slug) {
  document.getElementById("loading").style.display = "";
  document.getElementById("loading").textContent = "Loading…";
  const dir = "../data/ahupuaa-watersheds/" + slug + "/";
  meta = await fetch(dir + "meta.json").then(r => r.json());
  const [ahu, basins, streams] = await Promise.all([
    fetch(dir + meta.layers.ahupuaa).then(r => r.json()),
    fetch(dir + meta.layers.basins_vec).then(r => r.json()),
    fetch(dir + meta.layers.streams).then(r => r.json()),
    loadImages(dir),
  ]);
  ahupuaa = ahu.features;
  precomputeBBoxes(ahupuaa);
  basinById = new Map(basins.features.map(f => [f.properties.id, f.geometry]));

  [canvas.width, canvas.height] = meta.web_size;
  streamCanvas = renderStreams(streams.features);
  ahupuaaCanvas = renderAhupuaa(ahupuaa);
  matchCanvas = renderMatch(ahupuaa);

  state.hover = state.pinned = state.mismatches = state.pulse = null;
  buildSearchList();
  updateLegend();
  document.getElementById("mismatch-btn").classList.remove("on");
  showReadout(null, false);
  document.getElementById("loading").style.display = "none";
  document.title = `Ahupuaʻa Watershed Mapper — ${meta.island}`;
  compose();
}

function loadImages(dir) {
  const load = (src) => new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => rej(new Error("failed to load " + src));
    im.src = src;
  });
  return Promise.all([load(dir + meta.layers.base), load(dir + meta.layers.basins)])
    .then(([b, bs]) => { baseImg = b; basinsImg = bs; });
}

// --- offscreen layers (rebuilt per island) ---------------------------------
function offscreen() {
  const c = document.createElement("canvas");
  [c.width, c.height] = meta.web_size;
  return c;
}

function renderStreams(features) {
  const c = offscreen(), g = c.getContext("2d");
  const lo = Math.log10(meta.stream_threshold_cells);
  let hi = lo;
  for (const f of features) hi = Math.max(hi, Math.log10(f.properties.acc || 1));
  g.lineCap = "round"; g.lineJoin = "round";
  for (const f of features) {
    const t = (Math.log10(f.properties.acc || 1) - lo) / (hi - lo || 1);
    const w = 0.6 + 3.4 * Math.max(0, Math.min(1, t));
    const c2 = f.geometry.coordinates;
    g.beginPath();
    g.moveTo(c2[0][0], c2[0][1]);
    for (let i = 1; i < c2.length; i++) g.lineTo(c2[i][0], c2[i][1]);
    g.strokeStyle = COL.stream; g.lineWidth = w; g.stroke();
    if (w > 2.4) { g.strokeStyle = COL.streamCore; g.lineWidth = w * 0.4; g.stroke(); }
  }
  return c;
}

// high-contrast boundaries: a dark halo under a light hairline, legible over any layer
function renderAhupuaa(features) {
  const c = offscreen(), g = c.getContext("2d");
  g.lineJoin = "round";
  for (const pass of [{ s: COL.haloDark, w: 3 }, { s: COL.lineLight, w: 1.1 }]) {
    g.strokeStyle = pass.s; g.lineWidth = pass.w;
    for (const f of features) { traceGeom(g, f.geometry); g.stroke(); }
  }
  return c;
}

// match mode: fill each ahupuaʻa by how well it matches a single computed watershed
function renderMatch(features) {
  const c = offscreen(), g = c.getContext("2d");
  for (const f of features) {
    g.fillStyle = matchColor(f.properties);
    traceGeom(g, f.geometry);
    g.fill("evenodd");
  }
  return c;
}

function matchColor(p) {
  if (p.dom_basin == null) return `rgb(${TINY_COLOR.join(",")})`;
  const f = p.dom_frac;
  let a = MATCH_STOPS[0], b = MATCH_STOPS[MATCH_STOPS.length - 1];
  for (let i = 0; i < MATCH_STOPS.length - 1; i++)
    if (f >= MATCH_STOPS[i][0] && f <= MATCH_STOPS[i + 1][0]) {
      a = MATCH_STOPS[i]; b = MATCH_STOPS[i + 1]; break;
    }
  const t = (f - a[0]) / (b[0] - a[0] || 1);
  const rgb = a[1].map((v, k) => Math.round(v + (b[1][k] - v) * t));
  return `rgb(${rgb.join(",")})`;
}

// --- compositing (per frame) -----------------------------------------------
function compose() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (state.layers.base) ctx.drawImage(baseImg, 0, 0);
  if (state.layers.basins) {
    ctx.globalAlpha = state.opacity;
    ctx.drawImage(state.mode === "match" ? matchCanvas : basinsImg, 0, 0);
    ctx.globalAlpha = 1;
  }
  if (state.layers.streams) ctx.drawImage(streamCanvas, 0, 0);

  // the pinned ahupuaʻa's computed watershed(s), under the boundary line
  const sel = state.pinned || state.hover;
  if (state.pinned) drawPinnedBasins(state.pinned);

  if (state.layers.ahupuaa) ctx.drawImage(ahupuaaCanvas, 0, 0);

  if (sel) {                                   // emphasise the boundary itself
    ctx.save();
    traceGeom(ctx, sel.geometry);
    ctx.fillStyle = "rgba(255,195,110,0.18)"; ctx.fill("evenodd");
    ctx.lineJoin = "round";
    ctx.strokeStyle = COL.haloDark; ctx.lineWidth = 4.5; ctx.stroke();
    ctx.strokeStyle = COL.accent; ctx.lineWidth = 2.2; ctx.stroke();
    ctx.restore();
  }
  if (state.mismatches) drawMismatches();
  if (state.pulse) drawPulse();
  drawChrome();
}

function drawPinnedBasins(f) {
  const ids = f.properties.basin_ids || [];
  ctx.save();
  ctx.lineJoin = "round";
  for (const id of ids) {
    const geom = basinById.get(id);
    if (!geom) continue;
    traceGeom(ctx, geom);
    ctx.fillStyle = "rgba(87,224,255,0.22)"; ctx.fill("evenodd");
    ctx.strokeStyle = COL.basinOv; ctx.lineWidth = 1.6; ctx.stroke();
  }
  ctx.restore();
}

function drawMismatches() {
  ctx.save();
  ctx.lineJoin = "round";
  for (const f of state.mismatches) {
    traceGeom(ctx, f.geometry);
    ctx.strokeStyle = COL.haloDark; ctx.lineWidth = 4.5; ctx.stroke();
    ctx.strokeStyle = COL.mismatch; ctx.lineWidth = 2.4; ctx.stroke();
  }
  ctx.restore();
}

// --- chrome: moku labels, scale bar, north arrow ---------------------------
function drawChrome() {
  const W = canvas.width, H = canvas.height;
  ctx.save();
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.font = `600 ${Math.round(W / 78)}px -apple-system, Segoe UI, sans-serif`;
  for (const m of meta.moku_labels || []) {
    const t = m.name.toUpperCase();
    ctx.lineWidth = 4; ctx.strokeStyle = "rgba(0,0,0,0.75)";
    ctx.strokeText(t, m.x, m.y);
    ctx.fillStyle = "rgba(255,255,255,0.9)"; ctx.fillText(t, m.x, m.y);
  }
  ctx.restore();

  drawScaleBar();
  drawNorthArrow();
}

function niceDistance(m) {                       // pick a round scale-bar length (m)
  const opts = [1000, 2000, 5000, 10000, 20000, 50000];
  let best = opts[0];
  for (const o of opts) if (Math.abs(o - m) < Math.abs(best - m)) best = o;
  return best;
}

function drawScaleBar() {
  const W = canvas.width, H = canvas.height;
  const target = 0.16 * W * meta.m_per_px;       // aim ~16% of width
  const dist = niceDistance(target);
  const px = dist / meta.m_per_px;
  const x = W * 0.03, y = H * 0.955, h = Math.max(5, W / 320);
  ctx.save();
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(x - 6, y - h - 20, px + 12, h + 34);
  ctx.fillStyle = "#fff"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1;
  ctx.fillRect(x, y, px, h);
  ctx.fillStyle = "rgba(0,0,0,0.6)"; ctx.fillRect(x, y, px / 2, h);  // ticks
  ctx.strokeRect(x, y, px, h);
  ctx.fillStyle = "#fff"; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.font = `600 ${Math.round(W / 130)}px -apple-system, sans-serif`;
  ctx.fillText(dist >= 1000 ? `${dist / 1000} km` : `${dist} m`, x, y - 4);
  ctx.restore();
}

function drawNorthArrow() {
  const W = canvas.width;
  const x = W * 0.965, y = W * 0.028, r = W / 90;
  ctx.save();
  ctx.translate(x, y);
  ctx.beginPath(); ctx.moveTo(0, -r); ctx.lineTo(r * 0.6, r); ctx.lineTo(0, r * 0.45);
  ctx.lineTo(-r * 0.6, r); ctx.closePath();
  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.strokeStyle = "rgba(0,0,0,0.8)"; ctx.lineWidth = 2; ctx.stroke(); ctx.fill();
  ctx.fillStyle = "#fff"; ctx.strokeStyle = "rgba(0,0,0,0.8)";
  ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  ctx.font = `700 ${Math.round(W / 95)}px -apple-system, sans-serif`;
  ctx.lineWidth = 3; ctx.strokeText("N", 0, -r - 2); ctx.fillText("N", 0, -r - 2);
  ctx.restore();
}

function drawPulse() {
  const dt = performance.now() - state.pulse.t0;
  if (dt > 900) { state.pulse = null; return; }
  const p = dt / 900, r = (canvas.width / 40) * (0.4 + p);
  ctx.save();
  ctx.beginPath();
  ctx.arc(state.pulse.x, state.pulse.y, r, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(255,195,110,${1 - p})`;
  ctx.lineWidth = 3; ctx.stroke();
  ctx.restore();
  requestAnimationFrame(compose);
}

// --- geometry helpers ------------------------------------------------------
function traceGeom(g, geom) {
  g.beginPath();
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
  for (const poly of polys)
    for (const ring of poly) {
      g.moveTo(ring[0][0], ring[0][1]);
      for (let i = 1; i < ring.length; i++) g.lineTo(ring[i][0], ring[i][1]);
      g.closePath();
    }
}

function precomputeBBoxes(features) {
  for (const f of features) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const polys = f.geometry.type === "Polygon"
      ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const poly of polys) for (const [x, y] of poly[0]) {
      if (x < x0) x0 = x; if (x > x1) x1 = x;
      if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    f._bbox = [x0, y0, x1, y1];
    f._c = [(x0 + x1) / 2, (y0 + y1) / 2];
  }
}

function pointInRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
    if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi))
      inside = !inside;
  }
  return inside;
}
function pointInPolygon(x, y, poly) {
  if (!pointInRing(x, y, poly[0])) return false;
  for (let k = 1; k < poly.length; k++) if (pointInRing(x, y, poly[k])) return false;
  return true;
}
function featureAt(x, y) {
  for (const f of ahupuaa) {
    const b = f._bbox;
    if (x < b[0] || x > b[2] || y < b[1] || y > b[3]) continue;
    const polys = f.geometry.type === "Polygon"
      ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const poly of polys) if (pointInPolygon(x, y, poly)) return f;
  }
  return null;
}

// --- controls --------------------------------------------------------------
function buildViewMode() {
  document.querySelectorAll("#viewmode button").forEach(btn =>
    btn.addEventListener("click", () => {
      state.mode = btn.dataset.mode;
      document.querySelectorAll("#viewmode button")
        .forEach(b => b.classList.toggle("on", b === btn));
      document.getElementById("lyr-basins-label").textContent =
        state.mode === "match" ? "Match colouring" : "Computed basins";
      document.getElementById("opacity-label").textContent =
        state.mode === "match" ? "Match opacity" : "Basin opacity";
      updateLegend();
      compose();
    }));
}

function wireControls() {
  const bind = (id, key) => document.getElementById("lyr-" + id)
    .addEventListener("change", (e) => { state.layers[key] = e.target.checked; compose(); });
  bind("base", "base"); bind("basins", "basins");
  bind("streams", "streams"); bind("ahupuaa", "ahupuaa");
  const op = document.getElementById("opacity");
  op.addEventListener("input", () => { state.opacity = op.value / 100; compose(); });
}

function toWebPx(e) {
  const r = canvas.getBoundingClientRect();
  return [(e.clientX - r.left) * (canvas.width / r.width),
          (e.clientY - r.top) * (canvas.height / r.height)];
}

function wirePointer() {
  canvas.addEventListener("mousemove", (e) => {
    const [x, y] = toWebPx(e);
    const f = featureAt(x, y);
    if (f !== state.hover) {
      state.hover = f;
      if (!state.pinned) { showReadout(f, false); compose(); }
    }
  });
  canvas.addEventListener("mouseleave", () => {
    state.hover = null;
    if (!state.pinned) { showReadout(null, false); compose(); }
  });
  canvas.addEventListener("click", (e) => {
    const [x, y] = toWebPx(e);
    const f = featureAt(x, y);
    pin(f && f === state.pinned ? null : f);
  });
}

function pin(f) {
  state.pinned = f;
  if (f) state.pulse = { x: f._c[0], y: f._c[1], t0: performance.now() };
  showReadout(f || state.hover, !!f);
  compose();
}

// --- search + biggest mismatches -------------------------------------------
function norm(s) {
  return String(s).normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[ʻʼ'`]/g, "").toLowerCase().trim();
}

function buildSearchList() {
  const dl = document.getElementById("ahupuaa-names");
  dl.innerHTML = "";
  const seen = new Set();
  for (const f of [...ahupuaa].sort((a, b) =>
      a.properties.ahupuaa.localeCompare(b.properties.ahupuaa))) {
    const n = f.properties.ahupuaa;
    if (seen.has(n) || n === "N/A") continue;
    seen.add(n);
    const o = document.createElement("option");
    o.value = n; dl.appendChild(o);
  }
}

function wireSearchAndMismatch() {
  const input = document.getElementById("search");
  const go = () => {
    const q = norm(input.value);
    if (!q) return;
    const f = ahupuaa.find(ft => norm(ft.properties.ahupuaa) === q)
           || ahupuaa.find(ft => norm(ft.properties.ahupuaa).startsWith(q));
    if (f) pin(f);
  };
  input.addEventListener("change", go);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });

  document.getElementById("mismatch-btn").addEventListener("click", (e) => {
    if (state.mismatches) { state.mismatches = null; e.target.classList.remove("on"); }
    else {
      // real ahupuaʻa (not slivers) that genuinely split across several basins;
      // n_basins >= 2 excludes coastal strips too small to resolve at 0.5 km²
      state.mismatches = ahupuaa
        .filter(f => f.properties.n_basins >= 2 && (f.properties.acres || 0) >= 200)
        .sort((a, b) => a.properties.dom_frac - b.properties.dom_frac)
        .slice(0, 6);
      e.target.classList.add("on");
      listMismatches();
    }
    compose();
  });
}

function listMismatches() {
  const el = document.getElementById("readout");
  el.classList.remove("pinned");
  const items = state.mismatches.map(f => {
    const p = f.properties;
    return `<li data-name="${esc(p.ahupuaa)}"><span class="swatch" style="background:${matchColor(p)}"></span>`
      + `${esc(p.ahupuaa)} — ${Math.round(p.dom_frac * 100)}% one basin, splits across ${p.n_basins}</li>`;
  }).join("");
  el.innerHTML = `<div class="name" style="font-size:16px">Biggest mismatches</div>`
    + `<div class="where">Boundaries that span several computed watersheds — the cases worth discussing.</div>`
    + `<ol>${items}</ol>`;
  el.querySelectorAll("li").forEach(li => li.addEventListener("click", () => {
    const f = ahupuaa.find(ft => ft.properties.ahupuaa === li.dataset.name);
    pin(f);
  }));
}

// --- readout + legend ------------------------------------------------------
function showReadout(f, pinned) {
  const el = document.getElementById("readout");
  el.classList.toggle("pinned", pinned);
  if (!f) {
    el.innerHTML = '<div class="hint">Hover the map to inspect an ahupuaʻa. '
      + 'Click to pin it and see its computed watershed.</div>';
    return;
  }
  const p = f.properties;
  const name = p.ahupuaa === "N/A" ? "(unnamed parcel)" : p.ahupuaa;
  const acres = p.acres ? p.acres.toLocaleString() + " acres · " : "";
  const basins = pinned && p.basin_ids && p.basin_ids.length
    ? `<div class="stat"><span class="swatch" style="background:${COL.basinOv}"></span>`
      + `computed watershed${p.basin_ids.length > 1 ? "s" : ""} shown on the map</div>` : "";
  el.innerHTML =
    `<div class="name">${esc(name)}</div>`
    + `<div class="where">${esc(p.moku)} · ${esc(p.mokupuni)}</div>`
    + `<div class="note">${esc(p.note)}</div>`
    + `<div class="stat">${acres}${Math.round(p.dom_frac * 100)}% in its largest `
    + `computed basin${pinned ? " · pinned (click it again to release)" : ""}</div>`
    + basins;
}

function updateLegend() {
  const el = document.getElementById("legend");
  if (state.mode === "match") {
    el.innerHTML = `<h2>Match to computed drainage</h2>`
      + `<div class="match-ramp"></div>`
      + `<ul style="margin-top:8px">`
      + `<li><span></span>Green: the ahupuaʻa is one computed watershed.</li>`
      + `<li><span></span>Yellow: partial — a dominant basin plus others.</li>`
      + `<li><span></span>Red: drainage splits across several basins.</li>`
      + `<li><span class="sw" style="background:rgb(${TINY_COLOR.join(',')})"></span>Grey: too small to resolve at 10 m.</li>`
      + `</ul>`;
  } else {
    el.innerHTML = `<h2>Reading the map</h2><ul>`
      + `<li><span class="sw stream"></span>Streams — line weight grows with upstream drainage.</li>`
      + `<li><span class="sw basin"></span>Basins — each colour is one watershed draining to a stretch of coast.</li>`
      + `<li><span class="sw outline"></span>Ahupuaʻa outline — the cultural boundary.</li>`
      + `<li><span class="sw overlay"></span>Pinned: its computed watershed, over the boundary.</li>`
      + `</ul>`;
  }
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

boot().catch((err) => {
  const l = document.getElementById("loading");
  if (l) { l.style.display = ""; l.textContent = "Error: " + err.message; }
  console.error(err);
});
