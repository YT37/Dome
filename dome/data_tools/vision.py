"""Vision tools (STUB): photo cues, photo-to-scan room match, window check."""
from __future__ import annotations

from . import _stub


def photo_cues(photo_paths: list[str]) -> dict:
    """Read the ring photos once. keys: setting, window_floor_est, features"""
    return dict(_stub.scenario()["photo_cues"])


def room_match(photo_paths: list[str], scan_ids: list[str]) -> list[dict]:
    """keys: scan_id, P (0-1), evidence: [{photo, view_id, inliers, match_img}]"""
    sc = _stub.scenario()
    out = []
    for sid in scan_ids:
        hit = sc.get("room_match", {}).get(sid) or {"P": 0.05, "evidence": []}
        out.append({"scan_id": sid, "P": hit["P"], "evidence": list(hit.get("evidence", []))})
    return out


def window_check(window_crop: str, lat: float, lon: float, heading_deg: float) -> dict:
    """keys: W (0-1), checks: {name: bool}, floor_range: [lo, hi]"""
    sc = _stub.scenario()
    for sid, fix in sc.get("geo", {}).items():
        if abs(fix["lat"] - lat) < 1e-6 and abs(fix["lon"] - lon) < 1e-6 and sid in sc.get("window", {}):
            return dict(sc["window"][sid])
    return {"W": 0.0, "checks": {}, "floor_range": None}


def detect_exits(scan_id: str) -> list[dict]:
    """STRETCH (only after the 4 PM gate). keys: kind, x, y, floor, seen"""
    return []
