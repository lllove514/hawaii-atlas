"""Shared configuration and small helpers for the Ahupuaʻa Watershed Mapper.

Everything the pipeline needs to know about *where* data lives and *how* to
fetch it lives here, so the phase scripts stay about their own logic. The island
is a single variable (ISLAND) so the whole run can be re-pointed at Kauaʻi, Maui
or Hawaiʻi without touching the other scripts.

Nothing here hardcodes an unverified download URL: the DEM tile list is derived
from the ahupuaʻa layer's own extent at runtime, and every URL is HEAD-checked
before use (see discover_source.py / download.py).
"""

import math
import time
import unicodedata
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"            # raw downloads (gitignored)
PROCESSED = ROOT / "processed"  # intermediate + final rasters/vectors (gitignored)
WEB = ROOT.parent.parent / "data" / "ahupuaa-watersheds"   # exported web payload
for _d in (DATA, PROCESSED, WEB):
    _d.mkdir(parents=True, exist_ok=True)

# --- Island selection ------------------------------------------------------
# Change ISLAND to re-run the whole pipeline for another island. `mokupuni` is
# the exact value in the ahupuaʻa layer's island field (with ʻokina, U+02BB).
# `utm_epsg` is the metric CRS the DEM and vectors are aligned to.
ISLANDS = {
    "Oʻahu":    {"mokupuni": "Oʻahu",    "utm_epsg": 32604},  # UTM 4N
    "Kauaʻi":   {"mokupuni": "Kauaʻi",   "utm_epsg": 32604},  # UTM 4N
    "Molokaʻi": {"mokupuni": "Molokaʻi", "utm_epsg": 32604},  # UTM 4N
    "Lānaʻi":   {"mokupuni": "Lānaʻi",   "utm_epsg": 32604},  # UTM 4N
    "Maui":     {"mokupuni": "Maui",     "utm_epsg": 32604},  # UTM 4N (spans 4/5)
    "Hawaiʻi":  {"mokupuni": "Hawaiʻi",  "utm_epsg": 32605},  # UTM 5N
}
ISLAND = "Oʻahu"
ISLAND_CFG = ISLANDS[ISLAND]

# --- Data sources (roots verified live; specific URLs verified before use) --
# State of Hawaiʻi Statewide GIS Program, HistoricCultural service, layer 1.
ARCGIS_LAYER = "https://geodata.hawaii.gov/arcgis/rest/services/HistoricCultural/MapServer/1"
# USGS 3DEP 1/3 arc-second (~10 m) staged GeoTIFF tiles on the TNM S3 bucket.
USGS_13_TILE = ("https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/"
                "TIFF/current/{tile}/USGS_13_{tile}.tif")

# --- Hydrology parameters --------------------------------------------------
TARGET_RES_M = 10.0          # DEM resolution after reprojection to UTM (metres)
STREAM_THRESHOLD_CELLS = 5000  # flow-accum cells (~0.5 km^2) to call a cell "stream"
MIN_BASIN_KM2 = 0.5          # basins below this are "minor" (single-cell coastal drains)

# --- Web export ------------------------------------------------------------
WEB_MAX_WIDTH = 2200         # px width of exported raster layers (aspect preserved)

# --- Output file names (ascii-safe slug; display names keep their diacritics) --
def slug(name):
    """ascii, lowercase, hyphenless slug for filenames — 'Oʻahu' -> 'oahu'.

    Strips the ʻokina and folds macrons to plain vowels so filenames stay
    portable, while the diacritic form is preserved everywhere it's shown.
    """
    stripped = name.replace("ʻ", "").replace("ʼ", "").replace("'", "")
    ascii_ = unicodedata.normalize("NFKD", stripped).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "-" for c in ascii_.lower()).strip("-")


def paths(island=ISLAND):
    """All island-specific file paths in one dict, keyed by role."""
    s = slug(island)
    return {
        "dem_raw": DATA / f"{s}_dem_3dep.tif",         # merged+clipped WGS84 DEM
        "dem_utm": PROCESSED / f"{s}_dem_utm.tif",     # reprojected to metric CRS
        "ahupuaa_raw": DATA / f"{s}_ahupuaa.geojson",  # raw WGS84 boundaries
        "ahupuaa_utm": PROCESSED / f"{s}_ahupuaa_utm.gpkg",
        "flowacc": PROCESSED / f"{s}_flowacc.tif",
        "flowdir": PROCESSED / f"{s}_flowdir.tif",
        "streams": PROCESSED / f"{s}_streams.gpkg",
        "basins": PROCESSED / f"{s}_basins.tif",
        "basins_vec": PROCESSED / f"{s}_basins.gpkg",
    }


# --- HTTP session with retry/backoff ---------------------------------------
def make_session(total_retries=5, backoff=1.5):
    """A requests session that retries transient failures with backoff.

    Used for both the ArcGIS queries and the multi-hundred-MB DEM downloads, so
    an overnight run survives a flaky connection instead of dying on one 503.
    """
    s = requests.Session()
    retry = Retry(
        total=total_retries, connect=total_retries, read=total_retries,
        backoff_factor=backoff, status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = "ahupuaa-watershed-mapper/1.0 (research; contact via repo)"
    return s


def remote_size(url, session):
    """Content-Length of a URL in bytes, or None if the server won't say."""
    r = session.head(url, allow_redirects=True, timeout=30)
    r.raise_for_status()
    cl = r.headers.get("Content-Length")
    return int(cl) if cl is not None else None


def download_file(url, dest, session, chunk=1 << 20):
    """Resumable download: skip if complete, resume a partial with an HTTP Range.

    Returns the destination Path. An interrupted overnight run re-enters here and
    either skips a finished file or continues a partial from its current length.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = remote_size(url, session)
    have = dest.stat().st_size if dest.exists() else 0
    if size is not None and have == size:
        return dest  # already complete
    headers, mode = {}, "wb"
    if have and size is not None and have < size:
        headers["Range"] = f"bytes={have}-"  # resume partial
        mode = "ab"
    with session.get(url, stream=True, timeout=120, headers=headers) as r:
        r.raise_for_status()
        if headers.get("Range") and r.status_code == 200:
            mode = "wb"  # server ignored the range and re-sent the whole file
        with open(dest, mode) as f:
            for block in r.iter_content(chunk_size=chunk):
                f.write(block)
    if size is not None:
        assert dest.stat().st_size == size, (
            f"{dest.name}: got {dest.stat().st_size} bytes, expected {size}")
    return dest


# --- ArcGIS helpers --------------------------------------------------------
def layer_meta(session):
    """Fetch the ahupuaʻa layer's JSON metadata (fields, geometry type, etc.)."""
    r = session.get(ARCGIS_LAYER, params={"f": "json"}, timeout=30)
    r.raise_for_status()
    return r.json()


def island_extent_wgs84(session, mokupuni=None):
    """Bounding box (xmin, ymin, xmax, ymax) of one island's ahupuaʻa, in WGS84."""
    mokupuni = mokupuni or ISLAND_CFG["mokupuni"]
    r = session.get(ARCGIS_LAYER + "/query", timeout=60, params={
        "where": f"mokupuni='{mokupuni}'", "returnExtentOnly": "true",
        "outSR": 4326, "f": "json"})
    r.raise_for_status()
    e = r.json()["extent"]
    return (e["xmin"], e["ymin"], e["xmax"], e["ymax"])


def fetch_island_geojson(session, mokupuni=None, page=5000):
    """Full GeoJSON FeatureCollection for one island's ahupuaʻa, paginated.

    Pages through the layer with resultOffset so it works even if an island has
    more features than the server's maxRecordCount.
    """
    mokupuni = mokupuni or ISLAND_CFG["mokupuni"]
    feats, offset = [], 0
    while True:
        r = session.get(ARCGIS_LAYER + "/query", timeout=120, params={
            "where": f"mokupuni='{mokupuni}'", "outFields": "ahupuaa,moku,mokupuni,gisacres",
            "outSR": 4326, "resultOffset": offset, "resultRecordCount": page,
            "f": "geojson"})
        r.raise_for_status()
        fc = r.json()
        batch = fc.get("features", [])
        feats.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return {"type": "FeatureCollection", "features": feats}


# --- USGS 3DEP tiling ------------------------------------------------------
def dem_tiles_for_extent(xmin, ymin, xmax, ymax):
    """USGS 1x1-degree 1/3" tile names covering a WGS84 bbox.

    Tile 'nAAwBBB' spans lon [-BBB, -BBB+1], lat [AA-1, AA]; i.e. it is named for
    its north-west corner. We derive the covering set from the layer extent so no
    tile list is hardcoded — discover/download HEAD-check each before fetching.
    """
    tiles = []
    for west_edge in range(math.floor(xmin), math.floor(xmax) + 1):   # e.g. -159, -158
        for north_edge in range(math.ceil(ymin), math.ceil(ymax) + 1):  # e.g. 22
            tiles.append(f"n{north_edge:02d}w{-west_edge:03d}")
    return tiles


def tile_url(tile):
    return USGS_13_TILE.format(tile=tile)


# --- QA log ----------------------------------------------------------------
def write_qa_section(heading, body):
    """Insert/replace a '## <heading>' section in QA.md (idempotent on re-run)."""
    path = ROOT / "QA.md"
    text = path.read_text(encoding="utf-8") if path.exists() else "# QA log\n"
    marker = f"## {heading}"
    out, skip = [], False
    for ln in text.splitlines():
        if ln.strip() == marker:
            skip = True
            continue
        if skip and ln.startswith("## "):
            skip = False
        if not skip:
            out.append(ln)
    new = "\n".join(out).rstrip() + "\n\n" + marker + "\n\n" + body.rstrip() + "\n"
    path.write_text(new, encoding="utf-8")


# --- self-check ------------------------------------------------------------
def _selfcheck():
    # slug folds diacritics to portable ascii
    assert slug("Oʻahu") == "oahu", slug("Oʻahu")
    assert slug("Kauaʻi") == "kauai", slug("Kauaʻi")
    assert slug("Hawaiʻi") == "hawaii", slug("Hawaiʻi")
    # the ʻokina we store is the Hawaiian one (U+02BB), matching the dataset
    assert ISLAND_CFG["mokupuni"] == "Oʻahu"
    # tile math reproduces the two HEAD-verified Oʻahu tiles, nothing extra
    t = dem_tiles_for_extent(-158.282, 21.253, -157.645, 21.714)
    assert set(t) == {"n22w158", "n22w159"}, t
    # a single-degree box lands in exactly one tile
    assert dem_tiles_for_extent(-157.9, 21.3, -157.8, 21.4) == ["n22w158"]
    print("config self-check OK:", t, "| slug(Oʻahu)=", slug("Oʻahu"))


if __name__ == "__main__":
    _selfcheck()
