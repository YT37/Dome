"""Floor plan geometry for a Matterport scan (model frame, metres).

The Matterport floor plan raster ("colorplan", photogrammetric) has a flat dark
background. Mapping (checked against sweep room tags):
    px = (x - origin.x) * resolution,   py = height - (y - origin.y) * resolution
so +Y in the model is up in the image.

Used for: the unit's interior mask, casting a ray from a sweep to the wall it
hits, and "splatter": specks the scanner captured through glass, which land in
the background just beyond exterior walls that have windows.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from . import matterport as mp
from ._common import cached_file


def best_floorplans(scan_id: str) -> list[dict]:
    """One floor plan per floor: the jpg with the highest resolution."""
    best: dict[str, dict] = {}
    for f in mp.floorplans(scan_id):
        fid = (f.get("floor") or {}).get("id") or "?"
        score = (f.get("format") == "jpg", f.get("resolution") or 0, f.get("width") or 0)
        if fid not in best or score > best[fid]["_score"]:
            best[fid] = {**f, "_score": score}
    return sorted(best.values(), key=lambda f: ((f.get("floor") or {}).get("sequence") or 0))


def floorplan_file(scan_id: str, fp: dict) -> str:
    """Download (cached) a floor plan image; re-queries if the signed URL expired."""
    import requests

    def fetch():
        r = requests.get(fp["url"], timeout=90)
        if r.status_code in (403, 410):
            fid = (fp.get("floor") or {}).get("id")
            fresh = next((f for f in mp.floorplans(scan_id, refresh=True)
                          if (f.get("floor") or {}).get("id") == fid and f.get("format") == fp.get("format")
                          and f.get("width") == fp.get("width")), None)
            if fresh is None:
                r.raise_for_status()
            r = requests.get(fresh["url"], timeout=90)
        r.raise_for_status()
        return r.content
    key = ["floorplan", scan_id, (fp.get("floor") or {}).get("id"), fp.get("format"), fp.get("width"), fp.get("height")]
    return str(cached_file("matterport_fp", key, fp.get("format") or "jpg", fetch))


@dataclass
class RayHit:
    x: float              # exit point on the unit boundary (model metres)
    y: float
    dist: float           # metres from the sweep
    normal_deg: float     # outward wall normal, heading clockwise from +Y
    splatter: float       # 0-1, scanner specks found just beyond the wall


class FloorPlan:
    def __init__(self, scan_id: str, fp: dict, sweep_xy: list[tuple[float, float]]):
        self.scan_id, self.meta = scan_id, fp
        self.image_path = floorplan_file(scan_id, fp)
        img = cv2.imread(self.image_path)
        self.H, self.W = img.shape[:2]
        sc = self.W / fp["width"] if fp.get("width") else 1.0
        self.R = fp["resolution"] * sc            # px per metre in this image
        self.ox, self.oy = fp["origin"]["x"], fp["origin"]["y"]
        border = np.concatenate([img[:4].reshape(-1, 3), img[-4:].reshape(-1, 3)]).astype(np.float32)
        bg = np.median(border, axis=0)
        dist = np.linalg.norm(img.astype(np.float32) - bg, axis=2)
        content = (dist > 28).astype(np.uint8)
        self.content = content                    # anything the scanner captured
        k = max(3, int(0.2 * self.R)) | 1
        closed = cv2.morphologyEx(content, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        n, lab = cv2.connectedComponents(closed, 8)
        keep = set()
        for x, y in sweep_xy:
            px, py = self.to_px(x, y)
            if 0 <= px < self.W and 0 <= py < self.H and lab[int(py), int(px)] > 0:
                keep.add(int(lab[int(py), int(px)]))
        unit = np.isin(lab, list(keep)).astype(np.uint8) if keep else closed
        # fill holes (furniture gaps) so only the outer boundary counts
        cnts, _ = cv2.findContours(unit, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        filled = np.zeros_like(unit)
        cv2.drawContours(filled, cnts, -1, 1, thickness=cv2.FILLED)
        self.unit = filled
        self.splat = (content > 0) & (filled == 0)  # specks outside the unit
        blur = cv2.GaussianBlur(filled.astype(np.float32), (0, 0), max(1.0, 0.15 * self.R))
        self.gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=5)
        self.gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=5)

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.ox) * self.R, self.H - (y - self.oy) * self.R

    def to_model(self, px: float, py: float) -> tuple[float, float]:
        return self.ox + px / self.R, self.oy + (self.H - py) / self.R

    def outline_polygon(self, simplify_m: float = 0.15):
        """The unit's outer boundary as a shapely Polygon in model metres."""
        from shapely.geometry import Polygon
        cnts, _ = cv2.findContours(self.unit, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not cnts:
            return None
        c = max(cnts, key=cv2.contourArea)
        c = cv2.approxPolyDP(c, simplify_m * self.R, True)
        pts = [self.to_model(float(p[0][0]), float(p[0][1])) for p in c]
        if len(pts) < 3:
            return None
        poly = Polygon(pts)
        return poly if poly.is_valid else poly.buffer(0)

    def cast(self, x: float, y: float, heading_deg: float, max_m: float = 20.0) -> RayHit | None:
        """March from (x, y) along heading until leaving the unit. None if it never does."""
        h = math.radians(heading_deg)
        dx, dy = math.sin(h), math.cos(h)          # model frame
        step = 1.0 / self.R                         # one pixel
        px0, py0 = self.to_px(x, y)
        if not (0 <= px0 < self.W and 0 <= py0 < self.H) or not self.unit[int(py0), int(px0)]:
            return None
        n = int(max_m / step)
        for i in range(1, n):
            px, py = self.to_px(x + dx * i * step, y + dy * i * step)
            if not (0 <= px < self.W and 0 <= py < self.H) or not self.unit[int(py), int(px)]:
                ex, ey = x + dx * (i - 1) * step, y + dy * (i - 1) * step
                return RayHit(ex, ey, (i - 1) * step, self._normal(px, py, heading_deg),
                              self._splatter(ex, ey, dx, dy))
        return None

    def _normal(self, px: float, py: float, fallback_deg: float) -> float:
        ix = int(min(max(px, 0), self.W - 1))
        iy = int(min(max(py, 0), self.H - 1))
        gx, gy = -float(self.gx[iy, ix]), -float(self.gy[iy, ix])  # points out of the unit (image coords)
        if abs(gx) + abs(gy) < 1e-6:
            return fallback_deg % 360
        # image (gx right, gy down) -> model (x right, y up)
        return math.degrees(math.atan2(gx, -gy)) % 360

    def _splatter(self, ex: float, ey: float, dx: float, dy: float) -> float:
        """Share of samples 0.3-3 m beyond the wall (±0.3 m sideways) that hold scanner specks."""
        hits = total = 0
        for d in np.arange(0.3, 3.0, 0.05):
            for s in (-0.3, -0.15, 0.0, 0.15, 0.3):
                x = ex + dx * d - dy * s
                y = ey + dy * d + dx * s
                px, py = self.to_px(x, y)
                if 0 <= px < self.W and 0 <= py < self.H:
                    total += 1
                    hits += bool(self.splat[int(py), int(px)])
        return hits / total if total else 0.0


def load(scan_id: str) -> dict[str, FloorPlan]:
    """FloorPlan per Matterport floor id (empty if the scan has no floor plan)."""
    sweeps = mp._panos(scan_id)
    out = {}
    for fp in best_floorplans(scan_id):
        fid = (fp.get("floor") or {}).get("id")
        xy = [(s["position"]["x"], s["position"]["y"]) for s in sweeps
              if (s.get("floor") or {}).get("id") == fid and s.get("position")]
        try:
            out[fid] = FloorPlan(scan_id, fp, xy)
        except Exception:
            continue
    return out
