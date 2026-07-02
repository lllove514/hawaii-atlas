"""Regular lat/lon grid over the island bounding box, plus a land/island mask.

The mask is built by rasterizing the bundled Hawaii coastline (a small MultiPolygon, one
polygon per island) with Pillow, then labelling connected landmasses with scipy so each
island gets its own id. The coastline is coarse, so the land footprint is dilated a couple
of cells to keep coastal stations and cells from falling in "ocean".

Grid convention used everywhere downstream: row 0 is the NORTH edge (lat descending),
column 0 is the WEST edge (lon ascending). Cell (j, i) centre is
    lon = LON_MIN + (i + 0.5) * res
    lat = LAT_MAX - (j + 0.5) * res
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, os.path.dirname(__file__))
import ghcn

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
# Compact Hawaii-only clip we build and bundle; derived once from Natural Earth 10m land.
COAST_CACHE = os.path.join(DATA, "hawaii_coast.geojson")
NE_LAND_CACHE = os.path.join(DATA, "ne_10m_land.geojson")
NE_LAND_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
               "geojson/ne_10m_land.geojson")

# Known island centroids, used only to give each labelled landmass a human name.
ISLANDS = [
    ("Hawaiʻi", 19.60, -155.50), ("Maui", 20.80, -156.33),
    ("Kahoʻolawe", 20.55, -156.60), ("Lānaʻi", 20.83, -156.92),
    ("Molokaʻi", 21.13, -157.02), ("Oʻahu", 21.47, -157.98),
    ("Kauaʻi", 22.05, -159.50), ("Niʻihau", 21.90, -160.15),
]
ISLANDS_BY_NAME = {name: (lat, lon) for name, lat, lon in ISLANDS}


def grid_shape(res):
    nx = int(round((ghcn.LON_MAX - ghcn.LON_MIN) / res))
    ny = int(round((ghcn.LAT_MAX - ghcn.LAT_MIN) / res))
    return ny, nx


def cell_centers(res):
    """Return (lats, lons) 1-D arrays of cell-centre coordinates (north->south, west->east)."""
    ny, nx = grid_shape(res)
    lons = ghcn.LON_MIN + (np.arange(nx) + 0.5) * res
    lats = ghcn.LAT_MAX - (np.arange(ny) + 0.5) * res
    return lats, lons


def grid_meta(res):
    ny, nx = grid_shape(res)
    return {"res": res, "nx": nx, "ny": ny,
            "extent": [ghcn.LON_MIN, ghcn.LON_MAX, ghcn.LAT_MIN, ghcn.LAT_MAX]}


def _build_hawaii_coast():
    """Extract the Hawaiian island polygons from Natural Earth 10m land and save a compact
    Hawaii-only MultiPolygon (outer rings, coords rounded) that doubles as the web asset."""
    if not (os.path.exists(NE_LAND_CACHE) and os.path.getsize(NE_LAND_CACHE) > 0):
        os.makedirs(DATA, exist_ok=True)
        raw = ghcn.fetch(NE_LAND_URL)
        assert raw is not None, "Natural Earth land source unavailable"
        with open(NE_LAND_CACHE, "wb") as f:
            f.write(raw)
    with open(NE_LAND_CACHE, encoding="utf-8") as f:
        land = json.load(f)

    polys = []
    for feat in land["features"]:
        g = feat["geometry"]
        shapes = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for shape in shapes:
            ring = shape[0]  # outer ring
            if any(ghcn.in_bbox(y, x) for x, y in ring):
                polys.append([[[round(x, 5), round(y, 5)] for x, y in ring]])
    assert len(polys) >= 6, "expected the main Hawaiian islands, got %d" % len(polys)

    fc = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"name": "Hawaii"},
        "geometry": {"type": "MultiPolygon", "coordinates": polys}}]}
    with open(COAST_CACHE, "w") as f:
        json.dump(fc, f)
    return fc


def load_coastline():
    if os.path.exists(COAST_CACHE) and os.path.getsize(COAST_CACHE) > 0:
        with open(COAST_CACHE, encoding="utf-8") as f:
            return json.load(f)
    return _build_hawaii_coast()


def _polygons(geojson):
    """Flatten the coastline FeatureCollection to a list of outer rings [(lon,lat), ...]."""
    rings = []
    for feat in geojson["features"]:
        geom = feat["geometry"]
        polys = geom["coordinates"]
        if geom["type"] == "Polygon":
            polys = [polys]
        for poly in polys:            # each poly: [outer_ring, hole1, ...]
            rings.append(poly[0])     # outer ring only; islands have no meaningful holes
    return rings


def island_mask(res, dilate=1):
    """Rasterize the coastline to an island-id grid.

    Returns (mask, islands) where mask is int16 (ny, nx): 0 = ocean, k>=1 = island id,
    and islands is a list of {id, name, ncells} sorted by id.
    """
    ny, nx = grid_shape(res)
    img = Image.new("1", (nx, ny), 0)
    draw = ImageDraw.Draw(img)
    for ring in _polygons(load_coastline()):
        px = [((lon - ghcn.LON_MIN) / res, (ghcn.LAT_MAX - lat) / res) for lon, lat in ring]
        draw.polygon(px, fill=1)
    land = np.array(img, dtype=bool)
    if dilate > 0:
        land = ndimage.binary_dilation(land, iterations=dilate)

    labels, n = ndimage.label(land)   # connected landmasses -> 1..n
    mask = labels.astype(np.int16)

    lats, lons = cell_centers(res)
    islands = []
    for k in range(1, n + 1):
        rows, cols = np.where(labels == k)
        clat, clon = lats[rows].mean(), lons[cols].mean()
        name = min(ISLANDS, key=lambda it: (it[1] - clat) ** 2 + (it[2] - clon) ** 2)[0]
        islands.append({"id": k, "name": name, "ncells": int(rows.size)})
    return mask, islands


def island_at(mask, res, lat, lon):
    """Island id at a coordinate, or the nearest island's id within ~5 km if over water."""
    ny, nx = mask.shape
    i = int((lon - ghcn.LON_MIN) / res)
    j = int((ghcn.LAT_MAX - lat) / res)
    if not (0 <= i < nx and 0 <= j < ny):
        return 0
    if mask[j, i]:
        return int(mask[j, i])
    r = max(1, int(round(5.0 / (res * 111))))   # search radius in cells (~5 km)
    sub = mask[max(0, j - r):j + r + 1, max(0, i - r):i + r + 1]
    nz = sub[sub > 0]
    return int(np.bincount(nz).argmax()) if nz.size else 0


def _selfcheck():
    res = 0.02
    mask, islands = island_mask(res)
    assert mask.shape == grid_shape(res)
    land = int((mask > 0).sum())
    assert land > 0, "no land cells"
    assert 6 <= len(islands) <= 8, "unexpected island count: %d" % len(islands)
    names = {it["name"] for it in islands}
    for expect in ("Hawaiʻi", "Maui", "Oʻahu", "Kauaʻi", "Molokaʻi", "Lānaʻi"):
        assert expect in names, "missing island: %s" % expect
    # Hilo (windward Big Island) and Kailua-Kona (leeward) must land on the same island.
    hilo = island_at(mask, res, 19.72, -155.05)
    kona = island_at(mask, res, 19.64, -155.99)
    assert hilo > 0 and hilo == kona, "Hilo/Kona island mismatch (%s/%s)" % (hilo, kona)
    # Honolulu must be O'ahu.
    hon = island_at(mask, res, 21.31, -157.86)
    assert next(it for it in islands if it["id"] == hon)["name"] == "Oʻahu"
    print("grid selfcheck ok: %d land cells, islands=%s"
          % (land, [(it["name"], it["ncells"]) for it in islands]))


if __name__ == "__main__":
    _selfcheck()
