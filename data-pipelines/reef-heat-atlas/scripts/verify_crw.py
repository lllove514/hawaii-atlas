"""Cross-check: our computed DHW vs NOAA CRW's published CRW_DHW.

Our MMM is CRW's exact MMM (SST - HotSpot) and our DHW uses CRW's algorithm, so
the two should agree closely. Any residual is CRW's operational gap/QC handling.
For each target date we pull CRW_DHW on the matching stored frame date and report
the RMSE and max difference over water. Writes the result to QA.md.

Run:  python scripts/verify_crw.py
"""
import os

import numpy as np
import xarray as xr

import config
import common

TARGETS = ["2015-10-01", "2019-09-15", "2023-08-15"]
OUT_NC = os.path.join(config.PROC_DIR, "reef_weekly.nc")


def nearest_frame(dates, target):
    t = np.datetime64(target)
    arr = np.array(dates, dtype="datetime64[D]")
    return int(np.argmin(np.abs(arr - t)))


def main():
    with xr.open_dataset(OUT_NC) as ds:
        dates = [str(t)[:10] for t in ds["time"].values]
        our_dhw = ds["dhw"].values
        lat, lon = ds["latitude"].values, ds["longitude"].values

    rows = []
    for tgt in TARGETS:
        k = nearest_frame(dates, tgt)
        day = dates[k]
        iso = "%sT12:00:00Z" % day
        tmp = os.path.join(config.RAW_DIR, "_crw_dhw.nc")
        common.download(common.griddap_url("CRW_DHW", iso, iso), tmp)
        with xr.open_dataset(tmp) as ds:
            crw = ds["CRW_DHW"].isel(time=0).values
        os.remove(tmp)

        both = np.isfinite(crw) & np.isfinite(our_dhw[k])
        diff = our_dhw[k][both] - crw[both]
        rmse = float(np.sqrt(np.mean(diff ** 2)))
        mad = float(np.max(np.abs(diff)))
        rows.append((day, float(np.nanmax(our_dhw[k])), float(np.nanmax(crw)), rmse, mad))
        assert rmse < 0.75, "DHW disagrees with CRW at %s (RMSE %.2f)" % (day, rmse)

    print("VERIFICATION: CRW cross-check")
    print("-" * 60)
    print("%-12s %8s %8s %8s %8s" % ("frame", "ours_mx", "crw_mx", "rmse", "maxdiff"))
    for day, om, cm, rmse, mad in rows:
        print("%-12s %8.2f %8.2f %8.3f %8.3f" % (day, om, cm, rmse, mad))

    lines = ["", "## CRW cross-check (our DHW vs published CRW_DHW)", "",
             "| frame | our max | CRW max | RMSE | max diff |",
             "|-------|---------|---------|------|----------|"]
    for day, om, cm, rmse, mad in rows:
        lines.append("| %s | %.2f | %.2f | %.3f | %.3f |" % (day, om, cm, rmse, mad))
    with open(config.QA_PATH, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
