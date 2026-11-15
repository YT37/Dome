"""Render the synthetic ad photos for Ring A and decoy D from their Matterport scans.

Jobs come from data/synth/renders.json (photo id -> scan_id, view) and dome/synth/buildings.json
(scan_id -> label). Until Ishaan regenerates with the real ids, placeholder scan ids are mapped
to the real scans with --map (default: mp_4471=LqCMcmmVH3d, mp_2210=FQZd6kTpht1).

Honesty rule: each scan's sweeps are split (fixed seed) into an INDEX set (what room_match may
search) and a HOLDOUT set (the only sweeps photos are rendered from), alternating within each
room so both cover every room. renders/holdout_sweeps.json records the split; room_match must
leave holdout sweeps out of its index. Window photos aim at windows the hand-check confirmed
(handcheck/answer_keys/answer_key_<scan>.json), seen from holdout sweeps.

Outputs (git-ignored): data/photos/<photo_id>.jpg (no metadata, no ids in pixels or names),
renders/manifest.json (internal: photo, label, scan, sweep, yaw, pitch, fov, effects),
renders/holdout_sweeps.json, renders/contact_sheet.jpg, renders/photos.zip.

Usage: python scripts/render_photos.py [--map mp_4471=LqCMcmmVH3d,mp_2210=FQZd6kTpht1] [--seed 37]
"""
import argparse
import json
import math
import os
import sys
import zipfile
import zlib
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DOME_STUBS", "0")

from dome.data_tools import matterport as mp  # noqa: E402
from dome.data_tools import render  # noqa: E402
from dome.data_tools.inside_windows import _load_clip, unique_windows  # noqa: E402

ROOM_LABELS = ["a wide photo of an apartment living room", "a photo of a bedroom", "a photo of a kitchen",
               "a photo of a bathroom with a sink"]
CLOSE_LABELS = ["a close-up of a door", "a close-up of a blank wall", "the inside of a closet",
                "a photo of a ceiling", "a photo of a floor", "a close-up of a shower", "a narrow hallway",
                "a close-up of kitchen cabinets", "a close-up of an air vent", "a corner of an empty wall"]
WIN_LABELS = ["a window with a view of buildings outside", "a window with trees and the street outside"]
NOWIN_LABELS = ["a door", "a hallway", "a blank wall", "a closet", "a kitchen", "a bathroom"]


def clip_share(img: np.ndarray, good: list[str], bad: list[str]) -> float:
    """CLIP probability mass on the `good` labels for a clean render."""
    import torch
    from PIL import Image
    proc, model = _load_clip()
    pil = Image.fromarray(cv2.cvtColor(cv2.resize(img, (448, 336)), cv2.COLOR_BGR2RGB))
    with torch.no_grad():
        inp = proc(text=good + bad, images=pil, return_tensors="pt", padding=True)
        pr = model(**inp).logits_per_image.softmax(dim=-1)[0]
    return float(pr[: len(good)].sum())

PHOTOS = ROOT / "data" / "photos"
OUT = ROOT / "renders"


def split_sweeps(scan_id: str, seed: int) -> tuple[list[str], list[str]]:
    """INDEX / HOLDOUT sweeps: alternate within each room (shuffled with the seed);
    a room with one sweep keeps it in the index so the room stays searchable."""
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


def load_faces(scan_id: str) -> dict[str, dict[int, np.ndarray]]:
    by: dict[str, dict[int, np.ndarray]] = {}
    for f in mp.face_paths(scan_id, faces=(0, 1, 2, 3, 4, 5)):
        by.setdefault(f["sweep_id"], {})[f["face"]] = cv2.imread(f["path"])
    return by


def _texture(img: np.ndarray) -> float:
    g = cv2.cvtColor(cv2.resize(img, (256, 192)), cv2.COLOR_BGR2GRAY)
    return float((cv2.Canny(g, 60, 150) > 0).mean())


def window_targets(scan_id: str, holdout: list[str]) -> list[dict]:
    """(sweep, local yaw) aimed at confirmed windows, seen from holdout sweeps."""
    keyp = ROOT / "handcheck" / "answer_keys" / f"answer_key_{scan_id}.json"
    keep = None
    if keyp.exists():
        keep = {w["id"] for w in json.loads(keyp.read_text()).get("inside_windows", [])}
    out = []
    for w in unique_windows(scan_id)["windows"]:
        if keep is not None and w["id"] not in keep:
            continue
        for v in w["views"]:
            if v["sweep_id"] not in holdout:
                continue
            b = v["box"]
            cx = b["x"] + b["w"] / 2
            local = 90 * (v["face"] - 1) + math.degrees(math.atan((cx - 1024) / 1024))
            out.append({"window": w["id"], "sweep_id": v["sweep_id"], "yaw": local % 360, "size": b["w"] * b["h"]})
    out.sort(key=lambda t: -t["size"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="mp_4471=LqCMcmmVH3d,mp_2210=FQZd6kTpht1")
    ap.add_argument("--seed", type=int, default=37)
    a = ap.parse_args()
    remap = dict(kv.split("=") for kv in a.map.split(",") if kv)
    labels = {x["scan_id"]: x["label"] for x in json.loads((ROOT / "dome/synth/buildings.json").read_text())}
    jobs = [(pid, labels.get(v["scan_id"], "?"), remap.get(v["scan_id"], v["scan_id"]), v["view"])
            for pid, v in json.loads((ROOT / "data/synth/renders.json").read_text()).items() if v["scan_id"]]
    jobs.sort()
    PHOTOS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)

    split, faces, wtargets, used = {}, {}, {}, {}
    for scan in sorted({j[2] for j in jobs}):
        idx, hold = split_sweeps(scan, a.seed)
        split[scan] = {"index": idx, "holdout": hold}
        faces[scan] = load_faces(scan)
        wtargets[scan] = window_targets(scan, hold)
        print(f"{scan}: {len(idx)} index sweeps, {len(hold)} holdout sweeps, {len(wtargets[scan])} window views from holdout")
    (OUT / "holdout_sweeps.json").write_text(json.dumps(split, indent=1))

    manifest, thumbs = [], []
    for pid, label, scan, view in jobs:
        rng = np.random.default_rng(a.seed * 1000003 + zlib.crc32(pid.encode()))
        hold = split[scan]["holdout"]
        portrait = rng.random() < 0.4
        W, H = (768, 1024) if portrait else (1024, 768)
        fov = float(rng.uniform(60, 80))
        chosen = None
        for attempt in range(200):
            if view == "window" and wtargets[scan]:
                t = wtargets[scan][(attempt + int(rng.integers(0, len(wtargets[scan])))) % len(wtargets[scan])]
                sweep, yaw = t["sweep_id"], (t["yaw"] + rng.uniform(-5, 5)) % 360
                pitch, win_id = float(rng.uniform(-8, 6)), t["window"]
            else:
                sweep = hold[int(rng.integers(0, len(hold)))]
                yaw, pitch, win_id = float(rng.uniform(0, 360)), float(rng.uniform(-20, 10)), None
            prev = used.setdefault((scan, sweep), [])
            min_sep = 30 if view == "window" else 70     # window photos aim at a few windows
            if any(abs((yaw - p + 180) % 360 - 180) < min_sep for p in prev):
                continue                                  # no near-duplicates from one sweep
            img = render.perspective(faces[scan][sweep], W, H, fov, yaw, pitch, float(rng.uniform(-3, 3)))
            if _texture(img) < 0.02:
                continue                                  # blank wall or ceiling
            score = clip_share(img, WIN_LABELS, NOWIN_LABELS) if view == "window" else \
                clip_share(img, ROOM_LABELS, CLOSE_LABELS)
            if score < (0.5 if view == "window" else 0.7):
                continue                                  # not a window view / a close-up, not a room
            chosen = (sweep, yaw, pitch, img, win_id, score)
            break
        if chosen is None:
            raise SystemExit(f"{pid}: no acceptable view found")
        sweep, yaw, pitch, img, win_id, score = chosen
        used[(scan, sweep)].append(yaw)
        sil = rng.random() < (0.3 if view == "window" else 0.5)
        img, fx = render.degrade(img, rng, sil)
        q = int(rng.integers(50, 81))
        (PHOTOS / f"{pid}.jpg").write_bytes(render.encode_jpeg(img, q))
        manifest.append({"photo": pid, "label": label, "scan_id": scan, "sweep_id": sweep, "view": view,
                         "has_window": view == "window", "window": win_id, "yaw_local": round(yaw, 1),
                         "heading_model": round(mp.face_heading(_rot_of(scan, sweep), 1) + yaw, 1) % 360,
                         "pitch": round(pitch, 1), "hfov": round(fov, 1), "view_score": round(score, 3), "size": [W, H], "jpeg_quality": q, **fx})
        t = cv2.resize(img, (240, 320) if portrait else (320, 240))
        canvas = np.full((320, 320, 3), 255, np.uint8)
        canvas[:t.shape[0], :t.shape[1]] = t
        cv2.putText(canvas, f"{pid} {label} {view}", (4, 314), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
        thumbs.append(canvas)
        print(f"  {pid} {label} {view:8s} sweep {sweep[:6]} yaw {yaw:5.1f} pitch {pitch:5.1f} fov {fov:4.1f} sil {sil}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    rows = [np.hstack(thumbs[i:i + 8] + [np.full((320, 320, 3), 255, np.uint8)] * (8 - len(thumbs[i:i + 8])))
            for i in range(0, len(thumbs), 8)]
    cv2.imwrite(str(OUT / "contact_sheet.jpg"), np.vstack(rows))
    with zipfile.ZipFile(OUT / "photos.zip", "w", zipfile.ZIP_STORED) as z:
        for m in manifest:
            z.write(PHOTOS / f"{m['photo']}.jpg", f"photos/{m['photo']}.jpg")
    print(f"wrote {len(manifest)} photos to {PHOTOS}, manifest, contact sheet and zip in {OUT}")


_rot_cache: dict = {}


def _rot_of(scan: str, sweep: str) -> dict:
    if scan not in _rot_cache:
        _rot_cache[scan] = {loc["id"]: next((p["rotation"] for p in loc.get("panos") or []), None)
                            for loc in mp._panos(scan)}
    return _rot_cache[scan][sweep]


if __name__ == "__main__":
    main()
