"""Camera model for Vexcel oblique images (from elements/detect metadata).

Fitted with scripts/fit_oblique_camera.py on 12 Houston obliques (all four
directions): projecting each image's ground footprint ("geometry" at ground-z)
lands on the raster corners within ~10 px, with far ground at the top.

    world (UTM E, N, Z) -> camera:  Xc = M (P - C),   M = (Rx(omega) Ry(phi) Rz(kappa))^T
    image plane (mm):               x = -f Xc/Zc,  y = -f Yc/Zc
    full raster pixel:              col = W/2 + (x + pp0x)/ps,  row = H/2 - (y + pp0y)/ps
    crop pixel (returned image):    (col - bx, row - by) * (returned size / bbox size)

Angles are radians; camera position and ground-z are metres (UTM zone from metadata).
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

REQUIRED = ("camera-pos-x", "camera-pos-y", "camera-pos-z", "omega", "phi", "kappa", "focal-length",
            "pixel-size", "raster-size-width", "raster-size-height", "pixel-bbox", "width", "height",
            "utm-zone", "ground-z")


def _rot(axis: str, a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return {"x": np.array([[1, 0, 0], [0, c, -s], [0, s, c]]),
            "y": np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]),
            "z": np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])}[axis]


@lru_cache(maxsize=8)
def _transformers(zone: str):
    from pyproj import Transformer
    epsg = f"EPSG:{32600 + int(zone[:-1])}" if zone.upper().endswith("N") else f"EPSG:{32700 + int(zone[:-1])}"
    return (Transformer.from_crs("EPSG:4326", epsg, always_xy=True),
            Transformer.from_crs(epsg, "EPSG:4326", always_xy=True))


class ObliqueCamera:
    def __init__(self, meta: dict, image_size: tuple[int, int] | None = None):
        missing = [k for k in REQUIRED if meta.get(k) is None]
        if missing:
            raise ValueError(f"camera metadata missing {missing}")
        self.m = meta
        self.C = np.array([meta["camera-pos-x"], meta["camera-pos-y"], meta["camera-pos-z"]], float)
        A = _rot("x", meta["omega"]) @ _rot("y", meta["phi"]) @ _rot("z", meta["kappa"])
        self.M = A.T                       # world -> camera
        self.f, self.ps = meta["focal-length"], meta["pixel-size"]
        self.ppx, self.ppy = meta.get("pp0-x") or 0.0, meta.get("pp0-y") or 0.0
        self.W, self.H = meta["raster-size-width"], meta["raster-size-height"]
        bx, by, bw, bh = (float(v) for v in str(meta["pixel-bbox"]).split(","))
        self.bx, self.by = bx, by
        iw, ih = image_size or (meta["width"], meta["height"])
        self.sx, self.sy = iw / bw, ih / bh
        self.ground_z = float(meta["ground-z"])
        self.to_utm, self.to_ll = _transformers(meta["utm-zone"])

    # world -> image
    def project_utm(self, E: float, N: float, Z: float) -> tuple[float, float] | None:
        Xc = self.M @ (np.array([E, N, Z]) - self.C)
        if Xc[2] >= 0:                     # behind the camera
            return None
        x, y = -self.f * Xc[0] / Xc[2], -self.f * Xc[1] / Xc[2]
        col = self.W / 2 + (x + self.ppx) / self.ps
        row = self.H / 2 - (y + self.ppy) / self.ps
        return (col - self.bx) * self.sx, (row - self.by) * self.sy

    def project_lonlat(self, lon: float, lat: float, height_above_ground: float = 0.0):
        E, N = self.to_utm.transform(lon, lat)
        return self.project_utm(E, N, self.ground_z + height_above_ground)

    # image -> world
    def ray(self, u: float, v: float) -> tuple[np.ndarray, np.ndarray]:
        """Camera centre and unit direction (UTM) through crop pixel (u, v)."""
        col, row = u / self.sx + self.bx, v / self.sy + self.by
        x = (col - self.W / 2) * self.ps - self.ppx
        y = (self.H / 2 - row) * self.ps - self.ppy
        d = self.M.T @ np.array([x, y, -self.f])
        return self.C.copy(), d / np.linalg.norm(d)

    def on_vertical_plane(self, u: float, v: float, p0: np.ndarray, p1: np.ndarray):
        """Intersect the pixel's ray with the vertical plane through UTM points p0->p1 (E, N).

        Returns (s, h): metres along p0->p1 from p0, and metres above ground; None if parallel.
        """
        C, d = self.ray(u, v)
        t_dir = np.array([p1[0] - p0[0], p1[1] - p0[1]], float)
        L = float(np.linalg.norm(t_dir))
        if L == 0:
            return None
        t_dir /= L
        n = np.array([-t_dir[1], t_dir[0]])
        denom = n @ d[:2]
        if abs(denom) < 1e-9:
            return None
        lam = n @ (np.asarray(p0[:2]) - C[:2]) / denom
        P = C + lam * d
        s = float(t_dir @ (P[:2] - np.asarray(p0[:2])))
        return s, float(P[2] - self.ground_z)
