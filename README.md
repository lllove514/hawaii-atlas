# Hawaiʻi Atlas

Interactive maps of the Hawaiian Islands, built from public data.

I have family in Hawaiʻi. After a visit, I wanted maps of some of the things
I'd been looking at: how hot the water over the reefs actually gets, how much
of the Big Island is rock younger than the towns built on it, why the old land
divisions run from the ridgelines down to the sea. The data behind all of it
is public. NOAA, the USGS, and the state GIS office publish it, and these
pages draw it.

Each map is plain JavaScript drawing on a canvas element. There is no map
library, no framework, and no build step. A small Python pipeline behind each
map turns the raw data into the compact files the browser loads, and the whole
site runs as static files.

## The maps

| Map | What it shows | Data |
|-----|---------------|------|
| **[Reef Heat Atlas](reef-heat-atlas/)** | Daily sea-surface temperature and coral bleaching stress (Degree Heating Weeks) on a 5 km grid, 1985 to present, with SST, anomaly, and DHW layers, jumps to the big bleaching years, and a per-cell history sparkline. | NOAA Coral Reef Watch CoralTemp v3.1 (5 km daily), via the PacIOOS ERDDAP |
| **[Lava Flow History](lava-flow-history/)** | Every mapped lava flow on Hawaiʻi Island, replayed in order over the terrain. Younger flows bury older ones, ending with the 2022 Mauna Loa eruption. Includes landmark eruptions, an Age/Volcano toggle, and a running count of km² resurfaced. | USGS DS-144 geologic map (Wolfe & Morris; Trusdell), four USGS flow releases 2014 to 2022, USGS 3DEP elevation |
| **[Ahupuaʻa Watersheds](ahupuaa-watersheds/)** | The traditional land divisions of Oʻahu compared against watersheds computed by D8 flow routing on a 10 m DEM. A Match mode scores how well each ahupuaʻa tracks a single computed watershed. | State of Hawaiʻi Statewide GIS (OHA/DLNR) boundaries, USGS 3DEP 1/3″ elevation |
| **[Rainfall Gradient Explorer](rainfall-gradient/)** | Monthly rainfall interpolated from 764 weather stations, per island, as a scrubbable typical year plus a 2011 to 2025 time series. Click an island for its wettest and driest points. | NOAA GHCN-Daily station records, via NCEI |

The hub page (`index.html`) ties them together.

## Repository layout

```
index.html            the atlas hub
shared/               shared design tokens, chrome, and hub thumbnails
reef-heat-atlas/      each map's front end: index.html + app.js + style.css
lava-flow-history/
ahupuaa-watersheds/
rainfall-gradient/
data/                 the compact, committed browser payloads (about 20 MB total)
data-pipelines/       the Python that builds data/ from the raw sources,
                      one folder per map, each with its own README and QA notes
```

Raw downloads and intermediates (multi-GB NetCDF, DEM tiles, shapefile
releases) are gitignored. Every committed byte in `data/` can be regenerated
by the pipelines.

## Tech notes

- The front ends are plain ES2020 on canvas. Each app loads a compact payload
  and does its own coloring, hit-testing, and drawing. The reef map ships
  gzipped integer grids and inflates them in the browser with the native
  `DecompressionStream`; the lava map ships two indexed PNGs and a timeline
  JSON; the watershed map ships raster underlays plus GeoJSON vectors.
- The pipelines are plain Python: numpy, xarray, and netCDF4 for the reef map;
  geopandas, rasterio, shapely, and pysheds for the lava and watershed maps;
  numpy and scipy for the rainfall map. Downloads and
  compute steps resume if interrupted. Each pipeline ends with a verification
  script that decodes the shipped payload and checks it against the source
  data.
- One shared stylesheet (`shared/atlas.css`) carries the tokens, type, and
  controls. Each map keeps its own accent color and palette.

## Run it locally

The site is static, so any server from the repo root works:

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

To rebuild a dataset from scratch, see the README in its
`data-pipelines/<map>/` folder. Each is a short, numbered sequence of scripts.
The heavy downloads run overnight and resume if interrupted.

## Deploy to GitHub Pages

All paths are relative, so the site works from a project subpath
(`username.github.io/hawaii-atlas/`). Push to GitHub, then enable Pages for
the `main` branch root. No build step.

## Limitations

- **Reef:** the browser payload is weekly frames (DHW itself is computed
  daily). SST is quantized to 0.05 °C and DHW to 0.1 °C-week. The coastline is
  traced from the 5 km land mask, so it is blocky by construction. The anomaly
  baseline is the record's own per-pixel week-of-year mean rather than an
  external climatology. The DHW algorithm is cross-checked against CRW's
  published values (RMSE about 0.003 °C-weeks on spot dates).
- **Lava:** prehistoric flows are dated by map-unit age ranges; the slider
  orders them by range midpoint and always shows the original range. The
  slider is ordinal rather than linear in time, and color maps to log-age.
  Both choices trade precision for watchability. Flows are rasterized at 75 m,
  so slivers narrower than a pixel can drop out. The 2020 to 2024 Kīlauea
  summit eruptions, largely confined to the caldera, are not yet merged in.
- **Watersheds:** results depend on the 10 m DEM and a 0.5 km² stream/basin
  threshold. Ahupuaʻa boundaries are cultural and legal records, so divergence
  from computed drainage is a finding rather than an error. A few tiny coastal
  parcels are labeled as too small to resolve. Only Oʻahu ships processed; the
  pipeline takes one config change per additional island.
- **Rainfall:** stations cluster on coasts and in valleys, so the wettest
  ridges are under-sampled and peak rainfall is understated; IDW has no
  notion of terrain, so isolated stations leave bullseyes; Niʻihau and
  Kahoʻolawe have almost no qualifying stations and render mostly blank. The
  climatology averages each station's own record length rather than a fixed
  normal period.
- **General:** the reef and rainfall records end at whatever NOAA had
  published when the pipelines last ran. Re-run their download steps to
  refresh.

Per-map methods, verification evidence, and fuller limitation notes live in
each `data-pipelines/<map>/README.md` and `QA.md`. `AUDIT.md` documents the
consolidation of the three original standalone projects into this repo.

## Data credits

NOAA Coral Reef Watch (CoralTemp v3.1, via PacIOOS ERDDAP); USGS DS-144 /
I-2524A *Digital Database of the Geologic Map of the Island of Hawaiʻi*;
USGS ScienceBase flow releases (June 27th flow, Puʻuʻōʻō episode 61g, 2018
lower East Rift Zone, 2022 Mauna Loa); USGS 3DEP elevation; State of Hawaiʻi
Statewide GIS Program (ahupuaʻa boundaries, sourced from OHA with DLNR/SHPD
corrections); NOAA GHCN-Daily station records via NCEI; Natural Earth 10 m
coastlines.
