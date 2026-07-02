# Hawaiʻi Atlas

Four interactive maps of the Hawaiian Islands: reef heat, lava flows,
watersheds, and rainfall. Plain JavaScript on canvas, static files, public
data.

I have family in Hawaiʻi. After a visit, I wanted maps of some of the things
I'd been looking at: how hot the water over the reefs actually gets, how much
of the Big Island is rock younger than the towns built on it, why the old
land divisions run from the ridgelines down to the sea, and how it can pour
on one side of an island while the other side stays dry. Everything here is
made with public data from NOAA, the USGS, and the State of Hawaiʻi GIS
program.

## The maps

| Map | What it shows |
|-----|---------------|
| [Reef Heat Atlas](reef-heat-atlas/) | Daily sea-surface temperature and coral bleaching stress on a 5 km grid, 1985 to present. Scrub the record, jump to the big bleaching years, hover any cell for its full history. |
| [Lava Flow History](lava-flow-history/) | Every mapped lava flow on Hawaiʻi Island, replayed in order over the terrain. Younger flows bury older ones, ending with the 2022 Mauna Loa eruption. |
| [Ahupuaʻa Watersheds](ahupuaa-watersheds/) | The traditional land divisions of Oʻahu compared against watersheds computed from a 10 m elevation model. A Match mode scores how well each one tracks its drainage. |
| [Rainfall Gradient Explorer](rainfall-gradient/) | Monthly rainfall interpolated from 764 weather stations. Scrub a typical year, or click an island for its wettest and driest points. |

## Viewing the site

Once it's on GitHub Pages, it's just a link, no install:

```
https://<your-username>.github.io/hawaii-atlas/
```

To run it on your own machine instead, any static file server works, because
there is no build step:

```bash
git clone https://github.com/<your-username>/hawaii-atlas.git
cd hawaii-atlas
python3 -m http.server 8000
```

Then open http://localhost:8000. That's the whole setup.

## How it works

Each map is one folder with an `index.html`, an `app.js`, and a `style.css`.
The JavaScript draws everything on a `<canvas>` element: no map library, no
framework, no npm. A shared stylesheet (`shared/atlas.css`) carries the
common look, and each map keeps its own accent color.

The browser loads small pre-processed files from `data/`, about 20 MB across
all four maps. A few tricks keep that number down:

- The reef map's 2,153 weekly temperature grids ship gzipped (9 MB instead
  of 98) and are inflated in the browser with the native
  `DecompressionStream`.
- The lava map packs its whole timeline into two indexed PNGs and a JSON
  file, about 1 MB.
- The rainfall surfaces are `uint16` binary arrays that the browser colors
  itself, so changing the color scale never refetches anything.

## The process

Each map has a Python pipeline in `data-pipelines/` that turns the raw
sources into those small files. The raw inputs are large (about 2.5 GB across
the four projects: NetCDF satellite archives, DEM tiles, geologic map
databases, station records) and are gitignored, so the repo stays light.
Every committed byte in `data/` can be rebuilt from scratch.

The general shape is the same for all four:

1. Verify the data source actually responds before anything is hardcoded.
2. Download, resumably. Interrupted overnight runs pick up where they left
   off.
3. Compute: degree heating weeks for the reefs, a youngest-flow-wins raster
   for the lava, D8 flow routing for the watersheds, per-island IDW for the
   rainfall.
4. Export the compact browser payload.
5. Verify: each pipeline ends with a script that decodes the shipped payload
   and checks it against the source data.

Each pipeline's README covers its method, its numbers, and its limitations.
The QA.md files hold the verification output from the actual builds. AUDIT.md
is the log from consolidating the four projects into this repo.

## Rebuilding a dataset

You only need this if you want to regenerate the data (say, to pull the
reef record forward or process another island's watersheds):

```bash
cd data-pipelines/reef-heat-atlas    # or lava-flow-history, ahupuaa-watersheds, rainfall-gradient
```

Each folder's README lists its dependencies (conda for the geospatial
stacks, a venv is enough for reef and rainfall) and the scripts to run in
order. The heavy downloads are overnight jobs.

## Repo layout

```
index.html            the hub page
shared/               design tokens, shared controls, hub thumbnails
reef-heat-atlas/      one folder per map: index.html + app.js + style.css
lava-flow-history/
ahupuaa-watersheds/
rainfall-gradient/
data/                 committed browser payloads (~20 MB)
data-pipelines/       the Python that builds data/, one folder per map
AUDIT.md              consolidation log
```

## Publishing your own copy

The repo is GitHub Pages ready as-is. All paths are relative, so it works
from a project subpath.

```bash
gh repo create hawaii-atlas --public --source=. --push
gh api "repos/{owner}/hawaii-atlas/pages" -X POST \
  -f 'source[branch]=main' -f 'source[path]=/'
```

Without the `gh` CLI: create an empty repo on github.com, then

```bash
git remote add origin git@github.com:<your-username>/hawaii-atlas.git
git push -u origin main
```

and turn on Pages in the repo settings (Settings → Pages → Deploy from a
branch → `main`, `/ (root)`).

## Known limits

- **Reef:** weekly frames in the browser (the stress index itself is computed
  daily), and the coastline is traced from the 5 km satellite land mask, so
  it's blocky on purpose. The bleaching math is cross-checked against NOAA's
  published values.
- **Lava:** prehistoric flows only have age ranges, so the timeline orders
  them by range midpoint and always shows the range. The 2020–2024 Kīlauea
  summit eruptions are not merged in yet.
- **Watersheds:** only Oʻahu is processed so far. The pipeline takes one
  config change per additional island, but each is an overnight run.
- **Rainfall:** stations cluster near the coasts, so the wettest ridges are
  under-sampled and the interpolation leaves bullseyes around isolated
  stations. Niʻihau and Kahoʻolawe have almost no stations and render mostly
  blank, which is the data telling the truth.

## Data sources

- NOAA Coral Reef Watch CoralTemp v3.1 (5 km daily SST), via the PacIOOS
  ERDDAP
- USGS DS-144 / I-2524A digital geologic map of the Island of Hawaiʻi, plus
  four USGS ScienceBase flow releases (2014–2022) and 3DEP elevation
- State of Hawaiʻi Statewide GIS Program ahupuaʻa boundaries (OHA, with
  DLNR/SHPD corrections)
- NOAA GHCN-Daily station records via NCEI, with Natural Earth 10 m
  coastlines
