"""Phase 0: verify the GHCN-Daily source works end to end.

Fetches the station list, filters to Hawaii, downloads one station's daily record,
aggregates it to monthly PRCP totals, and prints a summary. Everything here is a dry run
for build_dataset.py; it caches the station file so the full build can reuse it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import ghcn

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
STATIONS_CACHE = os.path.join(DATA, "ghcnd-stations.txt")


def load_stations_text():
    """Read the cached station file, downloading it once if absent (resumable)."""
    if os.path.exists(STATIONS_CACHE) and os.path.getsize(STATIONS_CACHE) > 0:
        with open(STATIONS_CACHE, encoding="utf-8") as f:
            return f.read()
    print("downloading station metadata ...")
    text = ghcn.fetch(ghcn.STATIONS_URL).decode("utf-8", "replace")
    os.makedirs(DATA, exist_ok=True)
    with open(STATIONS_CACHE, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def main():
    stations = ghcn.hawaii_stations(load_stations_text())
    print("Hawaii stations found: %d" % len(stations))
    assert len(stations) >= 50, "expected >=50 Hawaii stations, got %d" % len(stations)

    # Prefer Hilo (a long, well-known windward record); fall back to the first station.
    sample = next((s for s in stations if s["id"] == "USW00021504"), stations[0])
    print("sample station: %s  %s  (%.4f, %.4f)  %.0fm"
          % (sample["id"], sample["name"], sample["lat"], sample["lon"], sample["elev"]))

    raw = ghcn.fetch(ghcn.DLY_URL.format(station=sample["id"]))
    assert raw is not None, "sample station .dly not found"
    months = list(ghcn.iter_dly_prcp(raw.decode("utf-8", "replace")))
    assert months, "no PRCP months parsed for sample station"

    years = sorted({y for y, *_ in months})
    totals = [t for _, _, t, _ in months]
    print("monthly PRCP records: %d   year span: %d-%d"
          % (len(months), years[0], years[-1]))

    # Plausibility: non-negative, and no single month above a physical ceiling. The wettest
    # spots on Earth reach ~1.5 m in a month; 6 m is comfortably impossible.
    assert min(totals) >= 0, "negative monthly total"
    assert max(totals) < 6000, "implausibly high monthly total: %.1f mm" % max(totals)

    # Show a concrete sample: the most recent complete-looking December.
    dec = [(y, t, n) for (y, m, t, n) in months if m == 12 and n >= 28]
    if dec:
        y, t, n = dec[-1]
        print("sample monthly total: Dec %d = %.1f mm (%.1f in) over %d days"
              % (y, t, t / 25.4, n))

    mean = sum(totals) / len(totals)
    print("mean monthly total across record: %.1f mm" % mean)
    print("\nVERIFICATION: phase 0")
    print("  stations >= 50: PASS (%d)" % len(stations))
    print("  sample totals plausible: PASS (min %.1f, max %.1f mm)" % (min(totals), max(totals)))


if __name__ == "__main__":
    main()
