"""Perspective views from Matterport cube faces, and ad-style degradations.

Pano-local frame (matches matterport.face_heading): side face k (1..4) looks along local
azimuth 90 * (k - 1), clockwise seen from above; face 0 = up, face 5 = down. A side face
image has x to the right and y down; a ray d hits side face k at
    x = (d . right_k) / (d . fwd_k),  y = (d . down) / (d . fwd_k).
The up/down faces' in-plane orientation is not documented: `UP_ORIENT` / `DOWN_ORIENT`
were chosen by matching their edges to the side faces (scripts/check_cube_faces.py).

Used to render the synthetic "ad photos" for Ring A and decoy D. Photos contain no people:
grey person-shaped silhouettes only.
"""
from __future__ import annotations

import math
import zlib

import cv2
import numpy as np

RENDER_SEED = 37   # fixed seed of the index / holdout sweep split (scripts/render_photos.py)


def split_sweeps(scan_id: str, seed: int = RENDER_SEED) -> tuple[list[str], list[str]]:
    """(INDEX, HOLDOUT) sweep ids. Ad photos are rendered only from HOLDOUT sweeps and
    room_match searches only INDEX sweeps, so a photo is never matched to the pano it was cut
    from. Alternates within each room (shuffled with the seed); a room with one sweep keeps it
    in the index so the room stays searchable."""
    from . import matterport as mp
    rng = np.random.default_rng(seed + zlib.crc32(scan_id.encode()))
    rooms: dict[str, list[str]] = {}
    for loc in mp._panos(scan_id):
        if not any(len(((p.get("skybox") or {}).get("children")) or []) >= 6 for p in loc.get("panos") or []):
            continue
        rooms.setdefault((loc.get("room") or {}).get("id") or "?", []).append(loc["id"])
    index, hold = [], []
    for rid in sorted(rooms):
        ids = sorted(rooms[rid])
        rng.shuffle(ids)
        for i, s in enumerate(ids):
            (index if (i % 2 == 0 or len(ids) == 1) else hold).append(s)
    return sorted(index), sorted(hold)

# (swap_xy, flip_x, flip_y) applied to (u, v) = projections on the up/down face's
# (local +X, local +Y) axes; fitted by scripts/check_cube_faces.py
UP_ORIENT = (False, False, False)
DOWN_ORIENT = (False, False, True)


def _dirs(width: int, height: int, hfov_deg: float, yaw_deg: float, pitch_deg: float, roll_deg: float = 0.0):
    """Unit ray directions (H, W, 3) in the pano-local frame (x right of front, y front, z up)."""
    f = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    xs = (np.arange(width) + 0.5 - width / 2) / f
    ys = (np.arange(height) + 0.5 - height / 2) / f
    X, Y = np.meshgrid(xs, ys)
    # camera frame: right, down, forward
    cam = np.stack([X, Y, np.ones_like(X)], -1)
    cam /= np.linalg.norm(cam, axis=-1, keepdims=True)
    r, p, yw = (math.radians(a) for a in (roll_deg, pitch_deg, yaw_deg))
    # roll about forward
    cr, sr = math.cos(r), math.sin(r)
    cam = cam @ np.array([[cr, sr, 0], [-sr, cr, 0], [0, 0, 1]]).T
    # camera axes in the local frame after pitch (up positive) and yaw (clockwise)
    fwd = np.array([math.sin(yw) * math.cos(p), math.cos(yw) * math.cos(p), math.sin(p)])
    right = np.array([math.cos(yw), -math.sin(yw), 0.0])
    down = np.cross(fwd, right)            # right x fwd = up, so fwd x right = down
    return cam[..., :1] * right + cam[..., 1:2] * down + cam[..., 2:3] * fwd


def _uv_cap(d: np.ndarray, sign: float, orient):
    """Projection of rays onto the up (sign=+1) or down (sign=-1) face, as pixel fractions in [-1, 1]."""
    z = d[..., 2] * sign
    u = d[..., 0] / z
    v = d[..., 1] / z
    swap, fx, fy = orient
    if swap:
        u, v = v, u
    if fx:
        u = -u
    if fy:
        v = -v
    return u, v


def perspective(faces: dict[int, np.ndarray], width: int, height: int, hfov_deg: float,
                yaw_deg: float, pitch_deg: float, roll_deg: float = 0.0) -> np.ndarray:
    """Render a perspective view from six cube faces {0..5: BGR image} (side faces required)."""
    d = _dirs(width, height, hfov_deg, yaw_deg, pitch_deg, roll_deg)
    out = np.zeros((height, width, 3), np.uint8)
    ax, ay, az = np.abs(d[..., 0]), np.abs(d[..., 1]), np.abs(d[..., 2])
    side = az < np.maximum(ax, ay)
    azim = (np.degrees(np.arctan2(d[..., 0], d[..., 1])) + 360) % 360
    k = (np.round(azim / 90).astype(int) % 4) + 1
    for face in (1, 2, 3, 4):
        m = side & (k == face)
        if not m.any() or face not in faces:
            continue
        c = math.radians(90 * (face - 1))
        fwd = np.array([math.sin(c), math.cos(c), 0.0])
        right = np.array([math.cos(c), -math.sin(c), 0.0])
        df = d @ fwd
        x = (d @ right) / df
        y = (-d[..., 2]) / df
        _sample(out, faces[face], m, x, y)
    for face, sign, orient in ((0, 1.0, UP_ORIENT), (5, -1.0, DOWN_ORIENT)):
        m = (~side) & (np.sign(d[..., 2]) == sign)
        if not m.any() or face not in faces:
            continue
        u, v = _uv_cap(d, sign, orient)
        _sample(out, faces[face], m, u, v)
    return out


def _sample(out: np.ndarray, img: np.ndarray, mask: np.ndarray, x: np.ndarray, y: np.ndarray) -> None:
    h, w = img.shape[:2]
    mapx = ((x + 1) / 2 * w - 0.5).astype(np.float32)
    mapy = ((y + 1) / 2 * h - 0.5).astype(np.float32)
    s = cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    out[mask] = s[mask]


# --- ad-style degradations -----------------------------------------------------------------

def _silhouette(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Paste a flat grey, featureless person silhouette (head, neck, shoulders, arms, torso,
    legs cut by the frame) at one side of the frame."""
    h, w = img.shape[:2]
    out = img.copy()
    H = h * rng.uniform(0.75, 1.15)                 # full-figure height in pixels
    cx = rng.choice([rng.uniform(0.04, 0.28), rng.uniform(0.72, 0.96)]) * w
    top = h - H * rng.uniform(0.62, 0.85)           # the frame cuts the legs
    u = H / 8.0                                     # head-height unit
    grey = int(rng.uniform(95, 150))
    mask = np.zeros((h, w), np.uint8)
    P = lambda pts: np.array([[cx + x * u, top + y * u] for x, y in pts], np.int32)  # noqa: E731
    cv2.ellipse(mask, (int(cx), int(top + 0.5 * u)), (int(0.38 * u), int(0.5 * u)), 0, 0, 360, 255, -1)  # head
    cv2.fillPoly(mask, [P([(-0.17, 0.85), (0.17, 0.85), (0.2, 1.2), (-0.2, 1.2)])], 255)                    # neck
    torso = [(-1.0, 1.35), (-0.75, 1.15), (0.75, 1.15), (1.0, 1.35), (0.85, 3.2), (0.7, 4.1),
             (-0.7, 4.1), (-0.85, 3.2)]
    cv2.fillPoly(mask, [P(torso)], 255)
    for sgn in (-1, 1):                                                                                     # arms
        cv2.fillPoly(mask, [P([(sgn * 0.95, 1.3), (sgn * 1.2, 1.5), (sgn * 1.15, 3.8), (sgn * 0.85, 3.9),
                               (sgn * 0.8, 1.6)])], 255)
    cv2.fillPoly(mask, [P([(-0.7, 4.0), (0.7, 4.0), (0.6, 8.0), (0.05, 8.0), (0.0, 4.6), (-0.05, 8.0),
                           (-0.6, 8.0)])], 255)                                                             # legs
    mask = cv2.GaussianBlur(mask, (0, 0), 1.5)
    a = (mask.astype(np.float32) / 255.0)[..., None] * 0.95
    out = (out * (1 - a) + np.full_like(out, grey) * a).astype(np.uint8)
    return out


def degrade(img: np.ndarray, rng: np.random.Generator, silhouette: bool) -> tuple[np.ndarray, dict]:
    """Phone-photo look: low light, colour cast, blur, noise, optional silhouette.
    Returns (image, the parameters used)."""
    p = {"gain": round(float(rng.uniform(0.45, 0.85)), 2), "gamma": round(float(rng.uniform(1.05, 1.6)), 2),
         "warm": round(float(rng.uniform(-0.12, 0.18)), 3), "blur": round(float(rng.uniform(0.4, 1.6)), 2),
         "noise": round(float(rng.uniform(3, 10)), 1), "silhouette": bool(silhouette)}
    x = img.astype(np.float32) / 255.0
    x = np.power(np.clip(x * p["gain"], 0, 1), p["gamma"])
    x[..., 2] *= 1 + p["warm"]            # red
    x[..., 0] *= 1 - p["warm"]            # blue
    x = np.clip(x * 255, 0, 255).astype(np.uint8)
    if rng.random() < 0.3:                # slight motion blur
        k = int(rng.integers(5, 11))
        ker = np.zeros((k, k), np.float32)
        ker[k // 2, :] = 1.0 / k
        M = cv2.getRotationMatrix2D((k / 2, k / 2), float(rng.uniform(0, 180)), 1.0)
        x = cv2.filter2D(x, -1, cv2.warpAffine(ker, M, (k, k)))
        p["motion_blur"] = k
    x = cv2.GaussianBlur(x, (0, 0), p["blur"])
    x = np.clip(x.astype(np.float32) + rng.normal(0, p["noise"], x.shape), 0, 255).astype(np.uint8)
    if silhouette:
        x = _silhouette(x, rng)
    return x, p


def encode_jpeg(img: np.ndarray, quality: int) -> bytes:
    """JPEG bytes with no metadata (cv2 writes no EXIF)."""
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()
