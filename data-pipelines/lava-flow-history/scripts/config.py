"""Shared configuration and the flow-age lookup for the Lava Flow History Map.

Everything downstream (discovery, download, rasterization, export) imports from
here so the data sources, projection, grid resolution, and — most importantly —
the map-unit -> age mapping live in exactly one place.

Age handling (see README):
  * Historically dated flows carry a calendar year in YEAR1/YEAR2 (e.g. 1984).
    We use that year directly.
  * Prehistoric flows carry only a map-unit code (UNITS / LABEL) whose age is a
    published *range* in radiocarbon years before present, e.g. "750-1,500 yr
    B.P." We keep both: a numeric sort key (a calendar year derived from the
    range midpoint) and the original range label for display.

Source of the unit->age table: USGS DS-144 / I-2524A geologic map of the Island
of Hawaii (Wolfe & Morris; digital database by Trusdell). The polygon attribute
PTYPE encodes volcano + deposit type + age class; the age of each class is given
in the map explanation. Only lava-flow deposit types are included here — cones,
tephra, and surficial units are not "lava flows" and are excluded from the map.
"""

from pathlib import Path

# --- Layout ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PROCESSED = ROOT / "processed"
WEB = ROOT.parent.parent / "data"
WEB_ASSETS = WEB / "lava-flow-history"

# --- Projection & grid ----------------------------------------------------
# NAD83 / UTM zone 5N — metres, correct for the Island of Hawaii. The flow
# polygons are already in this CRS; the DEM is reprojected into it so the
# hillshade and the flow-age raster share one grid, pixel-for-pixel.
TARGET_CRS = "EPSG:26905"
OUTPUT_PIXEL_M = 75.0          # web raster resolution (metres/pixel)

# Hillshade illumination (standard cartographic defaults).
HILLSHADE_AZIMUTH_DEG = 315.0
HILLSHADE_ALTITUDE_DEG = 45.0
HILLSHADE_Z_FACTOR = 1.0

# Radiocarbon "before present" is referenced to AD 1950 by convention; we use
# that to turn an age-in-years-BP into a calendar-year sort key.
BP_REFERENCE_YEAR = 1950

# --- Data sources (every URL below was fetched and verified) --------------
FLOW_ZIP_URL = "https://pubs.usgs.gov/ds/2005/144/data/bimp.zip"
# Path to the geology coverage inside the extracted zip, and its polygon layer.
FLOW_E00_RELPATH = "gis/bimpexport/bimp_fnl/bimp_e00/bimpgeo.e00"
# NB: the coverage's polygon (PAL) layer cannot be assembled by GDAL in bounded
# time, so Phase 1 rebuilds polygons from the ARC + LAB layers instead.

# Recent eruptions that post-date DS-144 (compiled ~2000–2005). Each is a USGS
# ScienceBase data release; we take the *final cumulative flow footprint* and add
# it as one polygon stamped with the eruption's calendar year. For each zip we
# take the shapefile whose name contains "flowfootprint" if present, else union
# every "*flow*" polygon shapefile (which covers single-flow and daily-chronology
# releases alike). All URLs were fetched and verified before use.
RECENT_SOURCES = [
    {
        "id": "kilauea_jun27",
        "url": ("https://www.sciencebase.gov/catalog/file/get/5cdd9871e4b029273746360f"
                "?f=__disk__d4%2F85%2F1d%2Fd4851d285b89ba608d704895a363e4b63d8274b5"),
        "zip": "kilauea_jun27_flow.zip",
        "year": 2016, "ptype": 106,
        "label": "A.D. 2014–2016 (Kīlauea June 27th flow, episode 61e)",
        "source": "USGS June 27th flow 2014–2016",
    },
    {
        "id": "kilauea_ep61g",
        "url": ("https://www.sciencebase.gov/catalog/file/get/597230e4e4b0ec1a4885edc1"
                "?f=__disk__40%2F76%2F5e%2F40765e106400494dce021f0abe9ca2c92a46b216"),
        "zip": "kilauea_ep61g.zip",
        "year": 2017, "ptype": 106,
        "label": "A.D. 2016–2017 (Kīlauea Puʻuʻōʻō episode 61g)",
        "source": "USGS Puʻuʻōʻō episode 61g 2016–2017",
    },
    {
        "id": "kilauea_2018_lerz",
        "url": ("https://www.sciencebase.gov/catalog/file/get/5eba3f6082ce25b5135d5b85"
                "?f=__disk__ec%2F1d%2F24%2Fec1d2475fef61d92fc624d784c40b51df0cfb21f"),
        "zip": "KIL_2018_LERZ_Shapefiles.zip",
        "year": 2018, "ptype": 106,
        "label": "A.D. 2018 (Kīlauea lower East Rift Zone)",
        "source": "USGS 2018 LERZ geospatial database",
    },
    {
        "id": "maunaloa_2022",
        "url": ("https://www.sciencebase.gov/catalog/file/get/666a1d25d34e9bcc607bda25"
                "?f=__disk__21%2F68%2F19%2F216819e94973703bc1e6b3b0840c0288356dfd3a"),
        "zip": "maunaloa_2022.zip",
        "year": 2022, "ptype": 209,
        "label": "A.D. 2022 (Mauna Loa Northeast Rift Zone)",
        "source": "USGS Mauna Loa 2022 geospatial database",
    },
]

# Youngest recorded flow overall — used as the timeline's recent bound in gates.
YOUNGEST_YEAR = max(s["year"] for s in RECENT_SOURCES)

# USGS 3DEP 1-arc-second DEM tiles covering the island (NW-corner named).
_DEM_BASE = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1/TIFF/current"
DEM_TILES = ["n20w156", "n21w156", "n20w155", "n19w156", "n20w157", "n21w157"]
def dem_tile_url(tile):
    return f"{_DEM_BASE}/{tile}/USGS_1_{tile}.tif"

# Island bounding box (lon/lat) used only as a sanity check for DEM coverage.
ISLAND_BBOX_LONLAT = (-156.10, 18.90, -154.75, 20.30)  # (W, S, E, N)

# --- Flow-unit age table --------------------------------------------------
# PTYPE (int) -> (bp_young, bp_old, formation, era_label)
# bp_* are radiocarbon years before present; for the historic classes the
# calendar year in YEAR1 takes precedence and these bounds are only a fallback.
_HISTORIC = "Historic (A.D. 1790 or younger)"
PTYPE_AGE = {
    # Kīlauea — Puna Basalt lava flows
    106: (0, 160, "Puna Basalt (Kīlauea)", _HISTORIC),
    107: (200, 750, "Puna Basalt (Kīlauea)", "200-750 yr B.P."),
    113: (200, 400, "Puna Basalt (Kīlauea)", "200-400 yr B.P."),
    114: (400, 750, "Puna Basalt (Kīlauea)", "400-750 yr B.P."),
    108: (750, 1500, "Puna Basalt (Kīlauea)", "750-1,500 yr B.P."),
    109: (1500, 3000, "Puna Basalt (Kīlauea)", "1,500-3,000 yr B.P."),
    110: (3000, 5000, "Puna Basalt (Kīlauea)", "3,000-5,000 yr B.P."),
    111: (5000, 10000, "Puna Basalt (Kīlauea)", "5,000-10,000 yr B.P."),
    112: (10000, 30000, "Hilina Basalt (Kīlauea)", ">10,000 yr B.P."),
    # Mauna Loa — Kau Basalt lava flows (+ older Kahuku/Ninole)
    209: (0, 160, "Kau Basalt (Mauna Loa)", _HISTORIC),
    210: (200, 750, "Kau Basalt (Mauna Loa)", "200-750 yr B.P."),
    211: (750, 1500, "Kau Basalt (Mauna Loa)", "750-1,500 yr B.P."),
    212: (1500, 3000, "Kau Basalt (Mauna Loa)", "1,500-3,000 yr B.P."),
    213: (3000, 10000, "Kau Basalt (Mauna Loa)", "3,000-10,000 yr B.P."),
    214: (10000, 30000, "Kau Basalt (Mauna Loa)", ">10,000 yr B.P."),
    215: (30000, 100000, "Kahuku Basalt (Mauna Loa)", ">30,000 yr B.P."),
    216: (100000, 300000, "Ninole Basalt (Mauna Loa)", "100,000-300,000 yr B.P."),
    217: (3000, 5000, "Kau Basalt (Mauna Loa)", "3,000-5,000 yr B.P."),
    218: (5000, 10000, "Kau Basalt (Mauna Loa)", "5,000-10,000 yr B.P."),
    # Hualalai lava flows
    308: (0, 160, "Hualalai Volcanics", _HISTORIC),
    309: (200, 750, "Hualalai Volcanics", "200-750 yr B.P."),
    310: (750, 1500, "Hualalai Volcanics", "750-1,500 yr B.P."),
    311: (1500, 3000, "Hualalai Volcanics", "1,500-3,000 yr B.P."),
    312: (3000, 5000, "Hualalai Volcanics", "3,000-5,000 yr B.P."),
    313: (5000, 10000, "Hualalai Volcanics", "5,000-10,000 yr B.P."),
    314: (10000, 30000, "Hualalai Volcanics", ">10,000 yr B.P."),
    317: (100000, 105000, "Waawaa Trachyte (Hualalai)", "~100,000 yr B.P."),
    # Mauna Kea lava flows
    405: (4000, 14000, "Laupahoehoe Volcanics (Mauna Kea)", "4,000-14,000 yr B.P."),
    406: (14000, 65000, "Laupahoehoe Volcanics (Mauna Kea)", "14,000-65,000 yr B.P."),
    408: (14000, 65000, "Laupahoehoe Volcanics (Mauna Kea)", "14,000-65,000 yr B.P."),
    407: (65000, 250000, "Hāmākua Volcanics (Mauna Kea)", "65,000-250,000 yr B.P."),
    # Kohala lava flows (oldest on the island)
    509: (120000, 230000, "Hāwī Volcanics (Kohala)", "120,000-230,000 yr B.P."),
    511: (120000, 230000, "Hāwī Volcanics (Kohala)", "120,000-230,000 yr B.P."),
    513: (120000, 230000, "Hāwī Volcanics (Kohala)", "120,000-230,000 yr B.P."),
    510: (250000, 700000, "Pololū Volcanics (Kohala)", "250,000-700,000 yr B.P."),
    512: (250000, 700000, "Pololū Volcanics (Kohala)", "250,000-700,000 yr B.P."),
}


def is_lava_flow(ptype):
    """True if this PTYPE is a lava-flow deposit we map."""
    try:
        return int(ptype) in PTYPE_AGE
    except (TypeError, ValueError):
        return False


def flow_age(ptype, year1, year2):
    """Return (year_sort:int, label:str, era:str) for one flow polygon.

    year_sort is a calendar-year sort key (larger == younger). Historically
    dated flows use their calendar year; prehistoric flows use the midpoint of
    their age range converted from years-BP to a calendar year.
    """
    ptype = int(ptype)
    bp_young, bp_old, formation, era = PTYPE_AGE[ptype]
    y1 = None if year1 is None else int(year1)
    y2 = None if year2 is None else int(year2)

    # A positive YEAR1 is a real calendar year — always prefer it.
    if y1 is not None and y1 > 0:
        if y2 is not None and y2 > y1:
            label = f"A.D. {y1}–{y2}"
        else:
            label = f"A.D. {y1}"
        return y1, label, "Historic (A.D. 1790 or younger)"

    # Otherwise fall back to the unit's age range.
    midpoint_bp = (bp_young + bp_old) / 2.0
    year_sort = int(round(BP_REFERENCE_YEAR - midpoint_bp))
    label = f"{formation}, {era}"
    return year_sort, label, era


def _selfcheck():
    # Table integrity: ranges are ordered and non-empty; labels present.
    for pt, (yb, yo, form, era) in PTYPE_AGE.items():
        assert 0 <= yb < yo, f"bad range for PTYPE {pt}: {yb}-{yo}"
        assert form and era, f"missing text for PTYPE {pt}"

    # Historic flow: calendar year wins over the range, ordering is by year.
    ys_1984, lab, era = flow_age(209, 1984, 1984)
    assert ys_1984 == 1984 and lab == "A.D. 1984", (ys_1984, lab)
    ys_range, lab2, _ = flow_age(106, 1983, 1986)
    assert lab2 == "A.D. 1983–1986", lab2

    # Prehistoric: no calendar year -> midpoint-derived sort key + range label.
    ys_pre, lab3, era3 = flow_age(211, -99999, -99999)   # 750-1,500 BP
    assert ys_pre == BP_REFERENCE_YEAR - 1125, ys_pre
    assert "750-1,500 yr B.P." in lab3 and "Mauna Loa" in lab3, lab3

    # Younger prehistoric ranges sort *after* older ones, and all before historic.
    younger = flow_age(210, -99999, -99999)[0]   # 200-750 BP
    older = flow_age(212, -99999, -99999)[0]     # 1,500-3,000 BP
    assert older < younger < 1790 < ys_1984, (older, younger, ys_1984)
    assert not is_lava_flow(701) and is_lava_flow(106)  # 701 = surficial fill
    print("config self-check OK")


if __name__ == "__main__":
    _selfcheck()
