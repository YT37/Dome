"""Fit the in-plane orientation of Matterport's up (0) and down (5) skybox faces.

For points just inside the top (bottom) edge of each side face, project the same ray onto
the up (down) face under all 8 orientations and compare colours; the right orientation
makes the seams continuous. Prints the best (swap, flip_x, flip_y) per cap and its error
vs the runner-up. Usage: python scripts/check_cube_faces.py <scan_id> [...]
"""
import itertools
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dome.data_tools import matterport as mp  # noqa: E402
from dome.data_tools import render  # noqa: E402

ORIENTS = list(itertools.product((False, True), repeat=3))


def sample(img, x, y):
    h, w = img.shape[:2]
    mx = ((x + 1) / 2 * w - 0.5).astype(np.float32)
    my = ((y + 1) / 2 * h - 0.5).astype(np.float32)
    return cv2.remap(img, mx[None], my[None], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0].astype(np.float32)


def errors(scan_id, max_sweeps=6):
    by = {}
    for f in mp.face_paths(scan_id, faces=(0, 1, 2, 3, 4, 5)):
        by.setdefault(f["sweep_id"], {})[f["face"]] = cv2.imread(f["path"])
    err = {0: np.zeros(8), 5: np.zeros(8)}
    xs = np.linspace(-0.9, 0.9, 200)
    for faces in list(by.values())[:max_sweeps]:
        if len(faces) < 6:
            continue
        for k in (1, 2, 3, 4):
            c = math.radians(90 * (k - 1))
            fwd = np.array([math.sin(c), math.cos(c), 0.0])
            right = np.array([math.cos(c), -math.sin(c), 0.0])
            for cap, yedge, sign in ((0, -0.985, 1.0), (5, 0.985, -1.0)):
                # side-face pixel (x, yedge) -> ray: d = fwd + x*right + y*down, down = (0,0,-1)
                d = fwd[None] + xs[:, None] * right[None] + yedge * np.array([0, 0, -1.0])[None]
                side_px = sample(faces[k], xs, np.full_like(xs, yedge))
                for i, o in enumerate(ORIENTS):
                    u, v = render._uv_cap(d, sign, o)
                    cap_px = sample(faces[cap], u, v)
                    err[cap][i] += float(np.abs(cap_px - side_px).mean())
    return err


if __name__ == "__main__":
    tot = {0: np.zeros(8), 5: np.zeros(8)}
    for s in sys.argv[1:]:
        e = errors(s)
        for c in tot:
            tot[c] += e[c]
    for cap, name in ((0, "UP_ORIENT"), (5, "DOWN_ORIENT")):
        order = np.argsort(tot[cap])
        print(f"{name} = {ORIENTS[order[0]]}   err {tot[cap][order[0]]:.0f} vs next {tot[cap][order[1]]:.0f} {ORIENTS[order[1]]}")
