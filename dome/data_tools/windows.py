"""Simple window detector for Matterport cube faces (inside view).

A window from inside is a bright, fairly low-texture region (sky, facade across
the street, blown-out glass), roughly rectangular, not tiny, and not just a ceiling
light. This is deliberately simple and deterministic; it is the first pass the
hand-check kit shows, and misses are recorded by hand in the answer key.
Upgrade path if it is too noisy: confirm with OWL-ViT / Grounding DINO ("window").
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

WORK = 512  # detection runs on a 512x512 copy of the face


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int
    score: float

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h, "score": round(self.score, 3)}


def detect_windows(image_path: str) -> list[dict]:
    """Window boxes in the image's own pixel coordinates, left to right.

    Each dict: x, y, w, h (pixels in the original image), score (0-1).
    """
    img = cv2.imread(image_path)
    if img is None:
        return []
    H, W = img.shape[:2]
    small = cv2.resize(img, (WORK, WORK), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0].astype(np.float32)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    S, V = hsv[:, :, 1].astype(np.float32), hsv[:, :, 2].astype(np.float32)

    # Sky/outdoor seed: bright and bluish (LAB b below neutral). White walls are
    # neutral-to-warm (b >= ~128) so they do not seed, which is what made the
    # brightness-only version fire on every wall.
    B = lab[:, :, 2].astype(np.float32)
    sky = (L >= 150) & (B <= 123)
    # bright region the seeds can grow into (glass, clouds, facades across the street)
    thr = max(160.0, float(np.percentile(L, 80)))
    bright = (L >= thr) | sky
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)

    grown = cv2.morphologyEx(bright.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n0, lab0, _, _ = cv2.connectedComponentsWithStats(grown, 8)
    sky_count = np.bincount(lab0.ravel(), weights=sky.ravel().astype(np.float64), minlength=n0)
    size = np.bincount(lab0.ravel(), minlength=n0).astype(np.float64)
    keep = np.zeros(n0, bool)
    keep[1:] = (sky_count[1:] / np.maximum(size[1:], 1)) >= 0.12
    mask = keep[lab0].astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 0.006 * WORK * WORK or area > 0.6 * WORK * WORK:
            continue
        if h < 0.08 * WORK or w < 0.03 * WORK:
            continue
        if y + h < 0.25 * WORK:              # entirely near the ceiling: lights
            continue
        if y > 0.75 * WORK:                  # entirely near the floor: reflections
            continue
        fill = area / float(w * h)
        if fill < 0.5:
            continue
        aspect = w / float(h)
        if not 0.15 <= aspect <= 4.0:
            continue
        region = labels[y:y + h, x:x + w] == i
        score = float(np.clip(0.5 * fill + 0.5 * (L[y:y + h, x:x + w][region].mean() / 255), 0, 1))
        sx, sy = W / WORK, H / WORK
        boxes.append(Box(int(x * sx), int(y * sy), int(w * sx), int(h * sy), score))

    boxes = _merge_overlaps(boxes)
    boxes.sort(key=lambda b: (b.x, b.y))
    return [b.as_dict() for b in boxes]


def _merge_overlaps(boxes: list[Box]) -> list[Box]:
    changed = True
    while changed:
        changed = False
        out: list[Box] = []
        for b in boxes:
            for i, o in enumerate(out):
                if _iou(b, o) > 0.2 or _contains(o, b) or _contains(b, o):
                    x0, y0 = min(b.x, o.x), min(b.y, o.y)
                    x1, y1 = max(b.x + b.w, o.x + o.w), max(b.y + b.h, o.y + o.h)
                    out[i] = Box(x0, y0, x1 - x0, y1 - y0, max(b.score, o.score))
                    changed = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def _iou(a: Box, b: Box) -> float:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union else 0.0


def _contains(a: Box, b: Box) -> bool:
    return a.x <= b.x and a.y <= b.y and a.x + a.w >= b.x + b.w and a.y + a.h >= b.y + b.h


# --- open-vocabulary detector (OWL-ViT), used when torch + transformers are installed ---

OWL_MODEL = "google/owlvit-base-patch32"
OWL_QUERIES = ["a window", "a glass balcony door"]
OWL_THRESHOLD = 0.12
_owl = None


def owl_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


def _load_owl():
    global _owl
    if _owl is None:
        from transformers import OwlViTForObjectDetection, OwlViTProcessor
        _owl = (OwlViTProcessor.from_pretrained(OWL_MODEL),
                OwlViTForObjectDetection.from_pretrained(OWL_MODEL).eval())
    return _owl


def detect_windows_owl(image_path: str) -> list[dict]:
    import torch
    from PIL import Image

    proc, model = _load_owl()
    im = Image.open(image_path).convert("RGB")
    W, H = im.size
    with torch.no_grad():
        inputs = proc(text=[OWL_QUERIES], images=im, return_tensors="pt")
        out = model(**inputs)
        sizes = torch.tensor([[H, W]])
        if hasattr(proc, "post_process_grounded_object_detection"):  # transformers >= 5
            res = proc.post_process_grounded_object_detection(
                outputs=out, threshold=OWL_THRESHOLD, target_sizes=sizes)[0]
        else:
            res = proc.post_process_object_detection(out, threshold=OWL_THRESHOLD, target_sizes=sizes)[0]
    boxes = []
    for (x0, y0, x1, y1), sc in zip(res["boxes"].tolist(), res["scores"].tolist()):
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        if (x1 - x0) * (y1 - y0) < 0.004 * W * H:
            continue
        boxes.append(Box(int(x0), int(y0), int(x1 - x0), int(y1 - y0), float(sc)))
    boxes = _nms(boxes, 0.4)
    boxes.sort(key=lambda b: (b.x, b.y))
    return [b.as_dict() for b in boxes]


def _nms(boxes: list[Box], iou: float) -> list[Box]:
    keep: list[Box] = []
    for b in sorted(boxes, key=lambda b: -b.score):
        if all(_iou(b, k) < iou and not _contains(k, b) for k in keep):
            keep.append(b)
    return keep


def detect_windows_best(image_path: str) -> tuple[list[dict], str]:
    """(boxes, method). OWL-ViT when available, else the simple heuristic. Cached per file."""
    import json
    import os

    from ._common import cached_json_stable
    # offline demo: replay the detector the real run used (OWL-ViT); nothing is recomputed
    method = "owlvit" if (os.environ.get("DOME_OFFLINE") == "1" or owl_available()) else "heuristic"
    st = os.stat(image_path)
    key = ["windows", method, "<path>", st.st_size, int(st.st_mtime)]
    fn = detect_windows_owl if method == "owlvit" else detect_windows
    boxes = cached_json_stable("windows", key, image_path, lambda: fn(image_path))
    return json.loads(json.dumps(boxes)), method
