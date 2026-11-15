"""Locator, window check: the window photo, the oblique facade, the checklist, W, the fingerprint.

Reads case/<id>/window_check.json ({scan_id: {property_id, photo, W, items, crop_box, oblique, reasons}})
and assets.json["fingerprint"] for the best-matching scan.
"""
from __future__ import annotations

from ._base import asset, fmt, not_recorded, step, table


def _yn(v):
    return {True: "✓ agree", False: "✗ differ", None: "unclear (not counted)"}.get(v, str(v))


def build(ctx) -> list:
    best, zone = ctx.best_match()
    pack, pack_src = ctx.pack()
    wc_all = ctx.load("window_check.json") or {}
    scan = (best or {}).get("scan_id")
    wc = wc_all.get(scan) if scan else None
    src = ctx.src("window_check.json")
    steps = []
    if not wc:
        W = (best or {}).get("W")
        final = "No window photo, so the window check did not run (W skipped, lead capped at Medium)" if W is None \
            else f"W {W}"
        steps.append(not_recorded("final", "Window check", final, ctx.src("matches.json")))
    else:
        ev_img = {e["photo"]: e.get("match_img") for e in (best or {}).get("evidence", [])}
        photo_img = asset(ev_img.get(wc.get("photo")))
        if photo_img:
            steps.append(step("photo", "The ad photo with a window", "image",
                              {"images": [{"src": photo_img, "label": wc.get("photo")}]},
                              f"{wc.get('photo')} shows a window view (ad photo on the left).", src))
        else:
            steps.append(step("photo", "The ad photo with a window", "text",
                              {"text": f"Window photo: {wc.get('photo')}",
                               "note": "the ad photo itself is not served to the page"},
                              f"{wc.get('photo')} is the ring photo with a window; the checklist below reads it.", src))
        band = next((o for o in (pack or {}).get("obliques", []) if o.get("floor_band")), None)
        if band and asset(band.get("img")):
            steps.append(step("facade", f"Oblique facade at floor {(pack or {}).get('floor', '?')}", "image",
                              {"images": [{"src": asset(band["img"]), "label": band.get("camera", {}).get("direction", "")}],
                               "box": wc.get("crop_box")},
                              f"The Vexcel oblique of the matched facade; floor band {band['floor_band'][0]}–"
                              f"{band['floor_band'][1]} m. Crop box used: {wc.get('crop_box')}.", [src, pack_src]))
        items = wc.get("items") or []
        if items:
            rows = [[i.get("item", "").replace("_", " "), i.get("ad"), i.get("oblique"), _yn(i.get("agree"))]
                    for i in items]
            counted = [i for i in items if i.get("agree") is not None]
            steps.append(step("checklist", "What the window sees vs. what the oblique shows", "table",
                              table(["item", "ad photo says", "oblique says", "agree"], rows),
                              f"{sum(1 for i in counted if i['agree'])} of {len(counted)} counted items agree; "
                              f"'unclear' is not counted.", src))
        steps.append(step("W", f"W = {fmt(wc.get('W'))}", "text",
                          {"text": f"W {fmt(wc.get('W'))}", "bullets": wc.get("reasons") or []},
                          "W is the window-view agreement the Briefer uses; High needs W ≥ 0.6.", src))

    fp = (pack or {}).get("fingerprint")
    if fp and not fp.get("skipped"):
        rows = [[i.get("item", "").replace("_", " "), i.get("ad"), i.get("facade"), _yn(i.get("agree"))]
                for i in fp.get("items", [])]
        n, of = fp.get("agree"), fp.get("of", 4)
        verdict = fp.get("verdict") or (f"fingerprint agrees ({n} of {of})" if (n or 0) >= 3 else "for analyst review")
        steps.append(step("fingerprint", f"Window fingerprint: {verdict}", "table",
                          table(["item", "ad photo", "facade", "agree"], rows),
                          f"{n} of {of} items agree → {verdict}. Pane count, mullions, shape and spacing compared "
                          f"with the facade grid.", pack_src))
    elif fp and fp.get("skipped"):
        steps.append(step("fingerprint", "Window fingerprint", "text",
                          {"text": f"skipped: {fp['skipped']}"}, "The fingerprint did not run.", pack_src))
    return steps
