"""Find the rotation/axis convention of Vexcel oblique camera metadata.

For each cached elements/detect response, project the image's ground footprint
corners (metadata "geometry", at ground-z) and its "image-center" with every
candidate convention; the right one puts the corners on the raster corners.
Usage: python scripts/fit_oblique_camera.py
"""
import glob
import itertools
import json
import math

import numpy as np
from pyproj import Transformer
from shapely import wkt

def R(axis, a):
    c, s = math.cos(a), math.sin(a)
    return {"x": np.array([[1, 0, 0], [0, c, -s], [0, s, c]]),
            "y": np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]),
            "z": np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])}[axis]

metas = []
for p in sorted(glob.glob("cache/vexcel/*.json")):
    d = json.load(open(p))
    if isinstance(d, dict) and d.get("images"):
        m = d["images"][0]["metadata"]
        if m.get("geometry"):
            metas.append(m)

def project(m, conv, E, N, Z):
    order, transpose, signs, sx, sy = conv
    ang = {"x": signs[0] * m["omega"], "y": signs[1] * m["phi"], "z": signs[2] * m["kappa"]}
    M = np.eye(3)
    for ax in order:
        M = M @ R(ax, ang[ax])
    if transpose:
        M = M.T
    Xc = M @ (np.array([E, N, Z]) - np.array([m["camera-pos-x"], m["camera-pos-y"], m["camera-pos-z"]]))
    f, ps = m["focal-length"], m["pixel-size"]
    x, y = -f * Xc[0] / Xc[2], -f * Xc[1] / Xc[2]
    W, H = m["raster-size-width"], m["raster-size-height"]
    return W / 2 + sx * (x - m["pp0-x"]) / ps, H / 2 + sy * (y - m["pp0-y"]) / ps

def score(conv):
    errs = []
    for m in metas:
        tr = Transformer.from_crs("EPSG:4326", f"EPSG:326{m['utm-zone'][:-1]}", always_xy=True)
        W, H = m["raster-size-width"], m["raster-size-height"]
        corners = [(0, 0), (W, 0), (W, H), (0, H)]
        g = wkt.loads(m["geometry"])
        for lon, lat in list(g.exterior.coords)[:4]:
            E, N = tr.transform(lon, lat)
            c, r = project(m, conv, E, N, m["ground-z"])
            errs.append(min(math.hypot(c - a, r - b) for a, b in corners))
    return float(np.median(errs)), float(np.max(errs))

convs = [(o, t, s, sx, sy) for o in itertools.permutations("xyz") for t in (False, True)
         for s in itertools.product((1, -1), repeat=3) for sx in (1, -1) for sy in (1, -1)]
res = sorted((score(c), c) for c in convs)
print(len(metas), "images")
for (med, mx), c in res[:6]:
    print(f"median corner err {med:8.1f} px  max {mx:8.1f}  conv {c}")
