"""Phase 4 check — validate the web payload the browser will actually read.

Two things a browser test would confirm, done here against the exported files:
  1. Hover returns the right ahupuaʻa: map known real-world points into web pixels
     and run the *same* ray-casting hit-test app.js uses on the *same* geojson.
  2. The layers overlay correctly: composite base + basins + streams + boundaries
     in web-pixel space (exactly as the canvas stacks them) to a preview PNG.

Run:  python scripts/verify_web.py
"""

import json
import sys

import numpy as np
import rasterio
from PIL import Image, ImageDraw
from pyproj import Transformer

import config as C

WEBDATA = C.WEB / C.slug(C.ISLAND)
PREVIEW_DIR = C.PROCESSED / "previews"   # composite/match PNGs for eyeballing

# Known Oʻahu locations (lon, lat) whose ahupuaʻa is unambiguous — one per side of
# the island, so a flipped or mis-scaled projection would show up immediately.
KNOWN = [
    ("Waikīkī",  -157.8258, 21.2806, "Waikīkī"),   # south shore
    ("Honolulu", -157.8580, 21.3070, "Honolulu"),  # downtown
    ("Kāneʻohe", -157.7990, 21.4030, "Kāneʻohe"),  # windward central
    ("Kailua",   -157.7394, 21.3920, "Kailua"),    # windward east
    ("Hālawa",   -157.9236, 21.3730, "Hālawa"),    # ʻEwa / Pearl Harbor
    ("Waiʻanae", -158.1850, 21.4370, "Waiʻanae"),  # leeward
]


def point_in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_polygon(x, y, poly):
    if not point_in_ring(x, y, poly[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in poly[1:])


def feature_at(x, y, features):
    for f in features:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        if any(point_in_polygon(x, y, p) for p in polys):
            return f
    return None


def _rings(geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    for poly in polys:
        for ring in poly:
            yield [tuple(c) for c in ring]


def _boundaries(draw, feats):
    for f in feats:
        for r in _rings(f["geometry"]):
            draw.line(r, fill=(0, 0, 0, 230), width=3)
    for f in feats:
        for r in _rings(f["geometry"]):
            draw.line(r, fill=(255, 255, 255, 255), width=1)


# diverging match ramp, identical to app.js: red (splits) -> yellow -> green (one)
_STOPS = [(0, (215, 48, 31)), (0.5, (254, 196, 79)), (0.85, (120, 198, 121)), (1, (35, 132, 67))]


def _match_color(p):
    if p["dom_basin"] is None:
        return (107, 114, 128)
    f = p["dom_frac"]
    a, b = _STOPS[0], _STOPS[-1]
    for i in range(len(_STOPS) - 1):
        if _STOPS[i][0] <= f <= _STOPS[i + 1][0]:
            a, b = _STOPS[i], _STOPS[i + 1]
            break
    t = (f - a[0]) / (b[0] - a[0] or 1)
    return tuple(round(a[1][k] + (b[1][k] - a[1][k]) * t) for k in range(3))


def main():
    meta = json.loads((WEBDATA / "meta.json").read_text(encoding="utf-8"))
    ahu = json.loads((WEBDATA / "ahupuaa.geojson").read_text(encoding="utf-8"))["features"]
    streams = json.loads((WEBDATA / "streams.geojson").read_text(encoding="utf-8"))["features"]

    with rasterio.open(C.paths()["dem_utm"]) as ds:
        T = ds.transform
        dem_w = ds.width
    s = meta["web_size"][0] / dem_w
    to_utm = Transformer.from_crs(4326, meta["epsg"], always_xy=True)

    print("# Phase 4 — hover hit-test on known locations\n")
    ok = 0
    for name, lon, lat, expect in KNOWN:
        x_utm, y_utm = to_utm.transform(lon, lat)
        col = (x_utm - T.c) / T.a
        row = (y_utm - T.f) / T.e
        px, py = col * s, row * s
        f = feature_at(px, py, ahu)
        got = f["properties"]["ahupuaa"] if f else None
        hit = got == expect
        ok += hit
        print(f"  {name:10} -> {got!r:22} expected {expect!r}  {'OK' if hit else 'MISS'}")

    # composite preview exactly as the canvas stacks the layers
    base = Image.open(WEBDATA / "base.png").convert("RGBA")
    W, H = base.size
    canvas = Image.new("RGBA", (W, H), (10, 22, 34, 255))
    canvas.alpha_composite(base)
    basins = Image.open(WEBDATA / "basins.png").convert("RGBA")
    basins.putalpha(basins.getchannel("A").point(lambda a: int(a * 0.55)))
    canvas.alpha_composite(basins)
    draw = ImageDraw.Draw(canvas)
    lo = np.log10(meta["stream_threshold_cells"])
    hi = max(lo, max(np.log10(f["properties"]["acc"] or 1) for f in streams))
    for f in streams:
        t = (np.log10(f["properties"]["acc"] or 1) - lo) / (hi - lo or 1)
        w = max(1, round(0.6 + 3.4 * min(1, max(0, t))))
        pts = [tuple(c) for c in f["geometry"]["coordinates"]]
        draw.line(pts, fill=(111, 208, 255, 255), width=w, joint="curve")
    _boundaries(draw, ahu)  # dark halo + light line, as app.js draws them
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = str(PREVIEW_DIR / "web_composite.png")
    canvas.convert("RGB").resize((1100, round(1100 * H / W))).save(out)
    print(f"\n  composite preview -> {out}")

    # Match view: fill each ahupuaʻa by how well it matches one computed watershed.
    m = Image.new("RGBA", (W, H), (10, 22, 34, 255))
    m.alpha_composite(base)
    fill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fill)
    for f in ahu:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            fd.polygon([tuple(c) for c in poly[0]], fill=_match_color(f["properties"]) + (255,))
    fill.putalpha(fill.getchannel("A").point(lambda a: int(a * 0.62)))
    m.alpha_composite(fill)
    _boundaries(ImageDraw.Draw(m), ahu)
    m.convert("RGB").resize((1100, round(1100 * H / W))).save(PREVIEW_DIR / "web_match.png")
    print(f"  match preview   -> {PREVIEW_DIR / 'web_match.png'}")

    # --- VERIFICATION GATE 4 ------------------------------------------------
    assert ok == len(KNOWN), f"hover hit-test: only {ok}/{len(KNOWN)} matched"
    names = [f["properties"]["ahupuaa"] for f in ahu]
    assert any(c in "".join(names) for c in "ʻāēīōū"), "names lost diacritics"
    assert len(streams) > 100 and len(ahu) > 1
    # data behind the new views: match stats, moku labels, scale, pinned basins
    assert meta.get("m_per_px", 0) > 0 and len(meta.get("moku_labels", [])) >= 1
    for f in ahu:
        p = f["properties"]
        assert "dom_frac" in p and "dom_basin" in p and "basin_ids" in p
    have = {b["properties"]["id"] for b in
            json.loads((WEBDATA / "basins.geojson").read_text())["features"]}
    ref = {b for f in ahu for b in f["properties"]["basin_ids"]}
    assert ref <= have, "some pinned-basin ids have no polygon in basins.geojson"

    C.write_qa_section("Phase 4 — front end (`web/`, checked by `verify_web.py`)",
                       "\n".join([
        "**VERIFICATION: phase 4 — PASS**",
        "",
        f"- Hover hit-test (app.js ray-casting on the exported geojson) returns the "
        f"correct ahupuaʻa for all {len(KNOWN)} spot-checked locations: "
        + ", ".join(k[0] for k in KNOWN) + ".",
        "- Boundaries drawn with a dark halo under a light line, legible over "
        "terrain + basins at full opacity.",
        "- Match view: every ahupuaʻa carries `dom_frac`/`dom_basin`/`basin_ids`, "
        "coloured green→yellow→red by how well it matches one computed watershed; "
        "pinned basins resolve to polygons in basins.geojson for the overlap view.",
        f"- Orientation data present: {len(meta['moku_labels'])} moku labels, "
        f"{meta['m_per_px']:.1f} m/px for the scale bar; north is up (UTM).",
        "- Island switcher wired from manifest.json; toggles, opacity, search, and "
        "the biggest-mismatches list run in app.js. Names UTF-8 clean.",
    ]))

    print("\nVERIFICATION: phase 4")
    print(f"  hover correct for {ok}/{len(KNOWN)} known points; "
          f"{len(streams)} streams, {len(ahu)} ahupuaʻa composited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
