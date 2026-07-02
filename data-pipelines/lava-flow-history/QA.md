# QA — Lava Flow History Map

Verification notes for each phase. Gates are hard `assert`s in the scripts; this
file records what was checked and the numbers behind it.

## Data-source discovery

* Flow polygons: USGS DS-144 `bimpgeo` coverage — 6,836 label points / ~6,745
  polygon faces, CRS EPSG:26905 (NAD83 / UTM 5N). Age fields `YEAR1`/`YEAR2`
  (calendar A.D.) present for historically dated flows; prehistoric flows dated
  by map-unit code via the published legend (`scripts/config.py:PTYPE_AGE`).
* Unit-code → age legend spot-checked against the values actually in the data:
  all observed `UNITS`↔`LABEL` pairs (211=k3, 212=k2, 106=p5, 108=p3, 113=p4y,
  114=p4o, 210=k4, 217=k1y, 218=k1o) match the DS-144 explanation.
* DEM: USGS 3DEP 1 arc-second, six tiles (n19–n21 / w155–w157); union extent
  covers the island bounding box; two SE/NE ocean tiles are absent (expected).
* Recent eruptions (post-DS-144): four USGS ScienceBase releases, each fetched
  and verified, reduced to their final cumulative flow footprint and stamped with
  a year — June 27th flow **26.8 km² → 2016**, Puʻuʻōʻō ep 61g **9.6 km² → 2017**,
  2018 lower East Rift Zone **35.7 km² → 2018**, Mauna Loa 2022 **36.1 km² → 2022**.
  Final flow layer: **5,569 polygons**, `year_sort` −473,050 … 2022.

## Known issue: ArcInfo PAL layer

GDAL's AVCE00 driver cannot assemble the polygon (`PAL`) layer of `bimpgeo.e00`
in bounded time (`ogrinfo -so PAL` and `pyogrio.read_dataframe(layer='PAL')` both
run for minutes without returning). Worked around by rebuilding polygons from the
arc network: `polygonize(ARC)` (fast) + spatial-join of the `LAB` label points
(which carry the attributes). 6,713 / 6,745 faces matched a label (99.5%);
unlabelled ocean/sliver faces are dropped.


## Phase 2 — flow-age raster year histogram

Grid 75 m/pixel; each pixel = 0.0056 km^2. Area is the youngest flow at each pixel (younger buries older).

| Era | pixels | area (km^2) |
| --- | ---: | ---: |
| 250,000-700,000 yr B.P. | 56,575 | 318.23 |
| 100,000-300,000 yr B.P. | 1,759 | 9.89 |
| 120,000-230,000 yr B.P. | 43,836 | 246.58 |
| 65,000-250,000 yr B.P. | 162,377 | 913.37 |
| ~100,000 yr B.P. | 1,192 | 6.71 |
| >30,000 yr B.P. | 488 | 2.75 |
| 14,000-65,000 yr B.P. | 208,812 | 1,174.57 |
| >10,000 yr B.P. | 29,405 | 165.40 |
| 4,000-14,000 yr B.P. | 27,314 | 153.64 |
| 5,000-10,000 yr B.P. | 96,105 | 540.59 |
| 3,000-10,000 yr B.P. | 3,955 | 22.25 |
| 3,000-5,000 yr B.P. | 114,865 | 646.12 |
| 1,500-3,000 yr B.P. | 275,281 | 1,548.46 |
| 750-1,500 yr B.P. | 288,717 | 1,624.03 |
| 400-750 yr B.P. | 69,036 | 388.33 |
| 200-750 yr B.P. | 179,045 | 1,007.13 |
| 200-400 yr B.P. | 17,714 | 99.64 |
| Historic (A.D. 1790 or younger) | 193,442 | 1,088.11 |
## Phase 2 — spot-checks (gate 2)

Raster year range −473,050 … 2022 matches the polygon layer exactly. The two
named young flows read back at their own coordinates, confirming "youngest wins":

* 2018 Kīlauea LERZ (−154.833, 19.477) → **2018**
* 2022 Mauna Loa NE Rift (−155.598, 19.458) → **2022**

The Historic bucket in the histogram above includes the four merged recent
eruptions (2016–2022); where a recent flow overlaps older mapped lava it wins, so
a few thousand pixels sit in Historic that a DS-144-only build left in the older
Puna/Kaʻū buckets. A second band, `volcano.tif` (1=Kīlauea … 5=Kohala, burned in
the same youngest-wins order), is asserted to cover exactly the same pixels.

## Phase 3 & 4 — payload + front-end verification

* **Ordinal timeline.** 73 distinct time steps, ordinals contiguous 1…73,
  `year_sort` strictly increasing (oldest −473,050 → youngest 2022). The recent
  eruptions occupy the four newest ordinals: 2016→70, 2017→71, 2018→72, 2022→73.
* **PNG round-trip.** `flow_age.png` decodes (`R<<8 | G`) to ordinals 1…73, every
  value present in `timeline.json`; 6,418 px of 2022 survive encode/decode; the
  **B** channel carries volcano ids 1…5 over exactly the lava mask.
* **Served & rendered.** `python -m http.server -d web` returns 200 for every
  file; headless Chrome screenshots at 1440×900 confirm the initial (unscrolled)
  view shows Play + slider + jumps + landmarks with **no scrolling**.
* **Playback.** Screenshots at start / mid / end confirm the frontier readout is
  monotonic ("Revealed to A.D. 1979" → "A.D. 2022"), the km² counter ticks up,
  and the reveal is additive (nothing un-erupts). Pacing spends ~2 s on the
  ancient shields and ~28 s on the historic era.
* **Legend.** The Age view is a single ordered colour bar (475k yr → 2022, four
  ticks); the Volcano view lists the five shields — no more overlapping bins.
* **Hover.** Over the 2018 flow the tooltip reads "Kīlauea · Puna Basalt · A.D.
  2018 · 8 yr ago"; the pixel→ordinal→label→volcano lookup matches the source.
* **Landmarks.** Selecting "1984 Mauna Loa" spotlights that flow (bright overlay)
  and captions its story; all seven landmark years resolve to real ordinals.