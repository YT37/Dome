"""Geolocation fix: place a Matterport scan on the right Vexcel building, facade and floor.

Two methods, combined:
1. Outline fit. The unit's outline (floor plan) and its windows (inside_windows) are
   rotated and moved onto each nearby Vexcel footprint. Good fits keep the unit inside
   the footprint and put every window wall on the footprint's outer edge, facing out.
2. Window fingerprint. For the best outline hypotheses, the oblique image that looks at
   each window wall is fetched, Vexcel's window detector runs on it, and every detected
   window is back-projected onto the facade plane with the oblique camera model
   (oblique_camera.py), giving metres along the facade and metres above ground. Windows
   cluster into floors; the unit's inside window pattern is slid along each floor and
   the best overlap gives the floor and the unit's position along the facade.

final score = 0.5 x outline + 0.5 x windows (outline only when the window step falls back).

Frames: model headings are clockwise from model +Y (matterport.py). heading_deg in the
output is the rotation to add to a model heading to get a true-north bearing, so the
model's +Y axis points to bearing heading_deg. Local world frame: metres east/north of
the rough pin.
Nothing is sent to Matterport: geocoordinates_patch is output only.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

from . import _stub
from ._common import cache_dir, cached_json, use_stubs

WALL_OFFSET_M = 0.3       # inside face of an exterior wall to the footprint's outer face
EDGE_TOL_M = 1.5          # a window counts as "on the facade" within this distance
FACADE_MAX_M = 3.0        # a window wall further than this from a footprint edge is not on it
                          # (courtyards and set-backs are missing from ground footprints)
ROT_REFINE = (-2, -1, 0, 1, 2)
PRIOR_WEIGHT, PRIOR_SCALE_M = 0.2, 60.0   # closeness to the rough pin breaks outline ties
MIN_MATCHED, MIN_WALL_SCORE = 2, 0.25     # weaker window matches count as no evidence
CONTRACT_KEYS = ("lat", "lon", "heading_deg", "building_id", "floor_range", "error_estimate_m", "evidence")


# --- small geometry helpers ------------------------------------------------------------

def _rot_cw(theta_deg: float) -> np.ndarray:
    """Rotate a heading clockwise by theta: model vector -> world vector (x east, y north)."""
    t = math.radians(theta_deg)
    return np.array([[math.cos(t), math.sin(t)], [-math.sin(t), math.cos(t)]])


def _heading(v) -> float:
    return math.degrees(math.atan2(v[0], v[1])) % 360


def _angdiff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


@dataclass
class Local:
    """Equirectangular metres around an origin (fine within a few km)."""
    lat0: float
    lon0: float

    @property
    def mx(self):
        return 111_320.0 * math.cos(math.radians(self.lat0))

    def to_xy(self, lon, lat):
        return ((lon - self.lon0) * self.mx, (lat - self.lat0) * 111_320.0)

    def to_ll(self, x, y):
        return (self.lon0 + x / self.mx, self.lat0 + y / 111_320.0)


@dataclass
class Hypothesis:
    building: dict
    theta: float                      # model -> true rotation, degrees clockwise
    t: np.ndarray                     # world translation of the model origin (local metres)
    outline_score: float
    inside_frac: float
    win_frac: float
    window_score: float | None = None
    floor: int | None = None
    unit_offset_m: float | None = None
    window_info: dict = field(default_factory=dict)
    prior: float = 0.0                # PRIOR_WEIGHT x closeness of the building to the rough pin

    @property
    def final(self) -> float:
        base = self.outline_score if self.window_score is None else 0.5 * self.outline_score + 0.5 * self.window_score
        return base + self.prior


# --- scan geometry (model frame) ----------------------------------------------------------

def scan_geometry(scan_id: str) -> dict:
    """Unit outline polygon and windows in the model frame, for the floor with most sweeps."""
    from shapely.geometry import MultiPoint

    from . import floorplan as fpm
    from . import matterport as mp
    from .inside_windows import unique_windows

    sweeps = mp._panos(scan_id)
    counts: dict[str, int] = {}
    for s in sweeps:
        fid = (s.get("floor") or {}).get("id")
        counts[fid] = counts.get(fid, 0) + 1
    main_floor = max(counts, key=counts.get) if counts else None
    plans = fpm.load(scan_id)
    outline, source = None, None
    if main_floor in plans:
        outline = plans[main_floor].outline_polygon()
        source = "floor plan"
    if outline is None or outline.area < 5:
        pts = [(s["position"]["x"], s["position"]["y"]) for s in sweeps
               if s.get("position") and (s.get("floor") or {}).get("id") == main_floor]
        outline = MultiPoint(pts).convex_hull.buffer(1.5) if len(pts) >= 3 else None
        source = "sweep hull"
    iw = unique_windows(scan_id)
    wins = [w for w in iw["windows"] if w["x"] is not None and w["floor_id"] == main_floor]
    return {"outline": outline, "outline_source": source, "windows": wins, "floor_id": main_floor,
            "detector": iw["detector"], "all_windows": iw["windows"]}


def _window_groups(wins: list[dict]) -> list[dict]:
    """Group windows by wall direction (normals within 35 degrees)."""
    groups: list[dict] = []
    for w in sorted(wins, key=lambda w: w["normal_deg"]):
        for g in groups:
            if _angdiff(g["normal"], w["normal_deg"]) < 35:
                g["windows"].append(w)
                vs = [math.radians(x["normal_deg"]) for x in g["windows"]]
                g["normal"] = math.degrees(math.atan2(sum(map(math.sin, vs)), sum(map(math.cos, vs)))) % 360
                break
        else:
            groups.append({"normal": w["normal_deg"], "windows": [w]})
    return groups


def _dominant_dir(segments: list[tuple[np.ndarray, np.ndarray]]) -> float:
    """Length-weighted dominant edge direction modulo 90 degrees (degrees in [0, 90))."""
    acc = np.zeros(2)
    for a, b in segments:
        d = b - a
        L = float(np.linalg.norm(d))
        if L < 0.5:
            continue
        ang = math.atan2(d[0], d[1]) * 4  # modulo 90 via angle x4
        acc += L * np.array([math.cos(ang), math.sin(ang)])
    return (math.degrees(math.atan2(acc[1], acc[0])) / 4) % 90


def _segments(poly) -> list[tuple[np.ndarray, np.ndarray]]:
    rings = [poly.exterior] + list(poly.interiors)
    out = []
    for r in rings:
        c = list(r.coords)
        out += [(np.array(c[i]), np.array(c[i + 1])) for i in range(len(c) - 1)]
    return out


# --- 1. outline fit ---------------------------------------------------------------------

def _transform(geom, theta: float, t: np.ndarray):
    from shapely import affinity
    R = _rot_cw(theta)
    return affinity.affine_transform(geom, [R[0, 0], R[0, 1], R[1, 0], R[1, 1], t[0], t[1]])


def _score(scan: dict, fp, theta: float, t: np.ndarray) -> tuple[float, float, float]:
    from shapely.geometry import Point
    world = _transform(scan["outline"], theta, t)
    inside = world.intersection(fp).area / max(world.area, 1e-6)
    wins = scan["windows"]
    if not wins:
        return inside, inside, 0.0
    R = _rot_cw(theta)
    ok = 0
    boundary = fp.boundary
    for w in wins:
        p = R @ np.array([w["x"], w["y"]]) + t
        n = R @ np.array([math.sin(math.radians(w["normal_deg"])), math.cos(math.radians(w["normal_deg"]))])
        near = boundary.distance(Point(*p)) <= EDGE_TOL_M
        outward = not fp.contains(Point(*(p + 2.0 * n))) and fp.buffer(0.5).contains(Point(*(p - 1.0 * n)))
        ok += near and outward
    wf = ok / len(wins)
    return 0.5 * inside + 0.5 * wf, inside, wf


def _translations(scan: dict, fp, theta: float) -> list[np.ndarray]:
    """Candidate translations putting window walls on footprint edges facing the same way."""
    R = _rot_cw(theta)
    segs = [(a, b) for a, b in _segments(fp) if np.linalg.norm(b - a) >= 2.0]

    def seg_normal(a, b):
        d = (b - a) / np.linalg.norm(b - a)
        n = np.array([d[1], -d[0]])  # right-hand normal; flip if it points inside
        mid = (a + b) / 2
        from shapely.geometry import Point
        if fp.contains(Point(*(mid + 1.0 * n))):
            n = -n
        return d, n

    groups = _window_groups(scan["windows"])
    cons = []  # (normal n, offset c, group) meaning n . t = c
    for g in groups:
        wn = R @ np.array([math.sin(math.radians(g["normal"])), math.cos(math.radians(g["normal"]))])
        pts = np.array([R @ np.array([w["x"], w["y"]]) for w in g["windows"]])
        depth = float(np.median(pts @ wn))
        for a, b in segs:
            d, n = seg_normal(a, b)
            if n @ wn < math.cos(math.radians(20)):
                continue
            c = float(n @ a) - WALL_OFFSET_M - depth
            cons.append((n, c, g, a, b, d))
    cands = []
    for i in range(len(cons)):
        for j in range(i + 1, len(cons)):
            n1, c1, g1 = cons[i][:3]
            n2, c2, g2 = cons[j][:3]
            if g1 is g2 or abs(n1 @ n2) > 0.5:
                continue
            A = np.array([n1, n2])
            cands.append(np.linalg.solve(A, np.array([c1, c2])))
    if not cands:  # one wall direction only: slide along each matching edge
        for n, c, g, a, b, d in cons:
            pts = np.array([R @ np.array([w["x"], w["y"]]) for w in g["windows"]])
            along = pts @ d
            L = float(np.linalg.norm(b - a))
            for s in np.arange(0, L, 1.0):
                t_along = float(a @ d) + s - float(along.min())
                cands.append(n * c + d * t_along)
    if not cands:  # no windows: centre the unit on footprint vertices
        cen = np.array(scan["outline"].centroid.coords[0])
        for a, _ in segs[:200]:
            cands.append(a - R @ cen)
    return cands


def outline_fit(scan: dict, buildings: list[dict], local: Local, top: int = 3) -> list[Hypothesis]:
    from shapely import wkt as swkt
    from shapely.geometry import Polygon

    if scan["outline"] is None:
        return []
    scan_segs = [(np.array(a), np.array(b)) for a, b in _segments(scan["outline"])]
    d_scan = _dominant_dir(scan_segs)
    hyps: list[Hypothesis] = []
    for b in buildings:
        g = swkt.loads(b["outline"])
        polys = list(g.geoms) if hasattr(g, "geoms") else [g]
        fp = None
        for p in polys:
            q = Polygon([local.to_xy(*xy) for xy in p.exterior.coords],
                        [[local.to_xy(*xy) for xy in r.coords] for r in p.interiors])
            fp = q if fp is None else fp.union(q)
        if fp is None or fp.area < 0.8 * scan["outline"].area:
            continue
        b = {**b, "_fp": fp}
        prior = PRIOR_WEIGHT * math.exp(-(b.get("distance_m") or 0.0) / PRIOR_SCALE_M)
        d_fp = _dominant_dir(_segments(fp))
        best_for_b: list[Hypothesis] = []
        for k in range(4):
            base = (d_fp - d_scan + 90 * k) % 360
            for dr in ROT_REFINE:
                theta = (base + dr) % 360
                for t in _translations(scan, fp, theta):
                    sc, ins, wf = _score(scan, fp, theta, t)
                    best_for_b.append(Hypothesis(b, theta, t, sc, ins, wf, prior=prior))
        best_for_b.sort(key=lambda h: -h.outline_score)
        # keep distinct hypotheses (rotation or position differ)
        kept: list[Hypothesis] = []
        for h in best_for_b:
            if all(_angdiff(h.theta, k_.theta) > 10 or np.linalg.norm(h.t - k_.t) > 4 for k_ in kept):
                kept.append(h)
            if len(kept) >= top:
                break
        hyps += kept
    hyps.sort(key=lambda h: (-round(h.outline_score + h.prior, 3), np.linalg.norm(h.t)))
    return hyps


# --- 2. window fingerprint ------------------------------------------------------------------

def _facade_segment(fp, p: np.ndarray, n: np.ndarray):
    """Footprint edge nearest a window point whose outward normal matches n."""
    best = None
    for a, b in _segments(fp):
        L = float(np.linalg.norm(b - a))
        if L < 2:
            continue
        d = (b - a) / L
        nn = np.array([d[1], -d[0]])
        from shapely.geometry import Point
        if fp.contains(Point(*((a + b) / 2 + nn))):
            nn = -nn
        if nn @ n < math.cos(math.radians(25)):
            continue
        s = float(np.clip((p - a) @ d, 0, L))
        dist = float(np.linalg.norm(a + d * s - p))
        if dist <= FACADE_MAX_M and (best is None or dist < best[0]):
            best = (dist, a, b, d, nn)
    return best


def _cluster_rows(items: list[dict], gap: float = 1.3) -> list[list[dict]]:
    items = sorted(items, key=lambda w: w["h"])
    rows: list[list[dict]] = []
    for w in items:
        if rows and w["h"] - np.mean([x["h"] for x in rows[-1]]) < gap:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [r for r in rows if len(r) >= 1]


def _match_pattern(inside: list[tuple[float, float]], row: list[tuple[float, float]], span: float) -> tuple[float, float]:
    """Best 1D overlap of the inside pattern slid along a row. Returns (score 0-1, offset)."""
    if not inside or not row:
        return 0.0, 0.0
    best = (0.0, 0.0)
    for off in np.arange(-span, span + 1e-9, 0.25):
        tot = 0.0
        used = 0
        for a, b in inside:
            a2, b2 = a + off, b + off
            ious = []
            for c, d in row:
                inter = max(0.0, min(b2, d) - max(a2, c))
                union = max(b2, d) - min(a2, c)
                ious.append(inter / union if union > 0 else 0.0)
            m = max(ious)
            tot += m
            used += m > 0.1
        lo = min(a for a, _ in inside) + off - 0.5
        hi = max(b for _, b in inside) + off + 0.5
        extra = sum(1 for c, d in row if c >= lo and d <= hi) - used
        score = tot / (len(inside) + max(0, extra))
        if score > best[0]:
            best = (score, off)
    return best


def _floors_for(building: dict, local: Local) -> int | None:
    """Story count for a footprint: a CoStar record inside it, else None."""
    from shapely import wkt as swkt

    from . import costar
    g = swkt.loads(building["outline"])
    poly = g if not hasattr(g, "geoms") else max(g.geoms, key=lambda p: p.area)
    pts = [(lat, lon) for lon, lat in poly.exterior.coords]
    try:
        rows = costar.properties_in_polygon(pts, [])
    except Exception:
        return None
    floors = [r["floors"] for r in rows if r.get("floors")]
    return max(floors) if floors else None


def window_fingerprint(scan: dict, h: Hypothesis, local: Local) -> None:
    """Fill h.window_score / floor / unit_offset_m / window_info (in place)."""
    from shapely.geometry import Point

    from . import vexcel as vx
    from .oblique_camera import ObliqueCamera

    fp = h.building["_fp"]
    R = _rot_cw(h.theta)
    n_floors = _floors_for(h.building, local)
    walls = []
    for g in _window_groups(scan["windows"]):
        wn = R @ np.array([math.sin(math.radians(g["normal"])), math.cos(math.radians(g["normal"]))])
        pts = [R @ np.array([w["x"], w["y"]]) + h.t for w in g["windows"]]
        centre = np.mean(pts, axis=0)
        seg = _facade_segment(fp, centre, wn)
        if seg is None:
            walls.append({"normal": round(_heading(wn), 1), "status": "window wall not on a footprint edge "
                          "(courtyard or set-back; ground footprints miss these)"})
            continue
        _, a, b, d, nn = seg
        cam_dir = (_heading(nn) + 180) % 360
        direction = min(vx.DIRECTIONS, key=lambda k: _angdiff(vx.DIRECTIONS[k], cam_dir))
        lon, lat = local.to_ll(*centre)
        area = vx.square_wkt(lat, lon, 35)
        if direction not in vx.oblique_directions(area):
            walls.append({"normal": _heading(nn), "status": f"no {direction} here"})
            continue
        det = vx.detect_oblique_windows(area, direction, threshold=0.4)
        if det["error"] or not det["boxes"]:
            walls.append({"normal": _heading(nn), "status": det["error"] or "no windows detected"})
            continue
        from PIL import Image
        with Image.open(det["image"]) as im:
            cam = ObliqueCamera(det["metadata"], im.size)
        A = np.array(cam.to_utm.transform(*local.to_ll(*a)))
        B = np.array(cam.to_utm.transform(*local.to_ll(*b)))
        L = float(np.linalg.norm(B - A))
        outside = []
        for i, bx in enumerate(det["boxes"]):
            cu, cv = bx["x"] + bx["w"] / 2, bx["y"] + bx["h"] / 2
            mid = cam.on_vertical_plane(cu, cv, A, B)
            left = cam.on_vertical_plane(bx["x"], cv, A, B)
            right = cam.on_vertical_plane(bx["x"] + bx["w"], cv, A, B)
            if not (mid and left and right):
                continue
            s, hh = mid
            if not (-1 <= s <= L + 1 and 0.5 <= hh <= 120):
                continue
            # the box must really sit on this facade: re-project and check it lands where detected
            E, N = A + (B - A) / L * s
            back = cam.project_utm(E, N, cam.ground_z + hh)
            if back is None or math.hypot(back[0] - cu, back[1] - cv) > 3:
                continue
            outside.append({"i": i, "s": s, "h": hh, "s0": min(left[0], right[0]), "s1": max(left[0], right[0]),
                            "box": bx})
        rows = _cluster_rows(outside)
        if len(rows) < 1 or max(len(r) for r in rows) < 2:
            walls.append({"normal": _heading(nn), "status": "fewer than 2 windows in any row (trees or wrong facade)",
                          "image": det["image"]})
            continue
        # inside pattern along the same facade line (local metres -> s along a->b)
        dloc = (b - a) / np.linalg.norm(b - a)
        inside = []
        for w, p in zip(g["windows"], pts):
            s = float((p - a) @ dloc)
            half = (w.get("width_m") or 1.0) / 2
            inside.append((s - half, s + half))
        span = 6.0
        scored = []
        for ri, row in enumerate(rows):
            sc, off = _match_pattern(inside, [(o["s0"], o["s1"]) for o in row], span)
            scored.append((sc, ri, off))
        sc, ri, off = max(scored)
        # floor: count rows from the top when the story count is known (ground floors are
        # often shops with no window row), else from the bottom
        row_h = [float(np.mean([o["h"] for o in r])) for r in rows]
        if n_floors:
            floor = n_floors - (len(rows) - 1 - ri)
        else:
            floor = ri + 1
        walls.append({"normal": round(_heading(nn), 1), "direction": direction, "score": round(sc, 3),
                      "row": ri + 1, "rows": len(rows), "row_heights_m": [round(x, 1) for x in row_h],
                      "floor": floor, "offset_m": round(off, 2),
                      "unit_offset_m": round(min(a_ for a_, _ in inside) + off, 2),
                      "matched": [o["i"] for o in rows[ri]], "image": det["image"], "area_wkt": area,
                      "direction_ok": True, "segment": [a.tolist(), b.tolist()],
                      "inside_intervals": [(round(x + off, 2), round(y + off, 2)) for x, y in inside],
                      "outside_row": [(round(o["s0"], 2), round(o["s1"], 2), o["i"]) for o in rows[ri]],
                      "status": "ok" if (len(rows[ri]) >= MIN_MATCHED and sc >= MIN_WALL_SCORE) else "weak match"})
    good = [w for w in walls if w.get("status") == "ok"]
    h.window_info = {"walls": walls, "n_floors": n_floors}
    if not good:
        return
    best = max(good, key=lambda w: w["score"])
    h.window_score = float(np.mean([w["score"] for w in good]))
    floors = [w["floor"] for w in good]
    h.floor = max(set(floors), key=lambda f: (floors.count(f), -abs(f - best["floor"])))
    h.unit_offset_m = best["unit_offset_m"]
    h.window_info["best"] = best


# --- 3. evidence images ---------------------------------------------------------------------

def _overlay_image(scan_id: str, scan: dict, h: Hypothesis, local: Local, rough: tuple[float, float]) -> str:
    from PIL import Image, ImageDraw

    from . import vexcel as vx
    fp = h.building["_fp"]
    cx, cy = fp.centroid.coords[0]
    x0, y0, x1, y1 = fp.bounds
    half = max(x1 - x0, y1 - y0) / 2 + 30
    lon, lat = local.to_ll(cx, cy)
    path, (L0, B0, L1, T1) = vx.ortho_square(lat, lon, half)
    im = Image.open(path).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)

    def px(x, y):
        lo, la = local.to_ll(x, y)
        return ((lo - L0) / (L1 - L0) * W, (T1 - la) / (T1 - B0) * H)
    for ring in [fp.exterior] + list(fp.interiors):
        d.line([px(*c) for c in ring.coords], fill=(255, 210, 0), width=3)
    world = _transform(scan["outline"], h.theta, h.t)
    for g in (list(world.geoms) if hasattr(world, "geoms") else [world]):
        d.polygon([px(*c) for c in g.exterior.coords], outline=(0, 255, 120), width=5)
    R = _rot_cw(h.theta)
    for w in scan["windows"]:
        p = R @ np.array([w["x"], w["y"]]) + h.t
        n = R @ np.array([math.sin(math.radians(w["normal_deg"])), math.cos(math.radians(w["normal_deg"]))])
        a, b = px(*p), px(*(p + 3 * n))
        d.line([a, b], fill=(0, 200, 255), width=4)
        d.ellipse([a[0] - 5, a[1] - 5, a[0] + 5, a[1] + 5], fill=(0, 200, 255))
    rx, ry = px(*local.to_xy(rough[1], rough[0]))
    d.ellipse([rx - 9, ry - 9, rx + 9, ry + 9], fill=(255, 0, 0), outline=(255, 255, 255), width=3)
    out = cache_dir() / "geo" / f"{scan_id}_overlay.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    im.thumbnail((1600, 1600))
    im.save(out, quality=85)
    return str(out)


def _windows_image(scan_id: str, scan: dict, h: Hypothesis) -> str | None:
    from PIL import Image, ImageDraw
    best = (h.window_info or {}).get("best")
    if not best:
        return None
    from . import vexcel as vx
    det = vx.detect_oblique_windows(best["area_wkt"], best["direction"], 0.4)
    ob = Image.open(det["image"]).convert("RGB")
    d = ImageDraw.Draw(ob)
    for i, bx in enumerate(det["boxes"]):
        on = i in best["matched"]
        d.rectangle([bx["x"], bx["y"], bx["x"] + bx["w"], bx["y"] + bx["h"]],
                    outline=(0, 255, 0) if on else (255, 0, 255), width=4 if on else 1)
    # inside view: the largest window card on that wall
    wall_wins = [w for w in scan["windows"] if _angdiff((w["normal_deg"] + h.theta) % 360, best["normal"]) < 35]
    inside = None
    if wall_wins:
        w = max(wall_wins, key=lambda w: len(w["views"]))
        v = w["best_view"]
        b = v["box"]
        im = Image.open(v["path"]).convert("RGB")
        ImageDraw.Draw(im).rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]], outline=(0, 255, 0), width=10)
        inside = im
    Hh = 700
    ob = ob.resize((round(ob.width * Hh / ob.height), Hh))
    parts = [ob] + ([inside.resize((Hh, Hh))] if inside else [])
    sheet = Image.new("RGB", (sum(p.width for p in parts) + 10 * (len(parts) - 1), Hh), "white")
    x = 0
    for p in parts:
        sheet.paste(p, (x, 0))
        x += p.width + 10
    out = cache_dir() / "geo" / f"{scan_id}_windows.jpg"
    sheet.save(out, quality=85)
    return str(out)


# --- public --------------------------------------------------------------------------------

def _quat_z(angle_ccw_deg: float) -> dict:
    half = math.radians(angle_ccw_deg) / 2
    return {"x": 0.0, "y": 0.0, "z": round(math.sin(half), 6), "w": round(math.cos(half), 6)}


def fix_scan_location(scan_id: str, rough_lat: float, rough_lon: float,
                      radius_m: float = 300) -> dict:
    """Corrected location for a scan.

    Returns the contract keys: lat, lon, heading_deg (model frame to true north), building_id,
    floor_range, error_estimate_m, evidence (image paths + the notes JSON).
    The notes file cache/geo/<scan_id>_notes.json["result"] also holds floor, unit_offset_m,
    window_match {score, matched_windows, overlay_img}, method_scores {outline, windows} and
    geocoordinates_patch (Matterport GeoCoordinate shape; output only, never sent), until
    Avishek adds them to schemas.py. floor / window_match are None when the window
    fingerprint has no evidence; floor_range then comes from CoStar unit numbers or the
    story count.
    """
    if use_stubs():  # Avishek's stub
        fix = _stub.scenario().get("geo", {}).get(scan_id)
        if fix:
            return dict(fix)
        return {"lat": rough_lat, "lon": rough_lon, "heading_deg": 0.0, "building_id": None,
                "floor_range": None, "error_estimate_m": float(radius_m), "evidence": []}
    from . import vexcel as vx

    local = Local(rough_lat, rough_lon)
    scan = scan_geometry(scan_id)
    if scan["outline"] is None:
        raise RuntimeError(f"{scan_id}: no floor plan and too few sweeps to outline the unit")
    near = vx.building_details(rough_lat, rough_lon, radius_m)
    near = [b for b in near if b.get("building_type") not in ("shed", "garage")][:12]
    hyps = outline_fit(scan, near, local, top=2)[:4]
    if not hyps:
        raise RuntimeError(f"{scan_id}: no footprint within {radius_m} m fits the unit")
    for h in hyps:
        try:
            window_fingerprint(scan, h, local)
        except Exception as e:  # keep the outline result; record why the window step failed
            h.window_info = {"error": f"{type(e).__name__}: {e}"}
    hyps.sort(key=lambda h: -h.final)
    best = hyps[0]
    second = hyps[1] if len(hyps) > 1 else None

    R = _rot_cw(best.theta)
    centroid_model = np.array(scan["outline"].centroid.coords[0])
    cx, cy = R @ centroid_model + best.t
    lon, lat = local.to_ll(cx, cy)
    olon, olat = local.to_ll(*best.t)
    from . import costar
    n_floors = (best.window_info or {}).get("n_floors")
    cs = costar.unit_floors_for_scan(scan_id)
    floor_source = None
    if best.floor is not None:
        floor_range, floor_source = [best.floor, best.floor], "window fingerprint"
    elif cs["floors"]:
        floor_range, floor_source = [cs["floors"][0], cs["floors"][-1]], f"CoStar unit numbers ({cs['level']} level)"
    else:
        n = n_floors or cs.get("building_floors")
        floor_range, floor_source = ([1, n], "story count") if n else ([1, 1], "unknown")

    # error estimate: spread of hypotheses that score almost as well, floor of 3 m
    close = [h for h in hyps if h.final >= best.final - 0.05 and h.building["building_id"] == best.building["building_id"]]
    spread = max((float(np.linalg.norm(h.t - best.t)) for h in close), default=0.0)
    err = max(3.0 if best.window_score else 6.0, spread)

    evidence = [_overlay_image(scan_id, scan, best, local, (rough_lat, rough_lon))]
    wimg = _windows_image(scan_id, scan, best)
    if wimg:
        evidence.append(wimg)
    agree = second is None or second.building["building_id"] == best.building["building_id"]
    notes = {"confidence": "High" if (best.window_score and best.window_score >= 0.5 and agree) else
             "Medium" if best.final >= 0.6 else "Low",
             "hypotheses": [{"building_id": h.building["building_id"], "heading_deg": round(h.theta, 1),
                             "outline": round(h.outline_score, 3), "inside_frac": round(h.inside_frac, 3),
                             "windows_on_facade": round(h.win_frac, 3), "windows": h.window_score,
                             "floor": h.floor, "prior": round(h.prior, 3), "final": round(h.final, 3),
                             "walls": [{k: w.get(k) for k in ("normal", "status", "score", "floor")}
                                       for w in (h.window_info or {}).get("walls", [])]} for h in hyps],
             "outline_source": scan["outline_source"], "inside_windows": len(scan["windows"]),
             "floor_source": floor_source, "costar_unit_floors": cs["floors"],
             "walls": (best.window_info or {}).get("walls"), "window_error": (best.window_info or {}).get("error")}
    notes_path = cache_dir() / "geo" / f"{scan_id}_notes.json"
    notes_path.write_text(json.dumps(notes, indent=1, default=str))
    evidence.append(str(notes_path))

    wbest = (best.window_info or {}).get("best")
    full = {
        "lat": round(lat, 7), "lon": round(lon, 7),
        "heading_deg": round(best.theta % 360, 1),
        "building_id": best.building["building_id"],
        "floor_range": [int(floor_range[0]), int(floor_range[1])],
        "floor": best.floor,
        "unit_offset_m": best.unit_offset_m,
        "window_match": None if best.window_score is None else {
            "score": round(best.window_score, 3), "matched_windows": len(wbest["matched"]) if wbest else 0,
            "overlay_img": wimg},
        "method_scores": {"outline": round(best.outline_score, 3),
                          "windows": None if best.window_score is None else round(best.window_score, 3)},
        "error_estimate_m": round(err, 1),
        "evidence": evidence,
        "geocoordinates_patch": {
            "latitude": round(olat, 8), "longitude": round(olon, 8),
            # model -> ENU rotation about +Z, counter-clockwise = minus our clockwise heading;
            # sign convention vs Matterport still to confirm on a scan with trusted geocoordinates
            "rotation": _quat_z(-best.theta),
            "translation": {"x": 0.0, "y": 0.0, "z": 0.0},
        },
    }
    # Contract keys only until Avishek adds the rest to schemas.py; everything else is
    # kept in the notes file (also listed in evidence).
    notes["result"] = full
    notes_path.write_text(json.dumps(notes, indent=1, default=str))
    return {k: full[k] for k in CONTRACT_KEYS}
