"""Unique windows of a scanned unit, seen from inside.

1. Detect candidate boxes on every sweep's four side faces (OWL-ViT "window",
   or the simple heuristic without torch).
2. Keep a box only if CLIP calls it a window / glass door (window_probability) or the
   floor plan shows scanner specks just beyond the wall it points at.
3. Cast rays from the sweep through the box centre and edges to the unit boundary
   on the floor plan. Boxes from different sweeps that hit the same wall spot are the
   same window, so they are merged into one (IW1, IW2, ...).

Without a floor plan, step 3 is skipped and boxes that pass step 2 are listed per view.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import floorplan as fpm
from . import matterport as mp
from .windows import detect_windows_best

MERGE_M = 0.9           # hits closer than this on a similar wall = same window
MAX_DIST_M = 12.0
CONTRAST_MIN, EDGES_MIN, DARK_MIN, SPLAT_MIN = 56.0, 0.12, 0.09, 0.12


def looks_outdoor(img: np.ndarray, box: dict) -> tuple[bool, dict]:
    """Does the box show the outdoors? Real windows hold a detailed, high-contrast
    scene (buildings, trees, sky) and dark frames; doors, closets, mirrors and light
    strips are flat and pale. Thresholds set on 25 hand-labelled boxes from scan
    6WjHU7zCbLh (true min contrast 57, false max 55): re-check on more scans.
    """
    x0, y0 = int(box["x"]), int(box["y"])
    x1, y1 = int(box["x"] + box["w"]), int(box["y"] + box["h"])
    mx, my = (x1 - x0) // 10, (y1 - y0) // 10        # inner 80%: skip frame edges
    roi = img[y0 + my:y1 - my, x0 + mx:x1 - mx]
    if roi.size == 0 or roi.shape[0] < 4 or roi.shape[1] < 4:
        return False, {}
    roi = cv2.resize(roi, (128, max(4, int(128 * roi.shape[0] / roi.shape[1]))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    contrast = float(gray.std())
    edges = float((cv2.Canny(gray, 60, 150) > 0).mean())
    dark = float((gray < 60).mean())
    ok = contrast >= CONTRAST_MIN and (edges >= EDGES_MIN or dark >= DARK_MIN)
    return ok, {"contrast": round(contrast, 1), "edges": round(edges, 3), "dark": round(dark, 3)}


CLIP_MODEL = "openai/clip-vit-base-patch32"
WINDOW_LABELS = ["a window with a view of the outdoors", "a glass door to a balcony or patio"]
OTHER_LABELS = ["a closed interior door", "a mirror", "an open closet", "an air vent on a wall or ceiling",
                "a kitchen cabinet", "a refrigerator", "a lamp or light fixture", "a blank white wall",
                "a shower or bathtub", "a picture frame or artwork", "a doorway into another room"]
WINDOW_P_MIN = 0.5
_clip = None


def _load_clip():
    global _clip
    if _clip is None:
        from transformers import CLIPModel, CLIPProcessor
        _clip = (CLIPProcessor.from_pretrained(CLIP_MODEL), CLIPModel.from_pretrained(CLIP_MODEL).eval())
    return _clip


def window_probability(img: np.ndarray, box: dict) -> float:
    """CLIP zero-shot: probability the crop is a window/glass door rather than a door,
    mirror, closet, vent, cabinet, fridge, lamp, wall, shower, artwork or doorway.
    Replaces a contrast threshold that did not carry over between scans."""
    import torch
    from PIL import Image
    x0, y0 = max(0, int(box["x"])), max(0, int(box["y"]))
    x1, y1 = int(box["x"] + box["w"]), int(box["y"] + box["h"])
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.0
    pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    proc, model = _load_clip()
    with torch.no_grad():
        inp = proc(text=WINDOW_LABELS + OTHER_LABELS, images=pil, return_tensors="pt", padding=True)
        probs = model(**inp).logits_per_image.softmax(dim=-1)[0]
    return float(probs[: len(WINDOW_LABELS)].sum())


def _window_p_cached(path: str, img: np.ndarray, box: dict) -> float:
    import os
    from ._common import cached_json
    st = os.stat(path)
    key = ["clip_window", CLIP_MODEL, path, st.st_size, int(st.st_mtime), box["x"], box["y"], box["w"], box["h"]]
    return cached_json("windows", key, lambda: round(window_probability(img, box), 4))


def _angle(px: float, width: float) -> float:
    """Horizontal angle (deg, + = right) of an image column in a 90-degree cube face."""
    return math.degrees(math.atan((px - width / 2) / (width / 2)))


def unique_windows(scan_id: str) -> dict:
    """Returns {"windows": [...], "rejected": n, "detector": str, "has_floorplan": bool}.

    Each window: id, x, y (model m), normal_deg (outward, model heading), width_m,
    splatter, outdoor (bool), views: [{sweep_id, face, box, heading, dist_m}],
    best_view (one of views).
    """
    plans = fpm.load(scan_id)
    sweeps = {s["id"]: s for s in mp._panos(scan_id)}
    dets, rejected, method = [], 0, "none"
    for f in mp.face_paths(scan_id):
        boxes, method = detect_windows_best(f["path"])
        if not boxes:
            continue
        img = cv2.imread(f["path"])
        W = img.shape[1]
        face_h = mp.face_heading(f["rotation"], f["face"])
        sw = sweeps.get(f["sweep_id"]) or {}
        pos = sw.get("position") or {}
        plan = plans.get((sw.get("floor") or {}).get("id"))
        for b in boxes:
            # a window on a wall at eye level crosses the horizon line of the face
            if not (b["y"] < 0.62 * W and b["y"] + b["h"] > 0.40 * W):
                rejected += 1
                continue
            _, stats = looks_outdoor(img, b)          # kept as diagnostics only
            pw = _window_p_cached(f["path"], img, b)
            stats["window_p"] = pw
            outdoor = pw >= WINDOW_P_MIN
            hc = (face_h + _angle(b["x"] + b["w"] / 2, W)) % 360
            hit = left = right = None
            if plan is not None and pos:
                hit = plan.cast(pos["x"], pos["y"], hc, MAX_DIST_M)
                left = plan.cast(pos["x"], pos["y"], (face_h + _angle(b["x"], W)) % 360, MAX_DIST_M)
                right = plan.cast(pos["x"], pos["y"], (face_h + _angle(b["x"] + b["w"], W)) % 360, MAX_DIST_M)
            splat = hit.splatter if hit else 0.0
            if plan is not None and hit is None:
                rejected += 1
                continue
            if not (outdoor or splat >= SPLAT_MIN):
                rejected += 1
                continue
            width = math.hypot(left.x - right.x, left.y - right.y) if (left and right) else None
            dets.append({"sweep_id": f["sweep_id"], "face": f["face"], "path": f["path"], "box": b,
                         "heading": round(hc, 1), **stats,
                         "outdoor": outdoor, "hit": hit, "width": width, "floor_id": (sw.get("floor") or {}).get("id")})

    # merge views of the same window
    clusters: list[list[dict]] = []
    for d in sorted(dets, key=lambda d: -(d["box"]["w"] * d["box"]["h"])):
        h = d["hit"]
        for c in clusters:
            r = c[0]["hit"]
            if h is None or r is None or d["floor_id"] != c[0]["floor_id"]:
                continue
            ang = abs((h.normal_deg - r.normal_deg + 180) % 360 - 180)
            if math.hypot(h.x - r.x, h.y - r.y) < MERGE_M and ang < 45:
                c.append(d)
                break
        else:
            clusters.append([d])

    windows = []
    for c in clusters:
        hits = [d["hit"] for d in c if d["hit"]]
        if hits:
            x = float(np.median([h.x for h in hits]))
            y = float(np.median([h.y for h in hits]))
            nrm = math.degrees(math.atan2(sum(math.sin(math.radians(h.normal_deg)) for h in hits),
                                          sum(math.cos(math.radians(h.normal_deg)) for h in hits))) % 360
            splat = max(h.splatter for h in hits)
        else:
            x = y = nrm = None
            splat = 0.0
        widths = [d["width"] for d in c if d["width"]]
        best = c[0]  # largest box
        windows.append({
            "x": x, "y": y, "normal_deg": None if nrm is None else round(nrm, 1),
            "width_m": round(float(np.median(widths)), 2) if widths else None,
            "splatter": round(splat, 3), "outdoor": any(d["outdoor"] for d in c),
            "floor_id": best["floor_id"],
            "views": [{"sweep_id": d["sweep_id"], "face": d["face"], "box": d["box"], "heading": d["heading"],
                       "dist_m": round(d["hit"].dist, 2) if d["hit"] else None, "path": d["path"]} for d in c],
        })
        windows[-1]["best_view"] = windows[-1]["views"][0]
    # stable order: by wall direction, then position along it
    windows.sort(key=lambda w: (w["normal_deg"] is None, round((w["normal_deg"] or 0) / 30), w["x"] or 0, w["y"] or 0))
    for i, w in enumerate(windows, 1):
        w["id"] = f"IW{i}"
    return {"windows": windows, "rejected": rejected, "detector": method, "has_floorplan": bool(plans)}
