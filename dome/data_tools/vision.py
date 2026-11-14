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


def room_match(photo_paths: list[str], scan_ids: list[str]) -> list[dict]:
    """keys: scan_id, P (0-1), evidence: [{photo, view_id, inliers, match_img}]"""
    sc = _stub.scenario()
    out = []
    for sid in scan_ids:
        hit = sc.get("room_match", {}).get(sid) or {"P": 0.05, "evidence": []}
        out.append({"scan_id": sid, "P": hit["P"], "evidence": list(hit.get("evidence", []))})
    return out


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
