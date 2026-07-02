# QA — Reef Heat Atlas

Verification evidence for each build phase. Sections below Phase 0 are appended
by the scripts as their verification gates run (`download.py`, `compute_dhw.py`,
`verify_crw.py`). A full clean pipeline run regenerates them in order.

## Phase 0 — data discovery

Endpoint discovered by probing the CoastWatch ERDDAP entry point
`coastwatch.pfeg.noaa.gov/erddap/griddap/NOAA_DHW`, which 302-redirects to the
PacIOOS (University of Hawaii) ERDDAP `dhw_5km` — the Hawaii-local mirror of the
NOAA CRW CoralTemp 5 km daily product. Verified it returns cropped NetCDF.

- Grid (one day, 2019-09-15): 101 × 151, lat 18.025..23.025, lon −161.475..−153.975
- SST min/mean/max: 27.31 / 27.99 / 28.70 °C (plausible for Hawaii, Sept)
- Derived MMM (= SST − HotSpot): 26.10..27.68 °C, within observed SST range
- Checks passed: `15 < mean < 30`, crop brackets the main islands

Key finding: CRW publishes `CRW_HOTSPOT` **unclamped** (negative on cool days),
so `MMM = SST − HotSpot` recovers CRW's exact official MMM climatology from any
single day. Confirmed time-invariant (cross-day spread 0.0000 °C over 6 sampled
days), so we use it directly rather than recomputing a baseline.

## Phase 1 — download coverage

Source: NOAA Coral Reef Watch CoralTemp 5km daily (PacIOOS ERDDAP: dhw_5km)  
Coverage: 1985-04-01 .. 2026-06-29  
Expected days: 15065, downloaded: 15058, missing: 7.

Missing dates:
- 1996-04-03
- 2024-01-30
- 2024-07-04
- 2024-07-05
- 2024-07-06
- 2024-07-25
- 2026-04-25

## Phase 2 — max DHW per year (degC-weeks)

Weekly frames stored: 2153 from 15058 daily steps. DHW range 0.00..14.58; SST range 20.84..29.78.

| year | max DHW |
|------|---------|
| 1985 | 0.16 |
| 1986 | 1.57 |
| 1987 | 1.47 |
| 1988 | 0.62 |
| 1989 | 0.31 |
| 1990 | 0.17 |
| 1991 | 0.45 |
| 1992 | 1.67 |
| 1993 | 1.57 |
| 1994 | 0.30 |
| 1995 | 0.00 |
| 1996 | 5.76 |
| 1997 | 1.14 |
| 1998 | 0.00 |
| 1999 | 0.00 |
| 2000 | 0.00 |
| 2001 | 0.00 |
| 2002 | 0.15 |
| 2003 | 0.61 |
| 2004 | 4.31 |
| 2005 | 0.66 |
| 2006 | 0.61 |
| 2007 | 0.44 |
| 2008 | 0.00 |
| 2009 | 0.34 |
| 2010 | 0.34 |
| 2011 | 0.00 |
| 2012 | 0.00 |
| 2013 | 0.00 |
| 2014 | 8.94 |
| 2015 | 14.00 |
| 2016 | 2.66 |
| 2017 | 5.43 |
| 2018 | 1.20 |
| 2019 | 14.58 |
| 2020 | 8.32 |
| 2021 | 3.04 |
| 2022 | 2.23 |
| 2023 | 1.95 |
| 2024 | 0.00 |
| 2025 | 2.78 |
| 2026 | 1.29 |

## CRW cross-check (our DHW vs published CRW_DHW)

| frame | our max | CRW max | RMSE | max diff |
|-------|---------|---------|------|----------|
| 2015-09-28 | 12.54 | 12.54 | 0.003 | 0.004 |
| 2019-09-16 | 8.09 | 8.09 | 0.003 | 0.004 |
| 2023-08-14 | 0.00 | 0.00 | 0.000 | 0.000 |

## Phase 3 — web payload

Colour-in-the-browser design: ship scaled integer grids, not pre-rendered tiles.

- `sst.i16` Int16 (degC × 20, 0.05 °C), sentinel −32768 = no data — 65.7 MB
- `dhw.u8` UInt8 (degC-weeks × 10, 0.1) — 32.8 MB; total payload 98.5 MB
- `mask.u8` static water mask, `coast.json` 246 island-edge segments
- `manifest.json` grid edges, dates, scales, thresholds, per-year max DHW
- Frames: 2153 (weekly). Round-trip of a mid-record frame: SST error ≤ 0.020 °C,
  DHW error 0.000 — within quantisation. Every manifest date has a stored frame.

## Phase 4 — front end

Rendered and driven headlessly (Chrome via the DevTools Protocol against a live
`python -m http.server`):

- SST layer renders; islands are correctly placed and oriented (Big Island SE,
  Kaua'i / Ni'ihau NW) — see `docs/sst.png`.
- Layer toggle to DHW works; scrubbing the slider to 2015-09-28 updates the frame
  and the DHW field shows the severe 2015 heat stress — see `docs/dhw.png`.
- Hover readout at 21.52°N 159.73°W returned SST 28.00 °C, DHW 6.1 °C-wk,
  "Significant bleaching likely" — **matching an independent decode of the binary
  payload exactly** (SST 28.00, DHW 6.1).
- `scripts/verify_web.py` re-checks several reef points across three frames: max
  decode error vs source SST 0.020 °C, DHW 0.046 °C-weeks; orientation, scaling,
  and endianness all consistent.

## Phase 5 — skeptical self-review

Re-read every script and the front end; ran all self-checks and gates.

Findings and fixes:

1. **Unused dependencies claimed.** `scipy` and `pillow` were in the install
   line but never imported (the browser colours the grids, so no server-side
   PIL; DHW math is plain numpy). *Fix:* install line trimmed to the four used
   deps, with a note explaining why the other two are unused.
2. **README run order missing the Phase 4 gate.** `verify_web.py` wasn't listed.
   *Fix:* added as step 7, and to the repo-layout listing.
3. **Broken placeholder image** in the README. *Fix:* replaced with two real
   screenshots committed under `docs/`.
4. **Latitude orientation** (found during Phase 3): the processed grid is stored
   north-first (negative lat step). The first front-end draft assumed ascending
   latitude and would have rendered the islands upside-down. *Fix:* `build_web.py`
   normalises orientation to row 0 = north / col 0 = west and emits explicit
   cell-edge bounds; `app.js` uses those directly with no flips. Confirmed
   correct by the rendered screenshots and the hover cross-check.
5. **DHW float drift** (found during Phase 2): the rolling-window running sum
   left values like −0.0000 on calm pixels. *Fix:* clamp DHW output to ≥ 0
   (definitionally non-negative). Cross-check vs CRW then agrees to RMSE 0.003.

Checks re-run clean: `common.py` self-check, `verify_web.py`, all scripts compile,
`app.js` parses, and every file the README references exists.

## Phase 4 — pixel-art overhaul (readability pass)

Reworked the front end into a consistent 5 km pixel instrument and re-verified
headlessly (Chrome DevTools Protocol against a live server); screenshots in
`docs/` and the scratchpad.

Confirmed against the stated checklist:

- **(a) Crisp discrete pixel blocks.** `imageSmoothingEnabled = false` + nearest-
  neighbour upscaling; a zoomed crop shows flat 5 km squares with hard edges and
  no interpolation. Values quantise to discrete colour bands (stepped, not
  continuous). `BLOCK` config exposes a chunkiness factor (default 1 = one 5 km cell).
- **(b) Legend matches.** The legend renders the same discrete swatches as the map
  for all three layers, with 4 and 8 marked on DHW.
- **(c) SST shows structure.** Domain tightened to the regional 2–98th percentile
  ([23, 28] °C), so stepped spatial bands are visible instead of one flat colour.
  Added an SST-anomaly layer (SST − per-pixel day-of-year mean, diverging scale).
- **(d) DHW readable.** Zero is a calm teal (not black), the low end is sensitive
  (distinct bands at 1/2/3/4), 4 and 8 are discrete steps, with an explanatory
  caption. Verified on a calm frame (2013-03-11) — the whole ocean reads as safe.
- **(e) Consistent land.** Neutral gray blocky landmass + crisp coastline, identical
  in every view, distinct from all data colours.
- **(f) No orphan pixel.** `build_web.remove_specks` reclassified 1 isolated land
  speck (infilled from neighbours); coastline dropped from 246 to 242 segments.
- **(g) Orientation aids.** Island labels, 100 km scale bar, north arrow, slider
  date-range labels, a large current-date readout, and a "each pixel = one 5 km
  ocean cell" note.

Interactive re-check: layer toggle and slider scrub work; the hover readout on a
2015-09-28 reef cell (SST 28.45 °C, anomaly +1.11 °C, DHW 9.8 °C-wk, "severe")
matched an independent decode of the binary payload exactly. `verify_web.py`,
`common.py`, and all `py_compile`/`node --check` gates still pass; the black side
margins are gone (the framed map is sized to the data aspect and centred).
