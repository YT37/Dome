"""Locator, better GPS: rough pin, nearby footprints, outline fit, pin move, floor, oblique floor band.

Reads data/demo_assets/<scan>/assets.json["geo_steps"] for the best-matching scan (from matches.json).
No heading step: the heading for Ring A is not reliable.
"""
from __future__ import annotations

from ._base import asset, fmt, not_recorded, step, table


def _pt(lon, lat, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


def build(ctx) -> list:
    pack, src = ctx.pack()
    best, _ = ctx.best_match()
    if not pack:
        geo = (best or {}).get("geo") or {}
        return [not_recorded("final", "Better GPS",
                             f"pin moved {geo.get('pin_moved_m', '?')} m, error ±{geo.get('error_estimate_m', '?')} m",
                             ctx.src("matches.json"))]
    gs = pack.get("geo_steps")
    if not gs:
        fp = pack.get("fixed_pin") or {}
        return [not_recorded("final", "Better GPS", f"pin moved {fp.get('moved_m', '?')} m", src)]
    ortho = pack.get("ortho") or {}
    img = {"src": asset(ortho.get("img")), "bounds": ortho.get("bounds")} if ortho.get("img") else None
    rough, fixed = gs.get("rough_pin") or {}, gs.get("fixed_pin") or {}
    fps = gs.get("footprints") or []
    steps = []

    if rough:
        steps.append(step("rough", "The listing pin on Vexcel imagery", "map",
                          {"features": {"type": "FeatureCollection", "features": [
                              _pt(rough["lon"], rough["lat"], label="listing pin", color="#9aa0ad")]},
                           "image": img, "zoom": 18.6},
                          f"Where the record puts the building ({rough.get('source', 'listing coordinates')}).", src))

    if fps:
        feats = [{**f["geojson"], "properties": {"label": f["building_id"], "chosen": bool(f.get("chosen"))}}
                 for f in fps if f.get("geojson")]
        if rough:
            feats.append(_pt(rough["lon"], rough["lat"], label="listing pin", color="#9aa0ad"))
        steps.append(step("footprints", "Vexcel building footprints near the pin", "map",
                          {"features": {"type": "FeatureCollection", "features": feats}, "image": img, "zoom": 18.4},
                          f"{len(fps)} footprints within reach of the pin are candidates for the scanned building.", src))
        rows, hi = [], []
        for i, f in enumerate(fps):
            rows.append([f["building_id"], "not scored" if f.get("fit_score") is None else fmt(f["fit_score"], 3),
                         "not scored" if f.get("outline_score") is None else fmt(f["outline_score"], 3),
                         "—" if f.get("pin_prior") is None else fmt(f["pin_prior"], 2), "✓" if f.get("chosen") else ""])
            if f.get("chosen"):
                hi.append(i)
        steps.append(step("fit", "Scan outline fit per footprint", "table",
                          table(["footprint", "fit score", "outline score", "pin prior", "chosen"], rows, hi),
                          gs.get("fit_note") or "The scan's floor outline is fitted to each footprint; the best fit wins.",
                          src))

    if rough and fixed:
        line = {"type": "Feature", "properties": {"label": "move"},
                "geometry": {"type": "LineString", "coordinates": [[rough["lon"], rough["lat"]], [fixed["lon"], fixed["lat"]]]}}
        steps.append(step("move", f"Pin moved {fmt(fixed.get('moved_m'), 1)} m", "map",
                          {"features": {"type": "FeatureCollection", "features": [
                              _pt(rough["lon"], rough["lat"], label="listing pin", color="#9aa0ad"),
                              _pt(fixed["lon"], fixed["lat"], label="fixed pin", color="#ef5f5f"), line]},
                           "image": img, "zoom": 19},
                          f"Moved {fmt(fixed.get('moved_m'), 1)} m onto the chosen footprint; error estimate "
                          f"±{fmt(fixed.get('error_estimate_m'), 1)} m"
                          + (f", confidence {fmt(fixed.get('confidence'))}." if fixed.get("confidence") is not None else "."),
                          src))

    fl = gs.get("floor") or {}
    if fl:
        steps.append(step("floor", "Floor from the CoStar record", "table",
                          table(["building id", "type", "floors", "unit", "floor", "source"],
                                [[(best or {}).get("property_id", "—"), (pack.get("costar") or {}).get("type", "—"),
                                  (pack.get("costar") or {}).get("floors", "—"), fl.get("unit", "—"),
                                  fl.get("floor", "—"), fl.get("source", "—")]]),
                          "The unit number in the CoStar record gives the floor. No street address is shown.", src))

    band = next((o for o in pack.get("obliques", []) if o.get("floor_band")), None)
    band_img = asset(gs.get("floor_band_img")) or (asset(band.get("img")) if band else None)
    if band_img:
        cap = (f"Floor {fl.get('floor', pack.get('floor', '?'))}: {band['floor_band'][0]}–{band['floor_band'][1]} m above "
               f"ground on the Vexcel oblique." if band else "Vexcel oblique with the floor band.")
        steps.append(step("band", "Oblique view with the floor band", "image",
                          {"images": [{"src": band_img, "label": (band or {}).get("camera", {}).get("direction", "")}]},
                          cap, src))
    return steps
