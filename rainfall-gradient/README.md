# Rainfall Gradient Explorer — front end

Canvas app showing monthly rainfall across the Hawaiian Islands, interpolated
from 764 NOAA GHCN-Daily weather stations.

Two modes: a "typical year" climatology to scrub month by month, and a
2011–2025 time series for year-to-year variability. Click an island to see
its wettest and driest cells and the ratio between them; hover for the value
and the nearest station. Sparse months carry a low-confidence badge, and
islands without qualifying stations stay blank. Data loads from
[`../data/rainfall-gradient/`](../data/rainfall-gradient/).

Serve the repo root with any static server and open `/rainfall-gradient/`.
The pipeline and method notes live in
[`../data-pipelines/rainfall-gradient/`](../data-pipelines/rainfall-gradient/).
