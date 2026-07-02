# Lava Flow History — front end

Canvas app that replays every recorded lava flow on Hawaiʻi Island in
chronological order over a 3DEP hillshade. Younger flows bury older ones, from
the Kohala shields (roughly 700,000 years old) to the 2022 Mauna Loa eruption.

Playback is nonlinear: the deep past goes by quickly and the historic era gets
most of the screen time. There is an Age/Volcano toggle with per-volcano
surface shares, landmark spotlights, a hover readout, and URL-hash deep links
(`#mode=volcano&lm=1984`). Assets load from
[`../data/lava-flow-history/`](../data/lava-flow-history/).

Serve the repo root with any static server and open `/lava-flow-history/`.
The pipeline and verification notes live in
[`../data-pipelines/lava-flow-history/`](../data-pipelines/lava-flow-history/).
