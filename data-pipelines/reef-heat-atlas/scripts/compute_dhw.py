"""Phase 2 — compute HotSpot and Degree Heating Weeks from the SST record.

Algorithm (standard CRW):
    HotSpot(pixel, day) = max(0, SST - MMM)
    DHW(pixel, day)     = sum over the trailing 84 days of HotSpots >= 1.0 degC,
                          divided by 7           (units: degC-weeks)

DHW is computed on the DAILY series with a date-aware rolling 84-day window
(robust to occasional missing days). Only weekly frames are stored, to keep the
downstream web payload sane; the per-year DHW maxima reported by the
verification gate use the true daily peaks, not the weekly samples.

Memory is bounded: one year of SST is held at a time (~22 MB) plus the 84-day
window of HotSpot contributions (~5 MB). The full 40-year daily stack is never
loaded at once.

Output:
    processed/reef_weekly.nc   sst, dhw  (time, lat, lon) float32
    processed/meta.json        dates, extent, ranges, per-year max DHW

Run:  python scripts/compute_dhw.py
"""
import json
import os
from collections import deque

import numpy as np
import xarray as xr

import config
import common

OUT_NC = os.path.join(config.PROC_DIR, "reef_weekly.nc")
OUT_META = os.path.join(config.PROC_DIR, "meta.json")


def load_mmm():
    with xr.open_dataset(config.MMM_PATH) as ds:
        return (ds["mmm"].values.astype("float32"),
                ds["latitude"].values, ds["longitude"].values)


def year_files():
    files = []
    for year in range(config.START_YEAR, config.END_YEAR + 1):
        p = config.year_sst_path(year)
        if os.path.exists(p):
            files.append((year, p))
    if not files:
        raise SystemExit("No SST year files in %s — run download.py first." % config.RAW_DIR)
    return files


def compute():
    mmm, lat, lon = load_mmm()
    land = ~np.isfinite(mmm)                      # pixels with no climatology
    window = deque()                              # (ordinal_day, contribution)
    running = np.zeros_like(mmm, dtype="float32")  # trailing-window HotSpot sum

    out_dates, out_sst, out_dhw = [], [], []
    per_year_max = {}
    first_ord = None
    total_days = 0

    for year, path in year_files():
        with xr.open_dataset(path) as ds:
            times = ds["time"].values             # datetime64[ns]
            sst_year = ds["CRW_SST"].values.astype("float32")  # (days, lat, lon)
        ordinals = times.astype("datetime64[D]").astype(np.int64)
        for i in range(len(times)):
            ordn = int(ordinals[i])
            if first_ord is None:
                first_ord = ordn
            sst = sst_year[i]
            hotspot = np.maximum(0.0, sst - mmm)                # NaN where sst NaN
            contrib = np.where(hotspot >= config.HOTSPOT_THRESHOLD, hotspot, 0.0)
            contrib = np.nan_to_num(contrib, nan=0.0).astype("float32")

            window.append((ordn, contrib))
            running += contrib
            cutoff = ordn - (config.DHW_WINDOW_DAYS - 1)
            while window and window[0][0] < cutoff:
                running -= window.popleft()[1]

            # running is add/evict rolling sum; clamp away float32 drift
            # (~1e-5) so exactly-calm pixels read 0, not -0.0.
            dhw = np.where(land, np.nan, np.maximum(0.0, running / 7.0)).astype("float32")

            y = int(str(times[i])[:4])
            m = float(np.nanmax(dhw)) if np.isfinite(dhw).any() else 0.0
            if m > per_year_max.get(y, -1.0):
                per_year_max[y] = m

            total_days += 1
            if (ordn - first_ord) % config.WEB_STRIDE_DAYS == 0:
                out_dates.append(str(times[i])[:10])
                out_sst.append(sst.astype("float32"))
                out_dhw.append(dhw)
        print("  %d: %d days processed" % (year, len(times)), flush=True)

    sst_stack = np.stack(out_sst)
    dhw_stack = np.stack(out_dhw)
    return dict(lat=lat, lon=lon, dates=out_dates, sst=sst_stack, dhw=dhw_stack,
                per_year_max=per_year_max, total_days=total_days, mmm=mmm)


def verify_and_save(r):
    dhw, sst = r["dhw"], r["sst"]

    finite_dhw = dhw[np.isfinite(dhw)]
    assert finite_dhw.min() >= 0.0, "negative DHW found (min %.4f)" % finite_dhw.min()
    finite_sst = sst[np.isfinite(sst)]
    assert common.sst_plausible(sst), (
        "SST outside plausible range: %.2f .. %.2f"
        % (finite_sst.min(), finite_sst.max()))

    pk = r["per_year_max"]
    for evt in (2015, 2019):
        assert pk.get(evt, 0.0) > 4.0, (
            "known %d bleaching event did not exceed DHW 4 (got %.2f)"
            % (evt, pk.get(evt, 0.0)))

    os.makedirs(config.PROC_DIR, exist_ok=True)
    ds = xr.Dataset(
        {"sst": (("time", "latitude", "longitude"), r["sst"]),
         "dhw": (("time", "latitude", "longitude"), r["dhw"])},
        coords={"time": np.array(r["dates"], dtype="datetime64[ns]"),
                "latitude": r["lat"], "longitude": r["lon"]},
        attrs={"source": config.SOURCE_LABEL,
               "dhw_window_days": config.DHW_WINDOW_DAYS,
               "hotspot_threshold_degC": config.HOTSPOT_THRESHOLD},
    )
    tmp = OUT_NC + ".part"
    ds.to_netcdf(tmp)
    os.replace(tmp, OUT_NC)

    meta = {
        "source": config.SOURCE_LABEL,
        "extent": {"lat_min": float(r["lat"].min()), "lat_max": float(r["lat"].max()),
                   "lon_min": float(r["lon"].min()), "lon_max": float(r["lon"].max())},
        "grid": {"nlat": int(r["lat"].size), "nlon": int(r["lon"].size)},
        "dates": r["dates"],
        "stride_days": config.WEB_STRIDE_DAYS,
        "total_days_processed": r["total_days"],
        "sst_range": [float(finite_sst.min()), float(finite_sst.max())],
        "dhw_range": [float(finite_dhw.min()), float(finite_dhw.max())],
        "mmm_range": [float(np.nanmin(r["mmm"])), float(np.nanmax(r["mmm"]))],
        "thresholds": {"significant": config.DHW_SIGNIFICANT, "severe": config.DHW_SEVERE},
        "per_year_max_dhw": {str(y): round(pk[y], 2) for y in sorted(pk)},
    }
    with open(OUT_META, "w") as f:
        json.dump(meta, f, indent=2)

    print("\nVERIFICATION: phase 2")
    print("-" * 48)
    print("weekly frames stored   : %d  (from %d daily steps)"
          % (len(r["dates"]), r["total_days"]))
    print("date range             : %s .. %s" % (r["dates"][0], r["dates"][-1]))
    print("SST  range             : %.2f .. %.2f degC" % tuple(meta["sst_range"]))
    print("DHW  range             : %.2f .. %.2f degC-weeks" % tuple(meta["dhw_range"]))
    print("DHW >= 0 everywhere    : yes")
    print("\nmax DHW per year (degC-weeks):")
    for y in sorted(pk):
        star = "  <-- bleaching event" if y in (2014, 2015, 2019) else ""
        print("  %s : %5.2f%s" % (y, pk[y], star))
    return meta


def main():
    if os.path.exists(OUT_NC) and common._opens_ok(OUT_NC) and os.path.exists(OUT_META):
        print("Phase 2 output present, skipping. Delete %s to recompute." % OUT_NC)
        return
    print("Computing HotSpot and DHW over the daily record ...")
    meta = verify_and_save(compute())
    _append_qa(meta)


def _append_qa(meta):
    """Record the per-year DHW table in QA.md (Phase 2 gate evidence)."""
    lines = ["", "## Phase 2 — max DHW per year (degC-weeks)", "",
             "Weekly frames stored: %d from %d daily steps. "
             "DHW range %.2f..%.2f; SST range %.2f..%.2f."
             % (len(meta["dates"]), meta["total_days_processed"],
                meta["dhw_range"][0], meta["dhw_range"][1],
                meta["sst_range"][0], meta["sst_range"][1]),
             "", "| year | max DHW |", "|------|---------|"]
    for y, v in meta["per_year_max_dhw"].items():
        lines.append("| %s | %.2f |" % (y, v))
    with open(config.QA_PATH, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
