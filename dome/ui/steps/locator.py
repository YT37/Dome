"""Locator, photo to room: room groups, DINOv2 coarse ranking, shortlist, inliers, room groups matched, P.

Reads case/<id>/room_match.json (else data/matches/summary.json; old files only have
{scan_id: {P, evidence}}), matches.json and candidates.json.
"""
from __future__ import annotations

from ._base import asset, chart, fmt, not_recorded, step, table


def _normalise(rm: dict) -> dict:
    """Old summaries are {scan_id: {P, evidence}}; new ones have scans/P/coarse/... keys."""
    if "scans" in rm or "coarse" in rm:
        return rm
    scans = {k: v for k, v in rm.items() if isinstance(v, dict) and "P" in v}
    return {"scans": scans, "P": {k: v.get("P") for k, v in scans.items()}}


def build(ctx) -> list:
    raw, rm_src = ctx.room_match()
    best, zone = ctx.best_match()
    steps = []
    if not raw:
        final = f"Best scan {best.get('scan_id')} with P {best.get('P')}" if best else "No match recorded"
        return [not_recorded("final", "Photo to room", final, ctx.src("matches.json"))]
    rm = _normalise(raw)
    top = (best or {}).get("scan_id") or max(rm.get("P", {"": 0}), key=lambda k: rm["P"].get(k) or 0)
    props = ctx.property_of_scan()
    scans = rm.get("scans", {})
    min_inl = rm.get("min_inliers")

    # 1. ring photos grouped into rooms
    groups = rm.get("groups")
    photos = rm.get("photos")
    if groups:
        ev_img = {e["photo"]: e.get("match_img") for s in scans.values() for e in s.get("evidence", [])}
        gview = []
        for i, g in enumerate(groups):
            img = next((asset(ev_img[p]) for p in g["photos"] if ev_img.get(p)), None)
            gview.append({"label": f"room {i + 1}: " + ", ".join(g["photos"]), "src": img,
                          "matched": any(g.get("matched", {}).values())})
        steps.append(step("groups", "Ring photos grouped by room", "image",
                          {"images": [g for g in gview if g["src"]],
                           "list": [g["label"] for g in gview]},
                          f"{len(photos or [])} ring photos fall into {len(groups)} room groups. Images are shown "
                          f"for groups that matched a scan (ad photo left, scan view right); the rest are listed.",
                          rm_src))
    else:
        steps.append(not_recorded("groups", "Ring photos grouped by room",
                                  f"{(zone or {}).get('photos_used', '?')} photos used", rm_src))

    # 2. candidate scans on the map
    pts = []
    for z in (ctx.load("candidates.json") or {}).get("zones", []):
        for c in z.get("candidates", []):
            if c.get("has_scan") and c.get("lat") is not None:
                pts.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                            "properties": {"label": c.get("property_id"), "top": c.get("scan_id") == top}})
    if pts:
        steps.append(step("scans_map", "Scanned candidates in the dome", "map",
                          {"features": {"type": "FeatureCollection", "features": pts}},
                          f"{len(pts)} candidate buildings have a 3D scan. Red: the one that matched.",
                          ctx.src("candidates.json")))

    # 3. coarse ranking (DINOv2 retrieval)
    coarse = rm.get("coarse")
    if coarse:
        top15 = sorted(coarse, key=lambda c: c["rank"])[:15]
        steps.append(step("coarse", "Coarse ranking: which scans look like the photos", "chart",
                          chart([c["scan_id"] for c in top15],
                                [{"label": "DINOv2 similarity", "data": [c["score"] for c in top15]}],
                                horizontal=True, highlight=[i for i, c in enumerate(top15) if c["scan_id"] == top],
                                x="similarity"),
                          f"All {len(coarse)} scans ranked by global image similarity; the top "
                          f"{rm.get('coarse_keep', len(rm.get('shortlist', [])))} go on to point matching. "
                          f"Highlighted: {top}.", rm_src))
    else:
        steps.append(not_recorded("coarse", "Coarse ranking", f"{len(scans)} scans compared", rm_src))

    # 4. shortlist table
    shortlist = rm.get("shortlist")
    if shortlist:
        rank = {c["scan_id"]: c for c in coarse or []}
        rows = []
        for s in shortlist:
            c = props.get(s, {})
            rows.append([s, rank.get(s, {}).get("rank", "—"), fmt(rank.get(s, {}).get("score"), 3),
                         c.get("property_id", "—"), c.get("type", "—"), c.get("floors", "—")])
        steps.append(step("shortlist", "Shortlist for point matching", "table",
                          table(["scan", "coarse rank", "similarity", "building id", "type", "floors"], rows,
                                [i for i, s in enumerate(shortlist) if s == top]),
                          "Scans kept for DISK + LightGlue matching. No addresses: building ids only.",
                          [rm_src, ctx.src("candidates.json")]))

    # 5. one ad photo with its match image
    ev = sorted(scans.get(top, {}).get("evidence", []), key=lambda e: -(e.get("inliers") or 0))
    if ev and asset(ev[0].get("match_img")):
        e = ev[0]
        steps.append(step("pair", "One ad photo against the scan", "image",
                          {"images": [{"src": asset(e["match_img"]), "label": f"{e['photo']} → {e.get('view_id')}"}]},
                          f"{e['photo']}: {e.get('inliers')} matched points to {e.get('view_id')} (lines join the same "
                          f"physical points; RANSAC kept only geometrically consistent ones).", rm_src))

    # 6. inliers per photo per shortlisted scan
    full = rm.get("full")
    if full and shortlist:
        ph = list(full)
        clear = [s for s in shortlist if min_inl and any((full[p].get(s) or {}).get("inliers", 0) >= min_inl for p in ph)]
        steps.append(step("inliers", "Matched points per photo and scan", "chart",
                          chart(ph, [{"label": s, "data": [(full[p].get(s) or {}).get("inliers", 0) for p in ph],
                                      "highlight": s == top} for s in shortlist],
                                threshold={"value": min_inl, "label": f"min {min_inl} inliers"} if min_inl else None,
                                y="inliers"),
                          f"A photo counts as a match only at {min_inl}+ inliers. Scans with at least one photo over "
                          f"the line: {', '.join(clear) or 'none'} ({len(clear)} of {len(shortlist)}).", rm_src))
    else:
        steps.append(not_recorded("inliers", "Matched points per photo and scan",
                                  f"{len(ev)} photos matched {top}", rm_src))

    # 7. room groups matched
    if groups and shortlist:
        rows = [[", ".join(g["photos"])] + ["✓" if g.get("matched", {}).get(s) else "–" for s in shortlist]
                for g in groups]
        hit = sum(1 for g in groups if g.get("matched", {}).get(top))
        steps.append(step("groups_matched", "Room groups matched per scan", "table",
                          table(["room group"] + shortlist, rows),
                          f"P is the share of room groups that match: {hit} of {len(groups)} for {top}.", rm_src))

    # 8. P per scan
    P = rm.get("P") or {}
    if P:
        keys = shortlist or sorted(P, key=lambda k: -(P[k] or 0))[:8]
        thr = (zone or {}).get("threshold", 0.4)
        steps.append(step("P", "P per scan", "chart",
                          chart(keys, [{"label": "P", "data": [P.get(k) or 0 for k in keys]}],
                                threshold={"value": thr, "label": f"threshold {thr}"},
                                highlight=[i for i, k in enumerate(keys) if k == top], y="P"),
                          f"{top}: P {fmt(P.get(top))}. Other scans at or above the {thr} threshold: "
                          f"{len([k for k in P if k != top and (P[k] or 0) >= thr])} of {len(P) - 1}.",
                          [rm_src, ctx.src("matches.json")]))
    return steps
