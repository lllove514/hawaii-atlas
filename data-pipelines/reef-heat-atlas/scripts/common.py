"""Shared helpers: ERDDAP griddap URLs, resumable downloads, sanity checks."""
import os
import sys
import time

import numpy as np
import requests
import xarray as xr

import config


def griddap_url(var, start, end, ext="nc"):
    """Build an ERDDAP griddap request for one variable over the Hawaii crop.

    `start`/`end` are ISO strings (e.g. '2019-09-15T12:00:00Z'). ERDDAP clips
    silently to the available range, so requesting a whole calendar year is safe
    even for the partial first (1985) and last years.
    """
    box = "[(%s):(%s)][(%.4f):(%.4f)][(%.4f):(%.4f)]" % (
        start, end, config.LAT_MIN, config.LAT_MAX, config.LON_MIN, config.LON_MAX,
    )
    return "%s.%s?%s%s" % (config.ENDPOINT, ext, var, box)


def download(url, dest, tries=6, base_wait=3.0, expect_min_bytes=200):
    """Download `url` to `dest`, resumably and atomically.

    - If `dest` already exists and opens as valid NetCDF, skip (return False).
    - Otherwise stream to `dest + '.part'`, verify it opens, then atomic-rename.
      A crash mid-download leaves only the .part file, so the final path is never
      a truncated file that a later run would mistake for complete.
    - Retry with exponential backoff on network / server errors.

    Returns True if it downloaded, False if it was already present.
    """
    if os.path.exists(dest) and _opens_ok(dest):
        return False

    part = dest + ".part"
    for attempt in range(1, tries + 1):
        try:
            with requests.get(url, stream=True, timeout=180) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            f.write(chunk)
            size = os.path.getsize(part)
            if size < expect_min_bytes:
                raise IOError("suspiciously small response (%d bytes): %s"
                              % (size, _peek(part)))
            if not _opens_ok(part):
                raise IOError("downloaded file is not readable NetCDF")
            os.replace(part, dest)
            return True
        except Exception as exc:  # noqa: BLE001 — surface any failure, then retry
            if os.path.exists(part):
                os.remove(part)
            if attempt == tries:
                raise
            wait = base_wait * (2 ** (attempt - 1))
            sys.stderr.write("  retry %d/%d after error: %s (waiting %.0fs)\n"
                             % (attempt, tries, exc, wait))
            sys.stderr.flush()
            time.sleep(wait)


def _opens_ok(path):
    try:
        with xr.open_dataset(path) as ds:
            return len(ds.data_vars) > 0
    except Exception:
        return False


def _peek(path, n=180):
    """First bytes of a bad response — usually an ERDDAP text error message."""
    try:
        with open(path, "rb") as f:
            return f.read(n).decode("utf-8", "replace").strip()
    except Exception:
        return "<unreadable>"


# ---------------------------------------------------------------------------
# Sanity checks (used as assert conditions across the pipeline)
# ---------------------------------------------------------------------------
def sst_plausible(sst):
    """True if every finite SST value sits in the plausible reef-water envelope."""
    finite = np.asarray(sst)[np.isfinite(sst)]
    if finite.size == 0:
        return False
    return bool(finite.min() >= config.SST_MIN_PLAUSIBLE
                and finite.max() <= config.SST_MAX_PLAUSIBLE)


def covers_islands(lat, lon):
    """True if the grid extent brackets the main Hawaiian Islands."""
    lat, lon = np.asarray(lat), np.asarray(lon)
    return bool(lat.min() <= 19.0 and lat.max() >= 22.0
                and lon.min() <= -156.0 and lon.max() >= -155.0)


def _demo():
    assert sst_plausible(np.array([18.0, 25.0, 29.9, np.nan]))
    assert not sst_plausible(np.array([18.0, 40.0]))
    assert not sst_plausible(np.array([np.nan, np.nan]))
    assert covers_islands(np.linspace(18, 23, 100), np.linspace(-161.5, -154, 150))
    assert not covers_islands(np.linspace(30, 40, 10), np.linspace(0, 10, 10))
    assert "CRW_SST" in griddap_url("CRW_SST", "1985-04-01T12:00:00Z",
                                    "1985-04-01T12:00:00Z")
    print("common.py self-check OK")


if __name__ == "__main__":
    _demo()
