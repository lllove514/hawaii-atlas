"use strict";

// Reef Heat Atlas — vanilla-JS pixel instrument. Loads scaled 5 km grids and
// paints each cell as a flat, quantised colour block (no smoothing) so the data
// reads as deliberate pixel art. Layers: SST, seasonal anomaly, and DHW.

const DATA = "../data/reef-heat-atlas/";
const FPS = 8;
const BLOCK = 1;                 // display binning: N -> each drawn block = N*N cells
const SST_STEPS = 11;            // discrete colour bands
const ANOM_STEPS = 13;           // odd -> a band centred on zero (white)

const LAND = [104, 112, 124];    // neutral gray landmass, distinct from all data
const COAST = [12, 16, 22];      // crisp dark coastline
const NODATA = [50, 56, 66];     // water with no satellite value (cloud)

// Base ramps sampled into discrete steps.
const SST_BASE = [
  [0.0, [44, 90, 160]], [0.25, [74, 152, 181]], [0.45, [99, 198, 168]],
  [0.62, [182, 217, 87]], [0.78, [246, 196, 69]], [0.90, [239, 138, 60]],
  [1.0, [214, 69, 69]],
];
const ANOM_BASE = [
  [0.0, [33, 102, 172]], [0.22, [74, 144, 196]], [0.42, [168, 207, 227]],
  [0.5, [238, 238, 240]], [0.58, [244, 182, 160]], [0.78, [214, 96, 77]],
  [1.0, [160, 28, 44]],
];
// DHW: explicit non-linear bands. 0 is a calm teal (safe), low end is sensitive,
// 4 and 8 are band edges. [upper_bound, rgb].
const DHW_BANDS = [
  [0.5, [36, 59, 69]], [1, [44, 95, 107]], [2, [47, 143, 138]], [3, [125, 191, 122]],
  [4, [201, 217, 78]], [6, [244, 196, 48]], [8, [239, 138, 43]], [12, [225, 75, 58]],
  [16, [168, 44, 140]], [Infinity, [106, 27, 154]],
];

let M, SST, DHW, MASK;
let COASTLINE, CLIM, FWEEK, NW;   // coastline segs, day-of-year climatology
let SSTB, ANOMB;                  // precomputed band colours
let frame = 0, layer = "sst", playing = false, timer = null;
let grid, gctx, dW, dH;          // offscreen display-res canvas
let hover = null, bounds, midCos, scaleF = 1;

const ISLANDS = [
  ["Kauaʻi", 22.05, -159.5], ["Niʻihau", 21.9, -160.15],
  ["Oʻahu", 21.47, -157.98], ["Molokaʻi", 21.13, -157.0],
  ["Lānaʻi", 20.82, -156.92], ["Maui", 20.8, -156.33],
  ["Kahoʻolawe", 20.55, -156.6], ["Hawaiʻi Island", 19.6, -155.5],
];

const $ = (id) => document.getElementById(id);
const cv = $("map"), ctx = cv.getContext("2d");

function sample(stops, v) {
  if (v <= stops[0][0]) return stops[0][1];
  const last = stops[stops.length - 1];
  if (v >= last[0]) return last[1];
  for (let k = 1; k < stops.length; k++) {
    if (v <= stops[k][0]) {
      const [p0, c0] = stops[k - 1], [p1, c1] = stops[k];
      const t = (v - p0) / (p1 - p0);
      return [c0[0] + (c1[0] - c0[0]) * t, c0[1] + (c1[1] - c0[1]) * t, c0[2] + (c1[2] - c0[2]) * t];
    }
  }
  return last[1];
}
const bands = (base, n) =>
  Array.from({ length: n }, (_, k) => sample(base, (k + 0.5) / n).map(Math.round));

function stepColor(colors, v, lo, hi) {          // value -> flat band colour
  const t = (v - lo) / (hi - lo);
  const k = Math.max(0, Math.min(colors.length - 1, Math.floor(t * colors.length)));
  return colors[k];
}
function dhwColor(v) {
  for (const [lt, c] of DHW_BANDS) if (v < lt) return c;
  return DHW_BANDS[DHW_BANDS.length - 1][1];
}

async function fetchProgress(url, note) {
  const resp = await fetch(url);
  const total = +resp.headers.get("content-length") || 0;
  const reader = resp.body.getReader();
  const chunks = []; let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value); got += value.length;
    if (total) {
      $("loadfill").style.width = (100 * got / total).toFixed(1) + "%";
      $("loadtext").textContent = `${note} · ${(got / 1e6).toFixed(1)} / ${(total / 1e6).toFixed(1)} MB`;
    }
  }
  const buf = new Uint8Array(got); let off = 0;
  for (const c of chunks) { buf.set(c, off); off += c.length; }
  return inflate(buf);
}

// The grids ship gzipped; inflate with the browser's native DecompressionStream.
// If a server delivered them already-decoded (Content-Encoding), pass through.
async function inflate(buf) {
  if (buf[0] !== 0x1f || buf[1] !== 0x8b) return buf.buffer;
  const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}

async function boot() {
  M = await fetch(DATA + "manifest.json").then((r) => r.json());
  bounds = { w: M.west, e: M.east, s: M.south, n: M.north };
  midCos = Math.cos((bounds.s + bounds.n) / 2 * Math.PI / 180);
  SSTB = bands(SST_BASE, SST_STEPS);
  ANOMB = bands(ANOM_BASE, ANOM_STEPS);

  $("scrub").max = M.nframes - 1;
  $("d-min").textContent = M.dates[0]; $("d-max").textContent = M.dates[M.nframes - 1];
  $("now-span").textContent = `${M.dates[0]} — ${M.dates[M.nframes - 1]}`;
  wireUI(); drawLegend();
  window.addEventListener("resize", resize);
  resize();                                        // size the stage / loading box

  COASTLINE = await fetch(DATA + "coast.json").then((r) => r.json());
  MASK = new Uint8Array(await fetch(DATA + "mask.u8").then((r) => r.arrayBuffer()));
  SST = new Int16Array(await fetchProgress(DATA + "sst.i16.gz", "Loading SST"));
  DHW = new Uint8Array(await fetchProgress(DATA + "dhw.u8.gz", "Loading DHW"));

  $("loadtext").textContent = "Building seasonal climatology…";
  await new Promise((r) => setTimeout(r, 0));
  buildClimatology();

  dW = Math.ceil(M.nlon / BLOCK); dH = Math.ceil(M.nlat / BLOCK);
  grid = document.createElement("canvas");
  grid.width = dW; grid.height = dH;
  gctx = grid.getContext("2d");

  frame = M.nframes - 1; $("scrub").value = frame;
  $("loading").classList.add("done");
  resize();                                        // now renders
}

// Per-pixel mean SST for each week-of-year, for the anomaly layer. Computed in
// the browser from the SST stack, so no extra download.
function buildClimatology() {
  const npix = M.nlat * M.nlon, nd = M.dates.length;
  FWEEK = new Uint8Array(nd);
  for (let f = 0; f < nd; f++) {
    const d = M.dates[f];
    const y = +d.slice(0, 4);
    const utc = Date.UTC(y, +d.slice(5, 7) - 1, +d.slice(8, 10));
    const doy = Math.floor((utc - Date.UTC(y, 0, 1)) / 86400000);
    FWEEK[f] = Math.min(52, Math.floor(doy / 7));
  }
  NW = 53;
  const sum = new Float64Array(NW * npix), cnt = new Uint32Array(NW * npix);
  for (let f = 0; f < nd; f++) {
    const base = f * npix, wb = FWEEK[f] * npix;
    for (let c = 0; c < npix; c++) {
      const raw = SST[base + c];
      if (raw !== M.nodata_i16) { sum[wb + c] += raw; cnt[wb + c]++; }
    }
  }
  CLIM = new Float32Array(NW * npix);             // mean SST (degC) per week/pixel
  for (let i = 0; i < CLIM.length; i++) CLIM[i] = cnt[i] ? sum[i] / cnt[i] / M.sst_scale : NaN;
}

// value at a cell for the active layer, or null if no data
function cellValue(src, base) {
  if (layer === "dhw") return DHW[base + src] / M.dhw_scale;
  const raw = SST[base + src];
  if (raw === M.nodata_i16) return null;
  const sst = raw / M.sst_scale;
  if (layer === "sst") return sst;
  const c = CLIM[FWEEK[frame] * M.nlat * M.nlon + src];   // anomaly
  return Number.isNaN(c) ? null : sst - c;
}
function colorFor(v) {
  if (v === null) return NODATA;
  if (layer === "dhw") return dhwColor(v);
  if (layer === "anom") return stepColor(ANOMB, v, M.anom_display[0], M.anom_display[1]);
  return stepColor(SSTB, v, M.sst_display[0], M.sst_display[1]);
}

function paintGrid() {
  const { nlat, nlon } = M, npix = nlat * nlon, base = frame * npix;
  const img = gctx.createImageData(dW, dH), d = img.data;
  for (let I = 0; I < dH; I++) {
    for (let J = 0; J < dW; J++) {
      const i = Math.min(nlat - 1, I * BLOCK), j = Math.min(nlon - 1, J * BLOCK);
      const src = i * nlon + j;
      const c = MASK[src] === 0 ? LAND : colorFor(cellValue(src, base));
      const o = (I * dW + J) * 4;
      d[o] = c[0]; d[o + 1] = c[1]; d[o + 2] = c[2]; d[o + 3] = 255;
    }
  }
  gctx.putImageData(img, 0, 0);
}

const lon2x = (lon) => (lon - bounds.w) / (bounds.e - bounds.w) * cv.width;
const lat2y = (lat) => (bounds.n - lat) / (bounds.n - bounds.s) * cv.height;
const cellLat = (i) => bounds.n - (i + 0.5) * (bounds.n - bounds.s) / M.nlat;
const cellLon = (j) => bounds.w + (j + 0.5) * (bounds.e - bounds.w) / M.nlon;

function render() {
  paintGrid();
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.imageSmoothingEnabled = false;             // hard-edged pixel blocks
  ctx.drawImage(grid, 0, 0, cv.width, cv.height);

  ctx.strokeStyle = `rgb(${COAST[0]},${COAST[1]},${COAST[2]})`;
  ctx.lineWidth = Math.max(1, scaleF);
  ctx.beginPath();
  for (const s of COASTLINE.coordinates) {
    ctx.moveTo(lon2x(s[0][0]), lat2y(s[0][1]));
    ctx.lineTo(lon2x(s[1][0]), lat2y(s[1][1]));
  }
  ctx.stroke();

  drawLabels();
  drawScaleAndNorth();

  if (hover) {
    const x = lon2x(cellLon(hover.j)), y = lat2y(cellLat(hover.i));
    const cw = cv.width / M.nlon, ch = cv.height / M.nlat;
    ctx.strokeStyle = "rgba(255,255,255,.95)"; ctx.lineWidth = Math.max(1.5, scaleF * 1.5);
    ctx.strokeRect(x - cw / 2, y - ch / 2, cw, ch);
  }
  $("now-date").textContent = M.dates[frame];
}

function drawLabels() {
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.font = `600 ${11 * scaleF}px -apple-system, "Segoe UI", Roboto, sans-serif`;
  for (const [name, lat, lon] of ISLANDS) {
    if (lat > bounds.n || lat < bounds.s || lon < bounds.w || lon > bounds.e) continue;
    const x = lon2x(lon), y = lat2y(lat);
    ctx.lineWidth = 3 * scaleF; ctx.strokeStyle = "rgba(10,14,20,.85)";
    ctx.strokeText(name, x, y); ctx.fillStyle = "#f2f6fb"; ctx.fillText(name, x, y);
  }
}

function drawScaleAndNorth() {
  const km = 100;
  const widthKm = (bounds.e - bounds.w) * 111.32 * midCos;
  const barPx = km / widthKm * cv.width;
  const x0 = 14 * scaleF, y0 = cv.height - 18 * scaleF;
  ctx.strokeStyle = "rgba(240,245,251,.9)"; ctx.fillStyle = "rgba(240,245,251,.9)";
  ctx.lineWidth = 2 * scaleF;
  ctx.beginPath();
  ctx.moveTo(x0, y0 - 4 * scaleF); ctx.lineTo(x0, y0); ctx.lineTo(x0 + barPx, y0);
  ctx.lineTo(x0 + barPx, y0 - 4 * scaleF); ctx.stroke();
  ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.font = `${10.5 * scaleF}px ui-monospace, Menlo, monospace`;
  ctx.fillText(`${km} km`, x0, y0 - 6 * scaleF);
  // north arrow (north is up)
  const nx = x0 + 6 * scaleF, ny = y0 - 34 * scaleF, h = 20 * scaleF;
  ctx.beginPath(); ctx.moveTo(nx, ny); ctx.lineTo(nx, ny + h); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(nx - 4 * scaleF, ny + 6 * scaleF);
  ctx.lineTo(nx, ny); ctx.lineTo(nx + 4 * scaleF, ny + 6 * scaleF); ctx.stroke();
  ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  ctx.fillText("N", nx, ny - 2 * scaleF);
}

const RISK = (dhw) =>
  dhw >= M.thresholds.severe ? ["Severe bleaching + mortality", "#e14b3a"]
  : dhw >= M.thresholds.significant ? ["Significant bleaching likely", "#f4c430"]
  : dhw >= 1 ? ["Heat stress building", "#2f8f8a"]
  : ["No significant stress", "#8b98ab"];

function updateReadout() {
  const ro = $("readout");
  if (!hover) { ro.classList.add("hidden"); return; }
  ro.classList.remove("hidden");
  const npix = M.nlat * M.nlon, src = hover.i * M.nlon + hover.j, base = frame * npix;
  $("ro-date").textContent = M.dates[frame];
  $("ro-pos").textContent = `${cellLat(hover.i).toFixed(2)}°N  ${(-cellLon(hover.j)).toFixed(2)}°W`;
  const spark = $("ro-spark"), sparkNote = document.querySelector(".ro-spark-note");
  if (MASK[src] === 0) {
    for (const id of ["ro-sst", "ro-anom", "ro-dhw"]) $(id).textContent = id === "ro-sst" ? "land" : "—";
    $("ro-risk").textContent = "";
    spark.style.display = sparkNote.style.display = "none";
    return;
  }
  spark.style.display = sparkNote.style.display = "";
  const raw = SST[base + src];
  const sst = raw === M.nodata_i16 ? null : raw / M.sst_scale;
  const clim = CLIM[FWEEK[frame] * npix + src];
  const anom = (sst === null || Number.isNaN(clim)) ? null : sst - clim;
  const dhw = DHW[base + src] / M.dhw_scale;
  $("ro-sst").textContent = sst === null ? "no data" : sst.toFixed(2) + " °C";
  $("ro-anom").textContent = anom === null ? "—" : (anom >= 0 ? "+" : "") + anom.toFixed(2) + " °C";
  $("ro-dhw").textContent = dhw.toFixed(1) + " °C-wk";
  const [label, col] = RISK(dhw);
  const r = $("ro-risk"); r.textContent = label; r.style.color = col;
  drawSpark(src, npix);
}

// Small DHW-history chart for the hovered cell: full record, 4/8 threshold
// guides, and a marker at the current frame.
function drawSpark(src, npix) {
  const c = $("ro-spark"), g = c.getContext("2d"), W = c.width, H = c.height;
  const vmax = Math.max(10, M.dhw_display ? M.dhw_display[1] : 16);
  g.clearRect(0, 0, W, H);
  g.fillStyle = "rgba(255,255,255,0.05)";
  g.fillRect(0, 0, W, H);
  for (const t of [4, 8]) {
    const y = H - 1 - (t / vmax) * (H - 2);
    g.fillStyle = "rgba(244,196,48,0.35)";
    g.fillRect(0, Math.round(y), W, 1);
  }
  g.fillStyle = "rgba(75,179,212,0.9)";
  for (let x = 0; x < W; x++) {
    const f = Math.round(x / (W - 1) * (M.nframes - 1));
    const v = Math.min(vmax, DHW[f * npix + src] / M.dhw_scale);
    const h = (v / vmax) * (H - 2);
    if (h > 0.4) g.fillRect(x, H - 1 - h, 1, h);
  }
  const xf = Math.round(frame / (M.nframes - 1) * (W - 1));
  g.fillStyle = "rgba(255,255,255,0.85)";
  g.fillRect(xf, 0, 1, H);
}

function setFrame(f) {
  frame = Math.max(0, Math.min(M.nframes - 1, f | 0));
  $("scrub").value = frame; render(); updateReadout();
}
function play(on) {
  playing = on; $("play").textContent = on ? "❚❚" : "▶";
  if (timer) { clearInterval(timer); timer = null; }
  if (on) timer = setInterval(() => setFrame(frame >= M.nframes - 1 ? 0 : frame + 1), 1000 / FPS);
}
function setLayer(l) {
  layer = l;
  for (const k of ["sst", "anom", "dhw"]) $("t-" + k).classList.toggle("on", k === l);
  drawLegend(); render(); updateReadout();
}

// Peak-DHW frame of a given year, found from the loaded record itself.
const peakCache = new Map();
function peakFrame(year) {
  if (peakCache.has(year)) return peakCache.get(year);
  const npix = M.nlat * M.nlon;
  let best = 0, bestV = -1;
  for (let f = 0; f < M.nframes; f++) {
    if (+M.dates[f].slice(0, 4) !== year) continue;
    const base = f * npix;
    let mx = 0;
    for (let c = 0; c < npix; c++) { const v = DHW[base + c]; if (v > mx) mx = v; }
    if (mx > bestV) { bestV = mx; best = f; }
  }
  peakCache.set(year, best);
  return best;
}

function wireUI() {
  $("play").onclick = () => play(!playing);
  for (const b of document.querySelectorAll(".events button")) {
    b.onclick = () => { play(false); setLayer("dhw"); setFrame(peakFrame(+b.dataset.year)); };
  }
  $("scrub").oninput = (e) => { if (playing) play(false); setFrame(+e.target.value); };
  $("t-sst").onclick = () => setLayer("sst");
  $("t-anom").onclick = () => setLayer("anom");
  $("t-dhw").onclick = () => setLayer("dhw");
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space") { e.preventDefault(); play(!playing); }
    else if (e.code === "ArrowRight") { play(false); setFrame(frame + 1); }
    else if (e.code === "ArrowLeft") { play(false); setFrame(frame - 1); }
  });
  cv.addEventListener("mousemove", onMove);
  cv.addEventListener("mouseleave", () => { hover = null; render(); updateReadout(); });
}

function onMove(e) {
  const b = cv.getBoundingClientRect();
  const j = Math.floor((e.clientX - b.left) / b.width * M.nlon);
  const i = Math.floor((e.clientY - b.top) / b.height * M.nlat);
  if (i < 0 || i >= M.nlat || j < 0 || j >= M.nlon) {
    if (hover) { hover = null; render(); updateReadout(); }
    return;
  }
  hover = { i, j }; render(); updateReadout();
}

// --- legend: discrete swatches matching the map -------------------------
function drawLegend() {
  const bar = $("lg-bar"), bx = bar.getContext("2d"), W = bar.width, H = bar.height;
  bx.clearRect(0, 0, W, H);
  const ticks = $("lg-ticks"); ticks.innerHTML = "";
  const put = (frac, text, mark) => {
    const s = document.createElement("span");
    s.className = mark ? "mark" : ""; s.style.left = (100 * frac) + "%"; s.textContent = text;
    ticks.appendChild(s);
  };

  if (layer === "dhw") {
    $("lg-title").textContent = "Degree Heating Weeks (°C-weeks)";
    const n = DHW_BANDS.length, sw = W / n;
    for (let k = 0; k < n; k++) {
      const c = DHW_BANDS[k][1]; bx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
      bx.fillRect(Math.round(k * sw), 0, Math.ceil(sw), H);
    }
    put(0.02, "0");
    put(5 / n, "4", true); put(7 / n, "8", true); put(9 / n, "16");
    $("lg-note").textContent = "Calm teal = no heat stress · brighter = bleaching risk. 4: bleaching likely · 8: severe.";
  } else {
    const isAnom = layer === "anom";
    const colors = isAnom ? ANOMB : SSTB;
    const [lo, hi] = isAnom ? M.anom_display : M.sst_display;
    $("lg-title").textContent = isAnom ? "SST anomaly vs day-of-year mean (°C)"
                                       : "Sea-surface temperature (°C)";
    const n = colors.length, sw = W / n;
    for (let k = 0; k < n; k++) {
      const c = colors[k]; bx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
      bx.fillRect(Math.round(k * sw), 0, Math.ceil(sw), H);
    }
    if (isAnom) { put(0.02, "−3"); put(0.5, "0", true); put(0.98, "+3"); }
    else { put(0.02, lo.toFixed(0)); put(0.5, ((lo + hi) / 2).toFixed(0)); put(0.98, hi.toFixed(0)); }
    $("lg-note").textContent = isAnom
      ? "Warmer (red) or cooler (blue) than normal for this week of the year."
      : "Domain tightened to the regional range. Each block = one 5 km cell.";
  }
}

function resize() {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const app = $("app"), cs = getComputedStyle(app);
  const availW = app.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const availH = app.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)
    - document.querySelector("header").offsetHeight - $("controls").offsetHeight - 26;
  const aspect = (bounds.e - bounds.w) * midCos / (bounds.n - bounds.s);
  let w = availW, h = w / aspect;
  if (h > availH) { h = availH; w = h * aspect; }
  const stage = $("stage");
  stage.style.width = w + "px"; stage.style.height = h + "px";
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  scaleF = dpr;
  if (grid) render();
}

boot().catch((e) => { $("loadtext").textContent = "Load error: " + e.message; console.error(e); });
