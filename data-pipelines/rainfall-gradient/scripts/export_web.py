"""Phase 3: pack the interpolated surfaces into compact binaries the browser can color.

Surfaces are stored as uint16 tenths-of-a-millimetre (nodata = 65535). This halves the
payload versus float32 and still resolves rainfall to 0.1 mm, while leaving the colour
scale entirely to the client (we ship raw values, not pre-coloured PNGs). An island-id
mask and the coastline travel alongside so the front end can outline the islands, mask the
ocean, and answer "wettest/driest on this island".

Outputs (web/data/):
  climatology.bin / .json     12 monthly surfaces + metadata
  timeseries.bin  / .json     recent monthly surfaces + metadata (if present)
  mask_clim.bin / mask_ts.bin island-id grids (uint8) matching each product
  coastline.geojson           bundled island outlines
"""
import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import grid

ROOT = grid.ROOT
PROC = os.path.join(ROOT, "processed")
SURF = os.path.join(PROC, "surfaces")
WEB = os.path.join(ROOT, "..", "..", "data", "rainfall-gradient")

NODATA = 65535
SCALE = 10  # tenths of a mm


def encode(surf):
    scaled = np.round(surf * SCALE)
    assert np.nanmax(scaled) < NODATA, "value exceeds uint16 range: %.1f mm" % (np.nanmax(surf))
    out = np.where(np.isfinite(surf), np.clip(scaled, 0, NODATA - 1), NODATA)
    return out.astype("<u2")  # little-endian uint16 (browser is LE)


def robust_vmax(surfaces):
    """98th percentile of all land values — a colour ceiling that isn't hijacked by the
    single wettest cell on Kauaʻi, with the absolute max kept for reference."""
    vals = np.concatenate([s[np.isfinite(s)].ravel() for s in surfaces])
    return round(float(np.percentile(vals, 98)), 1), round(float(vals.max()), 1)


def pack(meta_path, surface_names, out_stem, res):
    with open(meta_path) as f:
        meta = json.load(f)
    surfaces = [np.load(os.path.join(SURF, n + ".npy")) for n in surface_names]
    for s in surfaces:
        assert s.shape == (meta["ny"], meta["nx"]), "surface shape != grid"

    stack = np.stack([encode(s) for s in surfaces])
    stack.tofile(os.path.join(WEB, out_stem + ".bin"))

    default_vmax, abs_max = robust_vmax(surfaces)
    mask, islands = grid.island_mask(res)
    mask.astype(np.uint8).tofile(os.path.join(WEB, "mask_%s.bin" % _tag(out_stem)))
    meta["encoding"] = {"type": "uint16", "scale": SCALE, "nodata": NODATA}
    meta["default_vmax"] = default_vmax
    meta["abs_max"] = abs_max
    meta["islands"] = [{"id": it["id"], "name": it["name"]} for it in islands]
    meta["n_surfaces"] = len(surfaces)
    with open(os.path.join(WEB, out_stem + ".json"), "w") as f:
        json.dump(meta, f)
    return meta, stack


def _tag(out_stem):
    return "clim" if out_stem == "climatology" else "ts"


def roundtrip_check(out_stem, surface_names):
    """Gate 3: read one surface back from the .bin and confirm it matches the .npy."""
    with open(os.path.join(WEB, out_stem + ".json")) as f:
        meta = json.load(f)
    ny, nx = meta["ny"], meta["nx"]
    raw = np.fromfile(os.path.join(WEB, out_stem + ".bin"), dtype="<u2")
    assert raw.size == len(surface_names) * ny * nx, "bin size mismatch"
    idx = len(surface_names) // 2
    back = raw.reshape(len(surface_names), ny, nx)[idx].astype(np.float32)
    back = np.where(back == NODATA, np.nan, back / SCALE)
    orig = np.load(os.path.join(SURF, surface_names[idx] + ".npy"))
    both = np.isfinite(back) & np.isfinite(orig)
    assert np.isfinite(back).sum() == np.isfinite(orig).sum(), "nodata pattern changed"
    assert np.max(np.abs(back[both] - orig[both])) <= 1.0 / SCALE + 1e-6, "round-trip drift"
    return idx, meta


def main():
    os.makedirs(WEB, exist_ok=True)

    # coastline (bundled outlines)
    grid.load_coastline()  # ensure built
    shutil.copyfile(grid.COAST_CACHE, os.path.join(WEB, "coastline.geojson"))

    # slim station list for the hover "nearest station" readout
    with open(os.path.join(PROC, "stations.json")) as f:
        stations = json.load(f)
    slim = [{"name": s["name"], "lat": s["lat"], "lon": s["lon"], "elev": s["elev"]}
            for s in stations]
    with open(os.path.join(WEB, "stations.json"), "w") as f:
        json.dump(slim, f)

    # climatology
    clim_names = ["clim_%02d" % m for m in range(1, 13)]
    clim_meta, _ = pack(os.path.join(PROC, "clim_meta.json"), clim_names, "climatology", 0.02)
    ci, _ = roundtrip_check("climatology", clim_names)
    assert len(clim_meta["months"]) == 12 and clim_meta["n_surfaces"] == 12

    print("\nVERIFICATION: phase 3")
    print("  climatology: 12 surfaces packed, default_vmax=%.0f mm, abs_max=%.0f mm"
          % (clim_meta["default_vmax"], clim_meta["abs_max"]))
    print("  round-trip surface #%d matches .npy within %.1f mm" % (ci, 1.0 / SCALE))

    # timeseries (optional)
    ts_meta_path = os.path.join(PROC, "ts_meta.json")
    if os.path.exists(ts_meta_path):
        with open(ts_meta_path) as f:
            tsm = json.load(f)
        ts_names = ["ts_%04d%02d" % (s["year"], s["month"]) for s in tsm["surfaces"]]
        ts_meta, _ = pack(ts_meta_path, ts_names, "timeseries", 0.04)
        ti, _ = roundtrip_check("timeseries", ts_names)
        assert all(s.get("year") for s in ts_meta["surfaces"])
        assert ts_meta["n_surfaces"] == len(ts_names)
        print("  timeseries: %d surfaces packed (%d-%d), round-trip #%d ok"
              % (len(ts_names), ts_meta["years"][0], ts_meta["years"][1], ti))

    # report payload
    total = sum(os.path.getsize(os.path.join(WEB, f)) for f in os.listdir(WEB))
    print("  total web payload: %.1f MB" % (total / 1e6))
    for f in sorted(os.listdir(WEB)):
        print("    %-22s %.2f MB" % (f, os.path.getsize(os.path.join(WEB, f)) / 1e6))


if __name__ == "__main__":
    main()
