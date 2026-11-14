"""Writes the stub scenario fixtures (ring_a, ring_b, ring_c, weak_ring).

All data here is SYNTHETIC: invented accounts, 555 phone numbers, invented property ids.
Run:  python samples/scenarios/make_scenarios.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def photos(prefix: int, n: int, windows: int, accounts: list[str], strength: str = "core") -> list[dict]:
    return [{"photo_id": f"img_{prefix + i}", "path": f"data/photos/img_{prefix + i}.jpg",
             "account": accounts[i % len(accounts)], "link_strength": strength,
             "has_window": i < windows} for i in range(n)]


def bldg(pid, lat, lon, typ, floors, scan=None, units=None, year=2005, address=None):
    return {"property_id": pid, "address": address or f"(synthetic) {pid}", "lat": lat, "lon": lon,
            "type": typ, "floors": floors, "units": units, "year_built": year,
            "has_scan": scan is not None, "scan_id": scan}


def box(lat0, lon0, lat1, lon1):
    return [[lat0, lon0], [lat1, lon0], [lat1, lon1], [lat0, lon1]]


def ev(photo, scan, sweep, az, inliers):
    return {"photo": photo, "view_id": f"{scan}/sweep_{sweep}/az_{az}", "inliers": inliers,
            "match_img": f"data/matches/{photo}_{scan}.jpg"}


SCENARIOS = {}

# ---- Ring A: one zone, one building, room + window match -> High ----
SCENARIOS["ring_a"] = {
    "scenario": "ring_a",
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
            "photos": photos(311, 9, 3, ["acct_017", "acct_102", "acct_118"]),
            "photo_expansion_used": False}],
        "weak_hints": [{"a": "acct_017", "b": "acct_404", "keys": ["place:cell_29.76_-95.37"],
                        "kinds": ["place"], "strength": 0.3,
                        "reason": "same 1 km cell only; one key kind is a hint, not a link"}]},
    "weak_photos": photos(390, 2, 0, ["acct_404"], "weak"),
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
        "mp_4471": {"core": {"P": 0.78, "evidence": [ev("img_311", "mp_4471", 12, 135, 212),
                                                     ev("img_314", "mp_4471", 7, 270, 164)]}},
        "mp_2210": {"core": {"P": 0.22, "evidence": [ev("img_312", "mp_2210", 3, 90, 41)]}},
        "mp_3302": {"core": {"P": 0.11, "evidence": []}}},
    "geo": {"mp_4471": {"lat": 29.7612, "lon": -95.3671, "heading_deg": 212, "building_id": "CS-88412",
                        "floor_range": [3, 5], "error_estimate_m": 12,
                        "evidence": ["scan floor plan matches building outline"]}},
    "window": {"mp_4471": {"W": 0.67, "floor_range": [3, 5],
                           "checks": {"road_front": True, "parking_front": True,
                                      "building_across": False}}},
}

# ---- Ring B: clues split over 2 areas, photos from 2 buildings -> two zones, two leads ----
SCENARIOS["ring_b"] = {
    "scenario": "ring_b",
    "rings": {
        "rings": [{
            "ring_id": "R-B", "members": ["acct_501", "acct_502", "acct_517", "acct_530"],
            "confidence": 0.82, "key_kinds": ["contact", "interaction", "text"],
            "links": [
                {"a": "acct_501", "b": "acct_502", "keys": ["contact:555-0177", "interaction:repost_x9"],
                 "kinds": ["contact", "interaction"], "strength": 0.93,
                 "reason": "same payment handle; reposted each other 9 times"},
                {"a": "acct_502", "b": "acct_517", "keys": ["text:tmpl_12", "interaction:reply_x6"],
                 "kinds": ["text", "interaction"], "strength": 0.78,
                 "reason": "same ad script; both amplify the same posts within an hour"}],
            "recruiters": [], "place_keys": ["cell_29.74_-95.39", "cell_29.81_-95.34"],
            "photos": photos(601, 8, 4, ["acct_501", "acct_502", "acct_517"]),
            "photo_expansion_used": False}],
        "weak_hints": []},
    "weak_photos": [],
    "zones": [
        {"zone_id": "Z-B1", "polygon": box(29.735, -95.400, 29.748, -95.385), "area_km2": 2.1,
         "weight_share": 0.55, "confidence": 0.70, "wide": False,
         "reasons": ["19 ads name Montrose", "landmark: the Westheimer mural"]},
        {"zone_id": "Z-B2", "polygon": box(29.805, -95.350, 29.818, -95.335), "area_km2": 2.1,
         "weight_share": 0.45, "confidence": 0.66, "wide": False,
         "reasons": ["15 ads name Northside", "area code 832 fits"]}],
    "buildings": [
        bldg("CS-51010", 29.7412, -95.3921, "multifamily", 5, "mp_5101", 80, 2011),
        bldg("CS-51022", 29.7440, -95.3890, "multifamily", 3, "mp_5102", 36, 1999),
        bldg("CS-51090", 29.7390, -95.3960, "retail", 1, None, None, 1988),
        bldg("CS-52070", 29.8110, -95.3421, "multifamily", 7, "mp_5207", 140, 2016),
        bldg("CS-52081", 29.8150, -95.3460, "hospitality", 9, "mp_5208", 180, 2004),
        bldg("CS-52099", 29.8080, -95.3390, "office", 4, None, None, 1992)],
    "photo_cues": {"setting": "apartment", "window_floor_est": [2, 4], "features": ["corner unit"]},
    "room_match": {
        "mp_5101": {"core": {"P": 0.71, "evidence": [ev("img_601", "mp_5101", 4, 45, 188)]}},
        "mp_5102": {"core": {"P": 0.18, "evidence": []}},
        "mp_5207": {"core": {"P": 0.66, "evidence": [ev("img_605", "mp_5207", 9, 180, 151)]}},
        "mp_5208": {"core": {"P": 0.09, "evidence": []}}},
    "geo": {
        "mp_5101": {"lat": 29.7415, "lon": -95.3917, "heading_deg": 48, "building_id": "CS-51010",
                    "floor_range": [2, 4], "error_estimate_m": 15, "evidence": []},
        "mp_5207": {"lat": 29.8113, "lon": -95.3418, "heading_deg": 301, "building_id": "CS-52070",
                    "floor_range": [2, 4], "error_estimate_m": 18, "evidence": []}},
    "window": {
        "mp_5101": {"W": 0.64, "floor_range": [2, 4],
                    "checks": {"road_front": True, "tree_line": True, "building_across": False}},
        "mp_5207": {"W": 0.61, "floor_range": [2, 4],
                    "checks": {"road_front": True, "parking_front": False, "building_across": True}}},
}

# ---- Ring C: vague city-wide clues, no window photos, no match until photo expansion ----
SCENARIOS["ring_c"] = {
    "scenario": "ring_c",
    "rings": {
        "rings": [{
            "ring_id": "R-C", "members": ["acct_701", "acct_702", "acct_713"],
            "confidence": 0.72, "key_kinds": ["text", "interaction", "time"],
            "links": [
                {"a": "acct_701", "b": "acct_702", "keys": ["text:tmpl_21", "interaction:repost_x7"],
                 "kinds": ["text", "interaction"], "strength": 0.8,
                 "reason": "reworded copy of the same script; 7 mutual reposts"},
                {"a": "acct_702", "b": "acct_713", "keys": ["text:tmpl_21", "time:batch_2026-09-03"],
                 "kinds": ["text", "time"], "strength": 0.68,
                 "reason": "same script; accounts created in the same batch"}],
            "recruiters": [], "place_keys": ["cell_29.76_-95.37"],
            "photos": photos(801, 5, 0, ["acct_701", "acct_702"]),
            "photo_expansion_used": False}],
        "weak_hints": [{"a": "acct_702", "b": "acct_744", "keys": ["photo:phash_77ab"], "kinds": ["photo"],
                        "strength": 0.4, "reason": "one shared room photo only; a hint, not a link"}]},
    "weak_photos": photos(850, 3, 0, ["acct_744"], "weak"),
    "zones": [{"zone_id": "Z-C1", "polygon": box(29.60, -95.60, 29.90, -95.20), "area_km2": 1290.0,
               "weight_share": 1.0, "confidence": 0.30, "wide": True,
               "reasons": ["ads only say 'Houston'", "most logins behind VPN", "no landmark named"]}],
    "buildings": [
        bldg("CS-60030", 29.7300, -95.4100, "multifamily", 4, "mp_6003", 48, 2009),
        bldg("CS-60041", 29.8200, -95.3000, "multifamily", 10, "mp_6004", 220, 2018),
        bldg("CS-60052", 29.6800, -95.5000, "hospitality", 6, "mp_6005", 110, 2001),
        bldg("CS-60110", 29.7700, -95.3600, "multifamily", 3, None, 24, 1984),
        bldg("CS-60120", 29.7000, -95.2800, "multifamily", 5, None, 60, 1996),
        bldg("CS-60130", 29.8500, -95.4500, "office", 15, None, None, 1979),
        bldg("CS-60140", 29.6500, -95.3300, "single_family", 2, None, 1, 1970)],
    "photo_cues": {"setting": "apartment", "window_floor_est": None, "features": []},
    "room_match": {
        "mp_6003": {"core": {"P": 0.31, "evidence": [ev("img_801", "mp_6003", 2, 0, 58)]},
                    "expanded": {"P": 0.62, "evidence": [ev("img_801", "mp_6003", 2, 0, 58),
                                                         ev("img_850", "mp_6003", 5, 90, 143),
                                                         ev("img_851", "mp_6003", 5, 225, 127)]}},
        "mp_6004": {"core": {"P": 0.12, "evidence": []}},
        "mp_6005": {"core": {"P": 0.08, "evidence": []}}},
    "geo": {"mp_6003": {"lat": 29.7304, "lon": -95.4096, "heading_deg": 95, "building_id": "CS-60030",
                        "floor_range": None, "error_estimate_m": 20, "evidence": []}},
    "window": {},
}

# ---- Weak ring: place + time only -> stop after the Zoner ----
SCENARIOS["weak_ring"] = {
    "scenario": "weak_ring",
    "rings": {
        "rings": [{
            "ring_id": "R-W", "members": ["acct_901", "acct_902"], "confidence": 0.35,
            "key_kinds": ["place", "time"],
            "links": [{"a": "acct_901", "b": "acct_902",
                       "keys": ["place:cell_29.72_-95.42", "time:lockstep_evenings"],
                       "kinds": ["place", "time"], "strength": 0.35,
                       "reason": "same 1 km cell and similar posting hours; both keys are common"}],
            "recruiters": [], "place_keys": ["cell_29.72_-95.42"],
            "photos": photos(951, 2, 0, ["acct_901"]), "photo_expansion_used": False}],
        "weak_hints": []},
    "weak_photos": [],
    "zones": [{"zone_id": "Z-W1", "polygon": box(29.715, -95.430, 29.728, -95.415), "area_km2": 2.1,
               "weight_share": 1.0, "confidence": 0.41, "wide": False,
               "reasons": ["6 ads name the same neighbourhood"]}],
    "buildings": [bldg("CS-70010", 29.7200, -95.4220, "multifamily", 4, "mp_7001", 40, 2003)],
    "photo_cues": {"setting": "apartment", "window_floor_est": None, "features": []},
    "room_match": {"mp_7001": {"core": {"P": 0.5, "evidence": []}}},
    "geo": {}, "window": {},
}

if __name__ == "__main__":
    for name, data in SCENARIOS.items():
        out = HERE / name / "scenario.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print("wrote", out)
