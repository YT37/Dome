"""Vision tools: photo cues and window check (Avishek, Gemini), room match (Yug).

photo_cues and window_check delegate to gemini_vision.py. With no image files on disk they
answer from the stub fixture, so the stub demo and the tests keep working.
"""
from __future__ import annotations

from . import _stub


def photo_cues(photo_paths: list[str]) -> dict:
    """Read the ring photos once. keys: setting, window_floor_est, features, source"""
    from . import gemini_vision
    return gemini_vision.photo_cues(photo_paths, stub=lambda: dict(_stub.scenario()["photo_cues"]))


def _real_photos(photo_paths: list[str]) -> bool:
    """Real matching runs only with real data tools and at least one photo file on disk."""
    from ._common import use_stubs
    from .gemini_vision import resolve
    return not use_stubs() and any(resolve(p).is_file() for p in photo_paths)


def room_match(photo_paths: list[str], scan_ids: list[str]) -> list[dict]:
    """keys: scan_id, P (0-1), evidence: [{photo, view_id, inliers, match_img}]

    Real (Yug, `room_match.py`): DINOv2 retrieval over each scan's index sweeps, SIFT +
    RANSAC re-rank, photos grouped by room, P = share of room groups that match the scan.
    Stub: the scenario fixture (stub data tools, or no photo files on disk)."""
    if _real_photos(photo_paths) and scan_ids:
        from . import room_match as rm
        from .gemini_vision import resolve
        return rm.room_match([str(resolve(p)) for p in photo_paths], list(scan_ids))
    sc = _stub.scenario()
    out = []
    for sid in scan_ids:
        hit = sc.get("room_match", {}).get(sid) or {"P": 0.05, "evidence": []}
        out.append({"scan_id": sid, "P": hit["P"], "evidence": list(hit.get("evidence", []))})
    return out


def photo_groups(photo_paths: list[str], renders: dict | None = None) -> list[dict]:
    """v2: group photos by room, photo to photo (same matcher as room_match; Yug's real
    version replaces this). keys: group_id, photos (photo ids), details, scan_id (or None).

    Stub: the scenario's `photo_groups` fixture, else the synthetic renders.json (which scan
    each rendered photo came from). Only groups of 2+ photos are returned."""
    from collections import defaultdict
    from pathlib import Path
    if _real_photos(photo_paths):
        from . import room_match as rm
        from .gemini_vision import resolve
        return rm.photo_groups([str(resolve(p)) for p in photo_paths])
    ids = {Path(p).stem for p in photo_paths}
    sc = _stub.scenario()
    if "photo_groups" in sc:
        out = []
        for g in sc["photo_groups"]:
            ph = [x for x in g["photos"] if x in ids]
            if len(ph) >= 2:
                out.append({**g, "photos": ph})
        return out
    by_scan = defaultdict(list)
    for pid in sorted(ids):
        scan = ((renders or {}).get(pid) or {}).get("scan_id")
        if scan:
            by_scan[scan].append(pid)
    return [{"group_id": f"RG-{i}", "photos": ph, "scan_id": scan,
             "details": [f"same room as scan {scan} (stub: synthetic render source)"]}
            for i, (scan, ph) in enumerate(sorted(by_scan.items()), 1) if len(ph) >= 2]


def _stub_window_check(lat: float, lon: float) -> dict:
    # the stub finds its scan by the stub geo's exact lat/lon (replace both together)
    sc = _stub.scenario()
    for sid, fix in sc.get("geo", {}).items():
        if abs(fix["lat"] - lat) < 1e-6 and abs(fix["lon"] - lon) < 1e-6 and sid in sc.get("window", {}):
            return dict(sc["window"][sid])
    return {"W": None, "checks": {}, "floor_range": None, "skipped": "no stub window data"}


def window_check(window_crop: str, lat: float, lon: float, heading_deg: float) -> dict:
    """keys: W (0-1, or None when the check could not run), checks: {name: bool},
    floor_range: [lo, hi] or None. `window_crop` may be the whole window photo; the window
    is found and cropped inside."""
    from . import gemini_vision, vexcel
    return gemini_vision.window_check(window_crop, lat, lon, heading_deg,
                                      stub=lambda: _stub_window_check(lat, lon),
                                      oblique_view=vexcel.oblique_view)


def detect_exits(scan_id: str) -> list[dict]:
    """STRETCH (only after the 4 PM gate). keys: kind, x, y, floor, seen"""
    return []
