"""Vexcel aerial imagery (STUB)."""
from __future__ import annotations


def oblique_view(lat: float, lon: float, heading_deg: float) -> str:
    """Image path of the oblique view from (lat, lon) looking along heading_deg."""
    return f"data/vexcel/oblique_{lat:.4f}_{lon:.4f}_{int(heading_deg) % 360}.jpg"


def building_outlines(lat: float, lon: float, radius_m: float) -> list[dict]:
    """keys: outline, height_m"""
    return []
