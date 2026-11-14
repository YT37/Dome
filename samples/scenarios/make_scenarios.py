"""Writes the stub fixture for Ring A, the one ring Dome is built and demoed around.

The stub data_tools (CoStar, Matterport, Vexcel, vision, geo) answer from this file until
Yug's real tools land. All data here is SYNTHETIC: invented accounts, 555 phone numbers,
invented property ids.

Run:  python samples/scenarios/make_scenarios.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def photos(prefix: int, n: int, windows: int, accounts: list[str]) -> list[dict]:
    return [{"photo_id": f"img_{prefix + i}", "path": f"data/photos/img_{prefix + i}.jpg",
             "account": accounts[i % len(accounts)], "has_window": i < windows} for i in range(n)]


def bldg(pid, lat, lon, typ, floors, scan=None, units=None, year=2005):
    return {"property_id": pid, "address": f"(synthetic) {pid}", "lat": lat, "lon": lon,
            "type": typ, "floors": floors, "units": units, "year_built": year,
            "has_scan": scan is not None, "scan_id": scan}


def box(lat0, lon0, lat1, lon1):
    return [[lat0, lon0], [lat1, lon0], [lat1, lon1], [lat0, lon1]]


def ev(photo, scan, sweep, az, inliers):
    return {"photo": photo, "view_id": f"{scan}/sweep_{sweep}/az_{az}", "inliers": inliers,
            "match_img": f"data/matches/{photo}_{scan}.jpg"}


# Ring A: one zone, one building, room + window match -> High lead.
RING_A = {
    "scenario": "ring_a",
    # the account to investigate in each dataset (the case follows the ring containing it)
    "seed_account": {"mini": "acct_017", "synth": "acct_103"},
    "rings": {
        "rings": [{
            "ring_id": "R-A", "members": ["acct_017", "acct_102", "acct_118", "acct_233"],
            "confidence": 0.91, "key_kinds": ["contact", "text", "photo"],
            "links": [
                {"a": "acct_017", "b": "acct_102", "keys": ["contact:555-0142", "text:tmpl_7"],
                 "kinds": ["contact", "text"], "strength": 0.96,
                 "reason": "same phone in 14 ads; reworded copy of the same script"},
                {"a": "acct_102", "b": "acct_118", "keys": ["photo:phash_9c1e", "text:tmpl_7"],
                 "kinds": ["photo", "text"], "strength": 0.92,
                 "reason": "same room photo reposted; same ad template"}],
            "recruiters": [{"account": "acct_233",
                            "reason": "bio says modelling agency; 31 of 33 reposts go to ring accounts"}],
            "place_keys": ["cell_29.76_-95.37"],
            "photos": photos(311, 9, 3, ["acct_017", "acct_102", "acct_118"])}],
        "weak_hints": [{"a": "acct_017", "b": "acct_404", "keys": ["place:cell_29.76_-95.37"],
                        "kinds": ["place"], "strength": 0.3,
                        "reason": "same 1 km cell only; one key kind is a hint, not a link"}]},
    "zones": [{"zone_id": "Z-A1", "polygon": box(29.755, -95.375, 29.768, -95.358),
               "area_km2": 2.4, "weight_share": 0.81, "confidence": 0.74, "wide": False,
               "reasons": ["34 ads name Midtown or a Midtown landmark", "area code 713 fits",
                           "login layer off"]}],
    "buildings": [
        bldg("CS-88412", 29.7603, -95.3681, "multifamily", 6, "mp_4471", 120, 2014),
        bldg("CS-88107", 29.7641, -95.3702, "multifamily", 4, "mp_2210", 64, 1998),
        bldg("CS-87990", 29.7590, -95.3625, "hospitality", 12, "mp_3302", 210, 2008),
        bldg("CS-88533", 29.7662, -95.3655, "multifamily", 2, None, 16, 1975),
        bldg("CS-88021", 29.7572, -95.3711, "office", 20, None, None, 1985),
        bldg("CS-88390", 29.7655, -95.3604, "single_family", 1, None, 1, 1962),
        bldg("CS-88615", 29.7618, -95.3733, "retail", 1, None, None, 1990),
        bldg("CS-90001", 29.8000, -95.4000, "multifamily", 8, "mp_9001", 150, 2019)],
    "photo_cues": {"setting": "apartment", "window_floor_est": [3, 5],
                   "features": ["balcony", "street trees"]},
    "room_match": {
        "mp_4471": {"P": 0.78, "evidence": [ev("img_311", "mp_4471", 12, 135, 212),
                                            ev("img_314", "mp_4471", 7, 270, 164)]},
        "mp_2210": {"P": 0.22, "evidence": [ev("img_312", "mp_2210", 3, 90, 41)]},
        "mp_3302": {"P": 0.11, "evidence": []}},
    "geo": {"mp_4471": {"lat": 29.7612, "lon": -95.3671, "heading_deg": 212, "building_id": "CS-88412",
                        "floor_range": [3, 5], "error_estimate_m": 12,
                        "evidence": ["scan floor plan matches building outline"]}},
    "window": {"mp_4471": {"W": 0.67, "floor_range": [3, 5],
                           "checks": {"road_front": True, "parking_front": True,
                                      "building_across": False}}},
}

if __name__ == "__main__":
    out = HERE / "ring_a" / "scenario.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(RING_A, indent=2), encoding="utf-8")
    print("wrote", out)
