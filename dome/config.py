"""Model name, thresholds and weights. Change the model in one line (or env DOME_MODEL)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# One-line model switch, e.g. DOME_MODEL=openai:gpt-5.5
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

# Linker key weights (R = 1 - prod(1 - w_k), capped)
KEY_WEIGHTS = {"contact": 0.9, "photo": 0.8, "device": 0.7, "text": 0.6,
               "interaction": 0.5, "place": 0.3, "time": 0.2}
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
EXPAND_MIN_HINT = 0.3         # photo expansion uses hints at least this strong
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
