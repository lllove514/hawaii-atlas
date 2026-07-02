"""Shared GHCN-Daily helpers: source URLs, fixed-width parsing, HTTP with backoff.

GHCN-Daily is distributed by NOAA/NCEI as one fixed-width .dly file per station plus a
fixed-width station metadata file. We use the per-station path because it is trivially
resumable (one file per station, skip what's already on disk) and lets us filter to
Hawaii before downloading anything heavy.
"""
import time
import requests

# NOAA/NCEI GHCN-Daily endpoints (reachability verified 2026-07; see README).
STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
DLY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{station}.dly"

# Hawaii bounding box, degrees (lat south->north, lon west->east).
LAT_MIN, LAT_MAX = 18.9, 22.3
LON_MIN, LON_MAX = -160.3, -154.8

DLY_LINE_LEN = 269  # 21 header chars + 31 days * 8 chars


def in_bbox(lat, lon):
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def parse_stations(text):
    """Parse ghcnd-stations.txt (fixed width) into a list of station dicts.

    Columns (1-based, per NOAA readme): ID 1-11, LAT 13-20, LON 22-30, ELEV 32-37,
    STATE 39-40, NAME 42-71.
    """
    out = []
    for line in text.splitlines():
        if len(line) < 71:
            continue
        out.append({
            "id": line[0:11].strip(),
            "lat": float(line[12:20]),
            "lon": float(line[21:30]),
            "elev": float(line[31:37]),   # -999.9 means missing
            "state": line[38:40].strip(),
            "name": line[41:71].strip(),
        })
    return out


def hawaii_stations(text):
    """Stations tagged state=HI that also fall inside the island bounding box
    (drops distant HI-flagged sites such as Midway/Kure)."""
    return [s for s in parse_stations(text)
            if s["state"] == "HI" and in_bbox(s["lat"], s["lon"])]


def iter_dly_prcp(text):
    """Yield (year, month, total_mm, n_days) for each PRCP month in a .dly file.

    Daily PRCP is stored in tenths of a millimeter; -9999 is missing and any non-blank
    quality flag (QFLAG) marks a value that failed QC, so both are excluded. Trace days
    are recorded as 0 and count as real observations. Months with no valid day are
    skipped entirely.
    """
    for line in text.splitlines():
        if line[17:21] != "PRCP":
            continue
        line = line.ljust(DLY_LINE_LEN)
        year, month = int(line[11:15]), int(line[15:17])
        total = n = 0
        for d in range(31):
            off = 21 + d * 8
            val = int(line[off:off + 5])
            qflag = line[off + 6]
            if val == -9999 or qflag != " ":
                continue
            total += val
            n += 1
        if n:
            yield year, month, total / 10.0, n


def fetch(url, tries=5, timeout=60, session=None):
    """GET with exponential backoff. Returns bytes, or None on a real 404."""
    sess = session or requests
    delay = 2.0
    last = None
    for _ in range(tries):
        try:
            r = sess.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return None
            last = "HTTP %d" % r.status_code
        except requests.RequestException as e:
            last = str(e)
        time.sleep(delay)
        delay = min(delay * 2, 30)
    raise RuntimeError("failed to fetch %s (%s)" % (url, last))


def _selfcheck():
    # bounding box
    assert in_bbox(19.72, -155.05)       # Hilo
    assert in_bbox(21.31, -157.86)       # Honolulu
    assert not in_bbox(28.21, -177.38)   # Midway (HI-flagged but far NW)

    # station line parsing against a real-format sample (built at exact columns)
    buf = [" "] * 71
    for s, start in [("USW00021504", 0), ("19.7192".rjust(8), 12),
                     ("-155.0530".rjust(9), 21), ("11.6".rjust(6), 31),
                     ("HI", 38), ("HILO INTL AP", 41)]:
        buf[start:start + len(s)] = list(s)
    st = parse_stations("".join(buf))[0]
    assert st["id"] == "USW00021504" and st["state"] == "HI"
    assert abs(st["lat"] - 19.7192) < 1e-6 and abs(st["lon"] + 155.0530) < 1e-6

    # .dly monthly aggregation: day1=10.0mm, day2 missing, day3=5.0mm,
    # day4=99.9mm but QC-flagged -> excluded. Expect 15.0mm over 2 valid days.
    def day(v, q=" "):
        return str(v).rjust(5) + " " + q + "0"
    days = [day(100), day(-9999), day(50), day(999, "X")] + [day(-9999)] * 27
    line = "USTEST00001" + "2020" + "01" + "PRCP" + "".join(days)
    assert len(line) == DLY_LINE_LEN, len(line)
    (year, month, total, n), = list(iter_dly_prcp(line))
    assert (year, month, n) == (2020, 1, 2), (year, month, n)
    assert abs(total - 15.0) < 1e-9, total
    print("ghcn selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
