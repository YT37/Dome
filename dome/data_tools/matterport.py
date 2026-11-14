"""Matterport scans (STUB)."""
from __future__ import annotations

from . import _stub


def sweep_views(scan_id: str) -> list[dict]:
    """keys: view_id, image_path, heading_deg (model frame), floor, sweep_id"""
    return [dict(v) for v in _stub.scenario().get("sweep_views", {}).get(scan_id, [])]
