"""Phase 4 gate — the web payload decodes to the same numbers the app shows.

Reproduces app.js's geometry and integer decoding in Python, for known reef
points and frames, and checks the result against the source processed grid. If
orientation, indexing, scaling, or endianness were wrong, this fails.

Run:  python scripts/verify_web.py
"""
import gzip
import json
import os

import numpy as np
import xarray as xr

import config

WEB = config.WEB_DATA_DIR
PROC_NC = os.path.join(config.PROC_DIR, "reef_weekly.nc")

# Known reef locations (lat, lon) to spot-check the hover readout.
POINTS = [
    ("Big Island (Kona)", 20.02, -155.98),
    ("Oahu (south)", 21.25, -157.90),
    ("Kauai (north)", 22.25, -159.55),
    ("French Frigate", 23.00, -161.30),
]
FRAMES = ["2015-09-28", "2019-09-16", "2005-01-05"]


def app_cell(m, lat, lon):
    """i (row from north), j (col from west) exactly as app.js computes them."""
    i = int((m["north"] - lat) / (m["north"] - m["south"]) * m["nlat"])
    j = int((lon - m["west"]) / (m["east"] - m["west"]) * m["nlon"])
    return i, j


def main():
    m = json.load(open(os.path.join(WEB, "manifest.json")))
    npix = m["nlat"] * m["nlon"]
    sst = np.frombuffer(gzip.open(os.path.join(WEB, "sst.i16.gz")).read(),
                        dtype="<i2").reshape(-1, m["nlat"], m["nlon"])
    dhw = np.frombuffer(gzip.open(os.path.join(WEB, "dhw.u8.gz")).read(),
                        dtype="u1").reshape(-1, m["nlat"], m["nlon"])
    mask = np.fromfile(os.path.join(WEB, "mask.u8"), dtype="u1").reshape(m["nlat"], m["nlon"])
    assert sst.shape[0] == dhw.shape[0] == m["nframes"] == len(m["dates"])
    assert sst[0].size == npix

    src = xr.open_dataset(PROC_NC)
    src_lat, src_lon = src["latitude"].values, src["longitude"].values

    def cell_center(i, j):
        clat = m["north"] - (i + 0.5) * (m["north"] - m["south"]) / m["nlat"]
        clon = m["west"] + (j + 0.5) * (m["east"] - m["west"]) / m["nlon"]
        return clat, clon

    print("VERIFICATION: phase 4 (web payload numbers)")
    print("-" * 70)
    print("%-20s %-11s %8s %8s  %s" % ("point", "date", "SST", "DHW", "risk"))
    frame_dates = np.array(m["dates"], dtype="datetime64[D]")
    worst_sst = worst_dhw = 0.0
    for want in FRAMES:
        f = int(np.argmin(np.abs(frame_dates - np.datetime64(want))))
        date = m["dates"][f]                        # nearest stored weekly frame
        for name, lat, lon in POINTS:
            i, j = app_cell(m, lat, lon)
            # decode exactly as the browser would
            raw = sst[f, i, j]
            v_sst = None if raw == m["nodata_i16"] else raw / m["sst_scale"]
            v_dhw = dhw[f, i, j] / m["dhw_scale"]

            # the app's cell centre must sit within one grid cell of the target
            # (this is what catches a flipped orientation)
            clat, clon = cell_center(i, j)
            assert abs(clat - lat) <= m["lat_res"] and abs(clon - lon) <= m["lon_res"], \
                "cell for %s is %.3f,%.3f — too far from %.3f,%.3f" % (name, clat, clon, lat, lon)
            assert abs(clat - src_lat[i]) < 1e-3 and abs(clon - src_lon[j]) < 1e-3

            # decode must equal the source value at the SAME (i, j)
            s_sst = float(src["sst"].values[f, i, j])
            s_dhw = float(src["dhw"].values[f, i, j])
            if mask[i, j]:                          # water pixel: values must agree
                if np.isfinite(s_sst) and v_sst is not None:
                    worst_sst = max(worst_sst, abs(v_sst - s_sst))
                worst_dhw = max(worst_dhw, abs(v_dhw - s_dhw))

            risk = ("severe" if v_dhw >= config.DHW_SEVERE
                    else "significant" if v_dhw >= config.DHW_SIGNIFICANT
                    else "watch" if v_dhw >= 1 else "none")
            ss = "land" if not mask[i, j] else ("no-data" if v_sst is None else "%.2f" % v_sst)
            print("%-20s %-11s %8s %8.1f  %s" % (name, date, ss, v_dhw, risk))

    assert worst_sst <= 1.0 / m["sst_scale"] + 1e-6, "SST decode error %.4f" % worst_sst
    assert worst_dhw <= 1.0 / m["dhw_scale"] + 1e-6, "DHW decode error %.4f" % worst_dhw
    src.close()
    print("-" * 70)
    print("max decode error vs source: SST %.4f degC, DHW %.4f degC-weeks"
          % (worst_sst, worst_dhw))
    print("cell geometry, orientation, scaling, endianness: all consistent.")


if __name__ == "__main__":
    main()
