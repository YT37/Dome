"""Locator (Avishek): which building's room and window view match the photos?  -> matches.json

P comes from vision.room_match, W from vision.window_check (Yug's tools). This file only
orchestrates and applies the threshold. A match is a lead to verify, not proof of presence.
"""
from __future__ import annotations

import math

from .. import config
from ..case import Case
from ..data_tools import geo, vision


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(
        math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def run(case: Case, zone_id: str) -> dict:
    cands, ring = case.load("candidates.json"), case.selected_ring()
    block = next((z for z in cands.zones if z.zone_id == zone_id), None) if cands else None
    if block is None or ring is None:
        raise ValueError(f"no candidates for zone {zone_id}")

    thr = config.MATCH_THRESHOLD
    scanned = {c.scan_id: c for c in block.candidates if c.has_scan}
    paths = [p.path for p in ring.photos]
    windows = [p for p in ring.photos if p.has_window]
    results = vision.room_match(paths, sorted(scanned)) if scanned else []

    matches = []
    for r in sorted(results, key=lambda r: (-r["P"], r["scan_id"])):
        c = scanned[r["scan_id"]]
        m = {"property_id": c.property_id, "scan_id": c.scan_id, "P": round(r["P"], 2), "W": None,
             "window_checked": False, "floor_range": None, "geo": None, "window_checks": {},
             "evidence": [{"photo": e["photo"], "view": e["view_id"], "inliers": e["inliers"],
                           "match_img": e.get("match_img")} for e in r.get("evidence", [])]}
        if r["P"] >= thr:
            fix = geo.fix_scan_location(c.scan_id, c.lat, c.lon)
            m["geo"] = {"lat": fix["lat"], "lon": fix["lon"], "heading_deg": fix["heading_deg"],
                        "pin_moved_m": round(_dist_m(c.lat, c.lon, fix["lat"], fix["lon"])),
                        "error_estimate_m": fix["error_estimate_m"]}
            m["floor_range"] = fix.get("floor_range")
            if windows:   # no window photo -> W stays null and the lead is capped at Medium
                w = vision.window_check(windows[0].path, fix["lat"], fix["lon"], fix["heading_deg"])
                m.update(W=round(w["W"], 2), window_checked=True, window_checks=w["checks"],
                         floor_range=w.get("floor_range") or m["floor_range"])
        matches.append(m)

    best = max((m["P"] for m in matches), default=0.0)
    out = {"zone_id": zone_id, "threshold": thr,
           "best_P": best, "above_threshold": best >= thr, "photos_used": len(paths),
           "window_photos": len(windows), "matches": matches}

    existing = case.load("matches.json")
    blocks = [z.model_dump() for z in existing.zones if z.zone_id != zone_id] if existing else []
    return {"case_id": case.case_id, "ring_id": ring.ring_id,
            "zones": sorted(blocks + [out], key=lambda z: z["zone_id"])}


if __name__ == "__main__":
    from . import cli
    cli("locator", "matches.json", run, [("--zone", {"required": True, "dest": "zone_id"})])
