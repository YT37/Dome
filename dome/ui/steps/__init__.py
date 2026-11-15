"""'Show the work' adapters (DOME_STEPS=1): one module per agent, each `build(ctx) -> dict`.

    GET /steps?case=<id>&agent=<name>
    -> {"agent", "title", "steps": [{"id", "title", "kind": image|chart|table|graph|map|text,
                                     "data", "caption", "source"}]}

Every adapter reads only the case folder, data/synth/, data/matches/ and data/demo_assets/
(never data/answer_key/). The result is scrubbed: no `address` key, street text masked.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from .. import globe
from ._base import Ctx, NOT_RECORDED, step

AGENTS = {
    "locator": "Locator · photo to room",
    "geo": "Locator · better GPS",
    "window": "Locator · window check",
    "money": "Linker · money layer",
    "linker": "Linker · notes to rings",
    "spotter": "Spotter · flagged accounts",
    "briefer": "Briefer · score and tier",
    "complex": "Topology · combinatorial complex",
    "zoner": "Zoner · the dome",
    "lister": "Lister · buildings that fit",
}


def build(case_dir: Path, agent: str, root: Path | None = None) -> dict:
    if agent not in AGENTS:
        raise KeyError(agent)
    ctx = Ctx(case_dir, root)
    try:
        mod = importlib.import_module(f".{agent}", __name__)
        steps = mod.build(ctx)
    except Exception as exc:   # one broken adapter never breaks the page
        steps = [step("error", "Could not build this view", "text",
                      {"text": f"{type(exc).__name__}: {str(exc)[:200]}", "note": NOT_RECORDED},
                      "The adapter failed on this case folder.", ctx.src(""))]
    out = {"agent": agent, "title": AGENTS[agent], "case": ctx.case, "steps": steps}
    return globe.scrub(out)
