"""Lister (Avishek): which buildings are inside the zone and fit the photos?  -> candidates.json

fit = 0.5 (property type matches) + 0.3 (floor count fits the window height) + 0.2 (other cues).
The vision model only reads the cues; the fit number is computed here.
"""
from __future__ import annotations

from .. import config
from ..case import Case
from ..data_tools import costar, vision

TYPES_FOR_SETTING = {"apartment": {"multifamily"}, "hotel": {"hospitality"},
                     "house": {"single_family"}}


def score_fit(prop: dict, cues: dict) -> tuple[float, list[str]]:
    w, fit, reasons = config.FIT_WEIGHTS, 0.0, []
    setting = cues.get("setting", "unknown")
    if prop["type"] in TYPES_FOR_SETTING.get(setting, set()):
        fit += w["type"]
        reasons.append(f"{prop['type']} matches {setting} photos")
    est, floors = cues.get("window_floor_est"), prop.get("floors")
    if est and floors:
        if floors >= est[0]:
            fit += w["floors"]
            reasons.append(f"{floors} floors fits a floor {est[0]} to {est[1]} view")
    elif floors:
        fit += w["floors"] / 2   # no window height to check against: half credit
        reasons.append("no window height estimate; floor count not checked")
    wanted = cues.get("features") or []
    if wanted:
        have = set(prop.get("features") or [])
        hits = [f for f in wanted if f in have]
        fit += w["cues"] * len(hits) / len(wanted)
        if hits:
            reasons.append("visible features match: " + ", ".join(hits))
    return round(min(fit, 1.0), 2), reasons


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(
        math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def hint_boost(prop: dict, hints) -> tuple[float, str]:
    """v2: up to +0.15 fit for a building within 500 m of a merchant or echo hint (a motel,
    short-term rental or rideshare drop-off the ring paid), scaled by the hint's weight.
    A boost can reorder the list but never lifts a lead past Low: only a photo match does."""
    best, why = 0.0, ""
    for h in hints:
        if h.kind not in ("merchant", "echo") or h.lat is None or h.lon is None:
            continue
        d = _dist_m(prop["lat"], prop["lon"], h.lat, h.lon)
        if d <= config.HINT_BOOST_RADIUS_M and config.HINT_BOOST_MAX * h.weight > best:
            best = round(config.HINT_BOOST_MAX * h.weight, 3)
            why = f"{int(d)} m from {h.text} ({h.kind} hint, +{best:.2f})"
    return best, why


def run(case: Case, zone_id: str, scanned_only: bool = False) -> dict:
    zones, ring = case.load("zones.json"), case.selected_ring()
    zone = next((z for z in zones.zones if z.zone_id == zone_id), None) if zones else None
    if zone is None or ring is None:
        raise ValueError(f"zone {zone_id} or ring not found")

    props = costar.properties_in_polygon([tuple(p) for p in zone.polygon], [])
    cues = vision.photo_cues([p.path for p in ring.photos])   # photos are read once
    cands = []
    for p in props:
        if scanned_only and not p.get("has_scan"):
            continue                                            # wide zone: scanned buildings only
        raw = str(p.get("type") or "").lower()
        p = {**p, "type": config.COSTAR_TYPE_MAP.get(raw, raw)}  # CoStar words -> Dome's three
        fit, reasons = score_fit(p, cues)
        boost, why = hint_boost(p, ring.location_hints)
        if boost:
            fit = round(min(1.0, fit + boost), 2)
            reasons.append(why)
        cands.append({"property_id": p["property_id"], "address": p["address"], "lat": p["lat"],
                      "lon": p["lon"], "type": p["type"], "floors": p.get("floors"), "fit": fit,
                      "has_scan": bool(p.get("has_scan")), "scan_id": p.get("scan_id"),
                      "fit_reasons": reasons})
    cands.sort(key=lambda c: (not c["has_scan"], -c["fit"], c["property_id"]))
    block = {"zone_id": zone_id, "scanned_only": scanned_only, "total_in_zone": len(props),
             "photo_cues": cues, "candidates": cands[:config.MAX_CANDIDATES]}

    existing = case.load("candidates.json")
    blocks = [z.model_dump() for z in existing.zones if z.zone_id != zone_id] if existing else []
    return {"case_id": case.case_id, "ring_id": ring.ring_id,
            "zones": sorted(blocks + [block], key=lambda z: z["zone_id"])}


if __name__ == "__main__":
    from . import cli
    cli("lister", "candidates.json", run,
        [("--zone", {"required": True, "dest": "zone_id"}),
         ("--scanned-only", {"action": "store_true", "dest": "scanned_only"})])
