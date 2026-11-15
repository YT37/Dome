"""Zoner: the dome polygon(s), with area, clue weight, confidence and the reasons."""
from __future__ import annotations

from ._base import fmt, not_recorded, step, table


def build(ctx) -> list:
    zones = (ctx.load("zones.json") or {}).get("zones")
    src = ctx.src("zones.json")
    if not zones:
        return [not_recorded("final", "Zoner", "no zones.json", src)]
    feats = [{"type": "Feature", "properties": {"label": z["zone_id"]},
              "geometry": {"type": "Polygon", "coordinates": [[[lo, la] for la, lo in z["polygon"]]]}} for z in zones]
    steps = [step("map", "The dome over the search area", "map",
                  {"features": {"type": "FeatureCollection", "features": feats}, "zoom": 14},
                  "Place clues give an area, never an address.", src),
             step("table", "Zone numbers", "table",
                  table(["zone", "area km²", "clue weight", "confidence Z", "wide"],
                        [[z["zone_id"], fmt(z.get("area_km2"), 1), fmt(z.get("weight_share")), fmt(z.get("confidence")),
                          "yes" if z.get("wide") else "no"] for z in zones]),
                  "A wide zone (most clues city-wide, or over 25 km²) keeps only scanned buildings.", src)]
    for z in zones:
        steps.append(step(f"reasons_{z['zone_id']}", f"Why {z['zone_id']}", "text",
                          {"text": z["zone_id"], "bullets": z.get("reasons", [])},
                          "The Zoner's own reasons, as written.", src))
    return steps
