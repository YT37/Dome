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

# Lister fit = type + floors + other cues
FIT_WEIGHTS = {"type": 0.5, "floors": 0.3, "cues": 0.2}

# Briefer score = 100 * R * (sum of weight * factor); W dropped and rescaled when missing
SCORE_WEIGHTS = {"Z": 0.15, "F": 0.10, "P": 0.45, "W": 0.30}

FOOTER = ("Leads for human verification. Place clues give areas, not addresses. "
          "Not evidence of anyone's presence. Generated from synthetic data.")
