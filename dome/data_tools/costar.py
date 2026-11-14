"""CoStar building records (STUB). Records describe buildings, never tenants."""
from __future__ import annotations

from . import _stub


def _inside(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon; polygon is [lat, lon] pairs."""
    inside = False
    n = len(polygon)
    for i in range(n):
        (y1, x1), (y2, x2) = polygon[i], polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def properties_in_polygon(polygon: list[tuple[float, float]], types: list[str]) -> list[dict]:
    """keys: property_id, address, lat, lon, type, floors, units, year_built, has_scan, scan_id

    Empty `types` means every property type.
    """
    out = []
    for b in _stub.scenario()["buildings"]:
        if _inside(b["lat"], b["lon"], polygon) and (not types or b["type"] in types):
            out.append(dict(b))
    return sorted(out, key=lambda b: b["property_id"])
