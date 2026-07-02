# QA log — Ahupuaʻa Watershed Mapper

Verification results per phase, plus the honest self-review at the end. Every
gate below is enforced by `assert`s in the named script, not just eyeballed.

## Phase 0 — source discovery (`scripts/discover_source.py`)

**VERIFICATION: phase 0 — PASS**

Island: **Oʻahu** (`mokupuni='Oʻahu'`, ʻokina U+02BB).

- Ahupuaʻa layer: State of Hawaiʻi Statewide GIS, `HistoricCultural/MapServer/1`.
  - Native CRS wkid 3750 (NAD83(HARN) / UTM 4N); queried in WGS84.
  - Attributes present: `ahupuaa`, `moku`, `mokupuni` (+ gisacres, other, ids).
  - **98** ahupuaʻa on Oʻahu across 6 moku (Kona, Koʻolauloa, Koʻolaupoko,
    Waialua, Waiʻanae, ʻEwa). Names round-trip with diacritics intact
    (ʻŌiʻo, Hanakaʻoe, …). No `�` replacement chars.
- DEM: USGS 3DEP 1/3″ (~10 m) tiles `n22w159`, `n22w158`, derived from the
  layer extent (not hardcoded) and HEAD-verified. CRS 4269, res 0.33″, union
  bounds lon[-159,-157] lat[21,22] fully contain the Oʻahu extent
  lon[-158.28,-157.64] lat[21.25,21.71].

Asserts: >1 feature; ʻokina/macron present in names; expected attributes exist;
DEM union covers the island extent; resolution ≈ 1/3″.

## Phase 1 — download + align (`scripts/download.py`)

**VERIFICATION: phase 1 — PASS**

- Downloaded the 98 Oʻahu ahupuaʻa (WGS84 GeoJSON) and the two 3DEP tiles
  (resumable HTTP-Range), mosaicked + clipped to the island bbox + 2 km margin.
- Reprojected both to **EPSG:32604** (UTM 4N): DEM 7056×5590 @ 10.0 m; boundaries
  98 features, same CRS.
- Asserts: outputs exist and are non-empty; DEM CRS == vector CRS == 32604;
  DEM resolution ≈ 10 m; vector extent lies within the DEM extent (5 m tol);
  names still UTF-8 clean after the reprojection round-trip.

## Phase 2 — flow routing (`scripts/flow.py`)

**VERIFICATION: phase 2 — PASS**

- Grid: 7056x5590 @ 10 m, 15,609,895 land cells.
- Accumulation min on land = 1 (>=1: every cell drains itself).
- High-accum (top 0.01%) mean elev 16.0 m vs land median 179.7 m; max-accum cell at 0.0 m (a coastal mouth).
- Ridgetops (top 5% elev) median accumulation 3.0 cells.
- Stream network: 1717 branches, **3871.2 km** total at threshold 5000 cells (~0.50 km²).
- Basins: 53317 coastal outlets (224 with area ≥ 0.5 km²); the tail is single-cell coastal drainages, expected on a 10 m coastline.

## Phase 5 — skeptical self-review

**VERIFICATION: phase 5 — PASS**

Re-ran the whole pipeline end to end from disk state (proving resumability): all
five `VERIFICATION: phase N` gates pass. Confirmed every file the README names
exists; `app.js` passes `node --check`. Place-name integrity across the exported
GeoJSON: 98 features, **0** `�` replacement characters; the ʻokina is **U+02BB**
(modifier letter turned comma, the correct Hawaiian character) and macrons are
real `LATIN … WITH MACRON` code points — not apostrophes or curly quotes.

An independent read of all six scripts raised the issues below; disposition:

*Fixed*
- **DEM nodata could be dropped**, making the ocean mask (`== nodata`) silently
  fail on a DEM without a nodata value. `reproject_dem` now sets nodata and passes
  `src/dst_nodata`; `condition_and_route` guards `nodata is None`.
- **Non-atomic raster writes.** An interrupted write left a truncated `.tif` that
  the `size > 0` resume check would trust. All raster writes now go to a `.tmp`
  and `os.replace` into place (atomic), so a killed write can't pass as complete.
- **Resume corruption if a server ignored `Range`** (200 vs 206): `download_file`
  now detects a full-body response to a range request and overwrites instead of
  appending.
- **Weak "peaks in valleys" assert.** `peak_elev < land_median` is near-guaranteed
  by geography; tightened to `peak_elev < 25th-percentile land elevation`
  (16.0 m < 33.5 m), which a scrambled routing would fail.
- **Misleading convergence assert.** The basin path-doubling now tracks a real
  `converged` flag and fails if it doesn't reach a fixpoint within 64 rounds.
- **Coastline hillshade** was shaded against a false 0 m sea wall at cliff coasts;
  ocean is now filled by nearest-land elevation before the gradient.
- Tidied a leaked file handle in the DEM mosaic (merge now opens tiles itself).

*Considered, kept by design (documented)*
- The basin count is dominated by single-cell coastal drainages — inherent to
  delineating a 10 m coastline without pour-point snapping. Only basins ≥ 0.5 km²
  are drawn and used in the ahupuaʻa comparison; the raw count is reported honestly.

*Open, low risk*
- A socket that trickles bytes below the 120 s read timeout could stall an
  unattended run; the retry/backoff adapter covers dropped connections but not a
  slow-loris server. Acceptable for these two well-behaved public hosts.

## Phase 3 — web export (`scripts/export_web.py`)

**VERIFICATION: phase 3 — PASS**

- Payload in `web/data/oahu/`: base.png + basins.png at 2200×1743, basins.geojson (224 polygons), streams.geojson (1368 branches), ahupuaa.geojson (98 features), meta.json.
- All 5 layers named in meta.json exist; every basin referenced by an ahupuaʻa has a matching polygon.
- Accumulation raster round-trips; ahupuaʻa names survive UTF-8 clean.
- Concordance: 28/98 ahupuaʻa track a single computed watershed for ≥75% of their area; the rest is the interesting divergence.
- Manifest: islands available = Oʻahu.

## Phase 4 — front end (`web/`, checked by `verify_web.py`)

**VERIFICATION: phase 4 — PASS**

- Hover hit-test (app.js ray-casting on the exported geojson) returns the correct ahupuaʻa for all 6 spot-checked locations: Waikīkī, Honolulu, Kāneʻohe, Kailua, Hālawa, Waiʻanae.
- Boundaries drawn with a dark halo under a light line, legible over terrain + basins at full opacity.
- Match view: every ahupuaʻa carries `dom_frac`/`dom_basin`/`basin_ids`, coloured green→yellow→red by how well it matches one computed watershed; pinned basins resolve to polygons in basins.geojson for the overlap view.
- Orientation data present: 6 moku labels, 32.1 m/px for the scale bar; north is up (UTM).
- Island switcher wired from manifest.json; toggles, opacity, search, and the biggest-mismatches list run in app.js. Names UTF-8 clean.
