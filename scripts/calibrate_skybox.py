"""Fit how Matterport skybox side faces map to model-frame headings.

Hypothesis: side face k (1..4) of a pano looks along model heading
    H_k = s * pano_yaw + o * 90 * (k - 1) + c        (degrees, clockwise from model +Y)
with s, o in {+1, -1} and offset c. For every pair of nearby sweeps we match SIFT
features between all side faces, turn them into rays in the model frame under each
hypothesis, and count matches that satisfy the epipolar (coplanarity) constraint
with the KNOWN baseline from the sweep positions. The right hypothesis gives a sharp
peak. No pose estimation, so it is robust to small baselines.

Usage: python scripts/calibrate_skybox.py <scan_id> [<scan_id> ...]
"""
import math
import sys
from itertools import product
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dome.data_tools import matterport as mp  # noqa: E402

SIZE = 768
F = SIZE / 2
sift = cv2.SIFT_create(3000)
_feat = {}
EPS = 0.004  # |m_b . (t x m_a)| threshold (unit vectors), about 0.25 degrees


def feats(path):
    if path not in _feat:
        img = cv2.resize(cv2.imread(path, cv2.IMREAD_GRAYSCALE), (SIZE, SIZE))
        _feat[path] = sift.detectAndCompute(img, None)
    return _feat[path]


def matches(pa, pb):
    ka, da = feats(pa)
    kb, db = feats(pb)
    if da is None or db is None or len(ka) < 10 or len(kb) < 10:
        return np.zeros((0, 2)), np.zeros((0, 2))
    m = cv2.BFMatcher().knnMatch(da, db, k=2)
    good = [a for a, b in (x for x in m if len(x) == 2) if a.distance < 0.7 * b.distance]
    A = np.float32([ka[g.queryIdx].pt for g in good]).reshape(-1, 2)
    B = np.float32([kb[g.trainIdx].pt for g in good]).reshape(-1, 2)
    return A, B


def cam_rays(px):
    """Pixels -> unit rays in face camera coords (x right, y down, z forward)."""
    x = (px[:, 0] - SIZE / 2) / F
    y = (px[:, 1] - SIZE / 2) / F
    v = np.stack([x, y, np.ones_like(x)], 1)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def to_model(rays, heading_deg):
    """Face camera rays -> model frame (z up) for a face looking along heading_deg."""
    h = math.radians(heading_deg)
    fwd = np.array([math.sin(h), math.cos(h), 0.0])
    right = np.array([math.cos(h), -math.sin(h), 0.0])
    down = np.array([0.0, 0.0, -1.0])
    return rays[:, :1] * right + rays[:, 1:2] * down + rays[:, 2:3] * fwd


def collect(scan_id, max_pairs=25):
    faces = mp.face_paths(scan_id)
    by = {}
    for f in faces:
        by.setdefault(f["sweep_id"], {})[f["face"]] = f
    pairs = []
    ids = sorted(by)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            pa, pb = by[a][1]["position"], by[b][1]["position"]
            t = np.array([pb["x"] - pa["x"], pb["y"] - pa["y"], pb["z"] - pa["z"]])
            if 0.8 <= np.linalg.norm(t[:2]) <= 5 and abs(t[2]) < 0.5:
                pairs.append((np.linalg.norm(t), a, b, t))
    pairs.sort()
    data = []
    for _, a, b, t in pairs[:max_pairs]:
        ya, yb = mp.quat_yaw_deg(by[a][1]["rotation"]), mp.quat_yaw_deg(by[b][1]["rotation"])
        for ka, kb in product((1, 2, 3, 4), repeat=2):
            A, B = matches(by[a][ka]["path"], by[b][kb]["path"])
            if len(A) >= 8:
                data.append((t / np.linalg.norm(t), ya, yb, ka, kb, cam_rays(A), cam_rays(B)))
    return data


def score(data, s, o, c):
    n = 0
    for t, ya, yb, ka, kb, ra, rb in data:
        ma = to_model(ra, s * ya + o * 90 * (ka - 1) + c)
        mb = to_model(rb, s * yb + o * 90 * (kb - 1) + c)
        resid = np.abs(np.einsum("ij,ij->i", mb, np.cross(t, ma)))
        ok = resid < EPS
        if not ok.any():
            continue
        # cheirality: solve la*ma - lb*mb = t; both depths must be positive. Without
        # this, c and c + 180 score the same (the constraint ignores the sign of t).
        a, b = ma[ok], mb[ok]
        aa = (a * a).sum(1); bb = (b * b).sum(1); ab = (a * b).sum(1)
        at = a @ t; bt = b @ t
        det = aa * bb - ab * ab
        good = np.abs(det) > 1e-6
        la = np.where(good, (bb * at - ab * bt) / np.where(good, det, 1), -1)
        lb = np.where(good, (ab * at - aa * bt) / np.where(good, det, 1), -1)
        n += int(((la > 0) & (lb > 0)).sum())
    return n


def main(scans):
    data = []
    for sc in scans:
        d = collect(sc)
        print(f"{sc}: {len(d)} face pairs, {sum(len(x[5]) for x in d)} matches")
        data += d
    results = []
    for s, o in product((1, -1), (1, -1)):
        coarse = [(score(data, s, o, c), c) for c in range(0, 360, 2)]
        best_n, best_c = max(coarse)
        fine = [(score(data, s, o, c), c) for c in np.arange(best_c - 2, best_c + 2.01, 0.25)]
        n, c = max(fine)
        others = sorted(x[0] for x in coarse)
        results.append((n, s, o, c % 360))
        print(f"s={s:+d} o={o:+d}: best c={c % 360:7.2f}  inliers={n}  (median over c: {others[len(others)//2]})")
    n, s, o, c = max(results)
    print(f"\nBEST: SKYBOX_YAW_SIGN={s}  FACE_ORDER={o}  SKYBOX_OFFSET_DEG={c:.2f}  inliers={n}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["znrV5PNxA9T"])
