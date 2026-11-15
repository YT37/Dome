"""Topology: the combinatorial complex by rank, account scores, model-vs-rules disagreements, held-out result.

Reads case/<id>/complex.json. The held-out result comes from complex.json["eval_structural"], else
dome/models/complex_struct_eval.json (the committed evaluation of the structural model).
Wallet, room and building nodes are in the complex but are NOT scored: no model score is shown for them.
"""
from __future__ import annotations

import json
from collections import Counter

from ._base import chart, fmt, not_recorded, step, table

EVAL_FILE = "dome/models/complex_struct_eval.json"


def _eval(ctx, cx):
    ev = cx.get("eval_structural")
    if ev:
        return ev, ctx.src("complex.json") + " (eval_structural)"
    p = ctx.root / EVAL_FILE
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")), EVAL_FILE
    return None, None


def build(ctx) -> list:
    cx = ctx.load("complex.json")
    src = ctx.src("complex.json")
    if not cx or not cx.get("ranks"):
        return [not_recorded("final", "Combinatorial complex", "no complex.json in this case", src)]
    ranks = cx["ranks"]
    keys = sorted(ranks)
    unscored = set(cx.get("unscored") or [])
    steps = []
    by = {r: Counter(c.get("kind") for c in ranks[r]) for r in keys}
    steps.append(step("ranks", "Cells by rank", "chart",
                      chart([f"rank {r}" for r in keys], [{"label": "cells", "data": [len(ranks[r]) for r in keys]}]),
                      "; ".join(f"rank {r}: " + ", ".join(f"{n} {k}" for k, n in by[r].most_common(6)) for r in keys) + ".",
                      src))
    rows = [[c.get("id"), r, c.get("kind"), len(c.get("members", [])), c.get("reason") or "—"]
            for r in keys if r != "0" for c in ranks[r]]
    rows.sort(key=lambda x: (-int(x[1]), -x[3]))
    if rows:
        steps.append(step("cells", "Higher cells and why they exist", "table",
                          table(["cell", "rank", "kind", "members", "reason"], rows[:60]),
                          f"{len(rows)} higher cells; each reason as the complex builder wrote it.", src))
    sc = cx.get("scores") or {}
    if sc:
        items = sorted(sc.items(), key=lambda kv: -(kv[1] or 0))
        thr = cx.get("threshold")
        steps.append(step("scores", "Model scores: accounts only", "chart",
                          chart([k for k, _ in items], [{"label": "P(in a ring)", "data": [v for _, v in items]}],
                                threshold={"value": thr, "label": f"threshold {thr}"} if thr is not None else None,
                                horizontal=True),
                          f"{cx.get('model') or 'structural model'}. Not scored: {', '.join(sorted(unscored)) or 'none'}. "
                          f"Trained on: {cx.get('trained_on', 'not recorded')}.", src))
    dis = cx.get("disagreements") or []
    if dis:
        steps.append(step("disagreements", f"Model vs rules: {len(dis)} disagreements", "table",
                          table(["account", "rules link it", "model score", "note"],
                                [[d.get("id"), "yes" if d.get("rules") else "no", fmt(d.get("model"), 3), d.get("note", "")]
                                 for d in dis]),
                          "Where the model and the two-kinds rule disagree. The rules decide the ring; these are for an "
                          "analyst to look at.", src))
    ev, esrc = _eval(ctx, cx)
    fresh = (ev or {}).get("fresh_test")
    if fresh:
        rows = [["fresh held-out ring", fresh.get("dataset"), fresh.get("ring_found"), fmt(fresh.get("precision")),
                 fmt(fresh.get("recall")), fmt(fresh.get("auc"))]]
        for t in (ev.get("test") or []):
            rows.append(["test", t.get("dataset"), t.get("ring_found"), fmt(t.get("precision")), fmt(t.get("recall")),
                         fmt(t.get("auc"))])
        if ev.get("val"):
            v = ev["val"]
            rows.append(["validation", v.get("dataset"), v.get("ring_found"), fmt(v.get("precision")),
                         fmt(v.get("recall")), fmt(v.get("auc"))])
        steps.append(step("heldout", "Held-out result (structural model)", "table",
                          table(["split", "dataset", "ring found", "precision", "recall", "AUC"], rows, [0]),
                          "Computed on held-out rings from our own synthetic generator, not on real data. "
                          + (fresh.get("note") or "") + " " + (ev.get("protocol") or ""), esrc))
    else:
        steps.append(not_recorded("heldout", "Held-out result", f"{len(sc)} account scores recorded, no evaluation", src))
    return steps
