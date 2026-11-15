"""Topology: the combinatorial complex by rank, its scores, and evaluation if recorded."""
from __future__ import annotations

from ._base import chart, fmt, not_recorded, step, table


def build(ctx) -> list:
    cx = ctx.load("complex.json")
    src = ctx.src("complex.json")
    if not cx or not cx.get("ranks"):
        return [not_recorded("final", "Combinatorial complex", "no complex.json in this case", src)]
    ranks = cx["ranks"]
    keys = sorted(ranks)
    steps = [step("ranks", "Cells by rank", "chart",
                  chart([f"rank {r}" for r in keys], [{"label": "cells", "data": [len(ranks[r]) for r in keys]}]),
                  "Rank 0: accounts and identifiers. Rank 1: shared keys. Rank 2: groups. Rank 3: the ring.", src)]
    rows = [[c.get("id"), r, c.get("kind"), len(c.get("members", [])), c.get("reason") or "—"]
            for r in keys if r != "0" for c in ranks[r]][:60]
    if rows:
        steps.append(step("cells", "Higher cells and why they exist", "table",
                          table(["cell", "rank", "kind", "members", "reason"], rows), "Each cell's reason as written.", src))
    sc = cx.get("scores") or {}
    if sc:
        items = sorted(sc.items(), key=lambda kv: -(kv[1] or 0))[:20]
        steps.append(step("scores", f"Model scores{' · ' + cx['model'] if cx.get('model') else ''}", "chart",
                          chart([k for k, _ in items], [{"label": "score", "data": [v for _, v in items]}], horizontal=True),
                          "P(in a ring) from the topological model.", src))
    ev = {k: cx.get(k) for k in ("ablation", "test_split", "held_out", "metrics") if cx.get(k)}
    if ev:
        rows = [[k, str(v)[:120]] for k, v in ev.items()]
        steps.append(step("eval", "Evaluation", "table", table(["what", "result"], rows), "As recorded.", src))
    else:
        steps.append(not_recorded("eval", "Evaluation (ablation, test split, held-out)",
                                  f"{len(sc)} scores recorded, no evaluation", src))
    return steps
