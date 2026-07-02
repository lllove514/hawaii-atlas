"""Phase 3 — export the browser payload.

The front end thresholds an *ordinal timeline*: distinct eruption years are
ranked oldest->youngest and each gets an ordinal 1..N. We export:

  web/assets/hillshade.png   grayscale relief (copied from processed/)
  web/assets/flow_age.png    RGBA; (R<<8 | G) = ordinal, B = volcano id, A = mask
  web/assets/timeline.json   ordinal -> {year_sort, label, era, color, km2}, plus
                             a clean colour bar, narrative eras, landmark flows,
                             and the five source volcanoes

Colour encodes age with a warm "cooling lava" ramp (oldest dark red -> youngest
bright yellow) computed here so Python and the browser agree exactly. The blue
channel carries the source shield (1=Kīlauea .. 5=Kohala) so the browser can
recolour by volcano and name the flow under the cursor.

Ends at VERIFICATION GATE 3 (round-trips one overlay through the PNG).
"""

import json
import math
import shutil
import warnings

import numpy as np
import rasterio
from PIL import Image

import config

warnings.filterwarnings("ignore")

FLOW_AGE_TIF = config.PROCESSED / "flow_age.tif"
VOLCANO_TIF = config.PROCESSED / "volcano.tif"
HILLSHADE_PNG = config.PROCESSED / "hillshade.png"
NODATA_YEAR = -32768
NOW = 2026   # reference year for converting a flow's calendar year into an age

# Warm ramp control points (rank 0 = oldest -> 1 = youngest).
_RAMP = [
    (0.00, (60, 12, 12)),     # near-black dark red — oldest shields
    (0.25, (128, 0, 0)),      # deep red
    (0.50, (203, 44, 24)),    # red
    (0.70, (244, 109, 67)),   # orange
    (0.85, (253, 174, 97)),   # light orange
    (1.00, (255, 238, 130)),  # bright yellow — youngest / freshest lava
]

# Source shields, keyed by the leading digit of the DS-144 PTYPE code. Colours
# are a distinct qualitative set that reads on the dark hillshade.
VOLCANOES = {
    1: {"name": "Kīlauea",   "rock": "Puna Basalt",         "color": [239, 71, 111]},
    2: {"name": "Mauna Loa", "rock": "Kaʻū Basalt",         "color": [255, 145, 77]},
    3: {"name": "Hualālai", "rock": "Hualālai Volcanics",   "color": [255, 209, 102]},
    4: {"name": "Mauna Kea", "rock": "Laupāhoehoe / Hāmākua",   "color": [6, 214, 160]},
    5: {"name": "Kohala",    "rock": "Hāwī / Pololū",        "color": [17, 138, 178]},
}

# Landmark eruptions worth spotlighting (the ones people have heard of). Only
# those whose year is actually present in the flow layer are kept. `year` is the
# DS-144 calendar year (the 1800-1801 Hualalai Huʻehuʻe flow is dated 1800).
LANDMARKS = [
    {"year": 1790, "name": "1790 Kīlauea",  "vol": 1,
     "blurb": "Explosive summit eruption, the deadliest in Hawaiʻi’s recorded history."},
    {"year": 1800, "name": "1800 Hualālai", "vol": 3,
     "blurb": "The Huʻehuʻe flow, from Hualālai’s last eruption, reached the Kona coast."},
    {"year": 1859, "name": "1859 Mauna Loa", "vol": 2,
     "blurb": "Longest historic Mauna Loa flow; ran to the sea north of Kona."},
    {"year": 1935, "name": "1935 Mauna Loa", "vol": 2,
     "blurb": "Bombed from the air in an attempt to divert it away from Hilo."},
    {"year": 1984, "name": "1984 Mauna Loa", "vol": 2,
     "blurb": "Stopped about 7 km short of Hilo; the volcano then slept 38 years."},
    {"year": 2018, "name": "2018 Kīlauea LERZ", "vol": 1,
     "blurb": "Lower East Rift Zone eruption. It buried Kapoho and built new land at the coast."},
    {"year": 2022, "name": "2022 Mauna Loa", "vol": 2,
     "blurb": "First eruption since 1984; the Northeast Rift Zone flow toward Saddle Road."},
]

# Narrative eras, oldest -> youngest, selected by the frontier's age in years.
ERAS = [
    {"name": "Ancient shields", "max_ago": 10_000_000, "min_ago": 65_000,
     "caption": "The Kohala and Mauna Kea shields take shape, hundreds of thousands of years ago."},
    {"name": "Ice-age flows", "max_ago": 65_000, "min_ago": 10_000,
     "caption": "Late-Pleistocene flows: Mauna Kea’s Laupāhoehoe lavas and early Mauna Loa."},
    {"name": "Early Holocene", "max_ago": 10_000, "min_ago": 3_000,
     "caption": "Early-Holocene resurfacing across Mauna Loa, Kīlauea and Hualālai."},
    {"name": "Late Holocene", "max_ago": 3_000, "min_ago": 750,
     "caption": "Late-Holocene flows repave the active volcanoes’ flanks."},
    {"name": "Pre-contact", "max_ago": 750, "min_ago": 237,
     "caption": "Flows from the few centuries before European contact."},
    {"name": "Historic era", "max_ago": 237, "min_ago": -1,
     "caption": "The historic era, A.D. 1790 to 2022."},
]


def ramp(t):
    """Interpolate the warm ramp at t in [0,1] -> (r,g,b) ints."""
    t = min(max(t, 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(_RAMP, _RAMP[1:]):
        if t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return tuple(int(round(a + (b - a) * f)) for a, b in zip(c0, c1))
    return _RAMP[-1][1]


def label_for(year_sort, era):
    """Hover/legend label: historic flows show their calendar year."""
    if year_sort >= 1790:
        return f"A.D. {year_sort}"
    return era


def age_ramp_t(year, lo, hi):
    """Ramp position for a flow's calendar year on the log-age axis (1=young)."""
    return 1.0 - (math.log10(max(1, NOW - year)) - lo) / (hi - lo) if hi > lo else 1.0


def export():
    config.WEB_ASSETS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HILLSHADE_PNG, config.WEB_ASSETS / "hillshade.png")

    with rasterio.open(FLOW_AGE_TIF) as ds:
        age = ds.read(1)
    with rasterio.open(VOLCANO_TIF) as ds:
        vol = ds.read(1)
    h, w = age.shape
    px_km2 = (config.OUTPUT_PIXEL_M ** 2) / 1e6

    # Rank distinct years oldest->youngest -> ordinal 1..N, with per-step area.
    years, counts = np.unique(age[age != NODATA_YEAR], return_counts=True)
    years = years.tolist()
    n = len(years)
    ordinal_of = {y: i + 1 for i, y in enumerate(years)}

    import geopandas as gpd
    flows = gpd.read_file(config.PROCESSED / "flows.gpkg")
    era_of = flows.groupby("year_sort")["era"].first().to_dict()

    # Colour maps to AGE on a log axis so an 8-year-old flow and a 700,000-year
    # shield stay distinguishable; youngest -> 1.0 (bright yellow).
    ages = [max(1, NOW - y) for y in years]
    lo, hi = math.log10(min(ages)), math.log10(max(ages))
    timeline = []
    for i, y in enumerate(years):
        era = era_of.get(y, "unknown")
        timeline.append({"ordinal": i + 1, "year_sort": int(y),
                         "label": label_for(y, era), "era": era,
                         "years_ago": int(NOW - y),
                         "km2": round(float(counts[i]) * px_km2, 3),
                         "color": list(ramp(age_ramp_t(y, lo, hi)))})

    # Encode ordinal into R (high byte) and G (low byte); B = volcano id; A=mask.
    years_arr = np.array(years, dtype=np.int32)
    mask = age != NODATA_YEAR
    ord_grid = np.zeros((h, w), dtype=np.uint32)
    ord_grid[mask] = np.searchsorted(years_arr, age[mask]).astype(np.uint32) + 1
    assert ord_grid.max() < 65536, "too many eras to encode in 16 bits"
    assert ord_grid[mask].min() >= 1, "ordinal underflow"

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = (ord_grid >> 8).astype(np.uint8)
    rgba[..., 1] = (ord_grid & 0xFF).astype(np.uint8)
    rgba[..., 2] = vol                     # 0 where no lava, else 1..5
    rgba[..., 3] = np.where(mask, 255, 0).astype(np.uint8)
    Image.fromarray(rgba, mode="RGBA").save(config.WEB_ASSETS / "flow_age.png")

    payload = {
        "pixel_size_m": config.OUTPUT_PIXEL_M, "width": w, "height": h,
        "n_eras": n, "now": NOW,
        "total_km2": round(float(mask.sum()) * px_km2, 1),
        "timeline": timeline,
        "colorbar": _colorbar(lo, hi),
        "eras": ERAS,
        "landmarks": _landmarks(ordinal_of),
        "volcanoes": {str(k): v for k, v in VOLCANOES.items()},
        "credit": "USGS DS-144 geologic map of the Island of Hawaiʻi "
                  "(Wolfe & Morris; Trusdell) + USGS flow data releases "
                  "2014–2022 (June 27th, ep 61g, 2018 LERZ, 2022 Mauna Loa) "
                  "+ USGS 3DEP elevation",
    }
    with open(config.WEB_ASSETS / "timeline.json", "w") as f:
        json.dump(payload, f)
    print(f"  exported {n} ordinals, {w}x{h} overlay, "
          f"{len(payload['landmarks'])} landmarks -> web/assets/")
    return years, ordinal_of, age


def _colorbar(lo, hi):
    """A clean age->colour bar: the ramp plus a few ordered, non-overlapping
    ticks (positions in [0,1], 0 = oldest / left, 1 = youngest / right)."""
    stops = [{"t": t, "color": list(c)} for t, c in _RAMP]
    max_age = int(round(10 ** hi))
    # Few, short, well-spaced ticks so the labels never collide in the legend.
    tick_ages = [(4, "2022"), (237, "1790"), (10000, "10k yr"),
                 (max_age, f"{round(max_age / 1000):,}k yr")]
    ticks = []
    for a, lab in tick_ages:
        if 4 <= a <= max_age:
            t = 1.0 - (math.log10(a) - lo) / (hi - lo) if hi > lo else 1.0
            ticks.append({"t": round(t, 4), "label": lab})
    return {"stops": stops, "ticks": ticks}


def _landmarks(ordinal_of):
    out = []
    for lm in LANDMARKS:
        if lm["year"] in ordinal_of:
            out.append({**lm, "ordinal": ordinal_of[lm["year"]]})
    return out


def gate3(years, ordinal_of, age):
    # Every timeline year must be representable in the exported PNG.
    tl = json.load(open(config.WEB_ASSETS / "timeline.json"))
    assert tl["n_eras"] == len(years)
    assert all(0 < e["ordinal"] < 65536 for e in tl["timeline"])
    # Ordinals are contiguous and strictly ordered oldest->youngest.
    assert [e["ordinal"] for e in tl["timeline"]] == list(range(1, len(years) + 1))
    ys = [e["year_sort"] for e in tl["timeline"]]
    assert all(ys[i] < ys[i + 1] for i in range(len(ys) - 1)), "timeline not ordered"
    # Every landmark resolves to a real ordinal.
    for lm in tl["landmarks"]:
        assert 1 <= lm["ordinal"] <= len(years), f"bad landmark {lm['name']}"

    # Round-trip: decode the PNG, reconstruct ordinals + volcano, compare to the
    # source for the youngest overlay.
    rgba = np.asarray(Image.open(config.WEB_ASSETS / "flow_age.png"))
    decoded = (rgba[..., 0].astype(np.uint32) << 8) | rgba[..., 1].astype(np.uint32)
    young = max(years)
    want = (age == young)
    got = (decoded == ordinal_of[young]) & (rgba[..., 3] > 0)
    assert np.array_equal(want, got), "round-trip mismatch for youngest overlay"
    # Volcano channel is present exactly where lava is, values in 1..5.
    vmask = rgba[..., 2] > 0
    assert np.array_equal(vmask, rgba[..., 3] > 0), "volcano/mask mismatch"
    assert rgba[..., 2].max() <= 5, "volcano id out of range"
    print(f"  round-trip OK: {want.sum()} pixels of year {young}; "
          f"volcano ids {sorted(np.unique(rgba[..., 2][vmask]).tolist())}")
    print("VERIFICATION: phase 3")


def _selfcheck():
    assert ramp(0.0) == _RAMP[0][1] and ramp(1.0) == _RAMP[-1][1]
    mid = ramp(0.5)
    assert all(0 <= c <= 255 for c in mid) and mid == _RAMP[2][1]
    # Youngest end must be brighter (higher luminance) than the oldest.
    lum = lambda c: 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
    assert lum(ramp(1.0)) > lum(ramp(0.0)), "ramp should brighten with youth"
    assert label_for(1984, "x") == "A.D. 1984"
    assert label_for(825, "750-1,500 yr B.P.") == "750-1,500 yr B.P."
    # ERAS tile the whole age axis with no gap at the historic boundary.
    assert ERAS[-1]["name"] == "Historic era" and ERAS[-1]["max_ago"] == 237
    print("export_web self-check OK")


if __name__ == "__main__":
    _selfcheck()
    print("== Export web payload ==")
    years, ordinal_of, age = export()
    gate3(years, ordinal_of, age)
