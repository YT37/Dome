"""Zoner: turns each ring's place clues into one or more search areas ("domes").

    python -m dome.agents.zoner case/<id> [--logins on] [--data data/synth]

Reads  case/<id>/rings.json, data/synth/posts.json (+ accounts.json when --logins on)
Writes case/<id>/zones.json, appends to case/<id>/log.jsonl

Method (deterministic, no network):
  1. Collect place clues from the ring members' posts. Each clue is a point, a precision and a weight.
  2. Lay a fixed 1 km grid over the city. Spread each clue's weight over the cells with a Gaussian
     whose sigma is the clue's precision_km.
  3. Keep the smallest set of cells holding 80% of the ring's weight.
  4. Each connected group of kept cells is a separate zone; its polygon is the union of its cells.
  5. weight_share = zone weight / ring weight;  confidence = weight_share / (1 + area_km2 / 10).
  6. wide = area > 25 km2, or most of the weight came from city-wide clues.

The Zoner gives areas only. It never outputs a point or an address.
"""

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from dome.agents._ishaan_models import RingZones
from dome.synth.common import load_gazetteer, load_json, save_json

# ---- tunable settings, all in one place -------------------------------------------------------

CLUE_WEIGHTS = {
    "area": 1.0,        # stated area, e.g. "Midtown"
    "landmark": 0.8,    # e.g. "McGowen station"
    "city": 0.1,        # city tag, e.g. "Houston"
    "area_code": 0.1,   # e.g. "713"
    "login": 0.6,       # only with --logins on
    "vpn_login": 0.0,   # VPN logins say nothing about location
}
CITY_WIDE_KINDS = {"city", "area_code"}
KEEP_SHARE = 0.80          # keep the smallest set of cells holding this share of the weight
MIN_ZONE_SHARE = 0.05      # drop specks holding less than this share
WIDE_AREA_KM2 = 25.0

CELL_KM = 1.0
GRID_CENTER = (29.7604, -95.3698)   # fixed grid origin (city centre)
GRID_HALF_KM = 60                   # grid covers +-60 km around the origin

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON = 111.320 * math.cos(math.radians(GRID_CENTER[0]))


# ---- coordinates ------------------------------------------------------------------------------

def to_km(lat, lon):
    return (lon - GRID_CENTER[1]) * KM_PER_DEG_LON, (lat - GRID_CENTER[0]) * KM_PER_DEG_LAT


def to_latlon(x, y):
    return GRID_CENTER[0] + y / KM_PER_DEG_LAT, GRID_CENTER[1] + x / KM_PER_DEG_LON


N_CELLS = int(2 * GRID_HALF_KM / CELL_KM)
_centres = (np.arange(N_CELLS) + 0.5) * CELL_KM - GRID_HALF_KM
CELL_X, CELL_Y = np.meshgrid(_centres, _centres)          # [row=y, col=x]


# ---- step 1: clues ----------------------------------------------------------------------------

def collect_clues(members, posts, gazetteer, accounts=None):
    """Return a list of clues: {kind, name, lat, lon, precision_km, weight}."""
    members = set(members)
    clues = []

    def add(kind, name, lat, lon, precision):
        clues.append({"kind": kind, "name": name, "lat": lat, "lon": lon,
                      "precision_km": precision, "weight": CLUE_WEIGHTS[kind]})

    for p in posts:
        if p["account_id"] not in members:
            continue
        names = ([p["stated_area"]] if p.get("stated_area") else []) + list(p.get("landmarks", []))
        for name in names:
            g = gazetteer.get(name)
            if g:   # stated areas may be a city or landmark too; the gazetteer kind decides the weight
                add(g["kind"], name, g["lat"], g["lon"], g["precision_km"])
        code = p.get("area_code")
        if code and code in gazetteer:
            g = gazetteer[code]
            add("area_code", code, g["lat"], g["lon"], g["precision_km"])

    if accounts is not None:
        for a in accounts:
            if a["account_id"] in members:
                for login in a.get("logins", []):
                    kind = "vpn_login" if login["vpn"] else "login"
                    add(kind, "login", login["lat"], login["lon"], login["precision_km"])

    return [c for c in clues if c["weight"] > 0]


# ---- steps 2-4: grid, keep 80%, connected zones -----------------------------------------------

def spread(clues):
    """Weight grid: each clue's weight spread with a Gaussian (sigma = precision_km)."""
    grid = np.zeros((N_CELLS, N_CELLS))
    for c in clues:
        x, y = to_km(c["lat"], c["lon"])
        sigma = max(c["precision_km"], CELL_KM / 4)
        g = np.exp(-((CELL_X - x) ** 2 + (CELL_Y - y) ** 2) / (2 * sigma ** 2))
        if g.sum() > 0:
            grid += c["weight"] * g / g.sum()
    return grid


def keep_cells(grid, share=KEEP_SHARE):
    """Boolean mask of the smallest set of cells holding `share` of the total weight."""
    flat = grid.ravel()
    order = np.argsort(-flat, kind="stable")
    cumulative = np.cumsum(flat[order])
    n_keep = int(np.searchsorted(cumulative, share * flat.sum()) + 1)
    mask = np.zeros(flat.shape, dtype=bool)
    mask[order[:n_keep]] = True
    return mask.reshape(grid.shape)


def connected_groups(mask):
    """Groups of kept cells that touch along an edge. Returns lists of (row, col)."""
    seen = np.zeros(mask.shape, dtype=bool)
    groups = []
    for start in zip(*np.nonzero(mask)):
        if seen[start]:
            continue
        stack, cells = [start], []
        seen[start] = True
        while stack:
            r, c = stack.pop()
            cells.append((r, c))
            for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= nr < N_CELLS and 0 <= nc < N_CELLS and mask[nr, nc] and not seen[nr, nc]:
                    seen[nr, nc] = True
                    stack.append((nr, nc))
        groups.append(sorted(cells))
    return groups


def cells_to_polygon(cells):
    """Union of cell squares, in km, as a shapely polygon."""
    squares = []
    for r, c in cells:
        x0 = c * CELL_KM - GRID_HALF_KM
        y0 = r * CELL_KM - GRID_HALF_KM
        squares.append(box(x0, y0, x0 + CELL_KM, y0 + CELL_KM))
    return unary_union(squares)


def polygon_latlon(poly_km):
    """Exterior ring as [[lat, lon], ...]."""
    if poly_km.geom_type == "MultiPolygon":
        poly_km = max(poly_km.geoms, key=lambda g: g.area)
    poly_km = poly_km.simplify(0)   # drop collinear points
    return [[round(lat, 5), round(lon, 5)] for lat, lon in
            (to_latlon(x, y) for x, y in poly_km.exterior.coords)]


def point_in_zone(zone, lat, lon):
    """True if (lat, lon) lies inside a zone dict's polygon (used by tests and the scorer)."""
    return Polygon([(lo, la) for la, lo in zone["polygon"]]).covers(Point(lon, lat))


# ---- steps 5-7: score and explain -------------------------------------------------------------

def zone_reasons(clues, poly_km, names_per_ad, logins_on):
    inside = Counter()
    for c in clues:
        if c["kind"] in ("area", "landmark") and poly_km.covers(Point(*to_km(c["lat"], c["lon"]))):
            inside[c["name"]] += 1
    reasons = []
    if inside:
        n_ads = sum(1 for names in names_per_ad if names & set(inside))
        reasons.append(f"{n_ads} ads name {join_names([n for n, _ in inside.most_common(3)])}")
    codes = Counter(c["name"] for c in clues if c["kind"] == "area_code")
    for code, n in codes.most_common(2):
        reasons.append(f"area code {code} fits ({n} ads, city-wide clue)")
    cities = Counter(c["name"] for c in clues if c["kind"] == "city")
    for city, n in cities.most_common(1):
        reasons.append(f"{n} ads only say '{city}' (city-wide clue)")
    if logins_on:
        logins = [c for c in clues if c["kind"] == "login"]
        n_in = sum(poly_km.covers(Point(*to_km(c["lat"], c["lon"]))) for c in logins)
        reasons.append(f"{n_in} of {len(logins)} non-VPN logins fall inside")
    else:
        reasons.append("login layer off")
    return reasons


def join_names(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def names_per_ad(members, posts):
    """For each ring ad that names a place: the set of place names it mentions."""
    members = set(members)
    out = []
    for p in posts:
        if p["account_id"] in members:
            names = set(([p["stated_area"]] if p.get("stated_area") else []) + list(p.get("landmarks", [])))
            if names:
                out.append(names)
    return out


def zones_for_ring(ring, posts, gazetteer, accounts=None):
    members = ring["members"]
    clues = collect_clues(members, posts, gazetteer, accounts)
    suffix = ring["ring_id"].split("-", 1)[-1]
    if not clues:
        return {"ring_id": ring["ring_id"], "zones": []}

    grid = spread(clues)
    total = grid.sum()
    city_wide = sum(c["weight"] for c in clues if c["kind"] in CITY_WIDE_KINDS)
    mostly_city_wide = city_wide > 0.5 * sum(c["weight"] for c in clues)
    ads = names_per_ad(members, posts)

    zones = []
    for cells in connected_groups(keep_cells(grid)):
        weight = sum(grid[r, c] for r, c in cells)
        share = weight / total
        if share < MIN_ZONE_SHARE:
            continue
        poly = cells_to_polygon(cells)
        area = len(cells) * CELL_KM ** 2
        wide = area > WIDE_AREA_KM2 or mostly_city_wide
        reasons = zone_reasons(clues, poly, ads, accounts is not None)
        if mostly_city_wide:
            reasons.insert(0, "most of the weight comes from city-wide clues (city tag, area code)")
        elif area > WIDE_AREA_KM2:
            reasons.insert(0, f"area is over {WIDE_AREA_KM2:.0f} km2")
        zones.append({"polygon": polygon_latlon(poly), "area_km2": round(area, 1),
                      "weight_share": round(share, 2),
                      "confidence": round(share / (1 + area / 10), 2),
                      "wide": wide, "reasons": reasons, "_weight": weight})

    zones.sort(key=lambda z: -z["_weight"])
    out = []
    for i, z in enumerate(zones, start=1):
        z.pop("_weight")
        out.append({"zone_id": f"Z-{suffix}{i}", **z})
    return {"ring_id": ring["ring_id"], "zones": out}


# ---- I/O --------------------------------------------------------------------------------------

def read_rings(case_dir):
    data = load_json(Path(case_dir) / "rings.json")
    if isinstance(data, dict):
        data = data.get("rings", [data])
    return data


def run(case_dir, data_dir="data/synth", logins=False):
    case_dir = Path(case_dir)
    rings = read_rings(case_dir)
    posts = load_json(Path(data_dir) / "posts.json")
    accounts = load_json(Path(data_dir) / "accounts.json") if logins else None
    gazetteer = load_gazetteer()

    result = [RingZones(**zones_for_ring(r, posts, gazetteer, accounts)).model_dump() for r in rings]
    save_json(case_dir / "zones.json", result)
    log(case_dir, {"agent": "zoner", "event": "wrote zones.json", "logins": "on" if logins else "off",
                   "rings": len(result), "zones": sum(len(r["zones"]) for r in result)})
    return result


def log(case_dir, entry):
    entry = {"time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
    with open(Path(case_dir) / "log.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def score_against_answer_key(result, rings, answer_key_path):
    """SCORING ONLY, never part of the pipeline: is each ring's true building inside a zone?

    Rings are matched to answer-key rings by member overlap. Returns (hits, n_rings, median_area).
    """
    from dome.synth.common import load_buildings
    key = load_json(answer_key_path)
    coords = {b["label"]: (b["lat"], b["lon"]) for b in load_buildings()}
    members_of = {r["ring_id"]: set(r["members"]) for r in rings}
    hits, areas = 0, []
    for ring in result:
        areas += [z["area_km2"] for z in ring["zones"]]
        labels = [k for k in key if k not in ("hard_negatives", "decoy_buildings")]
        best = max(labels, key=lambda k: len(members_of[ring["ring_id"]] & set(key[k]["members"])))
        true = [coords[b["label"]] for b in key[best]["buildings"]]
        if all(any(point_in_zone(z, *ll) for z in ring["zones"]) for ll in true):
            hits += 1
    return hits, len(result), float(np.median(areas)) if areas else 0.0


def main():
    ap = argparse.ArgumentParser(description="Zoner: place clues -> search zones.")
    ap.add_argument("case_dir")
    ap.add_argument("--data", default="data/synth")
    ap.add_argument("--logins", choices=["on", "off"], default="off")
    ap.add_argument("--answer-key", help="scoring only: print how many true buildings fall inside")
    args = ap.parse_args()
    result = run(args.case_dir, args.data, args.logins == "on")
    for ring in result:
        print(ring["ring_id"])
        for z in ring["zones"]:
            print(f"  {z['zone_id']}: {z['area_km2']} km2, share {z['weight_share']}, "
                  f"confidence {z['confidence']}, wide {z['wide']}")
            for reason in z["reasons"]:
                print(f"    - {reason}")
    print(f"wrote {Path(args.case_dir) / 'zones.json'}")
    if args.answer_key:
        hits, n, median = score_against_answer_key(result, read_rings(args.case_dir), args.answer_key)
        print(f"true building inside the dome: {hits} of {n} rings; median zone area {median:.1f} km2")


if __name__ == "__main__":
    main()
