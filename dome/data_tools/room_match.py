"""Real photo-to-scan room match (Yug): which Matterport scan were these ad photos taken in?

Pipeline, all on CPU and deterministic:
1. Index: for each candidate scan, perspective views of its INDEX sweeps only (the four side
   cube faces from `matterport.sweep_views` plus four views between them, 90 deg FOV).
   Holdout sweeps (render.split_sweeps) are left out, so a photo is never matched to the
   pano it was cut from. DINOv2-small embeddings (L2-normalised) and DISK keypoints are cached
   per scan under cache/vision/.
   With more than COARSE_MIN_SCANS candidates (a real zone holds ~125 scanned buildings), a
   coarse pass runs first: DINOv2 on the low-resolution side faces of every candidate's index
   sweeps, scans ranked by the mean over photos of the best face cosine; only the top
   COARSE_KEEP get the full check below, the rest get P = 0 with their coarse rank recorded.
   (On the 125-scan Ring A zone, A's and D's own photos rank their scan #1.)
2. Query: flat grey silhouette pixels are masked out of each photo (filled for the embedding,
   keypoints inside it dropped).
3. Per scan, the top `TOP_K` views by cosine are re-ranked with DISK + LightGlue (kornia)
   and a fundamental-matrix RANSAC (MAGSAC); a photo's score for a scan = most RANSAC
   inliers. (OpenCV SIFT was tried first: the dark, blurred ad photos gave it too few
   keypoints to separate the right room from the wrong building.)
4. The ring's photos are grouped by room (DINOv2 photo-photo cosine >= GROUP_COS, connected
   components). A group matches a scan when its best photo clears `MIN_INLIERS`.
   P(scan) = matched groups / groups.
Each matching photo's best view is saved side by side with its inlier lines to
data/matches/<photo_id>__<view>.jpg.

A match is a lead for a human to check against the scan, not proof of presence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from . import matterport as mp
from . import render
from ._common import cache_dir

DINO = "facebook/dinov2-small"
VIEW_PX = 1024          # index view render size (square, 90 deg FOV)
FEAT_PX = 768           # DISK runs on images resized so the long side is this
PHOTO_PX = 1024         # photos downscaled so the long side is at most this
N_KP = 2048             # DISK keypoints per image
TOP_K = 24              # views per scan re-ranked with LightGlue
RANSAC_PX = 2.0         # fundamental-matrix inlier threshold, pixels
MIN_INLIERS = 50        # a photo matches a scan at or above this many inliers. Tuned on A vs D
                        # only: wrong-building photos reach at most 25, right-building ones 61-993
GROUP_COS = 0.8         # photos in one room group: DINOv2 cosine at or above this
MAX_EVIDENCE = 8
COARSE_KEEP = 6         # scans kept after the coarse DINOv2 pass for the LightGlue check
COARSE_MIN_SCANS = 8    # with this many scans or fewer, skip the coarse pass
INDEX_VERSION = "v3"
ROOT = Path(__file__).resolve().parents[2]
MATCH_DIR = ROOT / "data" / "matches"

_model = None
_sift = None


def _dino():
    global _model
    if _model is None:
        import torch
        from transformers import AutoImageProcessor, AutoModel
        torch.set_num_threads(max(1, torch.get_num_threads()))
        _model = (AutoImageProcessor.from_pretrained(DINO), AutoModel.from_pretrained(DINO).eval())
    return _model


def _lg():
    global _sift
    if _sift is None:
        import torch
        from kornia.feature import DISK, LightGlueMatcher
        torch.set_grad_enabled(False)
        _sift = (DISK.from_pretrained("depth").eval(), LightGlueMatcher("disk").eval())
    return _sift


def embed(images: list[np.ndarray]) -> np.ndarray:
    """L2-normalised DINOv2 CLS embeddings for BGR images, (n, 384)."""
    import torch
    from PIL import Image
    proc, model = _dino()
    out = []
    for i in range(0, len(images), 16):
        pils = [Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)) for im in images[i:i + 16]]
        with torch.no_grad():
            o = model(**proc(images=pils, return_tensors="pt"))
        e = o.pooler_output.numpy()
        out.append(e / np.linalg.norm(e, axis=1, keepdims=True))
    return np.concatenate(out) if out else np.zeros((0, 384), np.float32)


def silhouette_mask(img: np.ndarray) -> np.ndarray:
    """uint8 mask, 255 where a flat grey silhouette was pasted (near-zero local variance,
    near-zero saturation, a sizeable connected blob). Ordinary walls carry sensor noise."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mu = cv2.blur(g, (7, 7))
    var = cv2.blur(g * g, (7, 7)) - mu * mu
    sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1]
    flat = ((var < 1.5) & (sat < 25)).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(flat, 8)
    keep = np.zeros_like(flat)
    min_area = 0.01 * img.shape[0] * img.shape[1]
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] >= min_area:
            keep[lab == k] = 255
    return cv2.dilate(keep, np.ones((9, 9), np.uint8))


def _fill(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if not mask.any():
        return img
    out = img.copy()
    out[mask > 0] = np.median(img[mask == 0], axis=0) if (mask == 0).any() else 127
    return out


def _features(img: np.ndarray, mask: np.ndarray | None = None):
    """DISK keypoints (feature-image pixels), descriptors, feature image size (h, w) and the
    scale from `img` to the feature image.
    Keypoints on a masked silhouette are dropped."""
    import kornia as K
    import torch
    disk, _ = _lg()
    sc = FEAT_PX / max(img.shape[:2])
    small = cv2.resize(img, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
    t = K.image_to_tensor(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)).float()[None] / 255
    torch.manual_seed(0)
    f = disk(t, N_KP, pad_if_not_divisible=True)[0]
    kp = f.keypoints.numpy().astype(np.float32)
    des = f.descriptors.numpy().astype(np.float32)
    if mask is not None and mask.any():
        m = cv2.resize(mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
        keep = m[kp[:, 1].astype(int).clip(0, m.shape[0] - 1), kp[:, 0].astype(int).clip(0, m.shape[1] - 1)] == 0
        kp, des = kp[keep], des[keep]
    return kp, des.astype(np.float16), (small.shape[0], small.shape[1]), sc


# --- index ------------------------------------------------------------------------------------

def _index_views(scan_id: str):
    """(view_id, sweep_id, heading_deg, image) for the scan's INDEX sweeps."""
    index, _ = render.split_sweeps(scan_id)
    keep = set(index)
    faces: dict[str, dict[int, np.ndarray]] = {}
    rot: dict[str, dict] = {}
    for f in mp.face_paths(scan_id, faces=(0, 1, 2, 3, 4, 5)):
        if f["sweep_id"] in keep:
            faces.setdefault(f["sweep_id"], {})[f["face"]] = cv2.imread(f["path"])
            rot[f["sweep_id"]] = f["rotation"]
    for sweep in sorted(faces):
        for az in range(0, 360, 45):
            img = render.perspective(faces[sweep], VIEW_PX, VIEW_PX, 90.0, float(az), 0.0)
            yield (f"{scan_id}/{sweep}/az_{az:03d}", sweep,
                   round((mp.face_heading(rot[sweep], 1) + az) % 360, 1), img)


def _index_path(scan_id: str) -> Path:
    d = cache_dir() / "vision"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{scan_id}_{INDEX_VERSION}.npz"


def scan_index(scan_id: str) -> dict:
    """Cached index: view_ids, sweep_ids, headings, embeddings, SIFT points/descriptors."""
    p = _index_path(scan_id)
    if p.exists():
        z = np.load(p, allow_pickle=True)
        return {k: z[k] for k in z.files}
    ids, sweeps, heads, imgs, pts, des, hws = [], [], [], [], [], [], []
    img_dir = p.parent / f"{scan_id}_{INDEX_VERSION}_views"
    img_dir.mkdir(exist_ok=True)
    for vid, sweep, head, img in _index_views(scan_id):
        ids.append(vid)
        sweeps.append(sweep)
        heads.append(head)
        cv2.imwrite(str(img_dir / (vid.replace("/", "__") + ".jpg")), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        imgs.append(img)
        a, b, hw, sc = _features(img)
        pts.append(a)                   # feature-image pixels
        des.append(b)
        hws.append(hw)
    emb = embed(imgs)
    out = {"view_ids": np.array(ids), "sweep_ids": np.array(sweeps), "headings": np.array(heads),
           "emb": emb, "pts": np.array(pts, dtype=object), "des": np.array(des, dtype=object),
           "hw": np.array(hws), "view_scale": np.array(FEAT_PX / VIEW_PX)}
    np.savez(p, **out)
    return out


def _view_image(scan_id: str, view_id: str) -> np.ndarray:
    return cv2.imread(str(_index_path(scan_id).parent / f"{scan_id}_{INDEX_VERSION}_views" /
                          (view_id.replace("/", "__") + ".jpg")))


# --- matching ---------------------------------------------------------------------------------

def verify(pa, da, hwa, pb, db, hwb) -> tuple[int, np.ndarray]:
    """LightGlue matches + fundamental-matrix RANSAC between two DISK feature sets (points in
    their feature-image pixels). Returns (inlier count, inlier pairs (n, 4))."""
    import torch
    from kornia.feature import laf_from_center_scale_ori
    if len(da) < 8 or len(db) < 8:
        return 0, np.zeros((0, 4), np.float32)
    _, lg = _lg()
    ka, kb = torch.from_numpy(np.ascontiguousarray(pa, np.float32)), torch.from_numpy(np.ascontiguousarray(pb, np.float32))
    la = laf_from_center_scale_ori(ka[None], torch.ones(1, len(ka), 1, 1))
    lb = laf_from_center_scale_ori(kb[None], torch.ones(1, len(kb), 1, 1))
    _, idx = lg(torch.from_numpy(np.asarray(da, np.float32)), torch.from_numpy(np.asarray(db, np.float32)),
                la, lb, hw1=tuple(int(x) for x in hwa), hw2=tuple(int(x) for x in hwb))
    idx = idx.numpy()
    if len(idx) < 8:
        return 0, np.zeros((0, 4), np.float32)
    a, b = pa[idx[:, 0]].astype(np.float32), pb[idx[:, 1]].astype(np.float32)
    cv2.setRNGSeed(0)
    try:
        F, inl = cv2.findFundamentalMat(a, b, cv2.USAC_MAGSAC, RANSAC_PX, 0.999, 10000)
    except cv2.error:                       # degenerate sample set: no model
        return 0, np.zeros((0, 4), np.float32)
    if F is None or inl is None:
        return 0, np.zeros((0, 4), np.float32)
    m = inl.ravel().astype(bool)
    return int(m.sum()), np.hstack([a[m], b[m]])


def _load_photo(path: str) -> np.ndarray | None:
    img = cv2.imread(str(path))
    if img is None:
        return None
    s = PHOTO_PX / max(img.shape[:2])
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img


def _match_image(photo: np.ndarray, view: np.ndarray, pairs: np.ndarray, out: Path) -> str:
    h = 512
    sa, sb = h / photo.shape[0], h / view.shape[0]
    A = cv2.resize(photo, None, fx=sa, fy=sa)
    B = cv2.resize(view, None, fx=sb, fy=sb)
    canvas = np.hstack([A, B])
    rng = np.random.default_rng(0)
    for x1, y1, x2, y2 in pairs[rng.permutation(len(pairs))[:120]]:
        c = tuple(int(v) for v in rng.integers(80, 256, 3))
        p1 = (int(x1 * sa), int(y1 * sa))
        p2 = (int(x2 * sb) + A.shape[1], int(y2 * sb))
        cv2.line(canvas, p1, p2, c, 1, cv2.LINE_AA)
        cv2.circle(canvas, p1, 3, c, -1)
        cv2.circle(canvas, p2, 3, c, -1)
    cv2.putText(canvas, f"{len(pairs)} inliers", (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out)


def _groups(emb: np.ndarray) -> list[list[int]]:
    n = len(emb)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    sim = emb @ emb.T
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= GROUP_COS:
                parent[find(i)] = find(j)
    by: dict[int, list[int]] = {}
    for i in range(n):
        by.setdefault(find(i), []).append(i)
    return sorted(by.values(), key=lambda g: g[0])


# --- coarse pass: DINOv2 on low-resolution cube faces, for many candidate scans -------------

Q_LOW = """query p($id: ID!) { model(id: $id) { locations { id room { id }
  panos { id skybox(resolution: "low") { status children } } } } }"""


def coarse_index(scan_id: str) -> np.ndarray:
    """DINOv2 embeddings of the four side faces (low resolution) of every INDEX sweep."""
    p = cache_dir() / "vision" / f"{scan_id}_coarse_{INDEX_VERSION}.npy"
    if p.exists():
        return np.load(p)
    from ._common import request_with_backoff
    index, _ = render.split_sweeps(scan_id)
    keep = set(index)
    body = mp.graphql(Q_LOW, {"id": scan_id})
    locs = ((body.get("data") or {}).get("model") or {}).get("locations") or []
    imgs = []
    for loc in sorted(locs, key=lambda l: l["id"]):
        if loc["id"] not in keep:
            continue
        pano = next((x for x in loc.get("panos") or [] if len(((x.get("skybox") or {}).get("children")) or []) >= 6), None)
        if pano is None:
            continue
        for face in (1, 2, 3, 4):
            r = request_with_backoff("GET", pano["skybox"]["children"][face], timeout=60)
            if r.ok:
                im = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
                if im is not None:
                    imgs.append(im)
    emb = embed(imgs) if imgs else np.zeros((0, 384), np.float32)
    np.save(p, emb)
    return emb


def coarse_rank(photo_emb: np.ndarray, scan_ids: list[str]) -> list[tuple[str, float]]:
    """Scans ranked by the mean over photos of each photo's best face cosine."""
    out = []
    for sid in scan_ids:
        try:
            e = coarse_index(sid)
        except Exception:                      # scan unavailable: rank it last, never invent
            e = np.zeros((0, 384), np.float32)
        sc = float(np.mean((photo_emb @ e.T).max(axis=1))) if len(e) and len(photo_emb) else -1.0
        out.append((sid, round(sc, 4)))
    return sorted(out, key=lambda x: (-x[1], x[0]))


def _score_cache(photo_bytes: bytes, scan_id: str) -> Path:
    key = hashlib.sha1(photo_bytes + f"|{scan_id}|{INDEX_VERSION}|{TOP_K}|{N_KP}|{FEAT_PX}".encode()).hexdigest()[:20]
    d = cache_dir() / "vision" / "scores"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.npz"


def photo_scores(photo_paths: list[str], scan_ids: list[str]) -> dict:
    """Per photo and scan: best view and inlier count (cached per photo bytes and scan).
    Also the photo embeddings and room groups."""
    photos, names, feats, imgs, raw = [], [], [], [], []
    for p in sorted(set(photo_paths)):
        img = _load_photo(p)
        if img is None:
            continue
        m = silhouette_mask(img)
        photos.append(_fill(img, m))
        imgs.append(img)
        names.append(Path(p).stem)
        raw.append(Path(p).read_bytes())
        feats.append((img, m))           # DISK features computed only on a cache miss
    emb = embed(photos)
    scores: dict[str, dict[str, dict]] = {n: {} for n in names}
    for sid in scan_ids:
        idx = None
        for i, n in enumerate(names):
            cp = _score_cache(raw[i], sid)
            if cp.exists():
                z = np.load(cp, allow_pickle=True)
                scores[n][sid] = json.loads(str(z["meta"])) | {"pairs": z["pairs"]}
                continue
            if idx is None:
                idx = scan_index(sid)
                sims = emb @ idx["emb"].T
            if len(feats[i]) == 2:
                feats[i] = _features(*feats[i])
            best = {"inliers": 0, "view_id": None, "pairs": np.zeros((0, 4), np.float32), "cos": 0.0}
            for j in np.argsort(-sims[i], kind="stable")[:TOP_K]:
                k, pairs = verify(feats[i][0], feats[i][1], feats[i][2], idx["pts"][j], idx["des"][j], idx["hw"][j])
                if k > best["inliers"]:
                    pairs = np.hstack([pairs[:, :2] / feats[i][3], pairs[:, 2:] / float(idx["view_scale"])])
                    best = {"inliers": k, "view_id": str(idx["view_ids"][j]), "pairs": pairs,
                            "cos": float(sims[i, j]), "heading_deg": float(idx["headings"][j])}
            scores[n][sid] = best
            np.savez(cp, pairs=best["pairs"], meta=json.dumps({k: v for k, v in best.items() if k != "pairs"}))
    return {"names": names, "images": imgs, "emb": emb, "scores": scores, "groups": _groups(emb)}


def room_match(photo_paths: list[str], scan_ids: list[str], save_images: bool = True) -> list[dict]:
    """keys: scan_id, P (0-1), evidence: [{photo, view_id, inliers, match_img}], plus
    groups / groups_matched (how P was counted)."""
    full, coarse = list(scan_ids), {}
    if len(scan_ids) > COARSE_MIN_SCANS:       # many candidates: coarse DINOv2 pass first
        ims = []
        for p in sorted(set(photo_paths)):
            im = _load_photo(p)
            if im is not None:
                ims.append(_fill(im, silhouette_mask(im)))
        ranked = coarse_rank(embed(ims), list(scan_ids))
        coarse = {sid: (i + 1, v) for i, (sid, v) in enumerate(ranked)}
        full = [sid for sid, _ in ranked[:COARSE_KEEP]]
    r = photo_scores(photo_paths, full)
    names, groups = r["names"], r["groups"]
    out = []
    for sid in scan_ids:
        if sid not in full:                    # not verified: P 0, and the record says why
            rank, v = coarse[sid]
            out.append({"scan_id": sid, "P": 0.0, "evidence": [], "groups": len(groups), "groups_matched": 0,
                        "min_inliers": MIN_INLIERS, "stage": "coarse",
                        "note": f"coarse DINOv2 rank {rank} of {len(scan_ids)} (score {v}); only the top "
                                f"{COARSE_KEEP} get the LightGlue check"})
            continue
        sc = {n: r["scores"][n][sid] for n in names}
        matched = [g for g in groups if max(sc[names[i]]["inliers"] for i in g) >= MIN_INLIERS]
        P = round(len(matched) / len(groups), 3) if groups else 0.0
        hits = sorted((n for n in names if sc[n]["inliers"] >= MIN_INLIERS),
                      key=lambda n: (-sc[n]["inliers"], n))[:MAX_EVIDENCE]
        evidence = []
        for n in hits:
            s = sc[n]
            img = None
            if save_images:
                img = _match_image(r["images"][names.index(n)], _view_image(sid, s["view_id"]), s["pairs"],
                                   MATCH_DIR / f"{n}__{s['view_id'].replace('/', '_')}.jpg")
            evidence.append({"photo": n, "view_id": s["view_id"], "inliers": s["inliers"], "match_img": img,
                             "heading_deg": s.get("heading_deg")})
        out.append({"scan_id": sid, "P": P, "evidence": evidence, "groups": len(groups),
                    "groups_matched": len(matched), "min_inliers": MIN_INLIERS, "stage": "lightglue",
                    **({"note": f"coarse DINOv2 rank {coarse[sid][0]} of {len(scan_ids)}"} if sid in coarse else {})})
    if save_images:
        write_summary(names, groups, r["scores"], coarse, full, out)
    return out


SUMMARY = MATCH_DIR / "summary.json"


def write_summary(names, groups, scores, coarse, full, out) -> Path:
    """In-between results of the last real run, for the "show the work" view and the asset
    pack: coarse ranking, shortlist, inliers per photo and scan, room groups, P per scan.
    `scans` keeps earlier runs' entries for other scans (the asset pack reads D's from there)."""
    prev = {}
    if SUMMARY.exists():
        try:
            prev = json.loads(SUMMARY.read_text())
        except ValueError:
            prev = {}
    scans = prev.get("scans") or {k: v for k, v in prev.items() if isinstance(v, dict) and "evidence" in v}
    for o in out:
        if o["stage"] == "lightglue":
            scans[o["scan_id"]] = {"P": o["P"], "evidence": o["evidence"]}
    summary = {
        "min_inliers": MIN_INLIERS, "coarse_keep": COARSE_KEEP, "photos": names,
        "coarse": [{"scan_id": sid, "score": v, "rank": rank}
                   for sid, (rank, v) in sorted(coarse.items(), key=lambda kv: kv[1][0])],
        "shortlist": list(full),
        "full": {n: {sid: {"inliers": scores[n][sid]["inliers"], "view_id": scores[n][sid]["view_id"]}
                     for sid in full} for n in names},
        "groups": [{"photos": [names[i] for i in g],
                    "matched": {sid: max(scores[names[i]][sid]["inliers"] for i in g) >= MIN_INLIERS
                                for sid in full}} for g in groups],
        "P": {o["scan_id"]: o["P"] for o in out},
        "scans": scans,
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=1))
    return SUMMARY


def photo_groups(photo_paths: list[str]) -> list[dict]:
    """Photos grouped by room, photo to photo (DINOv2 cosine, then SIFT/RANSAC confirms the
    link). keys: group_id, photos, details, scan_id (None: not matched to a scan here)."""
    photos, names, feats = [], [], []
    for p in sorted(set(photo_paths)):
        img = _load_photo(p)
        if img is None:
            continue
        m = silhouette_mask(img)
        photos.append(_fill(img, m))
        names.append(Path(p).stem)
        feats.append(_features(img, m))
    emb = embed(photos)
    out = []
    for g in _groups(emb):
        if len(g) < 2:
            continue
        links = []
        for a in g:
            for b in g:
                if a < b:
                    k, _ = verify(feats[a][0], feats[a][1], feats[a][2], feats[b][0], feats[b][1], feats[b][2])
                    links.append(k)
        out.append({"group_id": f"RG-{len(out) + 1}", "photos": [names[i] for i in g], "scan_id": None,
                    "details": [f"DINOv2 cosine >= {GROUP_COS}; best SIFT/RANSAC link {max(links)} inliers"]})
    return out
