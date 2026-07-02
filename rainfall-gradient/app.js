"use strict";

// ---- constants -----------------------------------------------------------------------
const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

// YlGnBu sequential ramp (ColorBrewer): perceptually ordered, dry -> wet.
const STOPS = [[255,255,217],[237,248,177],[199,233,180],[127,205,187],[65,182,196],
  [29,145,192],[34,94,168],[37,52,148],[8,29,88]];

function buildLUT(stops, n) {
  const lut = new Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1) * (stops.length - 1);
    const a = Math.floor(t), b = Math.min(a + 1, stops.length - 1), f = t - a;
    lut[i] = [0,1,2].map(c => Math.round(stops[a][c] + (stops[b][c] - stops[a][c]) * f));
  }
  return lut;
}
const LUT = buildLUT(STOPS, 256);

// ---- state ---------------------------------------------------------------------------
const state = {
  mode: "clim",
  monthIdx: 0,
  yearIdx: 0,
  vmax: 600,
  products: {},
  surprise: null,   // {island, wet:{lon,lat}, dry:{lon,lat}}
  playTimer: null,
};

let stations = [];
const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
const off = document.createElement("canvas");
const offctx = off.getContext("2d");
const mainEl = document.querySelector("main");
let layout = null;

// ---- data loading --------------------------------------------------------------------
async function loadProduct(stem, maskTag) {
  const meta = await (await fetch(`../data/rainfall-gradient/${stem}.json`)).json();
  const values = new Uint16Array(await (await fetch(`../data/rainfall-gradient/${stem}.bin`)).arrayBuffer());
  const mask = new Uint8Array(await (await fetch(`../data/rainfall-gradient/mask_${maskTag}.bin`)).arrayBuffer());
  const [x0, x1, y0, y1] = meta.extent;
  return {
    meta, values, mask,
    nx: meta.nx, ny: meta.ny, res: meta.res, extent: meta.extent,
    lonSpan: x1 - x0, latSpan: y1 - y0,
    nodata: meta.encoding.nodata, scale: meta.encoding.scale,
    islandName: new Map(meta.islands.map(it => [it.id, it.name])),
    extremesCache: new Map(),
  };
}

// ---- geometry helpers ----------------------------------------------------------------
function currentProduct() { return state.products[state.mode]; }
function surfaceIndex() { return state.mode === "clim" ? state.monthIdx : state.yearIdx * 12 + state.monthIdx; }
function currentSurfaceMeta() {
  const p = currentProduct();
  return state.mode === "clim" ? p.meta.months[state.monthIdx] : p.meta.surfaces[surfaceIndex()];
}

function computeLayout() {
  const r = mainEl.getBoundingClientRect();
  const p = currentProduct();
  const latMid = (p.extent[2] + p.extent[3]) / 2;
  const aspect = (p.lonSpan * Math.cos(latMid * Math.PI / 180)) / p.latSpan;
  let mw = r.width, mh = r.width / aspect;
  if (mh > r.height) { mh = r.height; mw = r.height * aspect; }
  layout = { cw: r.width, ch: r.height, mw, mh, ox: (r.width - mw) / 2, oy: (r.height - mh) / 2 };

  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
  canvas.style.width = r.width + "px";
  canvas.style.height = r.height + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function lonToX(lon) { const p = currentProduct(); return layout.ox + (lon - p.extent[0]) / p.lonSpan * layout.mw; }
function latToY(lat) { const p = currentProduct(); return layout.oy + (p.extent[3] - lat) / p.latSpan * layout.mh; }
function xToLon(x) { const p = currentProduct(); return p.extent[0] + (x - layout.ox) / layout.mw * p.lonSpan; }
function yToLat(y) { const p = currentProduct(); return p.extent[3] - (y - layout.oy) / layout.mh * p.latSpan; }

function cellOf(p, lat, lon) {
  return { i: Math.floor((lon - p.extent[0]) / p.res), j: Math.floor((p.extent[3] - lat) / p.res) };
}
function cellCenter(p, k) {
  const i = k % p.nx, j = (k / p.nx) | 0;
  return { lon: p.extent[0] + (i + 0.5) * p.res, lat: p.extent[3] - (j + 0.5) * p.res };
}
function distKm(la1, lo1, la2, lo2) {
  const dy = (la1 - la2) * 111.0;
  const dx = (lo1 - lo2) * 111.0 * Math.cos((la1 + la2) / 2 * Math.PI / 180);
  return Math.hypot(dx, dy);
}

// ---- rendering -----------------------------------------------------------------------
function renderSurface() {
  const p = currentProduct(), si = surfaceIndex(), n = p.nx * p.ny, base = si * n;
  if (off.width !== p.nx) { off.width = p.nx; off.height = p.ny; }
  const img = offctx.createImageData(p.nx, p.ny), d = img.data, vmax = state.vmax;
  for (let k = 0; k < n; k++) {
    const v = p.values[base + k], o = k * 4;
    if (v === p.nodata) { d[o + 3] = p.mask[k] ? 40 : 0; d[o] = d[o + 1] = d[o + 2] = 90; continue; }
    let t = (v / p.scale) / vmax; if (t > 1) t = 1; else if (t < 0) t = 0;
    const c = LUT[(t * 255) | 0];
    d[o] = c[0]; d[o + 1] = c[1]; d[o + 2] = c[2]; d[o + 3] = 235;
  }
  offctx.putImageData(img, 0, 0);
}

let coastline = null;
function drawCoast() {
  if (!coastline) return;
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(220,235,245,0.55)";
  for (const feat of coastline.features) {
    const geom = feat.geometry;
    const polys = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];
    for (const poly of polys) for (const ring of poly) {
      ctx.beginPath();
      ring.forEach(([lon, lat], idx) => {
        const x = lonToX(lon), y = latToY(lat);
        idx ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.closePath();
      ctx.stroke();
    }
  }
}

function drawMarkers() {
  const s = state.surprise;
  if (!s) return;
  const mark = (pt, color, label) => {
    const x = lonToX(pt.lon), y = latToY(pt.lat);
    ctx.beginPath(); ctx.arc(x, y, 6, 0, 2 * Math.PI);
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y, 2, 0, 2 * Math.PI); ctx.fillStyle = color; ctx.fill();
    ctx.font = "11px monospace"; ctx.fillStyle = color;
    ctx.fillText(label, x + 9, y + 4);
  };
  mark(s.wet, "#7cc6ff", "wettest");
  mark(s.dry, "#e6c07b", "driest");
}

function draw() {
  renderSurface();
  ctx.clearRect(0, 0, layout.cw, layout.ch);
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(off, layout.ox, layout.oy, layout.mw, layout.mh);
  drawCoast();
  drawMarkers();
  updateStamp();
}

// ---- readouts & legend ---------------------------------------------------------------
function updateStamp() {
  const m = currentSurfaceMeta();
  document.getElementById("stamp").textContent =
    state.mode === "clim" ? MONTHS[state.monthIdx] : `${MONTHS[state.monthIdx]}`;
  document.getElementById("conf").classList.toggle("hidden", !(m && m.low_confidence));
}

function drawLegend() {
  const lc = document.getElementById("legend-bar"), lctx = lc.getContext("2d");
  const img = lctx.createImageData(lc.width, 1);
  for (let x = 0; x < lc.width; x++) {
    const c = LUT[(x / (lc.width - 1) * 255) | 0], o = x * 4;
    img.data[o] = c[0]; img.data[o + 1] = c[1]; img.data[o + 2] = c[2]; img.data[o + 3] = 255;
  }
  for (let y = 0; y < lc.height; y++) lctx.putImageData(img, 0, y);
  document.getElementById("lg-mid").textContent = Math.round(state.vmax / 2);
  document.getElementById("lg-hi").textContent = Math.round(state.vmax) + "+";
}

function onHover(ev) {
  const r = canvas.getBoundingClientRect();
  const x = ev.clientX - r.left, y = ev.clientY - r.top;
  const p = currentProduct();
  const lon = xToLon(x), lat = yToLat(y);
  const place = document.querySelector("#readout .ro-place");
  const val = document.querySelector("#readout .ro-value");
  const stn = document.querySelector("#readout .ro-station");

  const { i, j } = cellOf(p, lat, lon);
  if (i < 0 || i >= p.nx || j < 0 || j >= p.ny) {
    place.textContent = "off map"; val.innerHTML = "&nbsp;"; stn.innerHTML = "&nbsp;"; return;
  }
  const v = p.values[surfaceIndex() * p.nx * p.ny + j * p.nx + i];
  place.textContent = `${Math.abs(lat).toFixed(3)}°N  ${Math.abs(lon).toFixed(3)}°W`;
  if (v === p.nodata) {
    val.textContent = p.mask[j * p.nx + i] ? "no data" : "— ocean —";
  } else {
    const mm = v / p.scale;
    val.textContent = `${mm.toFixed(1)} mm  ·  ${(mm / 25.4).toFixed(2)} in`;
  }
  let best = null, bd = 1e9;
  for (const s of stations) {
    const dd = distKm(lat, lon, s.lat, s.lon);
    if (dd < bd) { bd = dd; best = s; }
  }
  if (best) stn.textContent = `nearest: ${best.name.trim()} · ${bd.toFixed(1)} km`;
}

// ---- surprise (per-island extremes) --------------------------------------------------
function islandAt(p, lat, lon) {
  const { i, j } = cellOf(p, lat, lon);
  if (i < 0 || i >= p.nx || j < 0 || j >= p.ny) return 0;
  const here = p.mask[j * p.nx + i];
  if (here) return here;
  const counts = {};
  for (let dj = -3; dj <= 3; dj++) for (let di = -3; di <= 3; di++) {
    const jj = j + dj, ii = i + di;
    if (jj < 0 || jj >= p.ny || ii < 0 || ii >= p.nx) continue;
    const m = p.mask[jj * p.nx + ii];
    if (m) counts[m] = (counts[m] || 0) + 1;
  }
  let best = 0, bc = 0;
  for (const k in counts) if (counts[k] > bc) { bc = counts[k]; best = +k; }
  return best;
}

function extremes(p, si, island) {
  const key = si * 1000 + island;
  if (p.extremesCache.has(key)) return p.extremesCache.get(key);
  const n = p.nx * p.ny, base = si * n;
  let maxV = -1, minV = Infinity, maxK = -1, minK = -1;
  for (let k = 0; k < n; k++) {
    if (p.mask[k] !== island) continue;
    const v = p.values[base + k];
    if (v === p.nodata) continue;
    if (v > maxV) { maxV = v; maxK = k; }
    if (v < minV) { minV = v; minK = k; }
  }
  const res = maxK < 0 ? null : {
    maxMM: maxV / p.scale, minMM: minV / p.scale,
    wet: cellCenter(p, maxK), dry: cellCenter(p, minK),
  };
  p.extremesCache.set(key, res);
  return res;
}

function onClick(ev) {
  const r = canvas.getBoundingClientRect();
  const p = currentProduct();
  const lon = xToLon(ev.clientX - r.left), lat = yToLat(ev.clientY - r.top);
  const island = islandAt(p, lat, lon);
  const box = document.getElementById("surprise");
  if (!island) { box.classList.add("hidden"); state.surprise = null; draw(); return; }
  const ex = extremes(p, surfaceIndex(), island);
  if (!ex) { box.classList.add("hidden"); state.surprise = null; draw(); return; }

  const ratio = ex.minMM > 0 ? ex.maxMM / ex.minMM : Infinity;
  box.querySelector(".sp-island").textContent = p.islandName.get(island) || "island";
  box.querySelector(".sp-wetv").textContent = `${ex.maxMM.toFixed(0)} mm`;
  box.querySelector(".sp-dryv").textContent = `${ex.minMM.toFixed(0)} mm`;
  box.querySelector(".sp-ratio").innerHTML = isFinite(ratio)
    ? `wettest is <b>${ratio.toFixed(1)}×</b> the driest`
    : `driest cell is essentially dry`;
  box.classList.remove("hidden");
  state.surprise = { island, wet: ex.wet, dry: ex.dry };
  draw();
}

// ---- controls ------------------------------------------------------------------------
function setMonth(m) { state.monthIdx = m; document.getElementById("month").value = m; refreshSurprise(); draw(); }
function setYear(y) {
  state.yearIdx = y;
  const p = currentProduct();
  document.getElementById("year-stamp").textContent = p.meta.years[0] + y;
  refreshSurprise(); draw();
}

function refreshSurprise() {
  // recompute markers for the new surface if a surprise island is pinned
  if (!state.surprise) return;
  const p = currentProduct();
  const ex = extremes(p, surfaceIndex(), state.surprise.island);
  if (!ex) return;
  const ratio = ex.minMM > 0 ? ex.maxMM / ex.minMM : Infinity;
  const box = document.getElementById("surprise");
  box.querySelector(".sp-wetv").textContent = `${ex.maxMM.toFixed(0)} mm`;
  box.querySelector(".sp-dryv").textContent = `${ex.minMM.toFixed(0)} mm`;
  box.querySelector(".sp-ratio").innerHTML = isFinite(ratio)
    ? `wettest is <b>${ratio.toFixed(1)}×</b> the driest` : `driest cell is essentially dry`;
  state.surprise.wet = ex.wet; state.surprise.dry = ex.dry;
}

function togglePlay() {
  const btn = document.getElementById("play");
  if (state.playTimer) {
    clearInterval(state.playTimer); state.playTimer = null;
    btn.textContent = "▶"; btn.classList.remove("playing");
  } else {
    btn.textContent = "❚❚"; btn.classList.add("playing");
    state.playTimer = setInterval(() => setMonth((state.monthIdx + 1) % 12), 750);
  }
}

function setMode(mode) {
  if (mode === state.mode || !state.products[mode]) return;
  state.mode = mode;
  document.getElementById("mode-clim").classList.toggle("active", mode === "clim");
  document.getElementById("mode-ts").classList.toggle("active", mode === "ts");
  document.querySelector(".yearonly").classList.toggle("hidden", mode !== "ts");
  state.surprise = null;
  document.getElementById("surprise").classList.add("hidden");
  computeLayout();
  if (mode === "ts") setYear(state.yearIdx);
  draw();
}

function setVmax(v) {
  state.vmax = v;
  document.getElementById("vmax-val").textContent = Math.round(v) + " mm";
  drawLegend(); draw();
}

// ---- init ----------------------------------------------------------------------------
async function init() {
  state.products.clim = await loadProduct("climatology", "clim");
  stations = await (await fetch("../data/rainfall-gradient/stations.json")).json();
  coastline = await (await fetch("../data/rainfall-gradient/coastline.geojson")).json();

  try {
    state.products.ts = await loadProduct("timeseries", "ts");
    const yrs = state.products.ts.meta.years;
    const ys = document.getElementById("year");
    ys.min = 0; ys.max = yrs[1] - yrs[0]; ys.value = 0;
    document.getElementById("year-stamp").textContent = yrs[0];
  } catch (e) {
    document.getElementById("mode-ts").disabled = true;
  }

  state.vmax = Math.round(state.products.clim.meta.default_vmax);
  const vs = document.getElementById("vmax");
  vs.max = Math.max(1000, Math.round(state.products.clim.meta.abs_max));
  vs.value = state.vmax;
  document.getElementById("vmax-val").textContent = state.vmax + " mm";

  computeLayout();
  drawLegend();
  draw();

  canvas.addEventListener("mousemove", onHover);
  canvas.addEventListener("click", onClick);
  document.getElementById("month").addEventListener("input", e => setMonth(+e.target.value));
  document.getElementById("year").addEventListener("input", e => setYear(+e.target.value));
  document.getElementById("vmax").addEventListener("input", e => setVmax(+e.target.value));
  document.getElementById("play").addEventListener("click", togglePlay);
  document.getElementById("mode-clim").addEventListener("click", () => setMode("clim"));
  document.getElementById("mode-ts").addEventListener("click", () => setMode("ts"));
  document.querySelector("#surprise .close").addEventListener("click", () => {
    state.surprise = null; document.getElementById("surprise").classList.add("hidden"); draw();
  });
  window.addEventListener("resize", () => { computeLayout(); draw(); });
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    else if (e.code === "ArrowRight") setMonth((state.monthIdx + 1) % 12);
    else if (e.code === "ArrowLeft") setMonth((state.monthIdx + 11) % 12);
  });
}

init();
