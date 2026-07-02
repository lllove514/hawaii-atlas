# Hawaiʻi Atlas

Interactive maps of the Hawaiian Islands, built from public data.

I have family in Hawaiʻi, and a trip to visit them turned into this project.
The islands are full of data hiding in plain sight — warm water sitting over
the reefs, fresh black rock on the Big Island's flanks, ahupuaʻa names on road
signs marking land divisions far older than any modern survey. Back home, I
started pulling the public records behind what I'd been standing on and
building the maps I wished I'd had while I was there.

Everything is hand-built: vanilla JavaScript drawing on `<canvas>` — no map
library, no framework, no build step, no npm — with a small, dependency-light
Python pipeline behind each map. The whole site runs as static files.

## The maps

| Map | What it shows | Data |
|-----|---------------|------|
| **[Reef Heat Atlas](reef-heat-atlas/)** | Four decades of daily sea-surface temperature and coral-bleaching heat stress (Degree Heating Weeks), 1985–present, as a scrubbable 5 km pixel map with SST / anomaly / DHW layers, bleaching-event jumps, and per-cell history sparklines. | NOAA Coral Reef Watch CoralTemp v3.1 (5 km daily), via the PacIOOS ERDDAP |
| **[Lava Flow History](lava-flow-history/)** | Every recorded lava flow on Hawaiʻi Island animated oldest → newest over real terrain, younger flows burying older ones — with landmark eruptions, an Age ↔ Volcano toggle, and a running km²-resurfaced counter. | USGS DS-144 geologic map (Wolfe & Morris; Trusdell), four USGS flow releases 2014–2022, USGS 3DEP elevation |
| **[Ahupuaʻa Watersheds](ahupuaa-watersheds/)** | Traditional mauka-to-makai land divisions of Oʻahu laid over watersheds computed by D8 flow routing on a 10 m DEM — including a Match mode scoring how well each ahupuaʻa tracks a single computed watershed. | State of Hawaiʻi Statewide GIS (OHA/DLNR) boundaries, USGS 3DEP 1/3″ elevation |
| **[Rainfall Gradient Explorer](rainfall-gradient/)** | *Coming soon* — the islands' extreme windward/leeward rainfall gradients. | — |

The hub page (`index.html`) ties them together.

## Repository layout

```
index.html            the atlas hub
shared/               shared design tokens, chrome, and hub thumbnails
reef-heat-atlas/      each map's front end: index.html + app.js + style.css
lava-flow-history/
ahupuaa-watersheds/
rainfall-gradient/    styled placeholder for the fourth map
data/                 the compact, committed browser payloads (~15 MB total)
data-pipelines/       the Python that builds data/ from the raw sources,
                      one folder per map, each with its own README + QA notes
```

Raw downloads and intermediates (multi-GB NetCDF, DEM tiles, shapefile
releases) are gitignored; every committed byte in `data/` is reproducible by
the pipelines.

## Tech approach

- **Front ends** are plain ES2020 on `<canvas>`. Each app loads a compact
  payload — gzipped integer grids for the reef map (inflated in the browser
  with the native `DecompressionStream`), indexed PNGs + a timeline JSON for
  the lava map, raster underlays + GeoJSON vectors for the watershed map — and
  does all colouring, hit-testing, and drawing itself.
- **Pipelines** are plain Python (numpy / xarray / netCDF4 for the reef;
  geopandas / rasterio / shapely / pysheds for the geospatial two). Every
  download and compute step is resumable, and each pipeline ends with a
  verification script that decodes the shipped payload and checks it against
  the source data.
- **Design** is one shared stylesheet (`shared/atlas.css`) — tokens, type,
  controls — with a per-map accent, so the maps read as one project without
  losing their own character.

## Run it locally

The site is static; any server from the repo root works:

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

To rebuild a dataset from scratch, see the README in its
`data-pipelines/<map>/` folder (each is a short, numbered sequence of
scripts; the heavy downloads run overnight and resume if interrupted).

## Deploy to GitHub Pages

The repo is Pages-ready: all paths are relative, so it works from a project
subpath (`username.github.io/hawaii-atlas/`). Push to GitHub, then enable
Pages for the `master`/`main` branch root. No build step.

## Honest limitations

- **Reef:** the browser payload is weekly frames (DHW itself is computed
  daily); SST is quantised to 0.05 °C and DHW to 0.1 °C-week; the coastline is
  traced from the 5 km land mask, so it is blocky by construction; the anomaly
  baseline is the record's own per-pixel week-of-year mean, not an external
  climatology. The DHW algorithm is cross-checked against CRW's published
  values (RMSE ≈ 0.003 °C-weeks on spot dates).
- **Lava:** prehistoric flows are dated by map-unit age *ranges* (the slider
  orders them by range midpoint; the original range is always shown); the
  slider is ordinal, not linear in time, and colour maps to log-age — both
  deliberate; flows are rasterized at 75 m so sub-pixel slivers can drop out;
  the 2020–2024 Kīlauea summit eruptions (largely confined to the caldera) are
  not yet merged in.
- **Watersheds:** results depend on the 10 m DEM and a 0.5 km² stream/basin
  threshold; ahupuaʻa boundaries are cultural and legal records, so divergence
  from computed drainage is a finding, not an error — and a few tiny coastal
  parcels are honestly labelled "too small to resolve". Only Oʻahu ships
  processed; the pipeline is island-parameterised for the rest.
- **General:** the reef record ends at whatever day NOAA had published when
  the pipeline last ran; re-run `download.py` to refresh.

Per-map methods, verification evidence, and fuller limitation notes live in
each `data-pipelines/<map>/README.md` and `QA.md`. `AUDIT.md` documents the
consolidation of the three original standalone projects into this repo.

## Data credits

NOAA Coral Reef Watch (CoralTemp v3.1, via PacIOOS ERDDAP); USGS DS-144 /
I-2524A *Digital Database of the Geologic Map of the Island of Hawaiʻi*;
USGS ScienceBase flow releases (June 27th flow, Puʻuʻōʻō episode 61g, 2018
lower East Rift Zone, 2022 Mauna Loa); USGS 3DEP elevation; State of Hawaiʻi
Statewide GIS Program (ahupuaʻa boundaries, sourced from OHA with DLNR/SHPD
corrections).
