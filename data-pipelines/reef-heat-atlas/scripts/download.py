"""Phase 1 — bulk download of the daily SST record for the Hawaii crop.

One NetCDF file per calendar year (data/raw/sst_YYYY.nc), plus the official CRW
MMM climatology (data/raw/mmm.nc), derived as MMM = SST - HotSpot.

Resumable: a year already present and openable is skipped, so an interrupted
run resumes with no lost work. Downloads are atomic (.part -> rename) and
retried with backoff (see common.download).

Run:  python scripts/download.py            # full range from config
      python scripts/download.py 2015 2019   # just those years (dev/testing)
"""
import os
import re
import sys
import warnings

import numpy as np
import requests
import xarray as xr

import config
import common

# Days sampled to build a gap-free MMM. MMM = SST - HotSpot is constant in time
# per pixel, so averaging several cloud-free days only fills missing pixels.
MMM_SAMPLE_DAYS = [
    "2018-02-15T12:00:00Z", "2018-05-15T12:00:00Z", "2018-08-15T12:00:00Z",
    "2018-11-15T12:00:00Z", "2019-03-15T12:00:00Z", "2019-09-15T12:00:00Z",
]


def build_mmm():
    """Derive and save the official CRW MMM climatology for the crop."""
    if os.path.exists(config.MMM_PATH) and common._opens_ok(config.MMM_PATH):
        print("MMM present, skipping.")
        return

    print("Building MMM from %d sample days (SST - HotSpot) ..." % len(MMM_SAMPLE_DAYS))
    layers = []
    lat = lon = None
    for day in MMM_SAMPLE_DAYS:
        sst_p = os.path.join(config.RAW_DIR, "_mmm_sst.nc")
        hot_p = os.path.join(config.RAW_DIR, "_mmm_hot.nc")
        common.download(common.griddap_url("CRW_SST", day, day), sst_p)
        common.download(common.griddap_url("CRW_HOTSPOT", day, day), hot_p)
        with xr.open_dataset(sst_p) as ds:
            sst = ds["CRW_SST"].isel(time=0).values
            lat = ds["latitude"].values
            lon = ds["longitude"].values
        with xr.open_dataset(hot_p) as ds:
            hot = ds["CRW_HOTSPOT"].isel(time=0).values
        layers.append(sst - hot)
        os.remove(sst_p)
        os.remove(hot_p)

    stack = np.stack(layers)                       # (days, lat, lon)
    # MMM is time-invariant: where multiple days are finite they must agree.
    # All-NaN (land) columns are expected; silence their empty-slice warnings.
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        spread = np.nanstd(stack, axis=0)
        mmm = np.nanmean(stack, axis=0).astype("float32")
    max_spread = float(np.nanmax(spread[np.isfinite(spread)]))
    assert max_spread < 0.05, ("SST - HotSpot varies across days by %.3f; MMM is "
                               "not time-invariant as assumed" % max_spread)
    assert common.sst_plausible(mmm), "derived MMM outside plausible SST range"

    out = xr.Dataset(
        {"mmm": (("latitude", "longitude"), mmm)},
        coords={"latitude": lat, "longitude": lon},
        attrs={"description": "CRW Maximum Monthly Mean climatology (v3.1), "
                              "derived as SST - HotSpot; units degC",
               "source": config.SOURCE_LABEL},
    )
    tmp = config.MMM_PATH + ".part"
    out.to_netcdf(tmp)
    os.replace(tmp, config.MMM_PATH)
    print("  MMM saved: range %.2f .. %.2f degC (max cross-day spread %.4f)"
          % (float(np.nanmin(mmm)), float(np.nanmax(mmm)), max_spread))


def get_coverage():
    """Dataset's available time span, so we never ask ERDDAP for dates outside
    it (a start before coverage returns 404 rather than clipping)."""
    das = requests.get(config.ENDPOINT + ".das", timeout=60).text
    start = re.search(r'time_coverage_start "([^"]+)"', das).group(1)
    end = re.search(r'time_coverage_end "([^"]+)"', das).group(1)
    return start, end


def download_years(years, cov_start, cov_end):
    for i, year in enumerate(years, 1):
        dest = config.year_sst_path(year)
        tag = "[%d/%d] %d" % (i, len(years), year)
        if os.path.exists(dest) and common._opens_ok(dest):
            print("%s  already present, skip" % tag)
            continue
        # ISO timestamps compare correctly as strings; clamp to coverage.
        start = max("%d-01-01T12:00:00Z" % year, cov_start)
        end = min("%d-12-31T12:00:00Z" % year, cov_end)
        if start > end:
            print("%s  outside dataset coverage, skip" % tag)
            continue
        url = common.griddap_url("CRW_SST", start, end)
        print("%s  downloading ..." % tag, flush=True)
        common.download(url, dest)
        with xr.open_dataset(dest) as ds:
            n = ds.sizes["time"]
        print("%s  %d days, %.1f MB" % (tag, n, os.path.getsize(dest) / 1e6))


def verify(cov_start, cov_end):
    """Gate 1: count days vs expected, list gaps, assert no empty files."""
    present = []
    for year in range(config.START_YEAR, config.END_YEAR + 1):
        p = config.year_sst_path(year)
        if not os.path.exists(p):
            continue
        assert os.path.getsize(p) > 0, "zero-length file: %s" % p
        with xr.open_dataset(p) as ds:
            present.append(ds["time"].values.astype("datetime64[D]"))
    present = np.unique(np.concatenate(present)) if present else np.array([], "datetime64[D]")

    start = np.datetime64(cov_start[:10]); end = np.datetime64(cov_end[:10])
    expected = np.arange(start, end + np.timedelta64(1, "D"), dtype="datetime64[D]")
    gaps = np.setdiff1d(expected, present)

    print("\nVERIFICATION: phase 1")
    print("-" * 48)
    print("expected days          : %d  (%s .. %s)" % (len(expected), start, end))
    print("downloaded days        : %d" % len(present))
    print("missing days (gaps)    : %d" % len(gaps))
    if len(gaps):
        shown = ", ".join(str(g) for g in gaps[:12])
        print("first gaps             : %s%s" % (shown, " ..." if len(gaps) > 12 else ""))

    lines = ["", "## Phase 1 — download coverage", "",
             "Source: %s  " % config.SOURCE_LABEL,
             "Coverage: %s .. %s  " % (start, end),
             "Expected days: %d, downloaded: %d, missing: %d."
             % (len(expected), len(present), len(gaps)), ""]
    if len(gaps):
        lines.append("Missing dates:")
        lines += ["- %s" % g for g in gaps]
    else:
        lines.append("No gaps: every day in the coverage window is present.")
    with open(config.QA_PATH, "a") as f:
        f.write("\n".join(lines) + "\n")
    return len(gaps)


def main():
    os.makedirs(config.RAW_DIR, exist_ok=True)
    if len(sys.argv) > 1:
        years = [int(a) for a in sys.argv[1:]]
    else:
        years = list(range(config.START_YEAR, config.END_YEAR + 1))
    build_mmm()
    cov_start, cov_end = get_coverage()
    print("Dataset coverage: %s .. %s" % (cov_start, cov_end))
    download_years(years, cov_start, cov_end)
    print("Download step complete (%d years)." % len(years))
    if len(sys.argv) == 1:                        # full run -> run the gate
        verify(cov_start, cov_end)


if __name__ == "__main__":
    main()
