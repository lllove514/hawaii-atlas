"""Phase 0 — locate and verify the two data sources for the chosen island.

Confirms, without downloading anything heavy, that:
  * the Hawaiʻi Statewide GIS ahupuaʻa layer loads, with UTF-8 names intact and
    more than one feature on the island, and reports its CRS + key attributes;
  * the USGS 3DEP tiles that cover the island's extent actually exist and, read
    straight from their HTTP headers, span that extent at ~10 m resolution.

Run:  python scripts/discover_source.py
"""

import sys

import rasterio

import config as C


def main():
    session = C.make_session()
    isl = C.ISLAND
    mokupuni = C.ISLAND_CFG["mokupuni"]
    print(f"# Discovering sources for {isl} (mokupuni='{mokupuni}')\n")

    # --- Ahupuaʻa boundary layer -------------------------------------------
    meta = C.layer_meta(session)
    sr = meta.get("extent", {}).get("spatialReference", {})
    layer_crs = sr.get("latestWkid") or sr.get("wkid")
    fields = [f["name"] for f in meta.get("fields", [])]
    print("Ahupuaʻa layer:", C.ARCGIS_LAYER)
    print("  name        :", meta.get("name"))
    print("  geometryType:", meta.get("geometryType"))
    print("  CRS (wkid)  :", layer_crs)
    print("  attributes  :", ", ".join(fields))

    fc = C.fetch_island_geojson(session, mokupuni)
    feats = fc["features"]
    names = [f["properties"]["ahupuaa"] for f in feats]
    mokus = sorted({f["properties"]["moku"] for f in feats})
    print(f"  {isl} features: {len(feats)}")
    print("  moku present :", ", ".join(mokus))
    print("  sample names :", ", ".join(names[:6]))

    # --- Elevation (USGS 3DEP) ---------------------------------------------
    ext = C.island_extent_wgs84(session, mokupuni)
    print(f"\n{isl} ahupuaʻa extent (WGS84):")
    print("  lon [%.4f, %.4f]  lat [%.4f, %.4f]" % (ext[0], ext[2], ext[1], ext[3]))
    tiles = C.dem_tiles_for_extent(*ext)
    print("USGS 3DEP 1/3\" tiles covering it:", ", ".join(tiles))

    dem_bounds = []   # (left, bottom, right, top) of each verified tile
    resolutions = []
    for t in tiles:
        url = C.tile_url(t)
        size = C.remote_size(url, session)     # HEAD: proves it exists
        with rasterio.open("/vsicurl/" + url) as ds:  # header read over HTTP range
            b = ds.bounds
            dem_bounds.append((b.left, b.bottom, b.right, b.top))
            resolutions.append(ds.res)
            print(f"  {t}: {size/1e6:6.1f} MB  CRS {ds.crs.to_epsg()}  "
                  f"res {ds.res[0]*3600:.2f}\"  bounds "
                  f"[{b.left:.2f},{b.bottom:.2f},{b.right:.2f},{b.top:.2f}]")

    # union of tile bounds
    left = min(b[0] for b in dem_bounds); bottom = min(b[1] for b in dem_bounds)
    right = max(b[2] for b in dem_bounds); top = max(b[3] for b in dem_bounds)
    print("DEM union extent (WGS84):")
    print("  lon [%.4f, %.4f]  lat [%.4f, %.4f]" % (left, right, bottom, top))

    # --- VERIFICATION GATE 0 ------------------------------------------------
    assert len(feats) > 1, "ahupuaʻa layer returned <=1 feature for the island"
    # UTF-8 names: at least one real Hawaiian diacritic survived the round trip
    joined = "".join(names)
    assert any(ch in joined for ch in "ʻāēīōūĀĒĪŌŪ"), \
        "no ʻokina/macron found in names — UTF-8 likely mangled"
    for n in names:
        assert n and isinstance(n, str) and "�" not in n, f"bad name: {n!r}"
    assert {"ahupuaa", "moku", "mokupuni"} <= set(fields), "expected attributes missing"
    # DEM must cover the whole island extent (with a hair of tolerance)
    tol = 1e-6
    assert left <= ext[0] + tol and right >= ext[2] - tol \
        and bottom <= ext[1] + tol and top >= ext[3] - tol, \
        "DEM tiles do not fully cover the ahupuaʻa extent"
    # resolution really is ~1/3 arc-second (~10 m)
    assert all(abs(r[0] * 3600 - 1 / 3) < 0.02 for r in resolutions), \
        f"unexpected DEM resolution: {resolutions}"

    print("\nVERIFICATION: phase 0")
    print(f"  ahupuaʻa: {len(feats)} features, UTF-8 names OK, CRS {layer_crs}")
    print(f"  DEM: {len(tiles)} tiles @ ~1/3\" cover the island extent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
