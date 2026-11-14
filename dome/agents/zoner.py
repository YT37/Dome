"""Zoner (Ishaan): where is the ring active, as an area?  -> zones.json

STUB so the pipeline runs. Place clues give an AREA (the dome), never an address.
"""
from __future__ import annotations

import copy

from ..case import Case
from ..data_tools import _stub


def run(case: Case) -> dict:
    ring = case.selected_ring()
    if ring is None:
        raise ValueError("no ring in rings.json; the Zoner needs a ring")
    return {"case_id": case.case_id, "ring_id": ring.ring_id,
            "zones": copy.deepcopy(_stub.scenario()["zones"])}


if __name__ == "__main__":
    from . import cli
    cli("zoner", "zones.json", run)
