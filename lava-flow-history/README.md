# Lava Flow History — front end

Canvas app animating every recorded lava flow on Hawaiʻi Island in
chronological order over a 3DEP hillshade — younger flows burying older ones,
from the ~700,000-year-old Kohala shields to the 2022 Mauna Loa eruption.

Nonlinear playback (the deep past flies by, the historic era gets screen
time), Age / Volcano recolouring with per-volcano surface shares, landmark
spotlights, hover readout, and URL-hash deep links (`#mode=volcano&lm=1984`).
Assets load from [`../data/lava-flow-history/`](../data/lava-flow-history/).

Serve the repo root with any static server and open `/lava-flow-history/`.
The pipeline and verification notes live in
[`../data-pipelines/lava-flow-history/`](../data-pipelines/lava-flow-history/).
