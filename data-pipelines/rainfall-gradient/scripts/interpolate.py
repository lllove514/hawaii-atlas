"""Phase 2: interpolate station monthly totals onto regular grids with IDW.

Two products:
  climatology  12 surfaces, one per calendar month, averaged over each station's record
               (the "scrub through a typical year" view). Grid: CLIM_RES.
  timeseries   monthly surfaces across a recent window, coarser grid (TS_RES), to keep the
               web payload small.

Interpolation is inverse-distance weighting done PER ISLAND: a cell is filled only from
stations on its own island, so rainfall never bleeds across the open-ocean channels
between islands (Kauaʻi stations cannot influence Oʻahu, etc.). Weight = 1/d^p, p=2.

Both loops are resumable: a surface already written to processed/surfaces/ is skipped, so
an interrupted overnight run continues where it stopped.
"""
import csv
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import ghcn
import grid

ROOT = grid.ROOT
PROC = os.path.join(ROOT, "processed")
SURF = os.path.join(PROC, "surfaces")
QA = os.path.join(ROOT, "QA.md")

CLIM_RES = 0.02          # ~2.2 km climatology grid
TS_RES = 0.04            # ~4.4 km time-series grid (half res -> quarter payload)
IDW_POWER = 2
MIN_DAYS = 25            # a station-month needs this many observed days to count
MIN_YEARS_CLIM = 5       # a station needs this many years of a calendar month to be in its climatology
MIN_STATIONS = 15        # below this, a surface is flagged low-confidence
TS_WINDOW_YEARS = 15     # most recent N complete years for the time series
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---- IDW core -------------------------------------------------------------------------

def idw_surface(res, mask, st_lat, st_lon, st_island, v, power=IDW_POWER):
    """Per-island inverse-distance weighting.

    v is a per-station value array (NaN where the station has no value this surface).
    Returns (surface[ny,nx] float32 with NaN over ocean/no-data, n_stations_used).
    """
    ny, nx = mask.shape
    surf = np.full((ny, nx), np.nan, np.float32)
    lats, lons = grid.cell_centers(res)
    finite = np.isfinite(v)
    used = 0
    for k in range(1, int(mask.max()) + 1):
        sel = finite & (st_island == k)
        if not sel.any():
            continue
        rows, cols = np.where(mask == k)
        if rows.size == 0:
            continue
        used += int(sel.sum())
        clat, clon = lats[rows], lons[cols]
        slat, slon, sv = st_lat[sel], st_lon[sel], v[sel]
        dy = (clat[:, None] - slat[None, :]) * 111.0
        dx = (clon[:, None] - slon[None, :]) * 111.0 * np.cos(np.radians(clat))[:, None]
        d = np.maximum(np.sqrt(dx * dx + dy * dy), 1e-6)   # 1e-6 km guards a cell-on-station
        w = d ** (-power)
        surf[rows, cols] = (w * sv[None, :]).sum(1) / w.sum(1)
    return surf, used


def surface_stats(surf):
    vals = surf[np.isfinite(surf)]
    if vals.size == 0:
        return {"vmin": None, "vmax": None, "vmean": None}
    return {"vmin": round(float(vals.min()), 1),
            "vmax": round(float(vals.max()), 1),
            "vmean": round(float(vals.mean()), 1)}


# ---- data loading ---------------------------------------------------------------------

def load_stations():
    with open(os.path.join(PROC, "stations.json")) as f:
        meta = json.load(f)
    return meta


def assign_islands(meta, res):
    """Map each station to an island id for the given grid; stations that fall on no
    landmass are attached to the geographically nearest island so none are lost."""
    mask, islands = grid.island_mask(res)
    ids = np.zeros(len(meta), np.int16)
    for n, s in enumerate(meta):
        k = grid.island_at(mask, res, s["lat"], s["lon"])
        if k == 0:
            k = min(islands, key=lambda it: (grid.ISLANDS_BY_NAME[it["name"]][0] - s["lat"]) ** 2
                    + (grid.ISLANDS_BY_NAME[it["name"]][1] - s["lon"]) ** 2)["id"]
        ids[n] = k
    return mask, islands, ids


def load_monthly(index):
    """Stream monthly.csv, keeping only rows with enough observed days.

    Returns (clim, ts) where
      clim[station_idx][month] -> list of yearly totals
      ts[(year,month)][station_idx] -> total
    index maps station_id -> array position.
    """
    clim = defaultdict(lambda: defaultdict(list))
    ts = defaultdict(dict)
    with open(os.path.join(PROC, "monthly.csv")) as f:
        r = csv.reader(f)
        next(r)
        for sid, year, month, prcp, ndays in r:
            if int(ndays) < MIN_DAYS:
                continue
            si = index.get(sid)
            if si is None:
                continue
            y, m, val = int(year), int(month), float(prcp)
            clim[si][m].append(val)
            ts[(y, m)][si] = val
    return clim, ts


# ---- products -------------------------------------------------------------------------

def save_surface(name, surf):
    np.save(os.path.join(SURF, name + ".npy"), surf)


def load_surface(name):
    p = os.path.join(SURF, name + ".npy")
    return np.load(p) if os.path.exists(p) else None


def build_climatology(meta, index, clim, mask, islands, island_ids):
    st_lat = np.array([s["lat"] for s in meta])
    st_lon = np.array([s["lon"] for s in meta])
    surfaces, metas = [], []
    for m in range(1, 13):
        name = "clim_%02d" % m
        v = np.full(len(meta), np.nan)
        for si, months in clim.items():
            vals = months.get(m)
            if vals and len(vals) >= MIN_YEARS_CLIM:
                v[si] = sum(vals) / len(vals)
        surf = load_surface(name)
        if surf is None:
            surf, used = idw_surface(CLIM_RES, mask, st_lat, st_lon, island_ids, v)
            save_surface(name, surf)
        else:
            used = int(np.isfinite(v).sum())
        assert np.nanmin(surf) >= -1e-6, "negative rainfall in %s" % name
        st = surface_stats(surf)
        st.update(label=MONTHS[m - 1], month=m, n_stations=used,
                  low_confidence=used < MIN_STATIONS)
        surfaces.append(surf)
        metas.append(st)
        print("  %s: %d stations, mean %.0f mm, max %.0f mm"
              % (MONTHS[m - 1], used, st["vmean"], st["vmax"]))
    meta_out = {"product": "climatology", **grid.grid_meta(CLIM_RES),
                "months": metas, "min_days": MIN_DAYS, "min_years": MIN_YEARS_CLIM,
                "idw_power": IDW_POWER}
    with open(os.path.join(PROC, "clim_meta.json"), "w") as f:
        json.dump(meta_out, f, indent=2)
    return surfaces, meta_out


def build_timeseries(meta, index, ts, summary_span):
    mask, islands, island_ids = assign_islands(meta, TS_RES)
    st_lat = np.array([s["lat"] for s in meta])
    st_lon = np.array([s["lon"] for s in meta])
    last_year = summary_span[1]
    # A "complete" year is one strictly before the final (possibly partial) record year.
    y1 = last_year - 1
    y0 = y1 - TS_WINDOW_YEARS + 1
    metas = []
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            name = "ts_%04d%02d" % (y, m)
            vals = ts.get((y, m), {})
            v = np.full(len(meta), np.nan)
            for si, val in vals.items():
                v[si] = val
            surf = load_surface(name)
            if surf is None:
                surf, used = idw_surface(TS_RES, mask, st_lat, st_lon, island_ids, v)
                save_surface(name, surf)
            else:
                used = int(np.isfinite(v).sum())
            assert np.nanmin(surf) >= -1e-6, "negative rainfall in %s" % name
            st = surface_stats(surf)
            st.update(label="%s %d" % (MONTHS[m - 1], y), year=y, month=m,
                      n_stations=used, low_confidence=used < MIN_STATIONS)
            metas.append(st)
        print("  timeseries %d done" % y)
    meta_out = {"product": "timeseries", **grid.grid_meta(TS_RES),
                "years": [y0, y1], "surfaces": metas, "min_days": MIN_DAYS,
                "idw_power": IDW_POWER}
    with open(os.path.join(PROC, "ts_meta.json"), "w") as f:
        json.dump(meta_out, f, indent=2)
    return meta_out


# ---- verification ---------------------------------------------------------------------

def sample(surf, res, lat, lon):
    """Value at a coordinate, falling back to the nearest finite cell within a few cells."""
    ny, nx = surf.shape
    i = int((lon - ghcn.LON_MIN) / res)
    j = int((ghcn.LAT_MAX - lat) / res)
    for r in range(0, 6):
        sub = surf[max(0, j - r):j + r + 1, max(0, i - r):i + r + 1]
        fin = sub[np.isfinite(sub)]
        if fin.size:
            return float(fin.mean())
    return float("nan")


def verify(clim_surfaces, clim_meta):
    annual = np.nansum(np.stack(clim_surfaces), axis=0)  # sum of 12 monthly means
    res = CLIM_RES
    checks = []

    # Windward (NE) should out-rain leeward (SW) on the same island.
    pairs = [
        ("Hawaiʻi", "Hilo (windward)", (19.72, -155.05), "Kona (leeward)", (19.64, -156.00)),
        ("Oʻahu", "Kāneʻohe (windward)", (21.40, -157.80), "Kapolei (leeward)", (21.34, -158.06)),
        ("Kauaʻi", "Wailua (windward)", (22.05, -159.34), "Waimea (leeward)", (21.96, -159.67)),
    ]
    for island, wname, wll, lname, lll in pairs:
        wet = sample(annual, res, *wll)
        dry = sample(annual, res, *lll)
        ok = wet > dry
        checks.append((island, wname, wet, lname, dry, ok))
        assert ok, "windward<=leeward on %s: %s %.0f vs %s %.0f" % (island, wname, wet, lname, dry)

    # Non-negativity + extent already asserted per surface; re-affirm extent here.
    for s in clim_meta["months"]:
        assert s["vmin"] is None or s["vmin"] >= -1e-6
    assert clim_meta["extent"] == [ghcn.LON_MIN, ghcn.LON_MAX, ghcn.LAT_MIN, ghcn.LAT_MAX]
    return checks, annual


def write_qa(clim_meta, checks):
    lines = ["", "## Interpolation", "",
             "Grid: %d×%d cells at %.3f° (climatology). IDW power %d, per island."
             % (clim_meta["nx"], clim_meta["ny"], clim_meta["res"], clim_meta["idw_power"]),
             "", "### Windward vs leeward (annual climatology, mm)", "",
             "| Island | Windward | mm | Leeward | mm | windward wetter |",
             "|---|---|--:|---|--:|:--:|"]
    for island, wn, wv, ln, lv, ok in checks:
        lines.append("| %s | %s | %.0f | %s | %.0f | %s |"
                     % (island, wn, wv, ln, lv, "✓" if ok else "✗"))
    lines += ["", "### Monthly climatology (island-mean over all land cells)", "",
              "| Month | Stations | Mean mm | Min cell | Max cell | Low-conf |",
              "|---|--:|--:|--:|--:|:--:|"]
    for s in clim_meta["months"]:
        lines.append("| %s | %d | %.0f | %.0f | %.0f | %s |"
                     % (s["label"], s["n_stations"], s["vmean"], s["vmin"], s["vmax"],
                        "yes" if s["low_confidence"] else ""))
    lines.append("")
    with open(QA, "a") as f:
        f.write("\n".join(lines))


def _selfcheck():
    # Two stations on one island; IDW must reproduce station values at the stations and
    # stay monotonic and non-negative between them.
    res = 0.02
    mask = np.zeros((10, 10), np.int16)
    mask[:, :] = 1
    st_lat = np.array([ghcn.LAT_MAX - 0.01, ghcn.LAT_MAX - 0.19])
    st_lon = np.array([ghcn.LON_MIN + 0.01, ghcn.LON_MIN + 0.19])
    v = np.array([100.0, 0.0])
    surf, used = idw_surface(res, mask, st_lat, st_lon, np.array([1, 1], np.int16), v)
    assert used == 2 and np.all(surf >= 0)
    assert abs(surf[0, 0] - 100.0) < 1.0 and abs(surf[9, 9] - 0.0) < 1.0, (surf[0, 0], surf[9, 9])
    assert surf[0, 0] > surf[5, 5] > surf[9, 9], "IDW not monotonic"
    # A station with NaN value is ignored; an island with no stations stays NaN.
    surf2, used2 = idw_surface(res, mask, st_lat, st_lon,
                               np.array([1, 1], np.int16), np.array([np.nan, np.nan]))
    assert used2 == 0 and np.isnan(surf2).all()
    print("interpolate selfcheck ok")


def main():
    os.makedirs(SURF, exist_ok=True)
    meta = load_stations()
    index = {s["id"]: n for n, s in enumerate(meta)}
    with open(os.path.join(PROC, "build_summary.json")) as f:
        span = json.load(f)["year_span"]

    print("loading monthly records ...")
    clim, ts = load_monthly(index)

    print("climatology:")
    mask, islands, island_ids = assign_islands(meta, CLIM_RES)
    clim_surfaces, clim_meta = build_climatology(meta, index, clim, mask, islands, island_ids)

    checks, _ = verify(clim_surfaces, clim_meta)
    write_qa(clim_meta, checks)

    print("timeseries (%d yr window):" % TS_WINDOW_YEARS)
    ts_meta = build_timeseries(meta, index, ts, span)

    print("\nVERIFICATION: phase 2")
    for island, wn, wv, ln, lv, ok in checks:
        print("  %s windward %.0f > leeward %.0f mm/yr: %s"
              % (island, wv, lv, "PASS" if ok else "FAIL"))
    print("  non-negativity: PASS (all %d clim + %d ts surfaces)"
          % (len(clim_meta["months"]), len(ts_meta["surfaces"])))
    print("  see QA.md for the monthly table")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
