"""Scan geolocation fix (STUB). NEW in the contract (added by Avishek)."""
from __future__ import annotations

from . import _stub


def fix_scan_location(scan_id: str, rough_lat: float, rough_lon: float, radius_m: float = 300) -> dict:
    """keys: lat, lon, heading_deg (model to true north), building_id, floor_range,
    error_estimate_m, evidence"""
    fix = _stub.scenario().get("geo", {}).get(scan_id)
    if fix:
        return dict(fix)
    return {"lat": rough_lat, "lon": rough_lon, "heading_deg": 0.0, "building_id": None,
            "floor_range": None, "error_estimate_m": float(radius_m), "evidence": []}
