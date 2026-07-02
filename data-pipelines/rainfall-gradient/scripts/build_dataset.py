"""Phase 1: download every Hawaii station's daily PRCP and aggregate to monthly totals.

Overnight-safe: each .dly is cached on disk and skipped if already present, 404s are
recorded with a .missing sentinel so they aren't retried, and ghcn.fetch backs off on
transient errors. Downloads run through a small thread pool to stay reasonable in
wall-clock without hammering NCEI.

Outputs (all in processed/):
  monthly.csv      station_id, year, month, prcp_mm, n_days   (one row per station-month)
  stations.json    per-station metadata (coords, elevation, record span, months reported)
  build_summary.json   totals for the verification gate
"""
import concurrent.futures
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import ghcn

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
DLY_DIR = os.path.join(DATA, "dly")
PROC = os.path.join(ROOT, "processed")
STATIONS_CACHE = os.path.join(DATA, "ghcnd-stations.txt")
QA = os.path.join(ROOT, "QA.md")

WORKERS = 8


def load_stations_text():
    if os.path.exists(STATIONS_CACHE) and os.path.getsize(STATIONS_CACHE) > 0:
        with open(STATIONS_CACHE, encoding="utf-8") as f:
            return f.read()
    text = ghcn.fetch(ghcn.STATIONS_URL).decode("utf-8", "replace")
    os.makedirs(DATA, exist_ok=True)
    with open(STATIONS_CACHE, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def download_one(sid):
    """Fetch one station's .dly if not already cached. Returns a status string."""
    path = os.path.join(DLY_DIR, sid + ".dly")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return "cached"
    if os.path.exists(path + ".missing"):
        return "missing"
    raw = ghcn.fetch(ghcn.DLY_URL.format(station=sid))
    if raw is None:
        open(path + ".missing", "w").close()
        return "missing"
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, path)  # atomic: a killed run never leaves a truncated .dly
    return "downloaded"


def download_all(stations):
    os.makedirs(DLY_DIR, exist_ok=True)
    counts = {"cached": 0, "downloaded": 0, "missing": 0}
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(download_one, s["id"]): s["id"] for s in stations}
        for fut in concurrent.futures.as_completed(futs):
            counts[fut.result()] += 1
            done += 1
            if done % 50 == 0 or done == len(stations):
                print("  downloaded %d/%d  (%s)" % (done, len(stations), counts), flush=True)
    return counts


def station_meta(s, months):
    """Build the metadata record for a station from its parsed monthly rows."""
    years = [y for y, _, _, _ in months]
    elev = s["elev"] if s["elev"] > -999 else None
    return {
        "id": s["id"], "name": s["name"],
        "lat": round(s["lat"], 4), "lon": round(s["lon"], 4), "elev": elev,
        "first_year": min(years), "last_year": max(years), "n_months": len(months),
    }


def aggregate(stations):
    """Parse cached .dly files into monthly.csv + stations.json. Atomic writes."""
    os.makedirs(PROC, exist_ok=True)
    meta, dropped, total_rows = [], [], 0
    tmp_csv = os.path.join(PROC, "monthly.csv.part")
    with open(tmp_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["station_id", "year", "month", "prcp_mm", "n_days"])
        for s in stations:
            path = os.path.join(DLY_DIR, s["id"] + ".dly")
            if not (os.path.exists(path) and os.path.getsize(path) > 0):
                dropped.append((s["id"], s["name"], "no data file"))
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                months = list(ghcn.iter_dly_prcp(f.read()))
            if not months:
                dropped.append((s["id"], s["name"], "no valid PRCP months"))
                continue
            for y, m, t, n in months:
                w.writerow([s["id"], y, m, round(t, 1), n])
                total_rows += 1
            meta.append(station_meta(s, months))
    os.replace(tmp_csv, os.path.join(PROC, "monthly.csv"))

    with open(os.path.join(PROC, "stations.json"), "w") as f:
        json.dump(meta, f)

    span = (min(m["first_year"] for m in meta), max(m["last_year"] for m in meta))
    summary = {"n_stations": len(meta), "n_dropped": len(dropped),
               "station_months": total_rows, "year_span": list(span)}
    with open(os.path.join(PROC, "build_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    return meta, dropped, summary


def write_qa(meta, dropped, summary):
    lines = ["# QA log", "",
             "## Download and aggregate", "",
             "- Stations kept: **%d**" % summary["n_stations"],
             "- Station-months aggregated: **%d**" % summary["station_months"],
             "- Year span: **%d–%d**" % tuple(summary["year_span"]),
             "- Stations dropped: **%d**" % len(dropped), ""]
    if dropped:
        lines.append("### Dropped stations (no coordinates / no data)")
        lines.append("")
        for sid, name, why in dropped:
            lines.append("- `%s` %s — %s" % (sid, name, why))
    else:
        lines.append("_No stations dropped: every kept station has valid coordinates "
                     "(bounding-box filter guarantees lat/lon) and at least one PRCP month._")
    lines.append("")
    with open(QA, "w") as f:
        f.write("\n".join(lines))


def _selfcheck():
    s = {"id": "USTEST", "name": "T", "lat": 20.123456, "lon": -156.7, "elev": -999.9}
    m = station_meta(s, [(1990, 1, 10.0, 30), (2001, 6, 5.0, 28), (1995, 12, 0.0, 31)])
    assert m["first_year"] == 1990 and m["last_year"] == 2001 and m["n_months"] == 3, m
    assert m["elev"] is None and m["lat"] == 20.1235, m
    print("build_dataset selfcheck ok")


def main():
    stations = ghcn.hawaii_stations(load_stations_text())
    print("Hawaii stations: %d" % len(stations))
    counts = download_all(stations)
    print("download summary: %s" % counts)

    meta, dropped, summary = aggregate(stations)
    write_qa(meta, dropped, summary)

    # Verification gate 1.
    assert all(ghcn.in_bbox(m["lat"], m["lon"]) for m in meta), "a kept station lacks coords"
    print("\nVERIFICATION: phase 1")
    print("  every kept station has coordinates: PASS (%d stations)" % len(meta))
    print("  station-months: %d   year span: %d-%d"
          % (summary["station_months"], *summary["year_span"]))
    print("  dropped (see QA.md): %d" % len(dropped))


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
