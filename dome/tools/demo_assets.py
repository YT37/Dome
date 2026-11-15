"""Location asset pack per scan for the demo UI.

    DOME_STUBS=0 python -m dome.tools.demo_assets <scan_id> [<scan_id> ...]

Writes data/demo_assets/<scan_id>/assets.json plus images beside it (images are git-ignored).
Image paths in the JSON are relative to the repo root. Nothing here contains a street
address; every API call goes through the data_tools caches.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

from dome.data_tools._common import REPO_ROOT

OUT_ROOT = REPO_ROOT / "data" / "demo_assets"
STOREY_M = 3.2
BUILDINGS = REPO_ROOT / "dome" / "synth" / "buildings.json"
SUMMARY = REPO_ROOT / "data" / "matches" / "summary.json"
JPG = {"quality": 90}


def _rel(p: Path) -> str:
    return str(Path(p).resolve().relative_to(REPO_ROOT))


def _haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _building_row(scan_id: str) -> dict:
    for b in json.loads(BUILDINGS.read_text()):
        if b.get("scan_id") == scan_id:
            return b
    return {}


# --- CoStar -----------------------------------------------------------------------------

def _costar(scan_id: str, row: dict) -> tuple[dict, int | None, str | None, str]:
    from dome.data_tools import costar
    p = costar.property_for_scan(scan_id) or {}
    info = {"type": p.get("type"), "floors": p.get("floors"), "units": p.get("units"),
            "year_built": p.get("year_built")}
    floor = source = None
    try:
        uf = costar.unit_floors_for_scan(scan_id)
        if uf.get("floors"):
            floor = int(uf["floors"][0])
            unit = (row.get("unit") or (uf["units"][0][0] if uf.get("units") else None))
            source = f"CoStar unit {unit}" if unit else "CoStar unit numbers"
    except Exception:
        pass
    label = row.get("label")
    bits = [f"{label} building" if label else "Building"]
    extra = [str(info["type"]).lower()] if info["type"] else []
    if info["floors"]:
        extra.append(f"{info['floors']} floors")
    name = f"Ring {label} building" if row.get("role") == "ring" else bits[0]
    if row.get("role") == "decoy":
        name = f"Decoy {label} building"
    if extra:
        name += f" ({', '.join(extra)})"
    return info, floor, source, name


# --- Vexcel -----------------------------------------------------------------------------

def _outline_for(fix: dict, lat: float, lon: float):
    from shapely import wkt as swkt
    from dome.data_tools import vexcel
    outs = vexcel.building_outlines(lat, lon, 60)
    pick = next((o for o in outs if o["building_id"] == fix.get("building_id")), None)
    if pick is None and outs:
        pick = outs[0]
    return (swkt.loads(pick["outline"]), pick) if pick else (None, None)


def _facade_edge(poly, heading_deg: float):
    """Longest footprint edge whose outward normal is within 40 deg of heading (lon/lat ends)."""
    lat0 = poly.centroid.y
    mx = 111320.0 * math.cos(math.radians(lat0))
    my = 110540.0
    ring = list(poly.exterior.coords)
    cx, cy = poly.centroid.x, poly.centroid.y
    best = None
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        dx, dy = (x1 - x0) * mx, (y1 - y0) * my
        L = math.hypot(dx, dy)
        if L < 3:
            continue
        nx, ny = dy / L, -dx / L
        if nx * ((x0 + x1) / 2 - cx) * mx + ny * ((y0 + y1) / 2 - cy) * my < 0:
            nx, ny = -nx, -ny
        brg = math.degrees(math.atan2(nx, ny)) % 360
        if abs((brg - heading_deg + 180) % 360 - 180) <= 40 and (best is None or L > best[0]):
            best = (L, (x0, y0), (x1, y1))
    return best[1:] if best else None


def _band_image(poly, fix_heading, direction, area_wkt, floor, dst: Path, fallback_img: str | None):
    """Oblique with the floor band drawn. Returns (image path, floor_band or None, camera dict)."""
    from PIL import Image, ImageDraw
    from dome.data_tools import vexcel
    from dome.data_tools.oblique_camera import ObliqueCamera
    det = vexcel.detect_oblique_windows(area_wkt, direction)
    img = det.get("image")
    meta = det.get("metadata") or {}
    camera = {"direction": direction, "capture_date": meta.get("capture-date")}
    if not img:
        if fallback_img:
            shutil.copyfile(fallback_img, dst)
            return dst, None, camera
        return None, None, camera
    im = Image.open(img).convert("RGB")
    band = None
    try:
        cam = ObliqueCamera(meta, im.size)
        edge = _facade_edge(poly, fix_heading) if poly is not None else None
        if floor and edge:
            lo, hi = (floor - 1) * STOREY_M, floor * STOREY_M
            pts = []
            for z in (lo, hi):
                for (lon, lat) in (edge[0], edge[1]) if z == lo else (edge[1], edge[0]):
                    pts.append(cam.project_lonlat(lon, lat, z))
            if all(p is not None for p in pts):
                over = Image.new("RGBA", im.size, (0, 0, 0, 0))
                ImageDraw.Draw(over).polygon(pts, fill=(255, 40, 40, 110), outline=(255, 40, 40, 255))
                im = Image.alpha_composite(im.convert("RGBA"), over).convert("RGB")
                band = [round(lo, 2), round(hi, 2)]
    except Exception:
        band = None
    im.save(dst, "JPEG", **JPG)
    return dst, band, camera


# --- Matterport / matches ----------------------------------------------------------------

def _summary(scan_id: str) -> dict | None:
    if not SUMMARY.exists():
        return None
    try:
        s = json.loads(SUMMARY.read_text())
        return (s.get("scans") or s).get(scan_id)
    except Exception:
        return None


def _matches_and_sweep(scan_id: str, out: Path):
    s = _summary(scan_id)
    ev = (s or {}).get("evidence") or []
    if not ev:
        return None, [], None
    matches = []
    for i, e in enumerate(ev):
        mi = e.get("match_img")
        dst = None
        if mi and Path(mi if Path(mi).is_absolute() else REPO_ROOT / mi).exists():
            src = Path(mi if Path(mi).is_absolute() else REPO_ROOT / mi)
            dst = out / f"match_{i}{src.suffix}"
            shutil.copyfile(src, dst)
        photo = e.get("photo")
        matches.append({"photo": photo, "match_img": _rel(dst) if dst else None,
                        "inliers": e.get("inliers")})
    top = max(ev, key=lambda e: e.get("inliers") or 0)
    parts = str(top.get("view_id", "")).split("/")
    sweep_id = parts[1] if len(parts) >= 3 else None
    sweep = {"sweep_id": sweep_id, "heading_deg": top.get("heading_deg"), "faces": None,
             "floorplan_img": None, "xy": None}
    if sweep_id:
        try:
            sweep.update(_sweep_assets(scan_id, sweep_id, out))
        except Exception:
            pass
    return sweep, matches, sweep_id


def _sweep_assets(scan_id: str, sweep_id: str, out: Path) -> dict:
    import cv2
    from dome.data_tools import floorplan, matterport as mp
    res = {}
    fp_all = mp.face_paths(scan_id, faces=(0, 1, 2, 3, 4, 5))
    by_face = {f["face"]: f for f in fp_all if f["sweep_id"] == sweep_id}
    faces = []
    for k in range(6):
        if k not in by_face:
            faces = None
            break
        dst = out / f"sweep_f{k}.jpg"
        shutil.copyfile(by_face[k]["path"], dst)
        faces.append(_rel(dst))
    res["faces"] = faces
    any_f = next(iter(by_face.values()), None)
    pos = (any_f or {}).get("position")
    if pos:
        res["xy"] = [round(pos["x"], 3), round(pos["y"], 3)]
        fps = floorplan.best_floorplans(scan_id)
        fp = next((f for f in fps if (f.get("floor") or {}).get("id") == any_f.get("floor_id")),
                  fps[0] if fps else None)
        if fp:
            img = cv2.imread(floorplan.floorplan_file(scan_id, fp))
            H, W = img.shape[:2]
            R = fp["resolution"] * (W / fp["width"] if fp.get("width") else 1.0)
            px = (pos["x"] - fp["origin"]["x"]) * R
            py = H - (pos["y"] - fp["origin"]["y"]) * R
            r = max(6, int(0.012 * W))
            cv2.circle(img, (int(px), int(py)), r + 2, (255, 255, 255), -1)
            cv2.circle(img, (int(px), int(py)), r, (0, 0, 255), -1)
            dst = out / "floorplan.png"
            cv2.imwrite(str(dst), img)
            res["floorplan_img"] = _rel(dst)
    return res


def _embed(scan_id: str, sweep: dict | None):
    if not sweep or not sweep.get("sweep_id"):
        return None
    from dome.data_tools import matterport as mp
    ss = None
    try:
        ids = [p["id"] for p in mp._panos(scan_id)]
        ss = ids.index(sweep["sweep_id"])
    except Exception:
        pass
    # sr = heading (degrees) of the matched view; the UI converts it to the viewer's rotation
    # Tested in a browser: loads (public model) and opens in the matched sweep. The default
    # splash and title show the listing's street address, so the UI must use `params`
    # (title, branding and details hidden, quick start) and never display the page title.
    return {"model_id": scan_id, "ss": ss, "sr": sweep.get("heading_deg"),
            "params": "qs=1&title=0&brand=0&mls=2&help=0&hr=0&dh=0&search=0",
            "note": "never show Matterport's title or details panel: they contain the address"}


# --- main --------------------------------------------------------------------------------

def _geo_steps(scan_id: str, row: dict, fix: dict, floor, floor_source, obliques, moved_m) -> dict:
    """What geo.fix_scan_location did, step by step, from its own notes (no new numbers):
    rough pin, nearby Vexcel footprints with the outline-fit scores geo computed (only its
    top hypotheses carry a score), the chosen footprint, the fixed pin, CoStar unit -> floor,
    and the oblique floor band. Heading is left out on purpose (Ring A's is unreliable)."""
    from shapely import wkt as swkt
    from shapely.geometry import mapping
    from dome.data_tools import vexcel
    try:
        notes = json.loads((REPO_ROOT / "cache" / "geo" / f"{scan_id}_notes.json").read_text())
    except Exception:
        notes = {}
    hyp = {h["building_id"]: h for h in notes.get("hypotheses") or []}
    feats = []
    for o in vexcel.building_outlines(row["lat"], row["lon"], 120):
        h = hyp.get(o["building_id"])
        feats.append({"building_id": o["building_id"],
                      "geojson": {"type": "Feature", "properties": {"building_id": o["building_id"]},
                                  "geometry": mapping(swkt.loads(o["outline"]))},
                      "fit_score": round(h["final"], 3) if h else None,
                      "outline_score": h.get("outline") if h else None,
                      "pin_prior": h.get("prior") if h else None,
                      "chosen": o["building_id"] == fix.get("building_id")})
    unit = row.get("unit")
    return {
        "rough_pin": {"lat": row["lat"], "lon": row["lon"], "source": "CoStar listing coordinates"},
        "footprints": feats,
        "fit_note": "fit_score = outline fit (floor plan vs footprint) + pin prior; scored only for "
                    "geo's top hypotheses, the rest are null (not scored, not zero)",
        "fixed_pin": {"lat": fix["lat"], "lon": fix["lon"], "moved_m": moved_m,
                      "error_estimate_m": fix["error_estimate_m"], "confidence": notes.get("confidence")},
        "floor": {"unit": unit, "floor": floor, "source": floor_source},
        "floor_band_img": next((o["img"] for o in obliques if o.get("floor_band")), None),
    }


def _fingerprint(scan_id: str, obliques: list[dict]) -> dict:
    """Window-grid fingerprint (gemini_vision.window_fingerprint): the scan's first window ad
    photo (sorted id, same order as the Locator) vs the facade floor band."""
    from dome.data_tools import gemini_vision
    band = next((o["img"] for o in obliques if o.get("floor_band")), None)
    renders = json.loads((REPO_ROOT / "data" / "synth" / "renders.json").read_text())
    wins = sorted(pid for pid, v in renders.items() if v.get("scan_id") == scan_id and v.get("view") == "window")
    photo = next((REPO_ROOT / "data" / "photos" / f"{p}.jpg" for p in wins
                  if (REPO_ROOT / "data" / "photos" / f"{p}.jpg").exists()), None)
    if band is None or photo is None:
        return {"skipped": "no floor band on the facade" if band is None else "no window ad photo for this scan"}
    out = gemini_vision.window_fingerprint(str(photo), str(REPO_ROOT / band))
    return {**out, "photo": photo.stem, "facade_img": band}


def build(scan_id: str) -> Path:
    from PIL import Image
    from shapely.geometry import mapping
    from dome.data_tools import geo, vexcel

    out = OUT_ROOT / scan_id
    out.mkdir(parents=True, exist_ok=True)
    row = _building_row(scan_id)
    rough_lat, rough_lon = row["lat"], row["lon"]
    info, floor, floor_source, name = _costar(scan_id, row)

    fix = geo.fix_scan_location(scan_id, rough_lat, rough_lon)
    lat, lon, heading = fix["lat"], fix["lon"], fix["heading_deg"]
    if floor is None:
        try:
            notes = json.loads((REPO_ROOT / "cache" / "geo" / f"{scan_id}_notes.json").read_text())
            gf = (notes.get("result") or {}).get("floor")
            if gf:
                floor, floor_source = int(gf), "window fingerprint"
        except Exception:
            pass

    poly, _ = _outline_for(fix, lat, lon)
    footprint = None
    if poly is not None:
        footprint = {"type": "Feature", "properties": {"building_id": fix.get("building_id")},
                     "geometry": mapping(poly)}

    path, bounds = vexcel.ortho_square(lat, lon, 60)
    ortho = out / "ortho.jpg"
    Image.open(path).convert("RGB").save(ortho, "JPEG", **JPG)

    obliques = []
    headings = [heading, (heading + 180) % 360]
    done = set()
    for i, h in enumerate(headings):
        try:
            op = vexcel.oblique_view(lat, lon, h)
            side = json.loads(Path(op).with_suffix(".json").read_text())
            direction = side["used"]
            if direction in done:
                continue
            done.add(direction)
            dst = out / f"oblique_{i}.jpg"
            area = vexcel.square_wkt(lat, lon, 40)
            img, band, camera = _band_image(poly, h, direction, area, floor if i == 0 else None,
                                            dst, op)
            if img is None:
                continue
            obliques.append({"img": _rel(img), "camera": camera, "floor_band": band})
        except Exception as e:  # no coverage for this facade; keep the rest of the pack
            print(f"  {scan_id}: oblique {i} skipped ({type(e).__name__})", file=sys.stderr)

    sweep, matches, _ = _matches_and_sweep(scan_id, out)
    moved = round(_haversine(rough_lat, rough_lon, lat, lon), 1)
    pack = {
        "display_name": name,
        "costar": info,
        "footprint_geojson": footprint,
        "rough_pin": {"lat": rough_lat, "lon": rough_lon, "source": "CoStar listing coordinates"},
        "fixed_pin": {"lat": lat, "lon": lon, "heading_deg": heading,
                      "error_estimate_m": fix["error_estimate_m"],
                      "moved_m": moved},
        "ortho": {"img": _rel(ortho), "bounds": [round(b, 7) for b in bounds]},
        "obliques": obliques,
        "floor": floor,
        "floor_source": floor_source,
        "matched_sweep": sweep,
        "matches": matches,
        "matterport_embed": _embed(scan_id, sweep),
        "geo_steps": _geo_steps(scan_id, row, fix, floor, floor_source, obliques, moved),
        "fingerprint": _fingerprint(scan_id, obliques),
    }
    dst = out / "assets.json"
    dst.write_text(json.dumps(pack, indent=1, sort_keys=False) + "\n")
    return dst


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for sid in argv:
        print(f"{sid}: {build(sid)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
