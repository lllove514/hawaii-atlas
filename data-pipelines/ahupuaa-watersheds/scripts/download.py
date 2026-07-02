"""Phase 1 — download the two layers and align them in a common metric CRS.

Overnight-safe: every step skips work whose output already exists, and the DEM
tile fetch resumes partial files with HTTP Range (see config.download_file). The
end state is two aligned products in the island's UTM zone:
  processed/<island>_dem_utm.tif      (DEM, metres, ~10 m grid)
  processed/<island>_ahupuaa_utm.gpkg (boundaries, same CRS)

Run:  python scripts/download.py
"""

import json
import os
import sys

import geopandas as gpd
import rasterio
from rasterio.merge import merge
from rasterio.warp import calculate_default_transform, reproject, Resampling

import config as C


def fetch_ahupuaa(session, P):
    """Download the island's ahupuaʻa boundaries as raw WGS84 GeoJSON."""
    dst = P["ahupuaa_raw"]
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  skip (exists): {dst.name}")
        return
    fc = C.fetch_island_geojson(session)
    dst.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {dst.name}: {len(fc['features'])} features")


def fetch_dem(session, P, ext):
    """Download the covering 3DEP tiles, then mosaic+clip to the island bbox."""
    dst = P["dem_raw"]
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  skip (exists): {dst.name}")
        return
    tiles = C.dem_tiles_for_extent(*ext)
    tile_paths = []
    for t in tiles:
        tp = C.DATA / f"USGS_13_{t}.tif"
        C.download_file(C.tile_url(t), tp, session)
        print(f"  have tile {t}: {tp.stat().st_size/1e6:.1f} MB")
        tile_paths.append(tp)

    # mosaic only the window we need (bbox + ~2 km margin) to bound memory
    m = 0.02  # degrees
    bounds = (ext[0] - m, ext[1] - m, ext[2] + m, ext[3] + m)
    with rasterio.open(tile_paths[0]) as s0:
        prof = s0.profile
    mosaic, transform = merge(tile_paths, bounds=bounds)  # opens/closes the tiles
    prof.update(height=mosaic.shape[1], width=mosaic.shape[2],
                transform=transform, compress="deflate", tiled=True)
    tmp = dst.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **prof) as out:
        out.write(mosaic)
    os.replace(tmp, dst)  # atomic: a killed write can't masquerade as complete
    print(f"  wrote {dst.name}: {mosaic.shape[2]}x{mosaic.shape[1]} cells")


def reproject_dem(P, dst_epsg):
    """Warp the WGS84 DEM to the island's UTM zone at ~10 m."""
    dst = P["dem_utm"]
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  skip (exists): {dst.name}")
        return
    with rasterio.open(P["dem_raw"]) as src:
        nd = src.nodata
        dst_crs = rasterio.crs.CRS.from_epsg(dst_epsg)
        transform, w, h = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds,
            resolution=C.TARGET_RES_M)
        prof = src.profile.copy()
        prof.update(crs=dst_crs, transform=transform, width=w, height=h,
                    nodata=nd, compress="deflate", tiled=True)
        tmp = dst.with_suffix(".tmp.tif")
        with rasterio.open(tmp, "w", **prof) as out:
            reproject(
                source=rasterio.band(src, 1), destination=rasterio.band(out, 1),
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=transform, dst_crs=dst_crs,
                src_nodata=nd, dst_nodata=nd,  # off-footprint stays nodata, not 0
                resampling=Resampling.bilinear)
        os.replace(tmp, dst)
    print(f"  wrote {dst.name}: {w}x{h} cells @ {C.TARGET_RES_M} m")


def reproject_ahupuaa(P, dst_epsg):
    """Reproject the boundaries to the same UTM zone (GeoPackage, UTF-8 safe)."""
    dst = P["ahupuaa_utm"]
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  skip (exists): {dst.name}")
        return
    gdf = gpd.read_file(P["ahupuaa_raw"]).to_crs(epsg=dst_epsg)
    gdf.to_file(dst, driver="GPKG")
    print(f"  wrote {dst.name}: {len(gdf)} features in EPSG:{dst_epsg}")


def main():
    session = C.make_session()
    P = C.paths()
    epsg = C.ISLAND_CFG["utm_epsg"]
    print(f"# Phase 1 download + align for {C.ISLAND} -> EPSG:{epsg}\n")

    ext = C.island_extent_wgs84(session)
    print("Ahupuaʻa boundaries:")
    fetch_ahupuaa(session, P)
    print("DEM (USGS 3DEP):")
    fetch_dem(session, P, ext)
    print("Reproject to metric CRS:")
    reproject_dem(P, epsg)
    reproject_ahupuaa(P, epsg)

    # --- VERIFICATION GATE 1 ------------------------------------------------
    for key in ("dem_utm", "ahupuaa_utm"):
        assert P[key].exists() and P[key].stat().st_size > 0, f"missing/empty: {P[key]}"
    with rasterio.open(P["dem_utm"]) as dem:
        dem_crs, dem_bounds = dem.crs.to_epsg(), dem.bounds
        res = dem.res
    gdf = gpd.read_file(P["ahupuaa_utm"])
    vec_crs = gdf.crs.to_epsg()
    vb = gdf.total_bounds  # minx, miny, maxx, maxy

    assert dem_crs == epsg == vec_crs, f"CRS mismatch: dem {dem_crs}, vec {vec_crs}"
    assert abs(res[0] - C.TARGET_RES_M) < 0.5, f"DEM res {res} != {C.TARGET_RES_M} m"
    tol = 5.0  # metres
    assert (vb[0] >= dem_bounds.left - tol and vb[2] <= dem_bounds.right + tol and
            vb[1] >= dem_bounds.bottom - tol and vb[3] <= dem_bounds.top + tol), \
        f"vector extent {vb} not within DEM extent {tuple(dem_bounds)}"
    # names still clean after reprojection round-trip
    names = "".join(gdf["ahupuaa"].astype(str))
    assert "�" not in names and any(c in names for c in "ʻāēīōū"), "names mangled"

    print("\nVERIFICATION: phase 1")
    print(f"  DEM {res[0]:.1f} m EPSG:{dem_crs}, {gdf.shape[0]} ahupuaʻa in EPSG:{vec_crs}")
    print(f"  vector extent within DEM extent (tol {tol} m); names UTF-8 clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
