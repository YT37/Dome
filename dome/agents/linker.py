"""Linker (Avishek): which flagged accounts are one ring, and why?  -> rings.json

STUB: returns the scenario's rings. The real Linker (handoff Task 3: keys, inverse-frequency
graph, two-kinds rule, Leiden) replaces run() and keeps this signature and output shape.
"""
from __future__ import annotations

import copy

from ..case import Case
from ..data_tools import _stub


def run(case: Case, expand_weak_photos: bool = False) -> dict:
    sc = _stub.scenario()
    data = {"case_id": case.case_id, **copy.deepcopy(sc["rings"])}
    if expand_weak_photos and data["rings"]:
        want = case.input.ring_id
        ring = next((r for r in data["rings"] if r["ring_id"] == want), None) or max(
            data["rings"], key=lambda r: (r["confidence"], r["ring_id"]))
        # photos from weak-hint accounts: one key kind only, so marked "weak"
        ring["photos"] += copy.deepcopy(sc.get("weak_photos", []))
        ring["photo_expansion_used"] = True
    return data


if __name__ == "__main__":
    from . import cli
    cli("linker", "rings.json", run,
        [("--expand-weak-photos", {"action": "store_true", "dest": "expand_weak_photos"})])
