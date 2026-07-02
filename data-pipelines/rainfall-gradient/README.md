# Rainfall Gradient Explorer: data pipeline

Builds the rainfall surfaces for the atlas map: monthly precipitation
interpolated from NOAA GHCN-Daily weather stations onto a regular grid,
per island, scrubbable month by month in the browser.

Hawaiʻi has one of the steepest rainfall gradients on Earth. Windward
mountain slopes can take in several meters of rain a year while a leeward
coast a few kilometers away stays near-desert, so a single number for
"Hawaiʻi rainfall" tells you almost nothing. The map exists to show the
gradient itself and how it moves through the seasons.

## Data source

- **NOAA GHCN-Daily** (Global Historical Climatology Network), distributed by
  NCEI as per-station fixed-width `.dly` files:
  - Station metadata: `https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt`
  - Per-station daily records: `https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{ID}.dly`
- Element used: **PRCP** (daily precipitation, tenths of a millimetre).
- Filtered to Hawaiʻi: `STATE == HI` and inside the island bounding box
  (lat 18.9–22.3 N, lon 160.3–154.8 W). 803 stations matched; 764 had usable
  precipitation records (the drop list is in `QA.md`).
- Record span in this build: **1899 to 2026**, 238,773 station-months.
- Coastline for masking and outlines: Natural Earth 10 m land, clipped and
  bundled with the web payload (about 15 KB, all eight main islands).

Daily values are aggregated to monthly station totals, excluding missing days
(`-9999`) and any day with a non-blank QC flag. A month needs at least 25
observed days to count, so a partially reported month cannot pass as a dry
one.

## Method: inverse-distance weighting

For each surface, station monthly totals are interpolated onto a regular
grid:

```
value(cell) = Σ wᵢ·vᵢ / Σ wᵢ ,   wᵢ = 1 / dᵢᵖ ,   p = 2
```

Two choices matter:

- **Per-island interpolation.** A cell is filled only from stations on its
  own island. The bounding box is mostly open ocean, and without this rule a
  cell on Oʻahu could be pulled toward a station cluster on Kauaʻi 150 km
  away. Islands with no qualifying stations in a month are left blank rather
  than guessed.
- **Distance in kilometres**, with a small floor so a cell sitting on a
  station takes that station's value.

A station contributes to a calendar month's climatology only if it has at
least 5 years of that month on record, which trims the noise from very short
volunteer records while keeping the dense spatial coverage. Surfaces built
from fewer than 15 stations are flagged `low_confidence` and badged in the
UI.

IDW keeps the stack dependency-light (numpy, scipy, requests, pillow; no
GDAL). Kriging is the natural upgrade: it would model spatial covariance
explicitly and give a per-cell uncertainty estimate, at the cost of a heavier
dependency and variogram fitting. The grid, masking, and web export would
carry over unchanged.

## Products

1. **Climatology**: 12 surfaces, one per calendar month, each averaged over
   all available years (a "typical year"). Grid about 0.02° (~2.2 km). This
   is the headline view.
2. **Time series**: monthly surfaces for the most recent 15 complete years
   (2011 to 2025 in this build), on a coarser 0.04° grid to keep the payload
   small.

Surfaces ship as `uint16` tenths-of-a-millimetre (nodata = 65535), which
halves the payload against float32 while resolving rainfall to 0.1 mm. The
browser colours them, so the scale can change live. Total payload: 5.4 MB.

## How confidence is handled

- Per-month station counts are stored; sparse months carry a badge in the UI.
- The hover readout names the nearest station and its distance, so a reader
  can judge how much a value is measured versus interpolated.
- Islands and months with no qualifying stations are left blank, never
  filled in.

## Running it end to end

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install numpy scipy requests pillow

python scripts/discover_source.py     # verify the source (fast)
python scripts/build_dataset.py       # download + aggregate (overnight-safe, resumable)
python scripts/interpolate.py         # IDW -> grids (resumable per surface)
python scripts/export_web.py          # pack the browser payload

cd ../.. && python3 -m http.server    # open http://localhost:8000/rainfall-gradient/
```

Every download and every interpolated surface is cached on disk and skipped
on re-run, so an interrupted overnight build restarts cleanly. To refresh the
record later, delete the newest `.dly` files and re-run `build_dataset.py`.

## Limitations

- **Mountain sparsity.** Stations cluster on the coasts and in valleys. The
  highest, wettest ridges are under-sampled, so peak rainfall is smoothed and
  likely understated.
- **IDW smoothing.** IDW produces bullseyes around isolated stations and has
  no notion of elevation or aspect, so it cannot recover the orographic
  detail terrain imposes. An atlas built with terrain covariates (as the
  official Rainfall Atlas of Hawaiʻi does) will be sharper. Kriging, above,
  is the first step in that direction.
- **Period-of-record climatology.** Months are averaged over each station's
  own record length rather than a fixed 1991–2020 normal period, trading
  temporal homogeneity for spatial density. Long and short records mix.
- **Sparse islands.** Niʻihau and Kahoʻolawe have almost no qualifying
  stations, so they render mostly blank. That is the data, not a bug.
- **Trace precipitation** counts as zero, per GHCN convention.

## Layout

```
scripts/    discover_source, build_dataset, interpolate, export_web,
            ghcn (shared parsing), grid (shared gridding)
data/       raw .dly files + station/coastline sources   (gitignored)
processed/  monthly.csv, stations, interpolated .npy surfaces (gitignored)
QA.md       build numbers, dropped stations, verification output

../../rainfall-gradient/       the canvas front end
../../data/rainfall-gradient/  the committed browser payload this pipeline writes
```
