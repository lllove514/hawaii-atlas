"""Phase 0 — discover and verify a working CRW SST endpoint.

Fetches ONE day of CoralTemp SST cropped to the Hawaiian Islands, reports the
grid, and derives the official CRW MMM climatology from that same day via
MMM = SST - HOTSPOT (CRW publishes HotSpot unclamped, so this is exact).

Run:  python scripts/discover_source.py
"""
import os

import numpy as np
import xarray as xr

import config
import common

REF_DAY = "2019-09-15T12:00:00Z"   # during the 2019 Hawaii bleaching event


def main():
    os.makedirs(config.RAW_DIR, exist_ok=True)
    sst_nc = os.path.join(config.RAW_DIR, "_probe_sst.nc")
    hot_nc = os.path.join(config.RAW_DIR, "_probe_hotspot.nc")

    print("Endpoint: %s" % config.ENDPOINT)
    print("Fetching one day (%s) cropped to Hawaii ..." % REF_DAY)
    common.download(common.griddap_url("CRW_SST", REF_DAY, REF_DAY), sst_nc)
    common.download(common.griddap_url("CRW_HOTSPOT", REF_DAY, REF_DAY), hot_nc)

    with xr.open_dataset(sst_nc) as ds:
        sst = ds["CRW_SST"].isel(time=0).values
        lat = ds["latitude"].values
        lon = ds["longitude"].values
    with xr.open_dataset(hot_nc) as ds:
        hotspot = ds["CRW_HOTSPOT"].isel(time=0).values

    mmm = sst - hotspot                       # exact official CRW MMM per pixel
    finite = sst[np.isfinite(sst)]
    mean = float(finite.mean())

    print("\nVERIFICATION: phase 0")
    print("-" * 48)
    print("grid shape (lat x lon) : %d x %d" % sst.shape)
    print("lat extent             : %.3f .. %.3f" % (lat.min(), lat.max()))
    print("lon extent             : %.3f .. %.3f" % (lon.min(), lon.max()))
    print("water pixels           : %d of %d" % (finite.size, sst.size))
    print("SST  min/mean/max      : %.2f / %.2f / %.2f degC"
          % (finite.min(), mean, finite.max()))
    mmm_f = mmm[np.isfinite(mmm)]
    print("MMM  min/mean/max      : %.2f / %.2f / %.2f degC (= SST - HotSpot)"
          % (mmm_f.min(), mmm_f.mean(), mmm_f.max()))

    assert common.sst_plausible(sst), "SST outside plausible reef-water range"
    assert 15.0 < mean < 30.0, "mean SST %.2f not in (15, 30)" % mean
    assert common.covers_islands(lat, lon), "crop does not cover the islands"
    # MMM is a climatological SST, so it must itself be plausible SST.
    assert common.sst_plausible(mmm), "derived MMM outside plausible SST range"
    print("checks passed: values plausible, crop covers the islands.")

    for tmp in (sst_nc, hot_nc):
        os.remove(tmp)


if __name__ == "__main__":
    main()
