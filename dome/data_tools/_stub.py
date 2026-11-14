"""Loads the active stub scenario (env DOME_SCENARIO, set by dome.case.Case)."""
from __future__ import annotations

import json
import os
from functools import lru_cache

from .. import config


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    path = config.SCENARIOS / name / "scenario.json"
    if not path.exists():
        raise FileNotFoundError(f"No stub scenario '{name}' at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def scenario() -> dict:
    return _load(os.environ.get("DOME_SCENARIO", "ring_a"))
