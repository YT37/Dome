"""Model name, thresholds and weights. Change the model in one line (or env DOME_MODEL)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Read ROOT/.env (API keys, DOME_MODEL, LangSmith) before anything else reads the env.
    Values already set in the real environment win."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if k.strip() and v:
                os.environ.setdefault(k.strip(), v)


_load_dotenv()

# LangSmith tracing needs a key; without one, every trace upload fails with 401 noise.
if os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and not os.environ.get("LANGSMITH_API_KEY"):
    os.environ["LANGSMITH_TRACING"] = "false"

# Pace model calls. Free tiers have small per-minute limits (Gemini free: 5 requests/minute),
# so the supervisor waits between calls instead of failing. DOME_MAX_RPM overrides.
DEFAULT_RPM = {"google_genai": 4}


def max_rpm(provider: str) -> float | None:
    v = os.environ.get("DOME_MAX_RPM")
    if v:
        return float(v) if float(v) > 0 else None
    return DEFAULT_RPM.get(provider)

# One-line model switch, e.g. DOME_MODEL=google_genai:gemini-3.5-flash (free tier)
MODEL = os.environ.get("DOME_MODEL", "anthropic:claude-sonnet-5-5")

CASE_ROOT = Path(os.environ.get("DOME_CASE_ROOT", ROOT / "case"))
SAMPLES = ROOT / "samples"
SCENARIOS = SAMPLES / "scenarios"

# Supervisor decisions (all numbers come from deterministic code, never the LLM)
RING_MIN_CONFIDENCE = 0.4   # R below this: stop after the Zoner
MATCH_THRESHOLD = 0.4       # Locator: a scan needs P >= this to count as a match
TIER_STRONG = 0.6           # High needs P, W and R all >= this
WIDE_AREA_KM2 = 25.0        # zone is "wide" above this area
MAX_CANDIDATES = 50
MAX_WINDOW_PHOTOS_TRIED = 3   # Locator: window photos tried, in photo-id order, for W

# CoStar property types -> the three Dome compares against photo cues (others pass through)
COSTAR_TYPE_MAP = {
    "multifamily": "multifamily", "apartment": "multifamily", "apartments": "multifamily",
    "residential_condo": "multifamily", "condo": "multifamily",
    "hospitality": "hospitality", "hotel": "hospitality", "motel": "hospitality",
    "single_family": "single_family", "homes": "single_family", "house": "single_family",
    "residential_detached": "single_family", "residential_townhouse": "single_family",
}

# Linker key weights (R = 1 - prod(1 - w_k), capped)
# v2: the 10 sticky notes (text = "same script"; time = posting-time/creation-burst tie-breaker)
KEY_WEIGHTS = {"money": 0.9, "contact": 0.9, "dm": 0.85, "room": 0.8, "photo": 0.8, "device": 0.7,
               "text": 0.6, "style": 0.5, "route": 0.5, "merchant": 0.4,
               "interaction": 0.5, "heartbeat": 0.4, "echo": 0.7, "place": 0.3, "time": 0.2}
# kinds that give an area, not identity: never count toward the two-kinds rule
NON_COUNTING_KINDS = ("place", "merchant")

# v2 patterns
HEARTBEAT_MIN_EVENTS = 20     # posts + messages + payments an account needs for a rhythm
HEARTBEAT_COSINE = 0.9        # same 24-hour rhythm
HEARTBEAT_MAX_OVERLAP = 0.05  # share of 10-minute slots both are active in (taking turns)
ECHO_WINDOW_MIN = 90
RELAY_MAX_DAYS = 7
HINT_BOOST_MAX = 0.15         # Lister: max fit boost near a merchant/echo hint
HINT_BOOST_RADIUS_M = 500
# topological ring scorer (dome/agents/topo.py); off with DOME_TOPO=0, skipped if not installed
TOPO_SCORE = os.environ.get("DOME_TOPO", "1") != "0"
RING_CONFIDENCE_CAP = 0.95

# Linker tuning
EMBED_MODEL = "all-MiniLM-L6-v2"
TEXT_MIN_WORDS = 5            # shorter texts are too short to call a script
# a post is an ad (and can share a text key) if it has a contact or a booking call-to-action
AD_CALL_TO_ACTION = (r"\b(dm|direct message|message to|text me|call me|to book|bookings?|"
                     r"appointments?|serious (people|inquiries))\b")
MINHASH_THRESHOLD = 0.5       # Jaccard on word 3-shingles: near-identical copies
EMBED_THRESHOLD = 0.75        # cosine: the same script reworded
PHASH_MAX_DISTANCE = 6        # Hamming distance between 64-bit pHashes
RARE_KEY_SIZE = 20            # a key shared by many more accounts than this counts for little
MAX_KEY_FANOUT = 150          # keys shared by more accounts than this are ignored
MIN_KEY_WEIGHT = 0.05         # after down-weighting, weaker keys do not count as a kind
MIN_REPEAT_INTERACTIONS = 2   # "repeated" reposts/replies between two accounts
LOCKSTEP_SECONDS = 300
LOCKSTEP_MIN_TIMES = 3
HINT_MIN_STRENGTH = 0.15      # weaker single-kind overlaps are not even kept as hints
MAX_WEAK_HINTS = 200
LEIDEN_MIN_SIZE = 20          # Leiden only splits linked groups at least this big
RING_KIND_MIN_LINKS = 2       # a kind counts for the ring if it is on at least this many links
REQUIRE_LAYER_AGREEMENT = True  # ring needs a content kind AND a connectivity kind
RECRUITER_BIO = r"modell?ing agency|job offers?|casting call|talent scout|hiring models"
RECRUITER_MIN_SHARE = 0.6     # share of an account's reposts/replies that go into the ring
DEVICE_LAYER = False          # lawful-only layer; off in the demo

# Lister fit = type + floors + other cues
FIT_WEIGHTS = {"type": 0.5, "floors": 0.3, "cues": 0.2}

# Briefer score = 100 * R * (sum of weight * factor); W dropped and rescaled when missing
SCORE_WEIGHTS = {"Z": 0.15, "F": 0.10, "P": 0.45, "W": 0.30}

FOOTER = ("Leads for human verification. Place clues give areas, not addresses. "
          "Not evidence of anyone's presence. Generated from synthetic data.")
