# Hawaiʻi Atlas consolidation audit

Working log for the consolidation of three standalone map projects into one
deployable repo. Phase 0 records the state found on disk before anything was
touched; later phases record what changed and why.

## Phase 0: inventory (as found)

Three sibling folders, each an independent project with its own `web/`,
`scripts/`, `data/` (raw downloads) and `processed/` (intermediates). All three
front ends were served and driven headlessly (Chrome DevTools Protocol);
screenshots and feature checks below reflect what actually ran, not what the
docs claim.

### 1. Reef Heat Atlas (`reef heat atlas/`)

- **What it does:** NOAA Coral Reef Watch 5 km daily SST around the islands,
  1985-04-01 → 2026-06-29, packed to 2,153 weekly frames. Three layers (SST
  on a 23–28 °C stepped scale; Anomaly, diverging, vs per-pixel week-of-year mean
  computed in the browser; DHW, stepped bands with thresholds at 4/8) plus
  play/scrub, hover readout (SST/anomaly/DHW/risk class), island labels, scale
  bar, north arrow, keyboard control.
- **Verified working:** loads (with progress bar), renders all three layers,
  scrubs to 2015-08-03 and shows the 2015 heat stress in DHW mode, hover
  readout matches an independent decode (per its own QA, re-confirmed by
  rendering). The pixel-art look is consistent across layers.
- **Payload:** `web/data/` = **95 MB** (`sst.i16` 65.7 MB, `dhw.u8` 32.8 MB,
  plus manifest/mask/coast ≈ 70 KB). Works, but heavy to serve and to clone.
  Measured gzip: sst → 8.7 MB, dhw → 0.42 MB (**98 MB → 9.1 MB**); the browser
  can inflate natively with `DecompressionStream`, so this is the obvious fix.
- **Raw data:** `data/raw/` 1.7 GB NetCDF (42 year files), `processed/` 251 MB.
  Reproducible via the pipeline; must never be committed.
- **Junk found:** `Miniforge3-Darwin-arm64.sh` (51 MB installer left in the
  project root), `scripts/__pycache__/`, and `1-reef-heat-atlas.md`, the
  original build-prompt document (leaked instructions; must not ship).
- **Code quality:** front end and pipeline are clean, commented for the reader,
  relative paths throughout. `README.md` and `QA.md` are thorough and accurate.

### 2. Lava Flow History (`lava flow history map/`)

- **What it does:** USGS DS-144 geologic map + four post-2003 flow releases +
  3DEP hillshade, rasterized to a 75 m "youngest flow wins" surface. Ordinal
  time slider with nonlinear playback pacing, speed/loop, era captions, km²
  resurfaced counter, jump chips, seven landmark-flow spotlights, Age/Volcano
  recolouring, hover tooltip (volcano, rock unit, year/age range), URL-hash
  deep links.
- **Verified working:** renders, Volcano mode recolours by the five shields
  with its own legend, landmark + hover verified via the `#hover=` test hook.
  The animation and pacing design is the strongest single feature in the repo.
- **Payload:** `web/assets/` = **1.2 MB** (hillshade.png 972 KB, flow_age.png
  260 KB, timeline.json 16 KB). Ideal for Pages as-is.
- **Raw data:** `data/` 282 MB (DS-144, DEM tiles, ScienceBase zips),
  `processed/` 26 MB. Gitignore.
- **Junk found:** `2-lava-flow-history-map.md` build prompt, `__pycache__/`.
- **Nits found:** colour-bar end ticks ("475k yr" / "10k yr") collide at the
  left edge at default width; "Following the brief" phrase in README (reads as
  instruction residue).

### 3. Ahupuaʻa Watershed Mapper (`ahupuaa watershed mapper/`)

- **What it does:** State GIS ahupuaʻa boundaries (98 on Oʻahu) over watersheds
  computed by D8 routing on the 10 m 3DEP DEM. Terrain/Match view modes, four
  layer toggles, opacity, hover/click-to-pin (pin overlays that ahupuaʻa's
  computed basins), diacritic-insensitive search, "Show biggest mismatches",
  island selector (Oʻahu processed; others listed, disabled), moku labels,
  scale bar, north arrow.
- **Verified working:** terrain and match modes render, pin/hover/search work,
  legend switches with mode. ʻokina/macrons render correctly everywhere
  checked (Koʻolauloa, Waiʻanae, ʻEwa…).
- **Bug found:** "Show biggest mismatches" ranks degenerate slivers first:
  entries like "Kualoa 1 — 0% one basin, splits across 0" (`n_basins = 0`,
  duplicate-name features suffixed 1/2). The filter needs `n_basins >= 2`
  (and ideally to skip the numbered fragments) so the list shows real,
  discussable mismatches.
- **Payload:** `web/data/` = **3.2 MB** (base.png 1.7 MB, three GeoJSONs
  ~1.3 MB, basins.png 104 KB, meta/manifest). Fine for Pages.
- **Raw data:** `data/` 149 MB, `processed/` 92 MB. Gitignore.
- **Junk found:** `4-ahupuaa-watershed-mapper.md` build prompt, `__pycache__/`,
  and `scripts/verify_web.py:23` hardcodes an absolute scratch path
  (`/private/tmp/claude-501/...`), broken on any other machine and an
  obvious machine-generated tell.

### Cross-cutting observations

- **Paths:** all three front ends already use relative asset paths; no
  absolute `/` references, no localhost URLs in web code. Subpath deployment
  should be a matter of proving it, not rewriting.
- **Pipelines** anchor paths at `ROOT = parent of scripts/`, expecting
  `ROOT/data`, `ROOT/processed`, `ROOT/web`. Moving pipelines into
  `data-pipelines/<project>/` means retargeting the web-output directory to the
  app folders (one or two lines per config).
- **Design:** each app has its own dark-theme CSS with similar but not
  identical tokens (different fonts, control styles, panel chrome). No shared
  stylesheet. Reef uses a system-font stack; lava uses a serif display look;
  ahupuaʻa a third variant. Unification target: shared tokens + control
  styling, keep each map's palette identity.
- **Docs:** per-project READMEs are solid (sources, method, limitations). QA.md files record real verification evidence, worth keeping,
  with build-phase jargon ("VERIFICATION: phase N — PASS") toned down to plain
  verification language where user-facing.
- **Encoding:** UTF-8 with correct ʻokina (U+02BB) and macrons in all data and
  UI checked so far.

### Fix list (carried into Phases 5–6)

| # | Item | Severity |
|---|------|----------|
| F1 | Delete build-prompt docs (`1-*.md`, `2-*.md`, `4-*.md`) and Miniforge installer | must-fix (AI-tell / junk) |
| F2 | Delete `__pycache__/` everywhere; gitignore | must-fix |
| F3 | Reef payload 95 MB → ship gzipped (~9 MB) + `DecompressionStream` inflate | must-fix (data strategy) |
| F4 | Ahupuaʻa mismatch list surfaces `n_basins = 0` slivers | must-fix (visible bug) |
| F5 | Absolute scratch path in `ahupuaa .../verify_web.py` | must-fix |
| F6 | Lava colour-bar end-tick collision | polish |
| F7 | "Following the brief" phrasing in lava README | polish (AI-tell) |
| F8 | QA docs use build-phase gate jargon | polish |
| F9 | No shared design system; three divergent dark themes | Phase 4 |
| F10 | No hub page, no cross-links between maps | Phase 1/6 |

**GATE 0: PASS.** all three apps load, render, and their headline features
work; inventory, payload sizes, junk, and bugs recorded above.

## Phase 1: consolidated structure

- New tree: app front ends at `reef-heat-atlas/`, `lava-flow-history/`,
  `ahupuaa-watersheds/`, `rainfall-gradient/` (placeholder); pipelines at
  `data-pipelines/<project>/{scripts,README.md,QA.md}` with their raw
  `data/` + `processed/` intermediates alongside (gitignored later); committed
  web payloads at `data/<project>/`; `shared/` + hub `index.html` stubbed.
- App data paths retargeted to `../data/<project>/`; pipeline configs
  retargeted to write there (`WEB_DATA_DIR` / `WEB_ASSETS` / `WEB`); the
  ahupuaʻa `export_web.py`'s `C.WEB / "data"` composition updated to match.
  All pipeline scripts still compile.
- Deleted: three build-prompt docs, Miniforge installer, `__pycache__`,
  legacy per-project `.claude/`, an empty commit-less `.git`, and the old
  per-project `.gitignore`s (superseded by one top-level file in Phase 3).

**GATE 1: PASS.** reef, lava, and ahupuaʻa all load and render from their new
locations through one root server (headless screenshots re-taken).

## Phase 2: static-path safety

- All asset/data references are relative (verified by grep and by exercising
  the apps). No `/`-rooted paths, no localhost URLs.
- Proof: served the *parent* of `hawaii-atlas/` so every page lived under
  `/hawaii-atlas/<app>/`, the exact GitHub Pages subpath shape. Hub and all
  three apps loaded and functioned through those subpaths (reef layer switch,
  lava era jump, ahupuaʻa name search all exercised headlessly).

**GATE 2: PASS.** screenshots `g2-hub/g2-reef/g2-lava/g2-ahupuaa` captured
via `http://localhost:8124/hawaii-atlas/...`.

## Phase 3: data strategy

- Reef grids now ship gzipped (`sst.i16.gz` 8.7 MB, `dhw.u8.gz` 0.42 MB;
  98 MB down to 9.1 MB with no loss, weekly resolution kept). `build_web.py` writes the
  gzip directly, `verify_web.py` reads it, and the app inflates it with the
  browser-native `DecompressionStream` (with a magic-byte pass-through in case
  a server ever delivers it pre-decoded). Verified end to end: 2,153 frames,
  DHW at 2015-08-03 renders identically to the raw-payload version.
- Top-level `.gitignore` excludes `data-pipelines/*/data/` and
  `data-pipelines/*/processed/` (the multi-GB reproducible inputs), plus
  pycache/OS cruft. Old per-project gitignores removed.
- `git init` done; staged tree = **14.6 MB / 57 files**, largest file 9.3 MB;
  no raw data staged (verified by dry-run grep).
- Tradeoff note: nothing was decimated; gzip alone got the payload to
  Pages-friendly size, so full temporal resolution ships.

**GATE 3: PASS.**

## Phase 4: unified design

- `shared/atlas.css`: one token set (background scale, ink, line, panel,
  serif/sans/mono stacks), shared button/segmented-control/slider/select
  styling, focus-visible states, and an `.atlas-home` chip linking every page
  back to the hub. Each map keeps its identity through its own `--accent`
  (reef teal, lava ember, ahupuaʻa amber, rainfall blue) and its map palette.
- Typography unified: serif display titles across all pages (extending the
  lava map's cartographic feel to the whole atlas), sans UI, mono numerics.
  System font stacks only, no webfont payload.
- App stylesheets rewritten to be app-specific layout only; ~40% of each was
  duplicated tokens/reset now served from shared/.
- Hub rebuilt: trip story (true details only; an HTML comment marks where
  personal lines/photos can go), 2×2 card grid with real map thumbnails
  (clipped from live renders), per-map accent, data-credit footer.
  Rainfall placeholder page shares the same chrome.
- Narrow-viewport pass at 390 px: hub single-column; reef header/controls wrap
  and legend compacts; lava HUD stacks; ahupuaʻa panel stacks above a 62vh map.

**GATE 4: PASS.** side-by-side screenshots (g4-hub/g4-reef/g4-lava/
g4-ahupuaa/g4-rain, m-* for mobile) show one design language.

## Phase 5: fix pass

| # | Item | Outcome |
|---|------|---------|
| F1 | Build-prompt docs + installer | **Fixed** (deleted, Phase 1) |
| F2 | `__pycache__` | **Fixed** (deleted + gitignored) |
| F3 | Reef payload | **Fixed** (gzip + DecompressionStream, Phase 3) |
| F4 | Mismatch list ranked `n_basins = 0` slivers | **Fixed**: filter now requires `n_basins >= 2`; list shows real cases (Maunalua 17% / splits 2 … Kailua 23% / splits 5). Also: source features named "N/A" (a few ʻEwa fragments) now read "(unnamed parcel)" and are excluded from search. |
| F5 | Hardcoded scratch path in ahupuaʻa `verify_web.py` | **Fixed**: previews now write to `processed/previews/` |
| F6 | Lava colour-bar tick collision | **Fixed**: overlapping tick labels are culled after layout (sorted by position; "10k yr" hides when it would collide) |
| F7 | "Following the brief" in lava README | **Fixed** |
| F8 | "VERIFICATION: phase N" jargon in QA docs / scripts | **Deferred**: these are the pipelines' own self-check banners and the QA files are genuine verification evidence; renaming across scripts and docs is churn with breakage risk and no reader benefit. |
| — | Accessibility basics | Map canvases got `role="img"` + `aria-label`; controls already keyboard-reachable (reef also has arrow/space bindings); focus-visible outline added in shared CSS (Phase 4). |
| — | Dead code sweep | No TODO/FIXME/console.log leftovers found in any app. |

**GATE 5: PASS.** every fix-list item resolved or deferred with rationale.

## Phase 6: improvements

Candidates considered:

| Candidate | Verdict | Rationale |
|-----------|---------|-----------|
| Reef: bleaching-event jump chips (2014 / 2015 / 2019 / 2020) | **Build** | The record's whole story in one click; peak-DHW frame found from the loaded data itself, so it stays truthful. |
| Reef: per-cell DHW history sparkline in the hover readout | **Build** | Turns hover from a point reading into four decades of history; data already in memory. |
| Lava: per-volcano surface share in Volcano-mode legend + story caption | **Build** | The "five volcanoes built this island" beat, computed from the pixels on screen. |
| Cross-links between maps in each app's chrome | Skip | The shared home chip + hub already do the navigation job; per-map link rows add clutter for little gain. |
| Ahupuaʻa: more islands (Kauaʻi/Maui/Hawaiʻi) | Skip | Pipeline is island-parameterised and documented, but each island is hours of DEM download + routing; nothing to verify into the repo tonight. The island switcher lists them as not yet processed. |
| Reef: separate "worst year" layer | Skip | Event chips + the DHW layer cover it without a fourth mode. |
| Reef deep-link hash (like lava's) | Skip | Nice-to-have; no story need yet. |
| Hub mini-map / photo strip | Skip | Placeholder comment left for personal photos; inventing content isn't mine to do. |

Built and verified:

- **Reef, bleaching-event chips** (2014 / 2015 / 2019 / 2020) in the control
  bar: pause, switch to DHW, jump to that year's peak-stress week, found by
  scanning the loaded record (2015 chip → 2015-10-26, the true peak). 
- **Reef, DHW history sparkline** in the hover readout: the full 1985–present
  record for the hovered cell, 4/8 °C-week guides, current-frame marker;
  hidden over land.
- **Lava, volcano surface shares**: Volcano-mode legend now shows each
  shield's share of the mapped lava surface, computed from the flow-age pixels
  (Kīlauea 14%, Mauna Loa 50%, Hualālai 8%, Mauna Kea 23%, Kohala 6%), and the
  caption carries the summary line ("Five shield volcanoes built the island.
  Mauna Loa alone paved 50% of the surface.").
- **Names fix found during verification:** the lava pipeline and payload had
  "Kilauea", "Pu‘u‘ō‘ō" (typographic quotes), "Hamakua", "Hawi", "Pololu" in
  display strings. Fixed to Kīlauea / Puʻuʻōʻō (U+02BB) / Hāmākua / Hāwī /
  Pololū in `config.py`, `export_web.py`, `build_rasters.py`, and the shipped
  `timeline.json`; scripts still compile; site-wide sweep for remaining
  ASCII-only names came back clean.

**GATE 6: PASS.** all three additions running, verified headlessly with
screenshots (g6-reef, g6-lava).

## Phase 7: docs, git, publish-ready

- Top-level `README.md`: story, per-map table, layout, tech approach, local
  run + Pages deploy, limitations, data credits.
- Short README in each app folder; pipeline READMEs updated for the new
  layout (run steps now serve the repo root; layout diagrams and payload
  descriptions match reality, including the gzipped reef grids).
- Final skeptical review, all automated:
  - Every `href`/`src` in every page resolves on disk; every payload file the
    apps fetch exists; every README link/image resolves.
  - No `�` replacement characters anywhere (the only matches are the
    pipelines' own encoding assertions); ʻokina/macron spot checks pass in
    the hub, app code, lava timeline, and ahupuaʻa GeoJSON.
  - Live re-test through the nested `/hawaii-atlas/` subpath: hub renders all
    four cards; reef 2019 event chip lands on 2019-10-28 and the anomaly
    layer toggles; lava `#lm=1984` deep link spotlights the 1984 flow with
    its caption; ahupuaʻa search for "Kaneohe" (no diacritics) pins
    Kāneʻohe · Koʻolaupoko · Oʻahu.

### Final state

One static, Pages-ready repo: a narrative hub linking three working maps
(plus a styled slot for the fourth) sharing one design system; all paths
relative and proven under a subpath; committed payload ~15 MB with all raw
data gitignored and reproducible; per-map pipelines documented with QA
evidence; no build prompts, installers, scratch paths, or other scaffolding
left anywhere in the tree.

## Prose pass

A reviewer flagged the site and repo text as reading machine-written. Rewrote
the user-facing prose against the usual tell lists: em-dash asides swapped for
commas, parentheses, or separate sentences; definition-list dashes changed to
colons; "Why it matters" and "honest limitations" headers renamed; stock
phrases removed ("hiding in plain sight", "the interesting part", "watch X
build", "no X, no Y, no Z" chains, triadic imagery); build-phase gate jargon
stripped from README run blocks. Covered the hub, the top README, the four app
READMEs, the three pipeline READMEs, in-app strings (lava title card and era
captions, ahupuaʻa lede and footer caveat, mismatch list), the lava
timeline.json payload plus its exporter, and this file. Verbatim quotes of old
buggy UI text were left as quotes. The lava payload was re-serialized with the
exporter's own json.dump settings so a pipeline re-run reproduces it.

## Rainfall integration, Phase 0: assessment of `_incoming-rainfall`

State as dropped in:

- **Layout** mirrors the other projects: `web/` (index/app/style), `scripts/`
  (six Python files), `data/` (297 MB raw: 803 GHCN-Daily `.dly` station
  files, station list, coastlines), `processed/`, `README.md`, `QA.md`.
- **Pipeline was half-run.** Stage 1 (download + monthly aggregation) had
  completed: all 803 station files on disk, 764 stations kept, 238,773
  station-months spanning 1899 to 2026, summary and QA both written. Stages 2
  and 3 (IDW interpolation, web export) had never been run, so the app had no
  payload and showed a blank page.
- **Ran the remaining stages** with the project's own venv. Interpolation
  produced 12 climatology surfaces (0.02°) and 180 monthly time-series
  surfaces (2011 to 2025, 0.04°); its built-in checks pass (windward >
  leeward on Hawaiʻi, Oʻahu, and Kauaʻi; all surfaces non-negative). Export
  packed a 5.5 MB `web/data/` payload with round-trip checks against the
  `.npy` surfaces.
- **App verified working** end to end: climatology renders for all eight
  islands, month scrub and play work, time-series mode enables itself when
  its files exist (2011 start), clicking an island reports its wettest and
  driest cells (Hawaiʻi: 17.4x in January 2011), hover readout shows value
  plus nearest station. Islands or months with no qualifying stations render
  blank, and sparse months carry a low-confidence badge.
- **Junk / tells to remove:** `3-rainfall-gradient-explorer.md` (build
  prompt), `.venv/` (161 MB), `.claude/`, `scripts/__pycache__/`, a stale
  `.gitignore`, a broken image placeholder in the README, and README prose
  with the same patterns cleaned elsewhere ("Why it matters", "Limitations
  (honest)", em-dash asides, "keeps each island's gradient honest").
- **Design:** its own near-miss dark theme (different tokens, own slider and
  panel styles, no shared stylesheet, no home chip). Needs the Phase 2
  conformance pass.
- **Genuinely incomplete, to label:** the time-series window ends at 2025
  and the climatology mixes record lengths (period-of-record, not a fixed
  normal period); both are documented limitations rather than bugs. Nothing
  in the app fakes missing data.

**GATE 0: PASS.** Real state documented; the app runs against a fully built
payload produced by its own pipeline.

## Rainfall integration, Phase 1: fold into the structure

- Front end moved into `rainfall-gradient/` (the placeholder page and its
  README were replaced); payload moved to `data/rainfall-gradient/` (5.4 MB);
  pipeline moved to `data-pipelines/rainfall-gradient/` with its raw `data/`
  and `processed/` alongside, matching the other three projects exactly.
- Deleted on the way in: the build-prompt doc, a 161 MB `.venv`, `.claude/`,
  `__pycache__`, and the stale per-project `.gitignore`. `_incoming-rainfall/`
  removed.
- `app.js` fetches retargeted to `../data/rainfall-gradient/`;
  `export_web.py` retargeted to write there. Scripts compile; app parses.

**GATE 1: PASS.** Rainfall loads from its final slot through the nested
subpath server; reef, lava, and ahupuaʻa re-verified unchanged.

## Rainfall integration, Phase 2: conform to the repo rules

- Relative paths held up under `/hawaii-atlas/rainfall-gradient/` (the app
  was exercised through the nested server: month scrub, hover readout with
  nearest station, ocean/no-data cases).
- Restyled onto `shared/atlas.css`: shared tokens, serif title, home chip,
  segmented mode toggle, shared scrub sliders, aria-labelled canvas, a
  narrow-window pass. Accent set to the rain blue its hub card already used.
- Data hygiene proven with `git check-ignore` and a dry-run add: the 297 MB
  of `.dly` files and the intermediates stay out; only scripts, docs, and the
  5.4 MB payload go in. Island names in the payload carry correct ʻokina and
  macrons (station names are GHCN's own uppercase ASCII).

**GATE 2: PASS.**

## Rainfall integration, Phase 3: labeling what is partial

- The app already carried the right instincts: sparse months show a
  low-confidence badge, unstationed islands and months render blank rather
  than interpolated over, and the hover readout names the nearest station and
  distance so measured versus interpolated is visible. Added a legend note
  ("unshaded land = no qualifying stations that month") so the blank state of
  Niʻihau and Kahoʻolawe reads as data honesty rather than a bug.
- Hub card replaced: real thumbnail (March climatology), plain description,
  GHCN-Daily source tag. No "in progress" tag, because after running the
  pipeline's own remaining stages nothing in the app is stubbed or faked; the
  genuine gaps (sparse ridges, blank islands, period-of-record climatology,
  time series ending 2025) are stated in the UI, the pipeline README, and the
  top README instead.

**GATE 3: PASS.** All four cards link to working maps; gaps are labeled, not
hidden.

## Rainfall integration, Phase 4: improvements

| Candidate | Verdict | Rationale |
|-----------|---------|-----------|
| Keyboard bindings (space to play, arrows for month) | **Built** | Matches the reef map's bindings; six lines. |
| Legend coverage note | **Built** (part of Phase 3) | The blank-island state needed a one-line explanation. |
| Kriging / terrain covariates | Skip | The pipeline README documents it as the upgrade path; a real change of method, not a polish item. |
| Shared island selector across maps | Skip | Only two maps are per-island in any sense, and their island models differ (processed-vs-not for watersheds, click-an-island here). A shared control would be chrome without shared behavior. |

**GATE 4: PASS.**

## Rainfall integration, Phase 5: docs and final state

- Pipeline README rewritten for the new layout, in the repo's plain style,
  with the build's real numbers (764 of 803 stations, 1899 to 2026 records,
  time series 2011 to 2025, 5.4 MB payload) and a limitations section that
  includes the blank islands. Broken image placeholder removed. QA headers
  and the script strings that write them now match.
- App-folder README added; top README table, tech notes, limitations, and
  credits cover the fourth map; hub card is live.
- Final checks: hub + all four apps exercised through the nested
  `/hawaii-atlas/` subpath (rainfall island-click on Oʻahu: wettest 18.2x the
  driest; reef, lava, ahupuaʻa unchanged); `git check-ignore` proves the
  297 MB of raw `.dly` files and intermediates stay out of git.

Final state: four working maps behind one hub, one design system, all paths
relative and Pages-ready; committed payload about 20 MB; every dataset
reproducible from its pipeline; nothing overstated.
