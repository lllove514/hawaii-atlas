"""Phase 2 — hillshade + flow-age raster, sharing one grid.

Outputs:
  processed/hillshade.png   grayscale relief, azimuth 315 / altitude 45
  processed/flow_age.tif    per-pixel eruption year of the *youngest* flow
                            covering it (younger buries older); nodata elsewhere

Both use the exact grid of processed/dem_utm.tif, so they overlay pixel-for-pixel.

Ends at VERIFICATION GATE 2 and appends a year histogram to QA.md.
"""

import warnings

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from PIL import Image

import config

warnings.filterwarnings("ignore")

DEM_TIF = config.PROCESSED / "dem_utm.tif"
FLOWS_GPKG = config.PROCESSED / "flows.gpkg"
HILLSHADE_PNG = config.PROCESSED / "hillshade.png"
FLOW_AGE_TIF = config.PROCESSED / "flow_age.tif"
VOLCANO_TIF = config.PROCESSED / "volcano.tif"
NODATA_YEAR = -32768


def hillshade(elev, px, azimuth_deg, altitude_deg, z=1.0):
    """Standard ESRI hillshade in [0,255]. NaNs are treated as flat (sea level).

    np.gradient returns (d/drow, d/dcol); row increases southward, so d/drow is
    ESRI's y-down dz/dy and d/dcol is dz/dx — exactly the convention its aspect
    formula and the 360-az+90 azimuth conversion expect.
    """
    z_arr = np.where(np.isfinite(elev), elev, 0.0).astype("float64") * z
    dz_dy, dz_dx = np.gradient(z_arr, px, px)
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(dz_dy, -dz_dx)
    az = np.radians(360.0 - azimuth_deg + 90.0)
    zenith = np.radians(90.0 - altitude_deg)
    hs = (np.cos(zenith) * np.cos(slope) +
          np.sin(zenith) * np.sin(slope) * np.cos(az - aspect))
    return np.clip(hs, 0, 1) * 255.0


def build_hillshade():
    if HILLSHADE_PNG.exists():
        print(f"  skip (exists): {HILLSHADE_PNG.name}")
        return
    with rasterio.open(DEM_TIF) as dem:
        elev = dem.read(1)
    hs = hillshade(elev, config.OUTPUT_PIXEL_M,
                   config.HILLSHADE_AZIMUTH_DEG, config.HILLSHADE_ALTITUDE_DEG,
                   config.HILLSHADE_Z_FACTOR).astype("uint8")
    Image.fromarray(hs, mode="L").save(HILLSHADE_PNG)
    print(f"  wrote hillshade {hs.shape[1]}x{hs.shape[0]} -> {HILLSHADE_PNG.name}")


def build_flow_age():
    if FLOW_AGE_TIF.exists() and VOLCANO_TIF.exists():
        print(f"  skip (exists): {FLOW_AGE_TIF.name}, {VOLCANO_TIF.name}")
        return
    with rasterio.open(DEM_TIF) as dem:
        transform, width, height, crs = dem.transform, dem.width, dem.height, dem.crs
    flows = gpd.read_file(FLOWS_GPKG)
    # Youngest wins: burn oldest first so younger flows overwrite older ones. The
    # volcano raster burns in the *same* order, so at every pixel the winning
    # polygon (and thus its volcano) matches the age raster exactly.
    flows = flows.sort_values("year_sort", ascending=True)
    volc = (flows["ptype"].astype(int) // 100).clip(1, 5)  # 1..5 = source shield
    age = rasterize(((g, int(y)) for g, y in zip(flows.geometry, flows.year_sort)),
                    out_shape=(height, width), transform=transform,
                    fill=NODATA_YEAR, dtype="int32", all_touched=False)
    vol = rasterize(((g, int(v)) for g, v in zip(flows.geometry, volc)),
                    out_shape=(height, width), transform=transform,
                    fill=0, dtype="uint8", all_touched=False)

    with rasterio.open(FLOW_AGE_TIF, "w", driver="GTiff", height=height,
                       width=width, count=1, dtype="int32", crs=crs,
                       transform=transform, nodata=NODATA_YEAR,
                       compress="deflate") as out:
        out.write(age, 1)
    with rasterio.open(VOLCANO_TIF, "w", driver="GTiff", height=height,
                       width=width, count=1, dtype="uint8", crs=crs,
                       transform=transform, nodata=0, compress="deflate") as out:
        out.write(vol, 1)
    covered = (age != NODATA_YEAR)
    # Age and volcano cover exactly the same pixels (same burn) — cheap invariant.
    assert ((vol != 0) == covered).all(), "volcano/age coverage mismatch"
    print(f"  wrote flow_age + volcano {width}x{height}  "
          f"{100*covered.mean():.1f}% of grid is mapped lava")


def gate2():
    flows = gpd.read_file(FLOWS_GPKG)
    with rasterio.open(FLOW_AGE_TIF) as ds:
        age = ds.read(1)
        transform = ds.transform
    valid = age[age != NODATA_YEAR]
    print(f"\n  raster year range: {valid.min()}..{valid.max()}  "
          f"(polygons: {int(flows.year_sort.min())}..{int(flows.year_sort.max())})")

    # Raster range must match the polygon data.
    assert valid.min() == int(flows.year_sort.min()), "min year mismatch"
    assert valid.max() == int(flows.year_sort.max()), "max year mismatch"
    assert valid.max() == config.YOUNGEST_YEAR, \
        f"youngest raster year {valid.max()} != youngest source {config.YOUNGEST_YEAR}"

    # Spot-check the named young flows at their own locations: an interior point
    # of each footprint must rasterize to that eruption's year — i.e. the flow is
    # present and (being youngest there) buries the older lava beneath it.
    from rasterio.warp import transform as warp_xy
    for year, name in [(2018, "Kīlauea LERZ"), (2022, "Mauna Loa NE Rift")]:
        rows_y = flows.loc[flows.year_sort == year, "geometry"]
        assert len(rows_y), f"no {year} {name} polygon in flow layer"
        pt = rows_y.iloc[0].representative_point()
        lon, lat = (v[0] for v in warp_xy(config.TARGET_CRS, "EPSG:4326", [pt.x], [pt.y]))
        col, row = ~transform * (pt.x, pt.y)
        got = int(age[int(row), int(col)])
        print(f"  sample @ {year} {name} ({lon:.3f}, {lat:.3f}): {got}")
        assert got == year, f"expected {year} at {name} location, got {got}"

    # Historic flows must be present as the most-recent ages generally.
    historic = (valid >= 1790).sum()
    print(f"  historic-age pixels (>=1790): {historic}")
    assert historic > 100, "too few historic-age pixels"

    write_histogram(valid, flows)
    print("VERIFICATION: phase 2")


def write_histogram(valid, flows):
    # Pixel histogram grouped by era (via the polygon era labels).
    era_by_year = (flows.groupby("year_sort")["era"].first().to_dict())
    from collections import Counter
    px_by_era = Counter()
    years, counts = np.unique(valid, return_counts=True)
    for y, c in zip(years.tolist(), counts.tolist()):
        px_by_era[era_by_year.get(y, "unknown")] += c
    px = config.OUTPUT_PIXEL_M
    km2 = (px * px) / 1e6
    lines = ["", "## Phase 2 — flow-age raster year histogram", "",
             f"Grid {px:.0f} m/pixel; each pixel = {km2:.4f} km^2. "
             "Area is the youngest flow at each pixel (younger buries older).",
             "", "| Era | pixels | area (km^2) |", "| --- | ---: | ---: |"]
    # Order eras oldest->youngest by the min year_sort mapping to each.
    order = sorted(px_by_era, key=lambda e: min(
        (y for y, ee in era_by_year.items() if ee == e), default=0))
    for e in order:
        n = px_by_era[e]
        lines.append(f"| {e} | {n:,} | {n*km2:,.2f} |")
    header = "## Phase 2 — flow-age raster year histogram"
    block = "\n".join(lines)
    qa = config.ROOT / "QA.md"
    text = qa.read_text() if qa.exists() else ""
    if header in text:
        # Replace just this section (up to the next "## " header) so re-runs are
        # idempotent and any later QA sections survive.
        before, _, rest = text.partition(header)
        after = rest.partition("\n## ")[2]
        after = ("\n## " + after) if after else ""
        text = before.rstrip() + "\n\n" + block + after
        qa.write_text(text)
    else:
        with open(qa, "a") as f:
            f.write("\n" + block)
    print("  wrote year histogram to QA.md")


def _selfcheck():
    # Flat ground -> uniform mid tone; a NW-facing slope (toward az 315 light)
    # must be brighter than the SE-facing slope of the same ridge.
    flat = np.zeros((5, 5))
    hs_flat = hillshade(flat, config.OUTPUT_PIXEL_M, 315, 45)
    assert np.allclose(hs_flat, hs_flat[0, 0]), "flat hillshade not uniform"
    yy, xx = np.mgrid[0:20, 0:20]
    # Ground rising toward SE faces NW (aspect = downhill), so it catches the
    # az-315 light; ground rising toward NW faces SE and falls into shadow.
    se_up = (xx + yy).astype(float) * 5
    assert hillshade(se_up, config.OUTPUT_PIXEL_M, 315, 45)[10, 10] > hs_flat[0, 0], \
        "NW-facing slope should be lit"
    nw_up = -(xx + yy).astype(float) * 5
    assert hillshade(nw_up, config.OUTPUT_PIXEL_M, 315, 45)[10, 10] < hs_flat[0, 0], \
        "SE-facing slope should be shaded"
    print("build_rasters self-check OK")


if __name__ == "__main__":
    _selfcheck()
    build_hillshade()
    build_flow_age()
    gate2()
