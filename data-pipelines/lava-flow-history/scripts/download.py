"""Phase 1 — download everything and reproject onto one common CRS.

Outputs (all resumable — existing outputs are skipped):
  processed/flows.gpkg   flow polygons in EPSG:26905 with year_sort/label/era
  processed/dem_utm.tif  island DEM mosaic reprojected to EPSG:26905

Ends at VERIFICATION GATE 1.
"""

import warnings

import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.crs import CRS
from shapely.ops import polygonize, unary_union

import config
from fetch import download, unzip

warnings.filterwarnings("ignore")

FLOWS_GPKG = config.PROCESSED / "flows.gpkg"
DEM_TIF = config.PROCESSED / "dem_utm.tif"

# One schema for every flow row, so the DS-144 base and the recent eruptions
# concatenate cleanly.
FLOW_COLUMNS = ["year_sort", "label", "era", "ptype", "source", "geometry"]


# --- flows -----------------------------------------------------------------
def build_flows():
    if FLOWS_GPKG.exists():
        print(f"  skip (exists): {FLOWS_GPKG.name}")
        return
    print("== Flows ==")
    zip_path = config.DATA / "bimp.zip"
    download(config.FLOW_ZIP_URL, zip_path, min_bytes=1_000_000)
    extract_dir = config.DATA / "ds144"
    e00 = extract_dir / config.FLOW_E00_RELPATH
    unzip(zip_path, extract_dir, marker=e00)

    gdf = read_ds144_polygons(e00)
    gdf = gdf[gdf.geometry.notna() & gdf["UNITS"].apply(config.is_lava_flow)].copy()
    ages = gdf.apply(lambda r: config.flow_age(r.UNITS, r.YEAR1, r.YEAR2),
                     axis=1, result_type="expand")
    gdf["year_sort"], gdf["label"], gdf["era"] = ages[0], ages[1], ages[2]
    gdf["ptype"] = gdf["UNITS"].astype(int)
    gdf["source"] = "DS-144"
    gdf = gdf[FLOW_COLUMNS]
    gdf = gdf.set_crs(config.TARGET_CRS, allow_override=True)  # coverage is UTM 5N

    recent = build_recent(gdf.crs)
    if len(recent):
        gdf = gpd.GeoDataFrame(pd.concat([gdf, recent], ignore_index=True), crs=gdf.crs)

    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    gdf.to_file(FLOWS_GPKG, driver="GPKG")
    print(f"  wrote {len(gdf)} flow polygons -> {FLOWS_GPKG.name} "
          f"(year_sort {gdf.year_sort.min()}..{gdf.year_sort.max()})")


def read_ds144_polygons(e00):
    """Rebuild the geology polygons from the coverage.

    GDAL's AVCE00 driver cannot assemble the polygon (PAL) layer for this
    coverage in reasonable time, but the arcs (ARC) and the per-polygon label
    points (LAB) both read quickly. We polygonize the arc network and tag each
    resulting face with the attributes of the label point it contains — exactly
    how an ArcInfo coverage encodes polygon topology.
    """
    print("  rebuilding polygons from arcs (ARC -> polygonize -> LAB join)...")
    arc = gpd.read_file(str(e00), layer="ARC")
    faces = list(polygonize(arc.geometry.values))
    poly = gpd.GeoDataFrame({"pid": range(len(faces))},
                            geometry=faces, crs=config.TARGET_CRS)
    lab = gpd.read_file(str(e00), layer="LAB").set_crs(
        config.TARGET_CRS, allow_override=True)
    joined = gpd.sjoin(poly, lab[["UNITS", "YEAR1", "YEAR2", "geometry"]],
                       predicate="contains", how="left").drop_duplicates("pid")
    matched = joined["UNITS"].notna().sum()
    print(f"    {len(faces)} faces, {matched} carry a map-unit label")
    assert matched > 100, "polygon/label join produced too few attributed faces"
    return joined[joined["UNITS"].notna()].copy()


def build_recent(target_crs):
    """Load each post-DS-144 eruption's final flow footprint as one polygon row.

    Returns a GeoDataFrame (possibly empty) of the recent flows, each stamped
    with its calendar year so it sorts as the youngest lava in its area.
    """
    rows = []
    for src in config.RECENT_SOURCES:
        geom = _recent_footprint(src, target_crs)
        if geom is None:
            print(f"  WARNING: no polygon for {src['id']}; skipping")
            continue
        print(f"  {src['id']}: {geom.area/1e6:.1f} km^2 -> year {src['year']}")
        rows.append({"year_sort": src["year"], "label": src["label"],
                     "era": "Historic (A.D. 1790 or younger)",
                     "ptype": src["ptype"], "source": src["source"], "geometry": geom})
    return gpd.GeoDataFrame(rows, columns=FLOW_COLUMNS, crs=target_crs)


def _recent_footprint(src, target_crs):
    """Extract one eruption's cumulative footprint from its shapefile zip.

    Prefer a single "*flowfootprint*" shapefile; otherwise union every polygon
    "*flow*" shapefile (covers both single-flow and daily-chronology releases).
    """
    zip_path = config.DATA / src["zip"]
    download(src["url"], zip_path, min_bytes=100_000)
    ddir = config.DATA / src["id"]
    unzip(zip_path, ddir, marker=ddir / ".extracted")
    (ddir / ".extracted").touch()

    shps = list(ddir.rglob("*.shp"))
    footprint = [p for p in shps if "flowfootprint" in p.name.lower()]
    cand = footprint or [p for p in shps if "flow" in p.name.lower()] or shps
    parts = []
    for p in cand:
        g = gpd.read_file(p)
        if g.geom_type.isin(["Polygon", "MultiPolygon"]).any():
            parts.append(g.to_crs(target_crs).geometry.unary_union)
    return unary_union(parts) if parts else None


# --- DEM -------------------------------------------------------------------
def build_dem():
    if DEM_TIF.exists():
        print(f"  skip (exists): {DEM_TIF.name}")
        return
    print("== DEM ==")
    dem_dir = config.DATA / "dem"
    tiles = []
    for t in config.DEM_TILES:
        dest = dem_dir / f"USGS_1_{t}.tif"
        try:
            download(config.dem_tile_url(t), dest, min_bytes=100_000)
            tiles.append(dest)
        except Exception as e:
            print(f"  tile {t} failed, continuing: {e}")
    assert tiles, "no DEM tiles downloaded"

    print(f"  mosaicking {len(tiles)} tiles...")
    srcs = [rasterio.open(t) for t in tiles]
    mosaic, m_transform = merge(srcs)
    src_crs = srcs[0].crs
    src_nodata = srcs[0].nodata
    for s in srcs:
        s.close()

    # Target grid: island bbox reprojected to UTM 5N, snapped to pixel size.
    dst_crs = CRS.from_user_input(config.TARGET_CRS)
    w, s, e, n = config.ISLAND_BBOX_LONLAT
    left, bottom, right, top = transform_bounds("EPSG:4326", dst_crs, w, s, e, n)
    px = config.OUTPUT_PIXEL_M
    left, bottom = np.floor(left / px) * px, np.floor(bottom / px) * px
    right, top = np.ceil(right / px) * px, np.ceil(top / px) * px
    width = int(round((right - left) / px))
    height = int(round((top - bottom) / px))
    dst_transform = rasterio.transform.from_origin(left, top, px, px)

    dst = np.full((height, width), np.nan, dtype="float32")
    reproject(source=mosaic[0], destination=dst,
              src_transform=m_transform, src_crs=src_crs, src_nodata=src_nodata,
              dst_transform=dst_transform, dst_crs=dst_crs, dst_nodata=np.nan,
              resampling=Resampling.bilinear)

    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    with rasterio.open(DEM_TIF, "w", driver="GTiff", height=height, width=width,
                       count=1, dtype="float32", crs=dst_crs,
                       transform=dst_transform, nodata=np.nan,
                       compress="deflate") as out:
        out.write(dst, 1)
    valid = np.isfinite(dst)
    print(f"  wrote DEM {width}x{height} @ {px:.0f} m -> {DEM_TIF.name}  "
          f"elev {np.nanmin(dst):.0f}..{np.nanmax(dst):.0f} m, "
          f"{100*valid.mean():.0f}% land")


# --- gate ------------------------------------------------------------------
def gate1():
    assert FLOWS_GPKG.exists() and FLOWS_GPKG.stat().st_size > 0
    assert DEM_TIF.exists() and DEM_TIF.stat().st_size > 0
    flows = gpd.read_file(FLOWS_GPKG)
    with rasterio.open(DEM_TIF) as dem:
        dem_crs, dem_bounds = dem.crs, dem.bounds
    fc = CRS.from_user_input(flows.crs)
    dc = CRS.from_user_input(dem_crs)
    tc = CRS.from_user_input(config.TARGET_CRS)
    print(f"\n  flows CRS {fc.to_authority()}, DEM CRS {dc.to_authority()}, "
          f"target {tc.to_authority()}")
    assert fc == tc and dc == tc, "CRS mismatch after reprojection"

    fb = flows.total_bounds  # minx,miny,maxx,maxy
    db = dem_bounds
    print(f"  flows extent: {tuple(round(v) for v in fb)}")
    print(f"  DEM   extent: {tuple(round(v) for v in (db.left,db.bottom,db.right,db.top))}")
    overlap = not (fb[2] < db.left or fb[0] > db.right or
                   fb[3] < db.bottom or fb[1] > db.top)
    assert overlap, "flow and DEM extents do not overlap"
    print(f"  flows: {len(flows)} polygons, year_sort "
          f"{int(flows.year_sort.min())}..{int(flows.year_sort.max())}")
    print("VERIFICATION: phase 1")


if __name__ == "__main__":
    config._selfcheck()
    build_flows()
    build_dem()
    gate1()
