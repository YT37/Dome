"""Lister: buildings in the zone, photo cues, the fit score, the kept list. No addresses."""
from __future__ import annotations

from collections import Counter

from ._base import chart, fmt, not_recorded, step, table


def build(ctx) -> list:
    cands = (ctx.load("candidates.json") or {}).get("zones")
    src = ctx.src("candidates.json")
    if not cands:
        return [not_recorded("final", "Lister", "no candidates.json", src)]
    best, _ = ctx.best_match()
    top = (best or {}).get("property_id")
    steps = []
    for z in cands:
        cs = z.get("candidates", [])
        scanned = sum(1 for c in cs if c.get("has_scan"))
        steps.append(step(f"funnel_{z['zone_id']}", f"{z['zone_id']}: from every building to the list", "chart",
                          chart(["in the zone", "kept", "with a scan"],
                                [{"label": "buildings", "data": [z.get("total_in_zone") or len(cs), len(cs), scanned]}]),
                          f"{z.get('total_in_zone')} CoStar buildings in the zone; {len(cs)} kept"
                          + (" (scanned only: wide zone)" if z.get("scanned_only") else "") + f"; {scanned} have a scan.",
                          src))
        cues = z.get("photo_cues") or {}
        steps.append(step(f"cues_{z['zone_id']}", "What the photos say about the building", "text",
                          {"text": f"setting: {cues.get('setting', 'unknown')}",
                           "bullets": [f"window floor estimate: {cues.get('window_floor_est')}",
                                       f"features: {', '.join(cues.get('features') or []) or 'none'}",
                                       f"read by: {cues.get('source', 'unknown')}"]},
                          "Photo cues are read once from the ring photos and drive the fit score.", src))
        bins = Counter(round((c.get("fit") or 0) * 10) / 10 for c in cs)
        keys = sorted(bins)
        steps.append(step(f"fit_{z['zone_id']}", "Fit score distribution", "chart",
                          chart([f"{k:.1f}" for k in keys], [{"label": "buildings", "data": [bins[k] for k in keys]}],
                                x="fit", y="buildings"),
                          "fit = 0.5 type match + 0.3 floors fit the window height + 0.2 other cues.", src))
        ranked = sorted(cs, key=lambda c: (-(c.get("fit") or 0), not c.get("has_scan")))[:12]
        steps.append(step(f"top_{z['zone_id']}", "Top of the list", "table",
                          table(["building id", "type", "floors", "fit", "scan"],
                                [[c.get("property_id"), c.get("type"), c.get("floors"), fmt(c.get("fit")),
                                  "yes" if c.get("has_scan") else "no"] for c in ranked],
                                [i for i, c in enumerate(ranked) if c.get("property_id") == top]),
                          "Building ids only; the address stays on the server.", src))
    return steps
