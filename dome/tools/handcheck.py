"""Hand-check kit for the window fingerprint.

    python -m dome.tools.handcheck --list             shortlist of scans worth hand-checking
    python -m dome.tools.handcheck --form <scan_id>   build the kit and open the click-through form
    python -m dome.tools.handcheck <scan_id>          build the kit only (handcheck/<scan_id>/index.html)
    python -m dome.tools.handcheck --verify <scan_id> compare geo.fix_scan_location with the answer key

The form saves handcheck/answer_keys/answer_key_<scan_id>.json when served by --form
(opened as a plain file, its Save button downloads the JSON instead).

Every API call goes through the data_tools caches, so re-running costs nothing. No keys
or signed URLs are written to any generated file. Images are at most 1600 px wide.

Conventions:
- Sweeps S01, S02, ... in the order the Matterport API lists them.
- Inside windows IW1, IW2, ...: one ID per physical window, merged across every sweep
  that sees it (see data_tools/inside_windows.py).
- Obliques: the letter is where the CAMERA looks. E1 = camera looking east (so the west
  facade), first tile along that facade.
- Model headings are clockwise from the model's +Y axis (see matterport.py).
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("DOME_STUBS", "0")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from dome.data_tools import costar, geo  # noqa: E402
from dome.data_tools import matterport as mp  # noqa: E402
from dome.data_tools import vexcel as vx  # noqa: E402
from dome.data_tools import floorplan as fpm  # noqa: E402
from dome.data_tools._common import REPO_ROOT  # noqa: E402
from dome.data_tools.inside_windows import unique_windows  # noqa: E402
from dome.data_tools.windows import detect_windows  # noqa: E402

OUT = REPO_ROOT / "handcheck"
KEYS_DIR = OUT / "answer_keys"
MAXW = 1600
FACE_NAMES = {1: "front", 2: "right", 3: "back", 4: "left"}
FACE_COLORS = {1: (255, 80, 80), 2: (80, 200, 80), 3: (80, 140, 255), 4: (255, 200, 0)}
DIR_LETTER = {"oblique-north": "N", "oblique-east": "E", "oblique-south": "S", "oblique-west": "W"}
CAMERA_LOOKS = {"oblique-north": "north", "oblique-east": "east", "oblique-south": "south", "oblique-west": "west"}
FACADE_SEEN = {"oblique-north": "south", "oblique-east": "west", "oblique-south": "north", "oblique-west": "east"}
ADDR_RE = re.compile(r"\b\d{2,6}\s+[\w .'-]*\b(st|street|ave|avenue|rd|road|blvd|dr|drive|ln|lane|way|pkwy|ct|pl|place|hwy)\b\.?", re.I)


def _safe_name(name: str) -> str:
    """Model names sometimes carry the street address: never write that into shared files."""
    return ADDR_RE.sub("(address hidden)", str(name or "")).replace("|", "/")


UNIT_RE = re.compile(r"(\d\s*(br|bd|bed)|studio|\bunit\b|\bapt\b|apartment|\d+\s*s\.?f\b|\d\s*x\s*\d|penthouse|\bmodel\b|loft|townho)", re.I)
AMENITY_RE = re.compile(r"(lobby|fitness|gym|pool|lounge|club|leasing|amenit|courtyard|roof|garage|mail|business|dog|pet|spa|game|theater|cinema|co-?work|parking|office|conference|kitchen\b.*demo)", re.I)


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _save(im: Image.Image, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = im.convert("RGB")
    if im.width > MAXW:
        im = im.resize((MAXW, round(im.height * MAXW / im.width)), Image.LANCZOS)
    im.save(path, quality=85)
    return str(path)


def _label(d: ImageDraw.ImageDraw, xy, text, size=18, fg=(255, 255, 255), bg=(0, 0, 0)):
    f = _font(size)
    x, y = xy
    bb = d.textbbox((x, y), text, font=f)
    d.rectangle([bb[0] - 2, bb[1] - 2, bb[2] + 2, bb[3] + 2], fill=bg)
    d.text((x, y), text, fill=fg, font=f)


# --- shared facts about a scan ---------------------------------------------------

def rough_location(scan_id: str) -> dict:
    """geocoordinates, else the CoStar record. (No street-address geocoder is used.)"""
    g = mp.geocoordinates(scan_id)
    prop = costar.property_for_scan(scan_id)
    if g and g.get("latitude") and g.get("longitude"):
        return {"lat": g["latitude"], "lon": g["longitude"], "source": "Matterport geocoordinates",
                "geocoordinates": g, "property": prop}
    if prop:
        return {"lat": prop["lat"], "lon": prop["lon"], "source": "CoStar record lat/lon",
                "geocoordinates": None, "property": prop}
    return {"lat": None, "lon": None, "source": "none", "geocoordinates": None, "property": None}


def _sweeps(scan_id: str) -> list[dict]:
    """Sweeps in API order with S-numbers, positions, rotation and floor id."""
    out = []
    for i, loc in enumerate(mp._panos(scan_id)):
        pano = next((p for p in loc.get("panos") or []), None)
        out.append({"label": f"S{i + 1:02d}", "sweep_id": loc["id"], "position": loc.get("position"),
                    "rotation": (pano or {}).get("rotation"),
                    "floor_id": (loc.get("floor") or {}).get("id"),
                    "has_faces": bool(pano and len(((pano.get("skybox") or {}).get("children")) or []) >= 6)})
    return out


# --- 1. shortlist -------------------------------------------------------------------

def _candidate_properties(limit: int) -> list[dict]:
    import sqlite3
    con = sqlite3.connect(costar.build_index())
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT p.*, COUNT(s.scan_id) AS n_scans FROM properties p JOIN scans s USING (property_id)
        WHERE p.type IN ('multifamily', 'residential_condo', 'residential_multifamily')
        GROUP BY p.property_id""").fetchall()
    con.close()

    def pref(r):
        f = r["floors"] or 0
        band = 0 if 4 <= f <= 12 else 1 if 3 <= f <= 20 else 2
        return (band, r["type"] != "multifamily", -min(r["n_scans"], 20), r["property_id"])
    return [dict(r) for r in sorted(rows, key=pref)[:limit]]


def _unit_scan(prop: dict, max_scans: int = 8) -> dict | None:
    """First scan of a property whose name looks like an apartment unit."""
    for sid in costar.scans_for_property(prop["property_id"])[:max_scans]:
        try:
            name = mp.model_details(sid).get("name") or ""
        except mp.MatterportError:
            continue
        if UNIT_RE.search(name) and not AMENITY_RE.search(name):
            return {"scan_id": sid, "name": name}
    return None


def _deep_check(scan_id: str, name: str, prop: dict) -> dict:
    row = {"scan_id": scan_id, "name": name, "property_id": prop["property_id"],
           "address": prop["address"], "type": prop["type"], "floors": prop["floors"],
           "units": prop["units"], "error": None}
    try:
        det = mp.model_details(scan_id)
        row["publication_address"] = (det.get("publication") or {}).get("address")
        row["has_floorplan"] = bool(mp.floorplans(scan_id))
        sw = _sweeps(scan_id)
        row["sweeps"] = len(sw)
        row["has_cube_faces"] = any(s["has_faces"] for s in sw)
        loc = rough_location(scan_id)
        row["geocoordinates"] = loc["geocoordinates"] is not None
        row["loc_source"] = loc["source"]
        lat, lon = loc["lat"], loc["lon"]
        b = vx.building_details(lat, lon, 40)
        row["footprint"] = any(x["distance_m"] <= 15 for x in b)
        row["oblique_dirs"] = [DIR_LETTER[d] for d in vx.oblique_directions(vx.square_wkt(lat, lon, 30))]
        # rough inside window count: simple detector on side faces of up to 6 sweeps
        faces = [s for s in sw if s["has_faces"]]
        step = max(1, len(faces) // 6)
        pick = {s["sweep_id"] for s in faces[::step][:6]}
        n = 0
        for f in mp.face_paths(scan_id):
            if f["sweep_id"] in pick:
                n += len(detect_windows(f["path"]))
        row["inside_windows"] = n
    except Exception as e:  # keep the list going; show the problem in the table
        row["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return row


def shortlist(pool: int = 60, deep: int = 25, top: int = 10) -> Path:
    props = _candidate_properties(pool)
    print(f"checking names of scans on {len(props)} apartment/condo properties ...")
    with ThreadPoolExecutor(8) as ex:
        units = list(ex.map(_unit_scan, props))
    cands = [(p, u) for p, u in zip(props, units) if u][:deep]
    print(f"deep-checking {len(cands)} unit scans (floor plan, sweeps, Vexcel, inside windows) ...")
    rows = []
    for i, (p, u) in enumerate(cands, 1):
        print(f"  [{i}/{len(cands)}] {u['scan_id']} {u['name']}")
        rows.append(_deep_check(u["scan_id"], u["name"], p))

    def rank(r):
        complete = sum(bool(r.get(k)) for k in ("has_floorplan", "has_cube_faces", "oblique_dirs", "footprint"))
        return (r["error"] is None, r["type"] == "multifamily", complete, r.get("inside_windows") or 0,
                r.get("sweeps") or 0)
    rows.sort(key=rank, reverse=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "shortlist.json").write_text(json.dumps(rows, indent=1))

    yn = lambda v: "yes" if v else "no"  # noqa: E731
    cell = lambda v: str(v).replace("|", "/")  # noqa: E731

    def addr(r):
        pub = r.get("publication_address") or ""
        looks_like_address = bool(re.search(r"\d+\s+\w+.*\b(st|street|ave|avenue|rd|road|blvd|dr|drive|ln|way|pkwy|ct|pl|hwy)\b", pub, re.I))
        return pub if looks_like_address else r["address"]
    lines = ["# Hand-check shortlist", "",
             f"Best {top} of {len(rows)} deep-checked unit scans (from {len(props)} CoStar apartment/condo "
             "properties, mid-rise first). Ranked: multifamily, then floor plan + cube faces + oblique + "
             "footprint all present, then most inside windows (simple detector, 6 sweeps max).", "",
             "Location used = Matterport geocoordinates, else the CoStar record.", "",
             "| # | scan_id | name | CoStar property | CoStar type | floors | units | floor plan | cube faces | sweeps | inside windows | obliques | footprint | geocoords |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows[:top], 1):
        if r["error"]:
            lines.append(f"| {i} | `{r['scan_id']}` | {cell(r['name'])} | {r['property_id']} | {r['type']} | {r['floors']} | {r['units']} | error: {r['error']} |||||||")
            continue
        lines.append(f"| {i} | `{r['scan_id']}` | {_safe_name(r['name'])} | {r['property_id']} | "
                     f"{r['type']} | {r['floors']} | {r['units']} | {yn(r['has_floorplan'])} | {yn(r['has_cube_faces'])} | "
                     f"{r['sweeps']} | {r['inside_windows']} | {''.join(r['oblique_dirs']) or 'none'} | "
                     f"{yn(r['footprint'])} | {yn(r['geocoordinates'])} |")
    lines += ["", "Next: `python -m dome.tools.handcheck <scan_id>` on the top pick."]
    path = OUT / "shortlist.md"
    path.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return path


def _footprint_area(lat: float, lon: float) -> float | None:
    from shapely import wkt as swkt
    b = [x for x in vx.building_details(lat, lon, 40) if x["distance_m"] <= 15]
    if not b:
        return None
    g = swkt.loads(b[0]["outline"])
    m = 111_320.0 * math.cos(math.radians(lat))
    return round(g.area * m * 111_320.0, 0)


def shortlist_small(deep: int = 25, top: int = 10) -> Path:
    """Small buildings for Ring A: 3-5 story apartments whose scan CoStar ties to one unit
    (exact floor), fewest units first. Ranked: complete data, small footprint (proxy for no
    courtyards), real inside windows."""
    import sqlite3
    us = costar.unit_scans()
    con = sqlite3.connect(costar.build_index())
    con.row_factory = sqlite3.Row
    props = {r["property_id"]: dict(r) for r in con.execute("SELECT * FROM properties")}
    con.close()
    per_prop: dict[str, tuple] = {}
    for sid, u in sorted(us.items()):
        p = props.get(u["property_id"])
        if not (p and p["type"] == "multifamily" and p["floors"] and 3 <= p["floors"] <= 5):
            continue
        fl = costar._floor_from_unit(u["unit"], u["floor_text"], p["floors"])
        if fl and u["property_id"] not in per_prop:
            per_prop[u["property_id"]] = (sid, u["unit"], fl)
    cands = sorted(per_prop.items(), key=lambda kv: (props[kv[0]]["units"] or 999, kv[0]))[:deep]
    print(f"{len(per_prop)} small buildings with unit-level scans; deep-checking {len(cands)} ...")
    rows = []
    for i, (pid, (sid, unit, fl)) in enumerate(cands, 1):
        p = props[pid]
        try:
            name = mp.model_details(sid).get("name") or ""
        except mp.MatterportError:
            name = "?"
        print(f"  [{i}/{len(cands)}] {sid} {pid} unit {unit} floor {fl}")
        r = _deep_check(sid, name, {**p, "type": p["type"]})
        r.update(unit=unit, unit_floor=fl)
        if r["error"] is None:
            loc = rough_location(sid)
            try:
                r["footprint_m2"] = _footprint_area(loc["lat"], loc["lon"])
            except Exception:
                r["footprint_m2"] = None
        rows.append(r)

    def rank(r):
        complete = sum(bool(r.get(k)) for k in ("has_floorplan", "has_cube_faces", "oblique_dirs", "footprint"))
        area = r.get("footprint_m2") or 99999
        return (r["error"] is None, complete, area <= 3000, r.get("inside_windows") or 0, -area)
    rows.sort(key=rank, reverse=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "shortlist_small.json").write_text(json.dumps(rows, indent=1, default=str))
    yn = lambda v: "yes" if v else "no"  # noqa: E731
    lines = ["# Small-building shortlist (Ring A candidates)", "",
             f"Best {top} of {len(rows)} deep-checked: 3-5 story apartments whose scan CoStar ties to one unit, "
             "so the floor is known exactly. Ranked: complete data, footprint <= 3000 m2 (no courtyards), "
             "most inside windows.", "",
             "| # | scan_id | name | CoStar property | floors | units | unit | unit floor | footprint m2 | floor plan | cube faces | sweeps | inside windows | obliques | geocoords |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows[:top], 1):
        if r["error"]:
            lines.append(f"| {i} | `{r['scan_id']}` | error: {r['error']} |||||||||||||")
            continue
        lines.append(f"| {i} | `{r['scan_id']}` | {_safe_name(r['name'])} | {r['property_id']} | {r['floors']} | "
                     f"{r['units']} | {r['unit']} | {r['unit_floor']} | {r.get('footprint_m2')} | {yn(r['has_floorplan'])} | "
                     f"{yn(r['has_cube_faces'])} | {r['sweeps']} | {r['inside_windows']} | {''.join(r['oblique_dirs']) or 'none'} | "
                     f"{yn(r['geocoordinates'])} |")
    path = OUT / "shortlist_small.md"
    path.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return path


MIDTOWN_HOUSTON = (29.7445, -95.3800)   # centre of Ishaan's gazetteer (Midtown, Montrose, EaDo)


def shortlist_near(lat: float = MIDTOWN_HOUSTON[0], lon: float = MIDTOWN_HOUSTON[1], km: float = 4.0,
                   deep: int = 24, top: int = 10) -> Path:
    """Ring A candidates near a point (default: Ishaan's Houston gazetteer): small apartment
    buildings (3-5 floors, <= 120 units) and condo listings, one unit-like scan each.
    Floors from CoStar unit numbers when known."""
    import sqlite3
    con = sqlite3.connect(costar.build_index())
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM properties")]
    con.close()
    m = 111.32 * math.cos(math.radians(lat))
    dist = lambda r: math.hypot((r["lat"] - lat) * 111.32, (r["lon"] - lon) * m)  # noqa: E731
    mf = [r for r in rows if r["type"] == "multifamily" and r["floors"] and 3 <= r["floors"] <= 5
          and (r["units"] or 0) <= 120 and dist(r) <= km]
    condo = [r for r in rows if r["type"] == "residential_condo" and dist(r) <= km]
    pool = sorted(mf, key=dist)[: deep * 2 // 3] + sorted(condo, key=dist)[: deep // 3]
    us = costar.unit_scans()
    out = []
    print(f"{len(mf)} small apartment buildings and {len(condo)} condo listings within {km} km; deep-checking {len(pool)} ...")
    for i, p in enumerate(pool, 1):
        scans = costar.scans_for_property(p["property_id"])
        unit_level = [s for s in scans if s in us]
        pick = None
        if unit_level:
            pick = {"scan_id": unit_level[0], "name": mp.model_details(unit_level[0]).get("name") or ""}
        elif p["property_id"].startswith("RL-"):
            pick = {"scan_id": scans[0], "name": mp.model_details(scans[0]).get("name") or ""}
        else:
            pick = _unit_scan(p) or {"scan_id": scans[0], "name": mp.model_details(scans[0]).get("name") or ""}
        sid = pick["scan_id"]
        print(f"  [{i}/{len(pool)}] {sid} {p['property_id']} {p.get('name') or ''}")
        r = _deep_check(sid, pick["name"], p)
        r["km"] = round(dist(p), 2)
        r["building_name"] = p.get("name")
        if p["property_id"].startswith("RL-"):
            unit = (p["address"] or "").split("Unit")[-1].strip(" ,") if "Unit" in (p["address"] or "") else None
            r["unit"], r["unit_floors"] = unit, [f for f in [costar._floor_from_unit(unit, None, p["floors"])] if f]
        else:
            uf = costar.unit_floors_for_scan(sid)
            r["unit"] = ",".join(str(u[0]) for u in uf["units"][:3]) if uf["units"] else None
            r["unit_floors"] = uf["floors"]
        if r["error"] is None:
            try:
                loc = rough_location(sid)
                r["footprint_m2"] = _footprint_area(loc["lat"], loc["lon"])
            except Exception:
                r["footprint_m2"] = None
        out.append(r)

    def rank(r):
        complete = sum(bool(r.get(k)) for k in ("has_floorplan", "has_cube_faces", "oblique_dirs", "footprint"))
        area = r.get("footprint_m2") or 99999
        return (r["error"] is None, complete, bool(r.get("unit_floors")), area <= 3000,
                min(r.get("sweeps") or 0, 20), r.get("inside_windows") or 0)
    out.sort(key=rank, reverse=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "shortlist_near.json").write_text(json.dumps(out, indent=1, default=str))
    yn = lambda v: "yes" if v else "no"  # noqa: E731
    lines = ["# Ring A shortlist near Ishaan's Houston gazetteer", "",
             f"Best {top} of {len(out)}: apartment buildings with 3-5 floors and <= 120 units, plus condo listings, "
             f"within {km} km of Midtown. Ranked: complete data, floor known from CoStar unit numbers, footprint "
             "<= 3000 m2, sweeps (renders need spare sweeps), inside windows.", "",
             "| # | scan_id | building | name | CoStar property | km | floors | units | unit floors | footprint m2 | floor plan | sweeps | inside windows | obliques | geocoords |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(out[:top], 1):
        if r["error"]:
            lines.append(f"| {i} | `{r['scan_id']}` | error: {r['error']} |||||||||||||")
            continue
        lines.append(f"| {i} | `{r['scan_id']}` | {_safe_name(r.get('building_name'))} | {_safe_name(r['name'])} | {r['property_id']} | "
                     f"{r['km']} | {r['floors']} | {r['units']} | {r.get('unit_floors') or '?'} | {r.get('footprint_m2')} | "
                     f"{yn(r['has_floorplan'])} | {r['sweeps']} | {r['inside_windows']} | {''.join(r['oblique_dirs']) or 'none'} | "
                     f"{yn(r['geocoordinates'])} |")
    path = OUT / "shortlist_near.md"
    path.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return path


def find_decoy(scan_a: str, max_m: float = 1000, top: int = 5) -> list[dict]:
    """Decoy D for Ring A: another scanned apartment building within max_m of A's CoStar
    point. Prefers scans tied to one unit (floor known), then complete data, then 200 m+
    away (so the zone holds both but they are clearly different buildings)."""
    import sqlite3
    pa = costar.property_for_scan(scan_a)
    if not pa:
        raise SystemExit(f"{scan_a} has no CoStar record")
    us = costar.unit_scans()
    con = sqlite3.connect(costar.build_index())
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT p.*, MIN(s.scan_id) AS first_scan FROM properties p JOIN scans s USING (property_id) "
        "WHERE p.type IN ('multifamily','residential_condo','residential_multifamily') "
        "AND p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ? GROUP BY p.property_id",
        (pa["lat"] - 0.01, pa["lat"] + 0.01, pa["lon"] - 0.011, pa["lon"] + 0.011))]
    con.close()
    m = 111_320.0 * math.cos(math.radians(pa["lat"]))
    out = []
    for r in rows:
        if r["property_id"] == pa["property_id"]:
            continue
        d = math.hypot((r["lat"] - pa["lat"]) * 111_320.0, (r["lon"] - pa["lon"]) * m)
        if d > max_m:
            continue
        unit_scan = next(((sid, u) for sid, u in sorted(us.items()) if u["property_id"] == r["property_id"]), None)
        sid = unit_scan[0] if unit_scan else costar.scans_for_property(r["property_id"])[0]
        out.append({"property_id": r["property_id"], "scan_id": sid, "distance_m": round(d),
                    "floors": r["floors"], "units": r["units"], "lat": r["lat"], "lon": r["lon"],
                    "unit": unit_scan[1]["unit"] if unit_scan else None,
                    "unit_floor": costar._floor_from_unit(unit_scan[1]["unit"], unit_scan[1]["floor_text"], r["floors"]) if unit_scan else None})
    out.sort(key=lambda r: (r["unit"] is None, not (200 <= r["distance_m"] <= max_m), r["distance_m"]))
    checked = []
    for r in out[:top * 3]:
        try:
            r["has_floorplan"] = bool(mp.floorplans(r["scan_id"]))
            sw = _sweeps(r["scan_id"])
            r["sweeps"] = len(sw)
            r["has_cube_faces"] = any(x["has_faces"] for x in sw)
            r["name"] = mp.model_details(r["scan_id"]).get("name")
        except Exception as e:
            r["error"] = str(e)[:80]
            continue
        if r["has_floorplan"] and r["has_cube_faces"]:
            checked.append(r)
        if len(checked) >= top:
            break
    for r in checked:
        print(r)
    return checked


# --- 2. kit + form for one scan -----------------------------------------------------------

def _target_building(lat: float, lon: float) -> tuple[dict | None, list[dict]]:
    near = vx.building_details(lat, lon, 80)
    inside = [b for b in near if b["distance_m"] == 0]
    return (inside or near or [None])[0], near


def _extent_m(wkt: str, lat: float) -> tuple[float, float, float, float]:
    """(centre_lat, centre_lon, width_m, height_m) of a WKT footprint."""
    from shapely import wkt as swkt
    g = swkt.loads(wkt)
    x0, y0, x1, y1 = g.bounds
    my, mx = 111_320.0, 111_320.0 * math.cos(math.radians(lat))
    return (y0 + y1) / 2, (x0 + x1) / 2, (x1 - x0) * mx, (y1 - y0) * my


def _floorplan_images(scan_id: str, sweeps: list[dict], inside: list[dict], kdir: Path) -> list[dict]:
    """Floor plan per floor with sweeps (small grey dots) and unique windows (IW labels)."""
    out = []
    for fid, plan in fpm.load(scan_id).items():
        im = Image.open(plan.image_path).convert("RGB")
        d = ImageDraw.Draw(im)
        R = plan.R
        for s in sweeps:
            if s["floor_id"] != fid or not s["position"]:
                continue
            px, py = plan.to_px(s["position"]["x"], s["position"]["y"])
            r = max(5, R / 14)
            d.ellipse([px - r, py - r, px + r, py + r], fill=(200, 200, 200), outline=(0, 0, 0), width=2)
        for w in inside:
            if w["floor_id"] != fid or w["x"] is None:
                continue
            px, py = plan.to_px(w["x"], w["y"])
            h = math.radians(w["normal_deg"] or 0)
            L = 0.6 * R
            d.line([px, py, px + L * math.sin(h), py - L * math.cos(h)], fill=(255, 60, 60), width=max(3, int(R / 20)))
            r = max(7, R / 9)
            d.ellipse([px - r, py - r, px + r, py + r], fill=(255, 60, 60), outline=(255, 255, 255), width=3)
            _label(d, (px + r + 2, py - r), w["id"], size=max(16, int(R / 3.5)), bg=(170, 0, 0))
        seq = (plan.meta.get("floor") or {}).get("sequence", 0)
        name = f"floorplan_{seq}.jpg"
        _save(im, kdir / "img" / name)
        out.append({"floor": (plan.meta.get("floor") or {}).get("label"), "image": f"img/{name}"})
    return out


def _inside_cards(inside: list[dict], kdir: Path) -> list[dict]:
    """One crop per unique window (its best view, box drawn)."""
    cards = []
    for w in inside:
        v = w["best_view"]
        b = v["box"]
        im = Image.open(v["path"]).convert("RGB")
        pad = int(max(b["w"], b["h"]) * 0.35)
        x0, y0 = max(0, b["x"] - pad), max(0, b["y"] - pad)
        x1, y1 = min(im.width, b["x"] + b["w"] + pad), min(im.height, b["y"] + b["h"] + pad)
        crop = im.crop((x0, y0, x1, y1))
        ImageDraw.Draw(crop).rectangle([b["x"] - x0, b["y"] - y0, b["x"] - x0 + b["w"], b["y"] - y0 + b["h"]],
                                       outline=(255, 40, 40), width=6)
        crop.thumbnail((420, 420))
        name = f"iw_{w['id']}.jpg"
        crop.save(kdir / "img" / name, quality=85)
        cards.append({"id": w["id"], "img": f"img/{name}", "views": len(w["views"]),
                      "normal_deg": w["normal_deg"], "width_m": w["width_m"],
                      "x": None if w["x"] is None else round(w["x"], 3),
                      "y": None if w["y"] is None else round(w["y"], 3), "floor_id": w["floor_id"]})
    return cards


def _raw_faces(scan_id: str, sweeps: list[dict], kdir: Path) -> list[str]:
    """Plain rows of the four side faces per sweep (no boxes), for looking around."""
    faces = {(f["sweep_id"], f["face"]): f for f in mp.face_paths(scan_id)}
    rows, tile = [], 300
    for s in sweeps:
        row = Image.new("RGB", (tile * 4, tile + 22), "white")
        dr = ImageDraw.Draw(row)
        got = False
        for k in (1, 2, 3, 4):
            f = faces.get((s["sweep_id"], k))
            if not f:
                continue
            got = True
            row.paste(Image.open(f["path"]).convert("RGB").resize((tile, tile)), ((k - 1) * tile, 22))
            dr.text(((k - 1) * tile + 4, 3), f"{s['label']} {FACE_NAMES[k]}", fill=(0, 0, 0), font=_font(15))
        if got:
            name = f"faces_{s['label']}.jpg"
            _save(row, kdir / "img" / name)
            rows.append(f"img/{name}")
    return rows


def _aerial(lat: float, lon: float, target: dict | None, near: list[dict], kdir: Path) -> str | None:
    if target is None:
        return None
    clat, clon, wm, hm = _extent_m(target["outline"], lat)
    half = max(wm, hm) / 2 + 30
    try:
        path, (x0, y0, x1, y1) = vx.ortho_square(clat, clon, half)
    except vx.VexcelError:
        return None
    from shapely import wkt as swkt
    im = Image.open(path).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    to_px = lambda x, y: ((x - x0) / (x1 - x0) * W, (y1 - y) / (y1 - y0) * H)  # noqa: E731
    lw = max(2, W // 400)
    for b in sorted(near, key=lambda b: b["building_id"] == target["building_id"]):
        g = swkt.loads(b["outline"])
        is_t = b["building_id"] == target["building_id"]
        for p in (list(g.geoms) if hasattr(g, "geoms") else [g]):
            d.line([to_px(x, y) for x, y in p.exterior.coords], fill=(255, 210, 0) if is_t else (0, 230, 255),
                   width=lw * (2 if is_t else 1))
        c = g.representative_point()
        cx, cy = to_px(c.x, c.y)
        if 0 <= cx <= W and 0 <= cy <= H:
            _label(d, (cx, cy), b["building_id"], size=max(14, W // 70), bg=(120, 90, 0) if is_t else (0, 70, 90))
    px, py = to_px(lon, lat)
    r = max(8, W // 120)
    d.ellipse([px - r, py - r, px + r, py + r], fill=(255, 0, 0), outline=(255, 255, 255), width=3)
    _label(d, (px + r + 3, py - r), "rough location", size=max(14, W // 70), bg=(160, 0, 0))
    ax, ay, L = W - 60, 90, 60
    d.line([ax, ay, ax, ay - L], fill=(255, 255, 255), width=6)
    d.polygon([(ax, ay - L - 18), (ax - 12, ay - L + 4), (ax + 12, ay - L + 4)], fill=(255, 255, 255))
    _label(d, (ax - 8, ay + 4), "N", size=24)
    _save(im, kdir / "img" / "aerial.jpg")
    return "img/aerial.jpg"


def _rows(boxes: list[dict]) -> list[list[dict]]:
    """Group boxes into rows (row 0 = lowest in the picture) by linking horizontal
    neighbours at the same height, then merging groups at the same height."""
    if not boxes:
        return []
    n = len(boxes)
    cy = [b["y"] + b["h"] / 2 for b in boxes]
    cx = [b["x"] + b["w"] / 2 for b in boxes]
    mh, mw = sorted(b["h"] for b in boxes)[n // 2], sorted(b["w"] for b in boxes)[n // 2]
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    order = sorted(range(n), key=lambda i: cx[i])
    for a_i, i in enumerate(order):
        for j in order[a_i + 1:]:
            if cx[j] - cx[i] > 4 * mw:
                break
            if abs(cy[i] - cy[j]) < 0.4 * mh:
                parent[find(i)] = find(j)
    groups: dict[int, list[dict]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(boxes[i])
    rows = list(groups.values())
    mean = lambda r: sum(b["y"] + b["h"] / 2 for b in r) / len(r)  # noqa: E731
    changed = True
    while changed:
        changed = False
        rows.sort(key=mean)
        for k in range(len(rows) - 1):
            if mean(rows[k + 1]) - mean(rows[k]) < 0.4 * mh:
                rows[k] += rows.pop(k + 1)
                changed = True
                break
    rows.sort(key=lambda r: -mean(r))
    return [sorted(r, key=lambda b: b["x"]) for r in rows]


def _facade_tiles(target: dict | None, lat: float, lon: float, dname: str) -> list[tuple[float, float, float]]:
    """(lat, lon, half_m) squares covering the facade a camera direction sees (camera
    looking north sees the south facade); long facades split so detection succeeds."""
    if target is None:
        return [(lat, lon, 30.0)]
    from shapely import wkt as swkt
    x0, y0, x1, y1 = swkt.loads(target["outline"]).bounds
    my, mx = 111_320.0, 111_320.0 * math.cos(math.radians(lat))
    if dname in ("oblique-north", "oblique-south"):
        edge_lat = y0 if dname == "oblique-north" else y1
        length = (x1 - x0) * mx
        n = max(1, math.ceil(length / 80))
        half = min(50.0, length / (2 * n) + 15)
        return [(edge_lat, x0 + (i + 0.5) * (x1 - x0) / n, half) for i in range(n)]
    edge_lon = x0 if dname == "oblique-east" else x1
    length = (y1 - y0) * my
    n = max(1, math.ceil(length / 80))
    half = min(50.0, length / (2 * n) + 15)
    return [(y0 + (i + 0.5) * (y1 - y0) / n, edge_lon, half) for i in range(n)]


def _obliques(target: dict | None, lat: float, lon: float, kdir: Path) -> list[dict]:
    """Clean oblique tiles + detected window boxes (scaled to the saved image) for the form."""
    probe = vx.square_wkt(lat, lon, 40) if target is None else target["outline"]
    dirs = vx.oblique_directions(probe)
    out = []
    for dname in ("oblique-north", "oblique-east", "oblique-south", "oblique-west"):
        if dname not in dirs:
            continue
        tiles = _facade_tiles(target, lat, lon, dname)
        for ti, (tlat, tlon, half) in enumerate(tiles, 1):
            name = DIR_LETTER[dname] + str(ti)
            area = vx.square_wkt(tlat, tlon, half)
            det = vx.detect_oblique_windows(area, dname, threshold=0.4)
            if det["image"] is None:
                continue
            im = Image.open(det["image"]).convert("RGB")
            sc = min(1.0, MAXW / im.width)
            _save(im, kdir / "img" / f"oblique_{name}.jpg")
            W, H = round(im.width * sc), round(im.height * sc)
            boxes = [{"i": i, "x": round(b["x"] * sc, 1), "y": round(b["y"] * sc, 1),
                      "w": round(b["w"] * sc, 1), "h": round(b["h"] * sc, 1), "conf": b["confidence"]}
                     for i, b in enumerate(det["boxes"], 1)]
            out.append({"name": name, "direction": dname, "camera_looks": CAMERA_LOOKS[dname],
                        "facade": FACADE_SEEN[dname], "img": f"img/oblique_{name}.jpg", "w": W, "h": H,
                        "scale_to_original": round(1 / sc, 4), "boxes": boxes, "rows": len(_rows(det["boxes"])),
                        "tile": ti, "tiles": len(tiles), "area_wkt": area, "error": det["error"]})
    return out


def _roof(lat: float, lon: float) -> dict:
    try:
        d = vx.roof_height(lat, lon)
    except vx.VexcelError as e:
        return {"error": str(e)}
    feats = sorted(d.get("features", []), key=lambda f: vx._collection_rank(f.get("properties", {})), reverse=True)
    if not feats:
        return {}
    s = (feats[0]["properties"].get("structures") or [{}])[0]
    return {k: v for k, v in s.items() if any(w in k for w in ("height", "eave", "stor", "elevation"))}


FORM_CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--muted:#666;--line:#ddd;--accent:#0a66c2;--ok:#1a7f37;--sel:#16a34a;--pt:#f97316}
@media (prefers-color-scheme: dark){:root{--bg:#161616;--card:#222;--ink:#eee;--muted:#aaa;--line:#3a3a3a;--accent:#4ea1ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1280px;margin:auto;padding:16px 16px 120px}
h1{margin:.2em 0 .1em;font-size:24px}.intro{color:var(--muted);margin-top:0}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
section h2{margin:0 0 4px;font-size:18px}.hint{color:var(--muted);margin:2px 0 12px;font-size:14px}
img{max-width:100%;display:block;border-radius:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
.card{border:2px solid var(--line);border-radius:8px;padding:6px;cursor:pointer;user-select:none}
.card.on{border-color:var(--sel)}.card.off{opacity:.45}
.card .t{display:flex;justify-content:space-between;font-weight:600;margin-top:4px}.card .m{color:var(--muted);font-size:12px}
.opts label{display:inline-flex;align-items:center;gap:6px;margin:4px 14px 4px 0;font-size:15px}
input[type=number]{width:90px;font-size:16px;padding:4px}input[type=text],textarea{width:100%;font:inherit;padding:6px}
.ob{margin:14px 0}.ob h3{margin:0 0 4px;font-size:15px}
.pic{position:relative;display:inline-block;max-width:100%;cursor:crosshair}
.pic img{border-radius:0}
.bx{position:absolute;border:1.5px solid rgba(255,0,255,.85);cursor:pointer}
.bx.on{border:3px solid var(--sel);background:rgba(22,163,74,.25)}
.pt{position:absolute;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;background:var(--pt);border:2px solid #fff;cursor:pointer}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;display:flex;gap:14px;align-items:center;justify-content:center}
button{font:inherit;font-weight:600;padding:8px 22px;border-radius:8px;border:0;background:var(--accent);color:#fff;cursor:pointer}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--accent);padding:4px 12px;font-weight:500}
#status{color:var(--muted)}#status.ok{color:var(--ok)}
details{margin-top:8px}summary{cursor:pointer;color:var(--accent)}
.missing{background:#fff3cd;color:#5c4400;padding:8px 12px;border-radius:6px}
"""

FORM_JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const insideOn = new Set(D.inside.map(w => w.id));      // default: all detected windows are real
const picked = {};                                       // oblique name -> {boxes:Set, points:[]}

function renderInside(){
  const g = $('#inside'); g.innerHTML = '';
  D.inside.forEach(w => {
    const c = document.createElement('div');
    c.className = 'card ' + (insideOn.has(w.id) ? 'on' : 'off');
    c.innerHTML = `<img src="${w.img}" alt="${w.id}"><div class="t"><span>${w.id}</span><span>${insideOn.has(w.id) ? 'real window' : 'not a window'}</span></div>
      <div class="m">seen from ${w.views} view${w.views>1?'s':''}${w.width_m ? ' · about ' + w.width_m + ' m wide' : ''}</div>`;
    c.onclick = () => { insideOn.has(w.id) ? insideOn.delete(w.id) : insideOn.add(w.id); renderInside(); };
    g.appendChild(c);
  });
}
function setAllInside(on){ insideOn.clear(); if(on) D.inside.forEach(w => insideOn.add(w.id)); renderInside(); }

function renderObliques(){
  const host = $('#obliques'); host.innerHTML = '';
  if(!D.obliques.length){ host.innerHTML = '<p class="missing">No oblique images here.</p>'; return; }
  D.obliques.forEach(o => {
    picked[o.name] = picked[o.name] || {boxes:new Set(), points:[]};
    const p = picked[o.name];
    const div = document.createElement('div'); div.className = 'ob';
    const part = o.tiles > 1 ? ` · part ${o.tile} of ${o.tiles}` : '';
    div.innerHTML = `<h3>${o.name}: camera looking ${o.camera_looks}, shows the <b>${o.facade.toUpperCase()}</b> facade${part}</h3>`;
    const pic = document.createElement('div'); pic.className = 'pic';
    pic.innerHTML = `<img src="${o.img}" width="${o.w}" height="${o.h}" style="height:auto">`;
    pic.onclick = e => {
      if(e.target !== pic.firstChild) return;
      const r = pic.getBoundingClientRect();
      p.points.push({x: +((e.clientX - r.left) / r.width * o.w).toFixed(1), y: +((e.clientY - r.top) / r.height * o.h).toFixed(1)});
      renderObliques();
    };
    o.boxes.forEach(b => {
      const el = document.createElement('div'); el.className = 'bx' + (p.boxes.has(b.i) ? ' on' : '');
      Object.assign(el.style, {left: b.x/o.w*100+'%', top: b.y/o.h*100+'%', width: b.w/o.w*100+'%', height: b.h/o.h*100+'%'});
      el.title = `${o.name} box ${b.i}`;
      el.onclick = e => { e.stopPropagation(); p.boxes.has(b.i) ? p.boxes.delete(b.i) : p.boxes.add(b.i); renderObliques(); };
      pic.appendChild(el);
    });
    p.points.forEach((pt, k) => {
      const el = document.createElement('div'); el.className = 'pt'; el.title = 'click to remove';
      Object.assign(el.style, {left: pt.x/o.w*100+'%', top: pt.y/o.h*100+'%'});
      el.onclick = e => { e.stopPropagation(); p.points.splice(k, 1); renderObliques(); };
      pic.appendChild(el);
    });
    div.appendChild(pic); host.appendChild(div);
  });
}

function collect(){
  const facades = [...document.querySelectorAll('input[name=facade]:checked')].map(i => i.value);
  const floorVal = $('#floor').value.trim();
  const out = [];
  D.obliques.forEach(o => {
    const p = picked[o.name]; if(!p) return;
    const k = o.scale_to_original;
    o.boxes.filter(b => p.boxes.has(b.i)).forEach(b => out.push({image:o.name, direction:o.direction, box:b.i,
      x:+(b.x*k).toFixed(1), y:+(b.y*k).toFixed(1), w:+(b.w*k).toFixed(1), h:+(b.h*k).toFixed(1), missed:false}));
    p.points.forEach(pt => out.push({image:o.name, direction:o.direction, box:null, x:+(pt.x*k).toFixed(1), y:+(pt.y*k).toFixed(1), missed:true}));
  });
  return {
    version: 2, scan_id: D.scan_id, checked_by: 'Yug',
    building: {vexcel_structure_id: $('#building').value.trim(), costar_property_id: D.costar_id, address: D.address},
    facades, unit_floor_from_ground: floorVal === '' ? null : parseInt(floorVal, 10), floor_sure: !$('#floorUnsure').checked,
    inside_windows: D.inside.filter(w => insideOn.has(w.id)).map(({img, ...w}) => w),
    inside_rejected: D.inside.filter(w => !insideOn.has(w.id)).map(w => w.id),
    outside_windows: out, outside_skipped: $('#skipOutside').checked,
    confidence: (document.querySelector('input[name=conf]:checked') || {}).value || null,
    notes: $('#notes').value.trim(),
  };
}

async function save(){
  const key = collect();
  const st = $('#status');
  if(!key.facades.length || key.unit_floor_from_ground === null){
    if(!confirm('Facade or floor is empty. Save anyway?')) return;
  }
  try {
    const r = await fetch('save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(key)});
    if(!r.ok) throw new Error(await r.text());
    st.textContent = 'Saved to ' + (await r.json()).path; st.className = 'ok';
  } catch(err) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(key, null, 2)], {type:'application/json'}));
    a.download = `answer_key_${D.scan_id}.json`; a.click();
    st.textContent = 'Downloaded. Move it into handcheck/answer_keys/ (open the form with --form to save directly).';
    st.className = '';
  }
}

async function prefill(){
  try {
    const r = await fetch('answer_key.json', {cache:'no-store'}); if(!r.ok) return;
    const k = await r.json(); if(k.version !== 2) return;
    $('#building').value = k.building?.vexcel_structure_id || $('#building').value;
    document.querySelectorAll('input[name=facade]').forEach(i => i.checked = (k.facades || []).includes(i.value));
    if(k.unit_floor_from_ground != null) $('#floor').value = k.unit_floor_from_ground;
    $('#floorUnsure').checked = k.floor_sure === false;
    insideOn.clear(); (k.inside_windows || []).forEach(w => insideOn.add(w.id));
    (k.outside_windows || []).forEach(w => {
      const o = D.obliques.find(o => o.name === w.image); if(!o) return;
      picked[o.name] = picked[o.name] || {boxes:new Set(), points:[]};
      if(w.box) picked[o.name].boxes.add(w.box);
      else picked[o.name].points.push({x: w.x / o.scale_to_original, y: w.y / o.scale_to_original});
    });
    $('#skipOutside').checked = !!k.outside_skipped;
    const c = document.querySelector(`input[name=conf][value="${k.confidence}"]`); if(c) c.checked = true;
    $('#notes').value = k.notes || '';
    renderInside(); renderObliques();
    $('#status').textContent = 'Loaded your saved answers.';
  } catch(e) {}
}

renderInside(); renderObliques(); prefill();
"""


def build_kit(scan_id: str) -> Path:
    kdir = OUT / scan_id
    if (kdir / "img").exists():
        shutil.rmtree(kdir / "img")  # old drawings with per-view IDs would be misleading
    (kdir / "img").mkdir(parents=True, exist_ok=True)
    det = mp.model_details(scan_id)
    loc = rough_location(scan_id)
    prop = loc["property"]
    sweeps = _sweeps(scan_id)
    lat, lon = loc["lat"], loc["lon"]
    print(f"{scan_id}: {det.get('name')} | {len(sweeps)} sweeps | location from {loc['source']}")
    target, near = _target_building(lat, lon) if lat is not None else (None, [])

    print("  inside windows (detect, filter, merge across sweeps) ...")
    iw = unique_windows(scan_id)
    cards = _inside_cards(iw["windows"], kdir)
    plans = _floorplan_images(scan_id, sweeps, iw["windows"], kdir)
    faces = _raw_faces(scan_id, sweeps, kdir)
    print(f"    {len(iw['windows'])} unique windows ({iw['rejected']} boxes rejected, detector {iw['detector']})")
    print("  aerial ...")
    aerial = _aerial(lat, lon, target, near, kdir) if lat is not None else None
    print("  obliques ...")
    obl = _obliques(target, lat, lon, kdir) if lat is not None else []
    roof = _roof(lat, lon) if lat is not None else {}

    tour = (det.get("publication") or {}).get("url")
    # no street address in saved answer keys (they are committed to a public repo)
    data = {"scan_id": scan_id, "costar_id": (prop or {}).get("property_id", ""), "address": "",
            "inside": cards, "obliques": obl}
    kit = {"scan_id": scan_id, "name": det.get("name"), "costar": prop,
           "rough_location": {k: loc[k] for k in ("lat", "lon", "source")}, "geocoordinates": loc["geocoordinates"],
           "target_building": target, "nearby_buildings": [{k: b[k] for k in ("building_id", "distance_m", "building_type")} for b in near],
           "sweeps": [{k: s[k] for k in ("label", "sweep_id", "position", "floor_id")} for s in sweeps],
           "inside_windows": [{k: v for k, v in w.items() if k not in ("views", "best_view")} | {"views": len(w["views"])} for w in iw["windows"]],
           "inside_detector": iw["detector"], "obliques": obl, "roof": roof}
    (kdir / "kit.json").write_text(json.dumps(kit, indent=1, default=str))

    esc = html.escape
    plan_html = "".join(f"<img src='{p['image']}' alt='floor plan'>" for p in plans) or \
        "<p class=missing>No floor plan for this scan.</p>"
    faces_html = "".join(f"<img src='{f}' alt='' loading=lazy style='margin:6px 0'>" for f in faces)
    roof_txt = ", ".join(f"{k.split('.')[-1]} {v:.1f} m" for k, v in roof.items() if isinstance(v, (int, float)))
    target_id = (target or {}).get("building_id", "")
    others = ", ".join([b["building_id"] for b in near if b["building_id"] != target_id][:8])
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Hand check {esc(scan_id)}</title>
<style>{FORM_CSS}</style></head><body><main>
<h1>Hand check: {esc(det.get('name') or scan_id)}</h1>
<p class=intro>{esc((prop or {}).get('address') or '')} · scan <code>{esc(scan_id)}</code>.
Answer the five questions and press <b>Save</b> at the bottom. Leave anything you are unsure about empty.
{f'<a href="{esc(tour)}" target=_blank rel=noopener>Open the 3D tour</a> to look out of the windows.' if tour else ''}</p>

<section><h2>1. Which building is the unit in?</h2>
<p class=hint>Yellow outline = the building at the rough location. North is up. Change the ID only if the unit is in a different outlined building{(' (others: ' + esc(others) + ')') if others else ''}.</p>
{f"<img src='{aerial}' alt='aerial'>" if aerial else "<p class=missing>No aerial image or footprint here.</p>"}
<p><label>Building ID <input type=text id=building value="{esc(target_id)}" style="max-width:260px"></label></p></section>

<section><h2>2. Which of these are real windows of the unit?</h2>
<p class=hint>Each card is one window, merged from every sweep that sees it. Click a card to mark it <b>not a window</b> (doors, mirrors, closets). Red dots on the floor plan show where each one is.</p>
<p><button class=ghost type=button onclick="setAllInside(true)">all real</button> <button class=ghost type=button onclick="setAllInside(false)">none</button></p>
<div class=grid id=inside></div>
<details><summary>Floor plan with the windows marked</summary>{plan_html}</details>
<details><summary>Look around: every sweep's four views</summary>{faces_html}</details></section>

<section><h2>3. Which side of the building do the windows face?</h2>
<p class=hint>Look out of the windows (3D tour or the cards) and match what you see (street, parking, pool, neighbours) to the aerial. Tick every side that has the unit's windows.</p>
<div class=opts>{''.join(f'<label><input type=checkbox name=facade value={v}> {v.title()}</label>' for v in ('north', 'east', 'south', 'west', 'courtyard'))}</div></section>

<section><h2>4. Which floor is the unit on, counting the ground floor as 1?</h2>
<p class=hint>Judge from the view: how far down is the street, and are you above the neighbours' roofs? {('Vexcel roof data: ' + esc(roof_txt) + '.') if roof_txt else ''}</p>
<div class=opts><label>Floor <input type=number id=floor min=1 max=80></label><label><input type=checkbox id=floorUnsure> not sure</label></div></section>

<section><h2>5. Optional: click the unit's windows from outside</h2>
<p class=hint>Only if you can tell. Click a pink box to select it (it turns green). Click anywhere else to drop an orange dot on a window the detector missed; click a dot to remove it.</p>
<div class=opts><label><input type=checkbox id=skipOutside> I can't tell which windows from outside</label></div>
<div id=obliques></div></section>

<section><h2>How sure are you overall?</h2>
<div class=opts>{''.join(f'<label><input type=radio name=conf value="{v}"> {v}</label>' for v in ('sure', 'fairly sure', 'unsure'))}</div>
<p><textarea id=notes rows=3 placeholder="Notes (optional): e.g. corner unit, windows face the pool courtyard"></textarea></p></section>
</main>
<div class=bar><button type=button onclick="save()">Save answers</button><span id=status></span></div>
<script type=application/json id=data>{json.dumps(data).replace('</', '<\\/')}</script>
<script>{FORM_JS}</script></body></html>"""
    (kdir / "index.html").write_text(page)
    print(f"  done: {kdir / 'index.html'}")
    return kdir / "index.html"


def serve_form(scan_id: str, port: int = 8765) -> None:
    """Serve the kit on 127.0.0.1 so the form's Save button writes the answer key."""
    import http.server
    import socketserver
    import webbrowser

    kdir = OUT / scan_id
    if not (kdir / "index.html").exists():
        build_kit(scan_id)
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    key_path = KEYS_DIR / f"answer_key_{scan_id}.json"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(kdir), **k)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.split("?")[0] == "/answer_key.json":
                if not key_path.exists():
                    self.send_error(404)
                    return
                body = key_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def do_POST(self):
            if self.path != "/save":
                self.send_error(404)
                return
            n = int(self.headers.get("Content-Length", 0))
            try:
                key = json.loads(self.rfile.read(min(n, 5_000_000)))
                assert key.get("scan_id") == scan_id and key.get("version") == 2
            except Exception:
                self.send_error(400, "bad answer key")
                return
            key_path.write_text(json.dumps(key, indent=2) + "\n")
            body = json.dumps({"path": str(key_path.relative_to(REPO_ROOT))}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            print(f"  saved {key_path.relative_to(REPO_ROOT)}")

    for p in range(port, port + 20):
        try:
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    else:
        raise SystemExit("no free port near 8765")
    url = f"http://127.0.0.1:{p}/"
    print(f"Hand-check form for {scan_id}: {url}\nAnswers save to {key_path.relative_to(REPO_ROOT)}. Ctrl-C to stop.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


# --- 3. verify -----------------------------------------------------------------------------

FACING = {"north": 0, "east": 90, "south": 180, "west": 270}


def _load_key(scan_id: str) -> dict:
    p = KEYS_DIR / f"answer_key_{scan_id}.json"
    if not p.exists():
        raise SystemExit(f"no answer key yet: run  python -m dome.tools.handcheck --form {scan_id}  and press Save")
    key = json.loads(p.read_text())
    if key.get("version") != 2:
        raise SystemExit(f"{p} is the old format; open the form again and press Save")
    return key


def _implied_rotation(key: dict) -> float | None:
    """Model->true rotation implied by the key: ticked facades vs the inside windows' wall normals.
    Each window's normal is matched to the nearest ticked compass facade after a common rotation."""
    normals = [w["normal_deg"] for w in key.get("inside_windows", []) if w.get("normal_deg") is not None]
    targets = [FACING[f] for f in key.get("facades", []) if f in FACING]
    if not normals or not targets:
        return None
    best = None
    for rot in range(360):
        err = sum(min(abs(((n + rot) - t + 180) % 360 - 180) for t in targets) for n in normals)
        if best is None or err < best[0]:
            best = (err, rot)
    return float(best[1])


def verify(scan_id: str) -> Path:
    key = _load_key(scan_id)
    kdir = OUT / scan_id
    loc = rough_location(scan_id)
    lines = [f"# Verify {scan_id}", "", f"Answer key confidence: {key.get('confidence')}", ""]
    try:
        res = geo.fix_scan_location(scan_id, loc["lat"], loc["lon"])
    except NotImplementedError as e:
        lines += ["**PENDING**: `geo.fix_scan_location` is not implemented in real mode yet.", "", f"`{e}`"]
        print("\n".join(lines))
        (kdir / "verify.md").write_text("\n".join(lines) + "\n")
        return kdir / "verify.md"
    # keys beyond the contract (floor, window_match, ...) live in the notes file
    notes_file = next((e for e in res.get("evidence", []) if str(e).endswith("_notes.json")), None)
    if notes_file and Path(notes_file).exists():
        res = {**json.loads(Path(notes_file).read_text()).get("result", {}), **res}
    checks = []
    want_b = (key.get("building") or {}).get("vexcel_structure_id")
    checks.append(("building", res.get("building_id") == want_b, f"got {res.get('building_id')}, key {want_b}"))
    want_f = key.get("unit_floor_from_ground")
    if want_f is None:
        checks.append(("floor", None, "not in key"))
    else:
        checks.append(("floor", res.get("floor") == want_f, f"got {res.get('floor')}, key {want_f}"
                       + ("" if key.get("floor_sure", True) else " (key not sure)")))
    want_h = _implied_rotation(key)
    if want_h is not None and res.get("heading_deg") is not None:
        dh = abs((res["heading_deg"] - want_h + 180) % 360 - 180)
        checks.append(("heading", dh <= 20, f"got {res['heading_deg']:.0f}, key implies {want_h:.0f} (diff {dh:.0f} deg)"))
    else:
        checks.append(("heading", None, "not comparable"))
    mine = {(w["image"], w["box"]) for w in key.get("outside_windows", []) if w.get("box")}
    got = {(m["image"], m["box"]) for m in ((res.get("window_match") or {}).get("matched_boxes") or [])}
    if key.get("outside_skipped") or not mine:
        checks.append(("windows", None, "key has no outside windows"))
    elif got:
        ov = len(mine & got) / len(mine | got)
        checks.append(("windows", ov >= 0.5, f"overlap {ov:.2f}"))
    else:
        checks.append(("windows", False, "geo reported no matched boxes"))
    word = {True: "PASS", False: "FAIL", None: "n/a"}
    lines += ["| field | result | detail |", "|---|---|---|"] + [f"| {n} | {word[ok]} | {d} |" for n, ok, d in checks]
    for p in res.get("evidence", []):
        if str(p).endswith(".jpg"):
            lines += ["", f"![evidence]({os.path.relpath(p, kdir)})"]
    (kdir / "verify.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return kdir / "verify.md"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan_id", nargs="?")
    ap.add_argument("--list", action="store_true", help="build handcheck/shortlist.md")
    ap.add_argument("--small", action="store_true", help="with --list: small-building shortlist (Ring A)")
    ap.add_argument("--near", action="store_true", help="with --list: Ring A candidates near Ishaan's Houston gazetteer")
    ap.add_argument("--form", metavar="SCAN_ID", help="build the kit if needed and open the form")
    ap.add_argument("--rebuild", action="store_true", help="with --form: rebuild the kit first")
    ap.add_argument("--verify", metavar="SCAN_ID")
    ap.add_argument("--decoy", metavar="SCAN_ID", help="find decoy D within 1 km of scan A")
    ap.add_argument("--pool", type=int, default=60, help="CoStar properties to consider for --list")
    ap.add_argument("--deep", type=int, default=25, help="unit scans to deep-check for --list")
    a = ap.parse_args(argv)
    if a.list and a.near:
        shortlist_near()
    elif a.list and a.small:
        shortlist_small(a.deep)
    elif a.list:
        shortlist(a.pool, a.deep)
    elif a.form:
        if a.rebuild:
            build_kit(a.form)
        serve_form(a.form)
    elif a.verify:
        verify(a.verify)
    elif a.decoy:
        find_decoy(a.decoy)
    elif a.scan_id:
        build_kit(a.scan_id)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
