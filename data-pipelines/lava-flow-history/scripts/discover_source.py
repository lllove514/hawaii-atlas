"""Phase 0 — locate and verify the data sources.

Downloads the flow-polygon dataset (small enough to grab whole) and probes the
DEM tiles over the network, then reports:
  * the flow layer's CRS, feature count, and the age attribute distribution;
  * the DEM's CRS, resolution, and extent, and whether the tiles cover the
    island.

Ends at VERIFICATION GATE 0 with hard asserts.
"""

import warnings

import pyogrio
import rasterio
from rasterio.crs import CRS

import config
from fetch import download, unzip

warnings.filterwarnings("ignore")


def probe_flows():
    print("== Flow polygons: USGS DS-144 geologic map of the Island of Hawaii ==")
    zip_path = config.DATA / "bimp.zip"
    download(config.FLOW_ZIP_URL, zip_path, min_bytes=1_000_000)
    extract_dir = config.DATA / "ds144"
    e00 = extract_dir / config.FLOW_E00_RELPATH
    unzip(zip_path, extract_dir, marker=e00)

    # GDAL cannot assemble the polygon (PAL) layer for this coverage in bounded
    # time; the per-polygon label points (LAB) carry the same attributes and
    # read fine, so we probe those. Phase 1 rebuilds the polygons from the arcs.
    info = pyogrio.read_info(str(e00), layer="LAB")
    crs = CRS.from_user_input(info["crs"])
    fields = list(info["fields"])
    print(f"  layer         : LAB (label points; polygons rebuilt in Phase 1)")
    print(f"  CRS           : {crs.to_string()}  ({crs.to_authority()})")
    print(f"  fields        : {fields}")

    # Read attributes only (no geometry) for the value distribution.
    print("  reading label attributes (~3 min, AVCE00 driver is slow)...")
    gdf = pyogrio.read_dataframe(str(e00), layer="LAB",
                                 columns=["UNITS", "LABEL", "YEAR1", "YEAR2"],
                                 read_geometry=False)
    n = len(gdf)
    lava = gdf[gdf["UNITS"].apply(config.is_lava_flow)]
    dated = lava[lava["YEAR1"] > 0]
    print(f"  total polygons: {n}")
    print(f"  lava-flow polygons (mapped): {len(lava)}")
    print(f"  historically dated (YEAR1>0): {len(dated)}  "
          f"range {int(dated.YEAR1.min())}-{int(dated.YEAR1.max())}")
    print("  age classes present (unit code -> era, count):")
    counts = lava["UNITS"].value_counts()
    for ptype, c in counts.items():
        era = config.PTYPE_AGE[int(ptype)][3]
        print(f"    {int(ptype):>4}  {era:<34} {c:>5}")

    # GATE: > 100 features and a usable age field.
    assert n > 100, f"flow layer has only {n} features"
    assert "YEAR1" in fields and "UNITS" in fields, "missing age fields"
    assert len(lava) > 100, f"only {len(lava)} lava-flow polygons"
    assert len(dated) > 20, "no historically dated flows found"
    return crs


def probe_dem():
    print("\n== DEM: USGS 3DEP 1 arc-second ==")
    reachable, bounds_union = [], None
    ref = None
    for tile in config.DEM_TILES:
        url = config.dem_tile_url(tile)
        vsi = f"/vsicurl/{url}"
        try:
            with rasterio.open(vsi) as ds:
                b = ds.bounds
                reachable.append(tile)
                bounds_union = _union(bounds_union, b)
                if ref is None:
                    ref = (ds.crs, ds.res)
                print(f"  {tile}: {ds.width}x{ds.height}  res={ds.res[0]:.6g} deg  "
                      f"bounds=({b.left:.3f},{b.bottom:.3f},{b.right:.3f},{b.top:.3f})")
        except Exception as e:
            print(f"  {tile}: unreachable ({e})")

    crs, res = ref
    print(f"  DEM CRS       : {crs.to_string()}  ({crs.to_authority()})")
    print(f"  DEM cell size : {res[0]:.6g} deg (~{res[0]*111320:.0f} m)")
    print(f"  covered extent: {tuple(round(v,3) for v in bounds_union)}")

    # GATE: tiles reachable and their union covers the island bbox.
    w, s, e, n = config.ISLAND_BBOX_LONLAT
    ul, ub, ur, ut = bounds_union
    assert len(reachable) >= 4, f"only {len(reachable)} DEM tiles reachable"
    assert ul <= w and ub <= s and ur >= e and ut >= n, \
        f"DEM extent {bounds_union} does not cover island {config.ISLAND_BBOX_LONLAT}"
    return crs


def probe_recent():
    print("\n== Recent eruptions (post-DS-144 USGS data releases) ==")
    import requests
    ok = 0
    for src in config.RECENT_SOURCES:
        try:
            r = requests.get(src["url"], stream=True, timeout=60,
                             headers={"User-Agent": "lava-flow-history-map/1.0"})
            r.raise_for_status()
            size = int(r.headers.get("content-length", 0))
            r.close()
            print(f"  {src['id']:<18} year {src['year']}  reachable "
                  f"({size/1e6:.1f} MB)  {src['source']}")
            ok += 1
        except Exception as e:
            print(f"  {src['id']:<18} UNREACHABLE: {e}")
    # GATE: every recent source the map claims must actually resolve.
    assert ok == len(config.RECENT_SOURCES), \
        f"only {ok}/{len(config.RECENT_SOURCES)} recent sources reachable"


def _union(acc, b):
    if acc is None:
        return [b.left, b.bottom, b.right, b.top]
    return [min(acc[0], b.left), min(acc[1], b.bottom),
            max(acc[2], b.right), max(acc[3], b.top)]


if __name__ == "__main__":
    config._selfcheck()
    flow_crs = probe_flows()
    dem_crs = probe_dem()
    probe_recent()
    print("\nSummary:")
    print(f"  flows CRS {flow_crs.to_authority()}, DEM CRS {dem_crs.to_authority()};"
          f" both reproject to {config.TARGET_CRS} in Phase 1.")
    print("VERIFICATION: phase 0")
