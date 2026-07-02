"""Phase 3 — pack the processed grids into a compact browser payload.

The front end colours the data itself (so SST/DHW toggle needs no re-render), so
we ship raw scaled arrays, not pre-rendered tiles:

    sst.i16.gz    Int16 LE, (frames, nlat, nlon), value = degC * 20,
                  sentinel -32768 = no data (land or cloud); gzipped
    dhw.u8.gz     UInt8,    (frames, nlat, nlon), value = degC-weeks * 10; gzipped
                  (DHW is defined on all water pixels; land uses the mask)
    mask.u8       UInt8,    (nlat, nlon), 1 = water, 0 = land
    coast.json    island coastlines (GeoJSON), traced from the land mask
    manifest.json grid, dates, scales, thresholds, per-year max DHW

written to the atlas-level data/reef-heat-atlas/ directory.

Run:  python scripts/build_web.py
"""
import gzip
import json
import os

import numpy as np
import xarray as xr

import config

IN_NC = os.path.join(config.PROC_DIR, "reef_weekly.nc")
IN_META = os.path.join(config.PROC_DIR, "meta.json")

SST_SCALE = 20      # Int16: 0.05 degC resolution
DHW_SCALE = 10      # UInt8: 0.1 degC-week resolution
DHW_CLIP = 25.0     # ponytail: UInt8 ceiling; Hawaii DHW stays well under this.
                    # If a hotter basin ever exceeds it, switch dhw.u8 to Int16.
NODATA_I16 = -32768


def coastline_segments(water, lat, lon):
    """Trace island outlines as the pixel edges where water meets land.

    Returns a GeoJSON MultiLineString: blocky at 5 km, but exact to the mask and
    fully self-contained (no external coastline download)."""
    dlat = float(lat[1] - lat[0])
    dlon = float(lon[1] - lon[0])
    segs = []
    nlat, nlon = water.shape
    for i in range(nlat):
        for j in range(nlon - 1):                 # vertical edges
            if water[i, j] != water[i, j + 1]:
                x = (lon[j] + lon[j + 1]) / 2
                segs.append([[x, lat[i] - dlat / 2], [x, lat[i] + dlat / 2]])
    for i in range(nlat - 1):                     # horizontal edges
        for j in range(nlon):
            if water[i, j] != water[i + 1, j]:
                y = (lat[i] + lat[i + 1]) / 2
                segs.append([[lon[j] - dlon / 2, y], [lon[j] + dlon / 2, y]])
    return {"type": "MultiLineString",
            "coordinates": [[[round(float(a), 4), round(float(b), 4)] for a, b in s]
                            for s in segs]}


def remove_specks(water, sst, dhw):
    """Reclassify isolated single-cell land specks (a land pixel with no land
    neighbour) as ocean, infilling SST/DHW from their 4-neighbours. Removes lone
    reef rocks that read as stray pixels; multi-cell islands are untouched."""
    land = ~water
    neigh = np.zeros(land.shape, dtype=int)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di == 0 and dj == 0:
                continue
            neigh += np.roll(np.roll(land, di, 0), dj, 1) & _no_wrap(land.shape, di, dj)
    isolated = np.argwhere(land & (neigh == 0))
    nlat, nlon = water.shape
    for i, j in isolated:
        nb = [(i + a, j + b) for a, b in ((-1, 0), (1, 0), (0, -1), (0, 1))
              if 0 <= i + a < nlat and 0 <= j + b < nlon and water[i + a, j + b]]
        if not nb:
            continue
        rows, cols = zip(*nb)
        water[i, j] = True
        sst[:, i, j] = np.nanmean(sst[:, rows, cols], axis=1)
        dhw[:, i, j] = np.nanmean(dhw[:, rows, cols], axis=1)
    if len(isolated):
        print("  removed %d isolated land speck(s)" % len(isolated))
    return water, sst, dhw


def _no_wrap(shape, di, dj):
    """Mask that is False on the edge rows/cols a np.roll would wrap in from."""
    m = np.ones(shape, dtype=bool)
    if di == 1:
        m[0, :] = False
    elif di == -1:
        m[-1, :] = False
    if dj == 1:
        m[:, 0] = False
    elif dj == -1:
        m[:, -1] = False
    return m


def main():
    if not os.path.exists(IN_NC):
        raise SystemExit("Missing %s — run compute_dhw.py first." % IN_NC)
    os.makedirs(config.WEB_DATA_DIR, exist_ok=True)

    with xr.open_dataset(IN_NC) as ds:
        sst = ds["sst"].values                    # (frames, nlat, nlon) float32
        dhw = ds["dhw"].values
        lat = ds["latitude"].values
        lon = ds["longitude"].values
        dates = [str(t)[:10] for t in ds["time"].values]
    meta = json.load(open(IN_META))

    # Normalise orientation to row 0 = north, col 0 = west, so the browser draws
    # row 0 at the top with no flips and no sign-of-step juggling.
    if lat[0] < lat[-1]:
        lat, sst, dhw = lat[::-1], sst[:, ::-1, :], dhw[:, ::-1, :]
    if lon[0] > lon[-1]:
        lon, sst, dhw = lon[::-1], sst[:, :, ::-1], dhw[:, :, ::-1]

    water = np.isfinite(np.where(np.isnan(dhw[0]), np.nan, 1.0))  # land = NaN DHW
    water, sst, dhw = remove_specks(water, sst, dhw)
    # DHW is defined on every water pixel, so its land mask is static.
    assert np.nanmax(dhw) <= DHW_CLIP, (
        "DHW max %.2f exceeds UInt8 ceiling %.1f — raise DHW_CLIP / use Int16"
        % (np.nanmax(dhw), DHW_CLIP))

    # SST -> Int16 with nodata sentinel
    sst_i16 = np.where(np.isfinite(sst), np.round(sst * SST_SCALE), NODATA_I16)
    sst_i16 = sst_i16.astype("<i2")
    # DHW -> UInt8 (land pixels irrelevant; masked in the browser)
    dhw_u8 = np.clip(np.nan_to_num(dhw, nan=0.0) * DHW_SCALE, 0, 255)
    dhw_u8 = np.round(dhw_u8).astype("u1")
    mask_u8 = water.astype("u1")

    # The big grids ship gzipped (SST compresses ~7x, DHW ~80x); the browser
    # inflates them natively with DecompressionStream, so no raw copy is kept.
    with gzip.open(os.path.join(config.WEB_DATA_DIR, "sst.i16.gz"), "wb",
                   compresslevel=9) as f:
        f.write(sst_i16.tobytes())
    with gzip.open(os.path.join(config.WEB_DATA_DIR, "dhw.u8.gz"), "wb",
                   compresslevel=9) as f:
        f.write(dhw_u8.tobytes())
    mask_u8.tofile(os.path.join(config.WEB_DATA_DIR, "mask.u8"))

    coast = coastline_segments(water, lat, lon)
    json.dump(coast, open(os.path.join(config.WEB_DATA_DIR, "coast.json"), "w"))

    dlat = abs(float(lat[1] - lat[0]))            # cell size (both positive)
    dlon = abs(float(lon[1] - lon[0]))
    # Tighten the SST colour domain to the actual regional spread (2nd..98th
    # percentile, rounded to 0.5 degC) so stepped bands have real contrast
    # instead of being crushed into a wide 18..30 range.
    fs = sst[np.isfinite(sst)]
    sst_lo = float(np.floor(np.percentile(fs, 2) * 2) / 2)
    sst_hi = float(np.ceil(np.percentile(fs, 98) * 2) / 2)
    manifest = {
        "source": meta["source"],
        "nlat": int(lat.size), "nlon": int(lon.size), "nframes": len(dates),
        # cell-edge extents of the drawn field (row 0 = north, col 0 = west)
        "north": float(lat[0]) + dlat / 2, "south": float(lat[-1]) - dlat / 2,
        "west": float(lon[0]) - dlon / 2, "east": float(lon[-1]) + dlon / 2,
        "lat_res": dlat, "lon_res": dlon, "cell_km": 5,
        "dates": dates,
        "sst_scale": SST_SCALE, "dhw_scale": DHW_SCALE, "nodata_i16": NODATA_I16,
        "sst_display": [sst_lo, sst_hi],          # tightened, degC
        "anom_display": [-3.0, 3.0],              # diverging, degC vs day-of-year mean
        "dhw_display": [0.0, 16.0],               # degC-weeks
        "thresholds": meta["thresholds"],
        "per_year_max_dhw": meta["per_year_max_dhw"],
    }
    json.dump(manifest, open(os.path.join(config.WEB_DATA_DIR, "manifest.json"), "w"),
              indent=2)

    _verify(sst_i16, dhw_u8, sst, dhw, dates, coast, manifest)


def _verify(sst_i16, dhw_u8, sst, dhw, dates, coast, manifest):
    # Every date in the manifest must map to a stored frame, and one frame must
    # round-trip back to the source grid within quantisation error.
    payload = (sst_i16.nbytes + dhw_u8.nbytes) / 1e6
    assert len(dates) == sst_i16.shape[0] == dhw_u8.shape[0]
    f = len(dates) // 2
    sst_rt = np.where(sst_i16[f] == NODATA_I16, np.nan, sst_i16[f] / SST_SCALE)
    both = np.isfinite(sst_rt) & np.isfinite(sst[f])
    max_sst_err = float(np.max(np.abs(sst_rt[both] - sst[f][both])))
    dhw_rt = dhw_u8[f] / manifest["dhw_scale"]
    wet = np.isfinite(dhw[f])
    max_dhw_err = float(np.max(np.abs(dhw_rt[wet] - dhw[f][wet])))
    assert max_sst_err <= 1.0 / SST_SCALE + 1e-6
    assert max_dhw_err <= 1.0 / manifest["dhw_scale"] + 1e-6
    assert len(coast["coordinates"]) > 20, "coastline suspiciously empty"

    print("VERIFICATION: phase 3")
    print("-" * 48)
    print("frames                 : %d" % len(dates))
    print("grid                   : %d x %d" % (manifest["nlat"], manifest["nlon"]))
    print("payload (sst+dhw)      : %.1f MB" % payload)
    print("coastline segments     : %d" % len(coast["coordinates"]))
    print("round-trip frame %d     : SST err <= %.3f degC, DHW err <= %.3f"
          % (f, max_sst_err, max_dhw_err))
    print("all %d dates have frames: yes" % len(dates))


if __name__ == "__main__":
    main()
