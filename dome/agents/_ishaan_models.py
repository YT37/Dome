"""TEMPORARY Pydantic models for the Zoner's and Briefer's outputs.

These match the JSON shapes in the plan exactly. Delete this file and import from
dome/schemas.py as soon as Avishek pushes it.
"""

from typing import Optional

from pydantic import BaseModel, Field


class Zone(BaseModel):
    zone_id: str
    polygon: list[list[float]]            # [[lat, lon], ...] exterior ring
    area_km2: float
    weight_share: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    wide: bool
    reasons: list[str]


class RingZones(BaseModel):
    ring_id: str
    zones: list[Zone]


class Lead(BaseModel):
    rank: int
    property_id: str
    display_name: str
    tier: str                              # "High" | "Medium" | "Low"
    score: int
    factors: dict[str, Optional[float]]    # R, Z, F, P, W (W may be None)
    reasons: list[str]
    verify_next: list[str]


class Brief(BaseModel):
    ring_id: str
    failed_steps: list[str]
    leads: list[Lead]
