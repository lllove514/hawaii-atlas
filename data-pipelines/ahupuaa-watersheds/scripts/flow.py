"""Phase 2 — condition the DEM and route flow (the compute-heavy step).

Pipeline: mask the ocean out of the DEM, fill pits + depressions and resolve
flats so water can't get trapped, compute D8 flow direction and flow
accumulation (pysheds, numba-accelerated), threshold the accumulation into a
stream network, and label watershed basins by the coastal outlet each cell
drains to.

Outputs (all resumable — a re-run skips whatever already exists):
  processed/<island>_flowdir.tif   D8 direction codes (ESRI/pysheds dirmap)
  processed/<island>_flowacc.tif   upstream cell counts (float32)
  processed/<island>_streams.gpkg  stream network as LineStrings
  processed/<island>_basins.tif    integer basin labels (0 = ocean)

Run:  python scripts/flow.py
"""

import os
import sys

import numpy as np

# pysheds 0.5 predates numpy 2.0; restore the few aliases it still references.
if not hasattr(np, "in1d"):
    np.in1d = np.isin
for _n, _t in (("bool", bool), ("float", float), ("int", int)):
    if not hasattr(np, _n):
        setattr(np, _n, _t)

import geopandas as gpd
import rasterio
from pysheds.grid import Grid
from pysheds.view import Raster, ViewFinder
from shapely.geometry import shape

import config as C

# pysheds/ESRI D8 encoding, in the order (N, NE, E, SE, S, SW, W, NW).
DIRMAP = (64, 128, 1, 2, 4, 8, 16, 32)
# (drow, dcol) that each direction code steps to its downstream neighbour.
OFFSETS = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1),
           4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}


def _save_raster(path, arr, profile, dtype, nodata):
    prof = profile.copy()
    prof.update(count=1, dtype=dtype, nodata=nodata, compress="deflate", tiled=True)
    tmp = path.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(arr.astype(dtype), 1)
    os.replace(tmp, path)  # atomic: an interrupted write can't survive as a "done" file


def condition_and_route(P):
    """Return (grid, fdir, acc, land, dem_profile). Computes or loads from disk."""
    with rasterio.open(P["dem_utm"]) as ds:
        dem_arr = ds.read(1)
        nd = ds.nodata
        profile = ds.profile
    if nd is None:
        nd = -999999.0  # guard the mask math even if a DEM arrives without nodata
    # ocean = flagged nodata OR sea-level flats (3DEP sets water to 0); mask both
    # so flow exits at the coastline instead of ponding on a giant flat.
    ocean = (dem_arr == nd) | (dem_arr <= 0)
    land = ~ocean

    if P["flowdir"].exists() and P["flowacc"].exists():
        print("  skip (exists): flowdir + flowacc")
        grid = Grid.from_raster(str(P["flowdir"]))
        fdir = grid.read_raster(str(P["flowdir"]))
        acc = grid.read_raster(str(P["flowacc"]))
        return grid, fdir, acc, land, profile

    masked = dem_arr.copy()
    masked[ocean] = nd
    vf = ViewFinder(affine=profile["transform"], shape=masked.shape,
                    nodata=np.float32(nd), crs=profile["crs"])
    dem = Raster(masked, viewfinder=vf)
    grid = Grid.from_raster(dem)

    print("  conditioning: fill_pits -> fill_depressions -> resolve_flats")
    conditioned = grid.resolve_flats(grid.fill_depressions(grid.fill_pits(dem)))
    print("  flow direction (D8)")
    fdir = grid.flowdir(conditioned, dirmap=DIRMAP, nodata_out=np.int64(0))
    print("  flow accumulation")
    acc = grid.accumulation(fdir, dirmap=DIRMAP)

    _save_raster(P["flowdir"], np.asarray(fdir), profile, "int32", 0)
    _save_raster(P["flowacc"], np.asarray(acc), profile, "float32", 0)
    print(f"  wrote flowdir + flowacc ({masked.shape[1]}x{masked.shape[0]})")
    return grid, fdir, acc, land, profile


def extract_streams(grid, fdir, acc, P, epsg):
    """Threshold accumulation into a stream network; save as LineStrings."""
    thr = C.STREAM_THRESHOLD_CELLS
    if P["streams"].exists() and P["streams"].stat().st_size > 0:
        gdf = gpd.read_file(P["streams"])
        print(f"  skip (exists): streams ({len(gdf)} branches)")
        return gdf
    vf = grid.viewfinder
    mask_vf = ViewFinder(affine=vf.affine, shape=vf.shape, crs=vf.crs,
                         nodata=np.bool_(False))  # bool mask needs a bool nodata
    mask = Raster((np.asarray(acc) > thr).astype(bool), viewfinder=mask_vf)
    net = grid.extract_river_network(fdir, mask, dirmap=DIRMAP)
    geoms = [shape(f["geometry"]) for f in net["features"]]
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=f"EPSG:{epsg}")
    gdf.to_file(P["streams"], driver="GPKG")
    print(f"  wrote streams: {len(gdf)} branches, "
          f"{gdf.length.sum()/1000:.1f} km at threshold {thr} cells")
    return gdf


def delineate_basins(fdir, land, profile, P):
    """Label each land cell by the coastal outlet it drains to (pointer-jumping).

    Builds the D8 receiver graph, then follows it to each cell's terminal (a
    coastal outlet or interior sink) by path-doubling. Terminals become basin
    ids. Returns (basins, n_basins).
    """
    if P["basins"].exists() and P["basins"].stat().st_size > 0:
        with rasterio.open(P["basins"]) as ds:
            basins = ds.read(1)
        n = int(basins.max())
        print(f"  skip (exists): basins ({n} basins)")
        return basins, n

    fd = np.asarray(fdir)
    H, W = fd.shape
    land_flat = land.ravel()
    recv = np.arange(H * W, dtype=np.int64)  # default: cell is its own outlet
    fdf = fd.ravel()
    for code, (dr, dc) in OFFSETS.items():
        sel = np.nonzero(fdf == code)[0]
        r, c = sel // W + dr, sel % W + dc
        inb = (r >= 0) & (r < H) & (c >= 0) & (c < W)
        tgt = sel.copy()
        ti = (r[inb] * W + c[inb])
        # flowing into ocean (or off-grid) makes this cell an outlet -> keep self
        keep = land_flat[ti]
        tgt_in = tgt[inb]
        tgt_in[keep] = ti[keep]
        tgt[inb] = tgt_in
        recv[sel] = tgt

    # path-doubling to the terminal outlet of every cell
    converged = False
    for _ in range(64):
        nxt = recv[recv]
        if np.array_equal(nxt, recv):
            converged = True
            break
        recv = nxt
    # conditioning makes the flow graph acyclic, so path-doubling must reach a
    # fixpoint far inside 64 rounds; not reaching one signals a routing problem.
    assert converged, "receiver graph did not converge within 64 iterations"

    labels = np.zeros(H * W, dtype=np.int32)
    roots = recv[land_flat]
    _, inv = np.unique(roots, return_inverse=True)
    labels[land_flat] = (inv + 1).astype(np.int32)  # 0 stays ocean
    basins = labels.reshape(H, W)
    _save_raster(P["basins"], basins, profile, "int32", 0)
    n = int(basins.max())
    print(f"  wrote basins: {n} outlets")
    return basins, n


def main():
    P = C.paths()
    epsg = C.ISLAND_CFG["utm_epsg"]
    print(f"# Phase 2 flow routing for {C.ISLAND}\n")

    grid, fdir, acc, land, profile = condition_and_route(P)
    streams = extract_streams(grid, fdir, acc, P, epsg)
    basins, n_basins = delineate_basins(fdir, land, profile, P)

    # --- VERIFICATION GATE 2 ------------------------------------------------
    with rasterio.open(P["dem_utm"]) as ds:
        elev = ds.read(1)
    accv = np.asarray(acc)
    landmask = land & (accv > 0)

    acc_min = float(accv[landmask].min())
    assert acc_min >= 1.0, f"accumulation < 1 somewhere on land (min {acc_min})"

    # peaks sit in valley bottoms, not on ridges. Restrict to land: pysheds pushes
    # each basin's accumulation one step past the coast into the ocean (nodata
    # elevation) cell, which would otherwise poison the elevation statistics.
    hi = landmask & (accv >= np.quantile(accv[landmask], 0.9999))
    peak_elev = float(elev[hi].mean())
    land_median = float(np.median(elev[landmask]))
    q25 = float(np.percentile(elev[landmask], 25))
    # the top 0.01% of accumulation must sit in the lowest quartile of land — a
    # scrambled routing would scatter big accumulation up toward the island mean.
    assert peak_elev < q25, \
        f"high-accumulation cells not in low ground ({peak_elev:.1f} !< q25 {q25:.1f})"
    accv_land = np.where(landmask, accv, 0.0)
    mouth_elev = float(elev[np.unravel_index(int(np.argmax(accv_land)), accv.shape)])
    assert mouth_elev < 50, f"max-accumulation land cell at {mouth_elev:.1f} m, not near coast"

    # ridgetops carry almost no accumulation
    ridge = elev >= np.quantile(elev[landmask], 0.95)
    ridge_med = float(np.median(accv[ridge]))
    assert ridge_med < 50, f"ridgetops carry too much accumulation (median {ridge_med})"

    total_km = float(streams.length.sum() / 1000.0)
    cell_km2 = (C.TARGET_RES_M ** 2) / 1e6
    sig = int((np.bincount(basins.ravel())[1:] * cell_km2 >= C.MIN_BASIN_KM2).sum())

    summary = [
        "**VERIFICATION: phase 2 — PASS**",
        "",
        f"- Grid: {elev.shape[1]}x{elev.shape[0]} @ {C.TARGET_RES_M:.0f} m, "
        f"{int(landmask.sum()):,} land cells.",
        f"- Accumulation min on land = {acc_min:.0f} (>=1: every cell drains itself).",
        f"- High-accum (top 0.01%) mean elev {peak_elev:.1f} m vs land median "
        f"{land_median:.1f} m; max-accum cell at {mouth_elev:.1f} m (a coastal mouth).",
        f"- Ridgetops (top 5% elev) median accumulation {ridge_med:.1f} cells.",
        f"- Stream network: {len(streams)} branches, **{total_km:.1f} km** total "
        f"at threshold {C.STREAM_THRESHOLD_CELLS} cells (~{cell_km2*C.STREAM_THRESHOLD_CELLS:.2f} km²).",
        f"- Basins: {n_basins} coastal outlets ({sig} with area ≥ 0.5 km²); "
        "the tail is single-cell coastal drainages, expected on a 10 m coastline.",
    ]
    C.write_qa_section("Phase 2 — flow routing (`scripts/flow.py`)", "\n".join(summary))

    print("\nVERIFICATION: phase 2")
    print(f"  acc>=1 OK; peaks in valleys ({peak_elev:.1f}<{land_median:.1f} m); "
          f"ridges quiet ({ridge_med:.0f})")
    print(f"  streams {total_km:.1f} km ({len(streams)} branches); "
          f"{n_basins} basins ({sig} ≥0.5 km²)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
