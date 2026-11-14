"""Locator (Avishek): which building's room and window view match the photos?  -> matches.json

P comes from vision.room_match (Yug), W from vision.window_check (Gemini, Avishek). This file
only orchestrates and applies the threshold. A match is a lead to verify, not proof of
presence. If the window check cannot run honestly, W stays null and the reason is recorded.
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
    windows = sorted((p for p in ring.photos if p.has_window), key=lambda p: p.photo_id)
    results = vision.room_match(paths, sorted(scanned)) if scanned else []
    cue_floors = block.photo_cues.window_floor_est

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
            w_floors = None
            # no window photo -> W stays null and the lead is capped at Medium. Otherwise use
            # the first window photo (fixed order) the check can run on; never the best of many.
            for photo in windows[:config.MAX_WINDOW_PHOTOS_TRIED]:
                w = vision.window_check(photo.path, fix["lat"], fix["lon"], fix["heading_deg"])
                if w.get("W") is not None:
                    m.update(W=round(w["W"], 2), window_checked=True, window_checks=w["checks"],
                             window_photo=photo.photo_id, window_skipped=None)
                    w_floors = w.get("floor_range")
                    break
                m["window_skipped"] = w.get("skipped") or "window check could not run"
            # tightest trustworthy floor range: geo fix, then window check, then photo cues
            fr = fix.get("floor_range") or w_floors or cue_floors
            m["floor_range"] = list(fr) if fr else None
        matches.append(m)

    best = max((m["P"] for m in matches), default=0.0)
    existing = case.load("matches.json")
    prev = next((z for z in existing.zones if z.zone_id == zone_id), None) if existing else None
    out = {"zone_id": zone_id, "attempt": (prev.attempt + 1) if prev else 1, "threshold": thr,
           "best_P": best, "above_threshold": best >= thr, "photos_used": len(paths),
           "window_photos": len(windows), "matches": matches,
           "room_groups": room_groups(case, ring, {m["scan_id"] for m in matches if m["P"] >= thr})}

    blocks = [z.model_dump() for z in existing.zones if z.zone_id != zone_id] if existing else []
    return {"case_id": case.case_id, "ring_id": ring.ring_id,
            "zones": sorted(blocks + [out], key=lambda z: z["zone_id"])}


def weak_photos(case: Case, ring) -> list[dict]:
    """Photos from accounts with a weak (one-kind) tie to the ring: {photo_id, path, account}."""
    rings = case.load("rings.json")
    near = sorted({h.b if h.a in ring.members else h.a for h in (rings.weak_hints if rings else [])
                   if (h.a in ring.members) != (h.b in ring.members)})
    if not near:
        return []
    if case.input.dataset is None:   # stub scenario
        from ..data_tools import _stub
        return [p for p in _stub.scenario().get("weak_photos", []) if p["account"] in near]
    from .linker import load_dataset
    out, seen = [], set()
    for p in load_dataset(case.input.dataset)["posts"]:
        if p["account"] in near:
            for ph in p["photos"]:
                if ph["photo_id"] not in seen:
                    seen.add(ph["photo_id"])
                    out.append({"photo_id": ph["photo_id"], "path": ph["path"], "account": p["account"]})
    return out


def room_groups(case: Case, ring, matched_scans: set = frozenset()) -> list[dict]:
    """v2 background fingerprint: group the ring's photos plus weak-hint accounts' photos by
    room (sockets, lamps, carpet, light through blinds), not by the whole image, so cropped or
    edited photos still group. Feeds the Linker's note 4 (`room`) via the supervisor."""
    import json
    owner = {p.photo_id: p.account for p in ring.photos}
    extra = weak_photos(case, ring)
    owner.update({p["photo_id"]: p["account"] for p in extra if p["photo_id"] not in owner})
    paths = [p.path for p in ring.photos] + [p["path"] for p in extra]
    renders = {}
    d = case.dataset_dir()
    if d is not None and (d / "renders.json").exists():
        renders = json.loads((d / "renders.json").read_text(encoding="utf-8"))
    try:
        groups = vision.photo_groups(paths, renders=renders)
    except TypeError:   # a real photo_groups(photo_paths) without the stub's renders argument
        groups = vision.photo_groups(paths)
    out = []
    for g in groups:
        accts = sorted({owner[x] for x in g["photos"] if x in owner})
        scan = g.get("scan_id")
        out.append({"group_id": g["group_id"], "photos": sorted(g["photos"]), "accounts": accts,
                    "scan_id": scan,
                    "details": list(g.get("details", [])),
                    # only a group that also holds ring photos ties an outsider to the ring
                    "outside_ring": [a for a in accts if a not in ring.members]
                    if any(a in ring.members for a in accts) else []})
    return out


if __name__ == "__main__":
    from . import cli
    cli("locator", "matches.json", run, [("--zone", {"required": True, "dest": "zone_id"})])
