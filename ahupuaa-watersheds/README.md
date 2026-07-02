# Ahupuaʻa Watershed Mapper — front end

Canvas app overlaying the traditional ahupuaʻa land divisions of Oʻahu on
watersheds computed by D8 flow routing over the USGS 10 m DEM.

Terrain and Match views, layer toggles, hover/click-to-pin (pinning overlays
that ahupuaʻa's computed watershed), diacritic-insensitive name search, and a
"biggest mismatches" list of the divisions that diverge most from the computed
drainage. Data loads from [`../data/ahupuaa-watersheds/`](../data/ahupuaa-watersheds/).

Serve the repo root with any static server and open `/ahupuaa-watersheds/`.
The pipeline (island-parameterised — Oʻahu ships processed, other islands
re-run with one config change) lives in
[`../data-pipelines/ahupuaa-watersheds/`](../data-pipelines/ahupuaa-watersheds/).
