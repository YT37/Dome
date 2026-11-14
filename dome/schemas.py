"""Pydantic models for every JSON file in case/<case_id>/. THE CONTRACT.

Schema changes go through Avishek. If this file and the handoff differ, this file wins.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# v1 kinds plus the v2 sticky notes and pattern kinds. `text` is the "same script" note and
# `time` the posting-time / creation-burst tie-breaker (names kept so v1 files still validate).
KeyKind = Literal["contact", "photo", "device", "text", "interaction", "place", "time",
                  "money", "dm", "room", "style", "route", "merchant", "heartbeat", "echo"]
RoleName = Literal["collector", "handler", "worker", "recruiter", "hub"]
Layers = Literal["content", "network", "both"]
Tier = Literal["High", "Medium", "Low"]
Unit = Field(ge=0.0, le=1.0)
LatLon = tuple[float, float]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- input ----------
class CaseInput(_Model):
    case_id: str
    scenario: Optional[str] = None      # stub scenario under samples/scenarios/
    ring_id: Optional[str] = None       # ring to investigate; default: highest confidence
    dataset: Optional[str] = None       # accounts/posts/interactions folder; None = stub Linker
    seed_account: Optional[str] = None  # investigate the ring that contains this account
    layers: Layers = "both"             # v2: content only, network only, or both
    private_layers: bool = True         # v2: messages + payments (Arlequin Track 1); False = --no-private


# ---------- v2 private inputs (synthetic) ----------
class Message(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    msg_id: str
    from_: str = Field(alias="from")
    to: str
    time: str
    text: str = ""


class Merchant(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    category: str = "other"            # lodging | rideshare | telecom | other
    area: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None


class Transaction(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    tx_id: str
    from_: str = Field(alias="from")
    to: str
    amount: float = 0.0
    time: str
    merchant: Optional[Merchant] = None


class FlaggedAccount(_Model):
    handle: str
    display_name: str = ""
    bio: str = ""
    created: Optional[str] = None
    last_active: Optional[str] = None
    flags: list[str] = []


class FlaggedAccountsFile(_Model):
    case_id: str
    synthetic: Literal[True] = True     # all accounts are synthetic, always
    accounts: list[FlaggedAccount]


# ---------- rings.json (Linker) ----------
class Link(_Model):
    a: str
    b: str
    keys: list[str]
    kinds: list[KeyKind]
    strength: float = Unit
    reason: str


class Recruiter(_Model):
    account: str
    reason: str


class RingPhoto(_Model):
    photo_id: str
    path: str
    account: str
    has_window: bool = False


class Role(_Model):
    account: str
    role: RoleName
    reason: str


class Handoff(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    key: str
    from_: str = Field(alias="from")
    to: str
    from_last_seen: str
    to_first_seen: str
    reason: str


class EventItem(_Model):
    type: Literal["ad", "message", "payment", "ride"]
    ref: str
    time: str


class Event(_Model):
    event_id: str
    start: str
    end: str
    members: list[str] = []
    items: list[EventItem] = []
    place_hint: Optional[str] = None
    reason: str = ""


class LocationHint(_Model):
    kind: Literal["merchant", "echo", "route", "chat_place", "login"]
    text: str                           # an area or a named business, never a person's address
    lat: Optional[float] = None
    lon: Optional[float] = None
    weight: float = Unit
    source: list[str] = []


class Ring(_Model):
    ring_id: str
    members: list[str] = Field(min_length=2)
    confidence: float = Field(ge=0.0, le=0.95)
    key_kinds: list[KeyKind]
    links: list[Link] = []
    recruiters: list[Recruiter] = []
    place_keys: list[str] = []
    photos: list[RingPhoto] = []
    # v2 (all default to empty so v1 files still validate)
    roles: list[Role] = []
    relay: list[Handoff] = []
    events: list[Event] = []
    location_hints: list[LocationHint] = []
    kind_counts: dict[str, int] = {}


class RingsFile(_Model):
    case_id: str
    rings: list[Ring] = []
    weak_hints: list[Link] = []
    layers: Layers = "both"
    private_layers: bool = False
    room_links_used: bool = False       # v2: Linker re-ran with the Locator's room groups


# ---------- zones.json (Zoner) ----------
class Zone(_Model):
    zone_id: str
    polygon: list[LatLon] = Field(min_length=3)   # [lat, lon]; an area, never an address
    area_km2: float = Field(ge=0)
    weight_share: float = Unit
    confidence: float = Unit
    wide: bool = False
    reasons: list[str] = []


class ZonesFile(_Model):
    case_id: str
    ring_id: str
    zones: list[Zone] = []


# ---------- candidates.json (Lister) ----------
class PhotoCues(_Model):
    setting: str = "unknown"
    window_floor_est: Optional[tuple[int, int]] = None
    features: list[str] = []
    # who read the photos: "gemini", "stub" (fixture, no image files) or "none" (neutral
    # cues because Gemini could not run on real photos)
    source: Literal["gemini", "stub", "none"] = "stub"


class Candidate(_Model):
    property_id: str
    address: str
    lat: float
    lon: float
    type: str
    floors: Optional[int] = None
    fit: float = Unit
    has_scan: bool = False
    scan_id: Optional[str] = None
    fit_reasons: list[str] = []

    @model_validator(mode="after")
    def _scan(self):
        if self.has_scan and not self.scan_id:
            raise ValueError("has_scan is true but scan_id is missing")
        return self


class CandidateZone(_Model):
    zone_id: str
    scanned_only: bool = False
    total_in_zone: int = Field(ge=0)
    photo_cues: PhotoCues
    candidates: list[Candidate] = []


class CandidatesFile(_Model):
    case_id: str
    ring_id: str
    zones: list[CandidateZone] = []


# ---------- matches.json (Locator) ----------
class GeoFix(_Model):
    lat: float
    lon: float
    heading_deg: float
    pin_moved_m: float = Field(ge=0)
    error_estimate_m: float = Field(ge=0)


class MatchEvidence(_Model):
    photo: str
    view: str
    inliers: int = Field(ge=0)
    match_img: Optional[str] = None


class Match(_Model):
    property_id: str
    scan_id: str
    P: float = Unit
    W: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    window_checked: bool = False
    floor_range: Optional[tuple[int, int]] = None
    geo: Optional[GeoFix] = None
    evidence: list[MatchEvidence] = []
    window_checks: dict[str, bool] = {}
    window_photo: Optional[str] = None      # photo id the window check used
    window_skipped: Optional[str] = None    # why the window check could not run (W stays null)

    @model_validator(mode="after")
    def _window(self):
        if not self.window_checked and self.W is not None:
            raise ValueError("W must be null when window_checked is false")
        if self.window_checked and self.W is None:
            raise ValueError("window_checked is true but W is null")
        return self


class RoomGroup(_Model):
    group_id: str
    photos: list[str]
    accounts: list[str] = []
    scan_id: Optional[str] = None       # null when the group matches no scan
    details: list[str] = []
    outside_ring: list[str] = []        # accounts in the group that are not ring members


class MatchZone(_Model):
    zone_id: str
    attempt: int = 1
    threshold: float = Unit
    best_P: float = Unit
    above_threshold: bool
    photos_used: int = Field(ge=0)
    window_photos: int = Field(ge=0)
    matches: list[Match] = []
    room_groups: list[RoomGroup] = []


class MatchesFile(_Model):
    case_id: str
    ring_id: str
    zones: list[MatchZone] = []


# ---------- brief.json (Briefer) ----------
class Factors(_Model):
    R: float = Unit
    Z: float = Unit
    F: float = Unit
    P: float = Unit
    W: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class Lead(_Model):
    rank: int = Field(ge=1)
    property_id: str
    # What the UI and summary show, e.g. "Building A (synthetic case)". Never a street address.
    display_name: str = Field(min_length=1)
    address: str                        # internal only (from CoStar); never rendered
    zone_id: str
    tier: Tier
    score: int = Field(ge=0, le=100)
    factors: Factors
    reasons: list[str] = []
    caps: list[str] = []
    verify_next: list[str] = []


class Brief(_Model):
    case_id: str
    ring_id: Optional[str] = None
    status: Literal["complete", "weak_ring_zone_only", "no_ring", "partial"]
    leads: list[Lead] = []
    zones: list[str] = []               # zone ids covered (the only output for a weak ring)
    failed_steps: list[str] = []
    decisions: list[str] = []
    summary: str = ""                   # plain-language case summary (written by the supervisor LLM)
    # "template": reasons are the Briefer's fixed wording. "llm": the supervisor rewrote the
    # reasons, next checks and summary. Tiers, scores and caps are always computed by code.
    text_source: Literal["template", "llm"] = "template"
    footer: str


# ---------- log.jsonl ----------
class LogEntry(_Model):
    ts: str
    case_id: str
    actor: Literal["supervisor", "scripted", "llm", "guard", "agent"]
    event: Literal["run_start", "tool_call", "tool_result", "validation_failed",
                   "step_failed", "refused", "decision", "run_end"]
    step: Optional[str] = None
    decision: Optional[str] = None
    evidence: dict[str, Any] = {}
    message: str = ""
    input_hash: Optional[str] = None
    output_file: Optional[str] = None


FILE_MODELS: dict[str, type[BaseModel]] = {
    "input.json": CaseInput,
    "flagged_accounts.json": FlaggedAccountsFile,
    "rings.json": RingsFile,
    "zones.json": ZonesFile,
    "candidates.json": CandidatesFile,
    "matches.json": MatchesFile,
    "brief.json": Brief,
}

__all__ = [n for n, v in list(globals().items())
           if isinstance(v, type) and issubclass(v, BaseModel) and not n.startswith("_")] + [
    "FILE_MODELS", "KeyKind", "Tier"]
