# Reef Heat Atlas — front end

Canvas app showing NOAA Coral Reef Watch 5 km daily SST and Degree Heating
Weeks around the Hawaiian Islands, 1985 to present, as weekly frames.

Three layers (SST, anomaly, DHW), play and scrub, jump buttons for the big
bleaching years (2014, 2015, 2019, 2020), and a hover readout with the cell's
full DHW history as a sparkline. Plain JavaScript with no dependencies. The
gzipped grids in [`../data/reef-heat-atlas/`](../data/reef-heat-atlas/) are
inflated in the browser with the native `DecompressionStream`.

Serve the repo root with any static server and open `/reef-heat-atlas/`.
The pipeline, the MMM/HotSpot/DHW method notes, and the verification evidence
live in [`../data-pipelines/reef-heat-atlas/`](../data-pipelines/reef-heat-atlas/).
