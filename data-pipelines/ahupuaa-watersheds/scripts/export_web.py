"""Phase 3 — export a lightweight, self-consistent web payload.

Everything is baked into one shared pixel space (web pixels = DEM pixels scaled
by a single factor) so the browser overlays rasters and vectors exactly, with no
projection code client-side. Written per island to web/data/<slug>/:

  base.png        grayscale hillshade, ocean transparent
  basins.png      significant watershed basins, each a distinct hue
  basins.geojson  those basins as polygons, for the click / overlap view
  streams.geojson stream network, per-branch accumulation -> line weight
  ahupuaa.geojson boundaries + names + concordance stats vs the basins
  meta.json       island, sizes, extent, layer list, moku labels, intro

and a top-level web/data/manifest.json listing which islands are available.

Run:  python scripts/export_web.py
"""

import json
import sys
from collections import defaultdict

import geopandas as gpd
import numpy as np
import rasterio
import shapely
from PIL import Image
from rasterio.features import rasterize, shapes as rio_shapes
from shapely.geometry import shape as shp_shape
from shapely.ops import unary_union

import config as C

OUT = C.WEB  # reassigned per-island in main()


def hillshade(z, res, az=315.0, alt=45.0):
    """Standard Horn hillshade in [0,1]."""
    gy, gx = np.gradient(z, res)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azr, altr = np.radians(360.0 - az + 90.0), np.radians(alt)
    hs = (np.sin(altr) * np.sin(slope)
          + np.cos(altr) * np.cos(slope) * np.cos(azr - aspect))
    return np.clip((hs + 1.0) / 2.0, 0.0, 1.0)


def _to_web(transform, s):
    """Return f((N,2) UTM xy) -> (N,2) web px for shapely.transform."""
    a, e, c, f = transform.a, transform.e, transform.c, transform.f

    def fn(xy):
        col = (xy[:, 0] - c) / a
        row = (xy[:, 1] - f) / e
        return np.column_stack([col * s, row * s])
    return fn


def distinct_colors(n):
    """n visually distinct RGB triples via the golden-angle around HSV."""
    import colorsys
    out = []
    for i in range(n):
        h = (i * 0.61803398875) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.95)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return out


def export_rasters(elev, nodata, transform, basins, s, web_w, web_h):
    """Write base.png (hillshade) and basins.png (colored significant basins)."""
    from scipy.ndimage import distance_transform_edt
    land = (elev != nodata) & (elev > 0)
    # extend land elevation into the ocean by nearest-neighbour before the
    # gradient, so cliff coastlines aren't shaded against a false 0 m sea wall;
    # the ocean is made transparent by the alpha channel afterwards.
    idx = distance_transform_edt(~land, return_distances=False, return_indices=True)
    hs = hillshade(elev[tuple(idx)].astype("float64"), C.TARGET_RES_M)
    g = (hs * 255).astype("uint8")
    rgba = np.dstack([g, g, g, np.where(land, 255, 0).astype("uint8")])
    (Image.fromarray(rgba, "RGBA")
     .resize((web_w, web_h), Image.LANCZOS).save(OUT / "base.png"))

    counts = np.bincount(basins.ravel())
    cell_km2 = (C.TARGET_RES_M ** 2) / 1e6
    sig = [lbl for lbl in range(1, len(counts))
           if counts[lbl] * cell_km2 >= C.MIN_BASIN_KM2]
    lut = np.zeros((len(counts), 4), dtype="uint8")
    for color, lbl in zip(distinct_colors(len(sig)), sig):
        lut[lbl] = (*color, 255)
    brgba = lut[basins]
    (Image.fromarray(brgba, "RGBA")
     .resize((web_w, web_h), Image.NEAREST).save(OUT / "basins.png"))
    return sig


def export_basins_vector(basins, sig, transform, s):
    """Significant basins as web-px polygons, so a pinned ahupuaʻa can show the
    computed watershed it should contain."""
    mask = np.isin(basins, np.asarray(sig, dtype="int32"))
    polys = defaultdict(list)
    for geom, val in rio_shapes(basins.astype("int32"), mask=mask,
                                transform=transform, connectivity=8):
        polys[int(val)].append(shp_shape(geom))
    fn = _to_web(transform, s)
    feats = []
    for lbl, gl in polys.items():
        g = unary_union(gl).simplify(35.0)
        if g.is_empty:
            continue
        feats.append({"type": "Feature", "properties": {"id": lbl},
                      "geometry": json.loads(shapely.to_geojson(shapely.transform(g, fn)))})
    (OUT / "basins.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    return len(feats)


def export_streams(transform, s, land):
    """Streams in web px, each branch carrying its downstream accumulation.

    pysheds terminates some branches on off-land cells at the grid edge, which
    would draw as long lines across the ocean. We keep only maximal runs of
    vertices that sit on labelled land cells, so every emitted segment is real.
    """
    from shapely.geometry import LineString
    gdf = gpd.read_file(C.paths()["streams"])
    with rasterio.open(C.paths()["flowacc"]) as ds:
        acc = ds.read(1)
        H, W = acc.shape
    a, e, c, f = transform.a, transform.e, transform.c, transform.f
    fn = _to_web(transform, s)
    feats = []
    for geom in gdf.geometry:
        xy = np.asarray(geom.coords)
        cols = ((xy[:, 0] - c) / a).astype(int).clip(0, W - 1)
        rows = ((xy[:, 1] - f) / e).astype(int).clip(0, H - 1)
        onland = land[rows, cols]
        i = 0
        while i < len(onland):
            if not onland[i]:
                i += 1
                continue
            j = i
            while j < len(onland) and onland[j]:
                j += 1
            if j - i >= 2:
                rep = float(acc[rows[i:j], cols[i:j]].max())
                px = shapely.transform(LineString(xy[i:j]).simplify(20.0), fn)
                coords = [[round(x, 1), round(y, 1)] for x, y in px.coords]
                if len(coords) >= 2:
                    feats.append({"type": "Feature",
                                  "properties": {"acc": round(rep)},
                                  "geometry": {"type": "LineString",
                                               "coordinates": coords}})
            i = j
    (OUT / "streams.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    return len(feats)


def concordance(ahu, transform, shape, basins, sig):
    """Per-ahupuaʻa stats vs the computed basins — the quantity the map is about.

    Rasterizes the ahupuaʻa and cross-tabulates its land cells against the
    significant basins. Returns one dict per feature: the dominant-basin fraction
    (`frac`), how many basins cover ≥10% of it (`n_basins`), the ids of those
    basins (`basin_ids`, largest first), the single dominant basin (`dom_basin`),
    and a plain-language note.
    """
    H, W = shape
    N = len(ahu)
    ids = list(range(1, N + 1))
    ah = rasterize(zip(ahu.geometry, ids), out_shape=(H, W),
                   transform=transform, fill=0, dtype="int32")
    sig_set = np.zeros(int(basins.max()) + 1, dtype=bool)
    sig_set[np.asarray(sig, dtype=int)] = True

    # denominator = the ahupuaʻa's *land* cells (basins>0), so embayed ocean in
    # coastal ahupuaʻa doesn't deflate the fraction.
    mask = (ah > 0) & (basins > 0)
    a = ah[mask].astype(np.int64)
    b = basins[mask].astype(np.int64)
    tot = np.bincount(a, minlength=N + 1).astype(float)

    issig = sig_set[b]
    maxlabel = int(basins.max())
    key = a[issig] * (maxlabel + 1) + b[issig]
    uk, cnt = np.unique(key, return_counts=True)
    ua, ub = uk // (maxlabel + 1), uk % (maxlabel + 1)

    dom = np.zeros(N + 1)
    dom_lbl = np.zeros(N + 1, dtype=int)
    big = defaultdict(list)  # ahupuaʻa id -> [(basin_label, cell_count), ...] ≥10%
    for aa, bb, c in zip(ua.tolist(), ub.tolist(), cnt.tolist()):
        if c > dom[aa]:
            dom[aa], dom_lbl[aa] = c, bb
        if tot[aa] > 0 and c >= 0.10 * tot[aa]:
            big[aa].append((bb, c))

    stats = []
    for i in ids:
        t = tot[i]
        frac = dom[i] / t if t else 0.0
        basin_ids = [bb for bb, _ in sorted(big[i], key=lambda kv: -kv[1])]
        nb = len(basin_ids)
        pct = round(frac * 100)
        if t == 0 or dom[i] == 0:
            note = "too small to resolve against the 0.5 km² basins"
        elif frac >= 0.75 and nb <= 1:
            note = f"tracks one watershed closely ({pct}% of its area)"
        elif frac >= 0.5:
            note = (f"mostly one watershed ({pct}%), with {nb} smaller "
                    f"basin{'s' if nb != 1 else ''}")
        else:
            note = f"drainage splits across {max(nb, 2)} basins (largest {pct}%)"
        stats.append({"frac": round(float(frac), 3), "n_basins": nb, "note": note,
                      "dom_basin": int(dom_lbl[i]) or None, "basin_ids": basin_ids})
    return stats


def export_ahupuaa(transform, s, basins, sig):
    """Boundaries in web px, with names (UTF-8) and concordance stats."""
    gdf = gpd.read_file(C.paths()["ahupuaa_utm"])
    with rasterio.open(C.paths()["dem_utm"]) as ds:
        shape = (ds.height, ds.width)
    stats = concordance(gdf, transform, shape, basins, sig)
    fn = _to_web(transform, s)
    feats = []
    for (_, row), st in zip(gdf.iterrows(), stats):
        geom = shapely.transform(row.geometry.simplify(20.0), fn)
        feats.append({
            "type": "Feature",
            "properties": {
                "ahupuaa": row["ahupuaa"], "moku": row["moku"],
                "mokupuni": row["mokupuni"],
                "acres": round(float(row["gisacres"])) if row["gisacres"] else None,
                "dom_frac": st["frac"], "n_basins": st["n_basins"], "note": st["note"],
                "dom_basin": st["dom_basin"], "basin_ids": st["basin_ids"],
            },
            "geometry": json.loads(shapely.to_geojson(geom)),
        })
    (OUT / "ahupuaa.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats},
                   ensure_ascii=False), encoding="utf-8")
    return gdf, [st["frac"] for st in stats]


def moku_labels(gdf, transform, s):
    """A label anchor (inside the district) per moku, in web px."""
    fn = _to_web(transform, s)
    out = []
    for moku, grp in gdf.groupby("moku"):
        p = grp.geometry.union_all().representative_point()
        x, y = fn(np.array([[p.x, p.y]]))[0]
        out.append({"name": moku, "x": round(float(x), 1), "y": round(float(y), 1)})
    return out


def write_manifest():
    """List the switcher islands and which have been processed (have a meta.json)."""
    switcher = ["Oʻahu", "Kauaʻi", "Maui", "Hawaiʻi"]
    islands = [{"name": nm, "slug": C.slug(nm),
                "available": (C.WEB / C.slug(nm) / "meta.json").exists()}
               for nm in switcher]
    (C.WEB / "manifest.json").write_text(
        json.dumps({"islands": islands, "default": C.slug(C.ISLAND)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return islands


def main():
    global OUT
    P = C.paths()
    OUT = C.WEB / C.slug(C.ISLAND)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"# Phase 3 web export for {C.ISLAND} -> {OUT.relative_to(C.ROOT)}\n")

    with rasterio.open(P["dem_utm"]) as ds:
        elev = ds.read(1)
        nodata = ds.nodata
        transform = ds.transform
        dem_w, dem_h = ds.width, ds.height
        bounds = ds.bounds
        epsg = ds.crs.to_epsg()
    with rasterio.open(P["basins"]) as ds:
        basins = ds.read(1)

    s = C.WEB_MAX_WIDTH / dem_w
    web_w, web_h = C.WEB_MAX_WIDTH, round(dem_h * s)
    print(f"  DEM {dem_w}x{dem_h} -> web {web_w}x{web_h} (scale {s:.4f})")

    sig = export_rasters(elev, nodata, transform, basins, s, web_w, web_h)
    n_bvec = export_basins_vector(basins, sig, transform, s)
    print(f"  base.png, basins.png, basins.geojson ({len(sig)} sig basins, {n_bvec} polygons)")
    n_streams = export_streams(transform, s, basins > 0)
    print(f"  streams.geojson ({n_streams} branches)")
    gdf, fracs = export_ahupuaa(transform, s, basins, sig)
    print(f"  ahupuaa.geojson ({len(gdf)} features)")

    meta = {
        "island": C.ISLAND,
        "mokupuni": C.ISLAND_CFG["mokupuni"],
        "epsg": epsg,
        "dem_size": [dem_w, dem_h],
        "web_size": [web_w, web_h],
        "utm_bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
        "m_per_px": round(C.TARGET_RES_M / s, 4),  # ground metres per web pixel
        "stream_threshold_cells": C.STREAM_THRESHOLD_CELLS,
        "min_basin_km2": C.MIN_BASIN_KM2,
        "n_ahupuaa": len(gdf),
        "n_basins_significant": len(sig),
        "moku_labels": moku_labels(gdf, transform, s),
        "layers": {
            "base": "base.png", "basins": "basins.png",
            "basins_vec": "basins.geojson", "streams": "streams.geojson",
            "ahupuaa": "ahupuaa.geojson",
        },
        "intro": ("Ahupuaʻa are traditional Hawaiian land divisions running mauka "
                  "to makai — ridge to reef — so each holds a full watershed. This "
                  "map overlays them on stream channels and basins computed from a "
                  "USGS 10 m elevation model, so you can see where the old "
                  "boundaries and the actual drainage agree, and where they part."),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    islands = write_manifest()

    # --- VERIFICATION GATE 3 ------------------------------------------------
    for name, rel in meta["layers"].items():
        f = OUT / rel
        assert f.exists() and f.stat().st_size > 0, f"missing web layer: {rel}"
    with rasterio.open(P["flowacc"]) as ds:  # round-trip the accumulation raster
        acc_rt = ds.read(1)
    assert acc_rt.shape == (dem_h, dem_w) and np.isfinite(acc_rt).all()
    fc = json.loads((OUT / "ahupuaa.geojson").read_text(encoding="utf-8"))
    names = [f["properties"]["ahupuaa"] for f in fc["features"]]
    assert len(names) == len(gdf) > 1
    joined = "".join(names)
    assert "�" not in joined and any(c in joined for c in "ʻāēīōū"), "names mangled"
    for png in ("base.png", "basins.png"):
        assert Image.open(OUT / png).size == (web_w, web_h), f"{png} size mismatch"
    # every basin id referenced by an ahupuaʻa has a polygon in basins.geojson
    have = {f["properties"]["id"] for f in
            json.loads((OUT / "basins.geojson").read_text())["features"]}
    ref = {b for f in fc["features"] for b in f["properties"]["basin_ids"]}
    assert ref <= have, f"basin_ids missing polygons: {sorted(ref - have)[:5]}"

    good = sum(1 for fr in fracs if fr >= 0.75)
    C.write_qa_section("Phase 3 — web export (`scripts/export_web.py`)", "\n".join([
        "**VERIFICATION: phase 3 — PASS**",
        "",
        f"- Payload in `web/data/{C.slug(C.ISLAND)}/`: base.png + basins.png at "
        f"{web_w}×{web_h}, basins.geojson ({n_bvec} polygons), streams.geojson "
        f"({n_streams} branches), ahupuaa.geojson ({len(gdf)} features), meta.json.",
        f"- All {len(meta['layers'])} layers named in meta.json exist; every basin "
        "referenced by an ahupuaʻa has a matching polygon.",
        "- Accumulation raster round-trips; ahupuaʻa names survive UTF-8 clean.",
        f"- Concordance: {good}/{len(gdf)} ahupuaʻa track a single computed "
        "watershed for ≥75% of their area; the rest is the interesting divergence.",
        f"- Manifest: islands available = "
        + ", ".join(i["name"] for i in islands if i["available"]) + ".",
    ]))

    print("\nVERIFICATION: phase 3")
    print(f"  all {len(meta['layers'])} layers present; names UTF-8 clean; "
          f"rasters {web_w}x{web_h}; {n_bvec} basin polygons")
    print(f"  {good}/{len(gdf)} ahupuaʻa ≥75% one watershed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
