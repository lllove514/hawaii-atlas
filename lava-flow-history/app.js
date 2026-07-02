"use strict";
// Lava Flow History of Hawaiʻi Island — canvas renderer.
//
// Assets share one grid (see scripts/export_web.py):
//   hillshade.png  grayscale relief
//   flow_age.png   RGBA; ordinal = (R<<8 | G), B = volcano id (1..5), A>0 = lava
//   timeline.json  ordinal -> {year_sort, label, era, color, km2, years_ago} + a
//                  colour bar, narrative eras, landmark flows, and volcano colours
//
// The slider is an ordinal threshold: pixels whose ordinal <= threshold are
// shown; nothing "un-erupts" as it rises. Playback advances a nonlinear clock so
// the deep past flies by and the historic era gets real screen time.

const $ = (id) => document.getElementById(id);
const els = {
  canvas: $("map"), slider: $("slider"), play: $("play"), speed: $("speed"),
  loop: $("loop"), caption: $("caption"), frontier: $("frontier"), area: $("area"),
  readout: $("readout"), credit: $("credit"), stage: $("stage"),
  modes: $("modes"), legendVolcano: $("legend-volcano"), colorbar: $("colorbar"),
  ticks: $("colorbar-ticks"), landmarks: $("landmarks"),
};
const ctx = els.canvas.getContext("2d", { willReadFrequently: false });

const LAVA_ALPHA = 0.82;      // flows tint the relief but let terrain show through
const PLAY_SECONDS = 30;      // full sweep at 1× speed
const SPOT = [255, 250, 205]; // landmark spotlight colour (bright warm white)

let meta, W, H, N, timeline, now;
let ordinals, volcanoIds;     // per-pixel: Uint16 ordinal (0=none), Uint8 volcano
let baseBuf, lavaAge, lavaVol; // Uint8ClampedArray(W*H*4)
let frame;
let cumDwell, cumKm2, totalDwell, landmarkOrds, lmPixels, volShare;
let mode = "age", spotOrd = 0, threshold = 1;
let playing = false, rafId = null, lastT = 0, clock = 0;

function loadImage(src) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = () => rej(new Error("failed to load " + src));
    img.src = src;
  });
}
function imageData(img) {
  const c = document.createElement("canvas");
  c.width = img.width; c.height = img.height;
  const cx = c.getContext("2d", { willReadFrequently: true });
  cx.drawImage(img, 0, 0);
  return cx.getImageData(0, 0, img.width, img.height).data;
}

async function init() {
  meta = await (await fetch("../data/lava-flow-history/timeline.json")).json();
  W = meta.width; H = meta.height; N = meta.n_eras; now = meta.now;
  timeline = meta.timeline;
  els.credit.textContent = "Data — " + meta.credit;

  const [hillImg, flowImg] = await Promise.all([
    loadImage("../data/lava-flow-history/hillshade.png"), loadImage("../data/lava-flow-history/flow_age.png"),
  ]);
  const hs = imageData(hillImg), fa = imageData(flowImg);

  els.canvas.width = W; els.canvas.height = H;
  frame = ctx.createImageData(W, H);

  // Colour lookup tables (age ramp per ordinal; volcano colour per id).
  const ageLut = new Uint8Array((N + 1) * 3);
  for (const e of timeline) {
    ageLut[e.ordinal * 3] = e.color[0];
    ageLut[e.ordinal * 3 + 1] = e.color[1];
    ageLut[e.ordinal * 3 + 2] = e.color[2];
  }
  const volLut = new Uint8Array(6 * 3);
  for (const [id, v] of Object.entries(meta.volcanoes)) {
    volLut[id * 3] = v.color[0]; volLut[id * 3 + 1] = v.color[1]; volLut[id * 3 + 2] = v.color[2];
  }

  // Precompute relief + both tinted lava layers once; animating is just choosing.
  const px = W * H;
  ordinals = new Uint16Array(px);
  volcanoIds = new Uint8Array(px);
  baseBuf = new Uint8ClampedArray(px * 4);
  lavaAge = new Uint8ClampedArray(px * 4);
  lavaVol = new Uint8ClampedArray(px * 4);
  const a = LAVA_ALPHA, ia = 1 - a;
  for (let i = 0, j = 0; i < px; i++, j += 4) {
    const g = hs[j];
    baseBuf[j] = g; baseBuf[j + 1] = g; baseBuf[j + 2] = g; baseBuf[j + 3] = 255;
    const ord = (fa[j] << 8) | fa[j + 1];
    lavaAge[j + 3] = lavaVol[j + 3] = 255;
    if (fa[j + 3] > 0 && ord > 0) {
      ordinals[i] = ord;
      const vid = fa[j + 2]; volcanoIds[i] = vid;
      const ka = ord * 3, kv = vid * 3;
      lavaAge[j] = ageLut[ka] * a + g * ia;
      lavaAge[j + 1] = ageLut[ka + 1] * a + g * ia;
      lavaAge[j + 2] = ageLut[ka + 2] * a + g * ia;
      lavaVol[j] = volLut[kv] * a + g * ia;
      lavaVol[j + 1] = volLut[kv + 1] * a + g * ia;
      lavaVol[j + 2] = volLut[kv + 2] * a + g * ia;
    } else {
      lavaAge[j] = lavaVol[j] = g;
      lavaAge[j + 1] = lavaVol[j + 1] = g;
      lavaAge[j + 2] = lavaVol[j + 2] = g;
    }
  }

  buildPacing();
  buildLegend();
  buildLandmarks();
  wire();
  els.slider.max = String(N);
  setThreshold(N);   // show the finished island on load; Play rewinds to the start
  applyHash();       // optional deep-link: #mode=volcano&t=60&lm=1984
}

function applyHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get("mode") === "volcano") setMode("volcano");
  if (h.has("lm")) {
    const lm = meta.landmarks.find((l) => timeline[l.ordinal - 1].year_sort === +h.get("lm"));
    if (lm) selectLandmark(lm.ordinal);
  }
  if (h.has("t")) setThreshold(+h.get("t"));
  if (h.get("autoplay")) play();
  if (h.has("hover")) {   // #hover=col,row — drive the real tooltip for testing
    const [ix, iy] = h.get("hover").split(",").map(Number);
    const r = els.canvas.getBoundingClientRect();
    const scale = Math.min(r.width / W, r.height / H);
    const offX = (r.width - W * scale) / 2, offY = (r.height - H * scale) / 2;
    els.canvas.dispatchEvent(new MouseEvent("mousemove", {
      clientX: r.left + offX + (ix + 0.5) * scale,
      clientY: r.top + offY + (iy + 0.5) * scale, bubbles: true }));
  }
}

// --- pacing: dwell weight per ordinal so play is nonlinear in real time -------
function buildPacing() {
  landmarkOrds = new Set(meta.landmarks.map((l) => l.ordinal));
  cumDwell = new Float64Array(N + 1);
  cumKm2 = new Float64Array(N + 1);
  for (let k = 1; k <= N; k++) {
    const e = timeline[k - 1];
    let w = e.year_sort >= 1790 ? 1.7 : 0.5;   // linger in the historic era
    if (landmarkOrds.has(k)) w += 2.6;         // and pause on the famous flows
    cumDwell[k] = cumDwell[k - 1] + w;
    cumKm2[k] = cumKm2[k - 1] + e.km2;
  }
  totalDwell = cumDwell[N];

  // Share of the island's mapped lava surface per volcano, from the pixels
  // themselves (the flow-age raster is already "youngest flow wins").
  const volCounts = new Uint32Array(6);
  let lavaPx = 0;
  for (let i = 0; i < ordinals.length; i++) {
    if (ordinals[i] > 0) { lavaPx++; volCounts[volcanoIds[i]]++; }
  }
  volShare = {};
  for (let id = 1; id <= 5; id++) volShare[id] = volCounts[id] / lavaPx;

  // Landmark pixel lists, for the spotlight overlay.
  lmPixels = new Map();
  for (const o of landmarkOrds) lmPixels.set(o, []);
  for (let i = 0; i < ordinals.length; i++) {
    const o = ordinals[i];
    if (o && landmarkOrds.has(o)) lmPixels.get(o).push(i);
  }
}
function ordinalAtClock(c) {          // largest k with cumDwell[k] <= c
  let lo = 1, hi = N, ans = 1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (cumDwell[m] <= c) { ans = m; lo = m + 1; } else hi = m - 1;
  }
  return ans;
}

// --- rendering ----------------------------------------------------------------
function setThreshold(t) { threshold = Math.max(1, Math.min(N, Math.round(t))); render(); }

function render() {
  const out = frame.data, px = W * H, lava = mode === "age" ? lavaAge : lavaVol;
  for (let i = 0, j = 0; i < px; i++, j += 4) {
    const src = (ordinals[i] > 0 && ordinals[i] <= threshold) ? lava : baseBuf;
    out[j] = src[j]; out[j + 1] = src[j + 1]; out[j + 2] = src[j + 2]; out[j + 3] = 255;
  }
  if (spotOrd && spotOrd <= threshold) {
    for (const idx of lmPixels.get(spotOrd)) {
      const j = idx * 4; out[j] = SPOT[0]; out[j + 1] = SPOT[1]; out[j + 2] = SPOT[2];
    }
  }
  ctx.putImageData(frame, 0, 0);
  els.slider.value = String(threshold);
  updateHud();
}

function updateHud() {
  const e = timeline[threshold - 1];
  els.frontier.innerHTML = `Revealed to <b>${yearLabel(e)}</b> · ${eraName(e.years_ago)}`;
  const km2 = cumKm2[threshold], pct = 100 * km2 / cumKm2[N];
  els.area.innerHTML =
    `<b>${Math.round(km2).toLocaleString()}</b> km² resurfaced · ${pct.toFixed(0)}% of mapped lava`;
  if (spotOrd) {
    const lm = meta.landmarks.find((l) => l.ordinal === spotOrd);
    els.caption.innerHTML = `★ <b>${lm.name}</b> — ${lm.blurb}`;
  } else if (mode === "volcano") {
    const top = Object.entries(volShare).sort((a, b) => b[1] - a[1])[0];
    els.caption.innerHTML = `Five shield volcanoes built the island — ` +
      `<b>${meta.volcanoes[top[0]].name}</b> alone paved ${Math.round(top[1] * 100)}% of its surface.`;
  } else {
    els.caption.textContent = eraCaption(e.years_ago);
  }
}

function yearLabel(e) {
  return e.year_sort >= 1790 ? `A.D. ${e.year_sort}` : `≈ ${fmtAgo(e.years_ago)} ago`;
}
function fmtAgo(y) {
  const step = y >= 100000 ? 10000 : y >= 10000 ? 1000 : y >= 1000 ? 100 : y >= 100 ? 10 : 1;
  return `${(Math.round(y / step) * step).toLocaleString()} yr`;
}
function eraFor(yearsAgo) {
  return meta.eras.find((b) => yearsAgo <= b.max_ago && yearsAgo > b.min_ago) || meta.eras[0];
}
function eraName(yearsAgo) { return eraFor(yearsAgo).name; }
function eraCaption(yearsAgo) { return eraFor(yearsAgo).caption; }

// --- playback -----------------------------------------------------------------
function togglePlay() { playing ? pause() : play(); }
function play() {
  spotOrd = 0; syncLandmarkChips();
  if (threshold >= N) { clock = 0; setThreshold(1); }
  else clock = cumDwell[threshold];
  playing = true; els.play.textContent = "❚❚";
  lastT = performance.now();
  const step = (nowT) => {
    if (!playing) return;
    const speed = parseFloat(els.speed.value);
    clock += (nowT - lastT) / 1000 * (totalDwell / PLAY_SECONDS) * speed;
    lastT = nowT;
    if (clock >= totalDwell) {
      setThreshold(N);
      if (els.loop.getAttribute("aria-pressed") === "true") { clock = 0; setThreshold(1); }
      else { pause(); return; }
    } else setThreshold(ordinalAtClock(clock));
    rafId = requestAnimationFrame(step);
  };
  rafId = requestAnimationFrame(step);
}
function pause() {
  playing = false; els.play.textContent = "▶";
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
}

// --- hover --------------------------------------------------------------------
function canvasPixelAt(ev) {
  const r = els.canvas.getBoundingClientRect();
  const scale = Math.min(r.width / W, r.height / H);   // object-fit: contain
  const offX = (r.width - W * scale) / 2, offY = (r.height - H * scale) / 2;
  const x = Math.floor((ev.clientX - r.left - offX) / scale);
  const y = Math.floor((ev.clientY - r.top - offY) / scale);
  return (x < 0 || y < 0 || x >= W || y >= H) ? null : { x, y, r };
}
function onHover(ev) {
  const p = canvasPixelAt(ev);
  if (!p) { els.readout.hidden = true; return; }
  const i = p.y * W + p.x, ord = ordinals[i];
  if (ord === 0 || ord > threshold) { els.readout.hidden = true; return; }
  const e = timeline[ord - 1], v = meta.volcanoes[volcanoIds[i]] || { name: "—", rock: "" };
  const age = e.year_sort >= 1790
    ? `${yearLabel(e)} · ${fmtAgo(e.years_ago)} ago` : e.label;
  els.readout.hidden = false;
  els.readout.innerHTML =
    `<span class="v">${v.name}</span> <span class="r">${v.rock}</span><br>` +
    `<span class="a">${age}</span>`;
  const sr = els.stage.getBoundingClientRect();
  els.readout.style.left = (ev.clientX - sr.left) + "px";
  els.readout.style.top = (ev.clientY - sr.top) + "px";
}

// --- legend + landmarks + wiring ---------------------------------------------
function buildLegend() {
  const stops = meta.colorbar.stops
    .map((s) => `rgb(${s.color[0]},${s.color[1]},${s.color[2]}) ${(s.t * 100).toFixed(1)}%`);
  els.colorbar.style.background = `linear-gradient(to right, ${stops.join(",")})`;
  els.ticks.innerHTML = "";
  for (const tk of meta.colorbar.ticks) {
    const d = document.createElement("div");
    d.className = "tick"; d.style.left = (tk.t * 100) + "%"; d.textContent = tk.label;
    // Keep the end ticks from spilling past the bar.
    if (tk.t <= 0.05) d.style.transform = "translateX(0)";
    else if (tk.t >= 0.95) d.style.transform = "translateX(-100%)";
    els.ticks.appendChild(d);
  }
  // hide any tick label that would collide with its left neighbour
  const boxes = [...els.ticks.children]
    .map((d) => ({ d, r: d.getBoundingClientRect() }))
    .sort((a, b) => a.r.left - b.r.left);
  let lastRight = -Infinity;
  for (const { d, r } of boxes) {
    if (r.left < lastRight + 4) { d.style.visibility = "hidden"; continue; }
    lastRight = r.right;
  }
  els.legendVolcano.innerHTML = "";
  for (const [id, v] of Object.entries(meta.volcanoes)) {
    const row = document.createElement("div"); row.className = "row";
    const sw = document.createElement("span"); sw.className = "sw";
    sw.style.background = `rgb(${v.color[0]},${v.color[1]},${v.color[2]})`;
    const t = document.createElement("span");
    t.innerHTML = `${v.name} <span class="rock">${v.rock}</span>`;
    const pct = document.createElement("span");
    pct.className = "share";
    pct.textContent = Math.round(volShare[id] * 100) + "%";
    pct.title = "share of the island's mapped lava surface";
    row.append(sw, t, pct); els.legendVolcano.appendChild(row);
  }
}
function buildLandmarks() {
  els.landmarks.innerHTML = "";
  for (const lm of meta.landmarks) {
    const b = document.createElement("button");
    b.textContent = lm.name; b.dataset.ord = lm.ordinal;
    b.addEventListener("click", () => selectLandmark(lm.ordinal));
    els.landmarks.appendChild(b);
  }
}
function selectLandmark(ord) {
  pause();
  spotOrd = (spotOrd === ord) ? 0 : ord;
  if (spotOrd) setThreshold(ord); else render();
  syncLandmarkChips();
}
function syncLandmarkChips() {
  for (const b of els.landmarks.children)
    b.classList.toggle("on", +b.dataset.ord === spotOrd);
}
function setMode(m) {
  mode = m;
  for (const b of els.modes.children) b.classList.toggle("on", b.dataset.mode === m);
  $("legend-age").hidden = m !== "age";
  els.legendVolcano.hidden = m !== "volcano";
  render();
}
function jump(kind) {
  pause(); spotOrd = 0; syncLandmarkChips();
  if (kind === "oldest") setThreshold(N);
  else if (kind === "historic") setThreshold(firstOrdinal((e) => e.year_sort >= 1790));
  else if (kind === "1000") setThreshold(firstOrdinal((e) => e.years_ago <= 1000));
}
function firstOrdinal(pred) {
  for (const e of timeline) if (pred(e)) return e.ordinal;
  return N;
}
function wire() {
  els.play.addEventListener("click", togglePlay);
  els.slider.addEventListener("input", () => {
    pause(); spotOrd = 0; syncLandmarkChips(); setThreshold(+els.slider.value);
  });
  els.loop.addEventListener("click", () => {
    const on = els.loop.getAttribute("aria-pressed") === "true";
    els.loop.setAttribute("aria-pressed", String(!on));
  });
  for (const b of els.modes.children) b.addEventListener("click", () => setMode(b.dataset.mode));
  for (const b of document.querySelectorAll("#jumps [data-jump]"))
    b.addEventListener("click", () => jump(b.dataset.jump));
  els.canvas.addEventListener("mousemove", onHover);
  els.canvas.addEventListener("mouseleave", () => (els.readout.hidden = true));
}

init().catch((e) => {
  els.credit.textContent = "error: " + e.message;
  console.error(e);
});
