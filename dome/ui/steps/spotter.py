"""Spotter: accounts scanned, signal heatmap, kinds-count histogram with the cut at 3, ranked queue."""
from __future__ import annotations

from collections import Counter

from ._base import chart, fmt, not_recorded, step, table


def build(ctx) -> list:
    sp = ctx.load("spotter.json")
    src = ctx.src("spotter.json")
    accounts = ctx.load_data("data/synth/accounts.json")
    n_acc = len(accounts) if isinstance(accounts, (list, dict)) else None
    if not sp:
        return [not_recorded("final", "Spotter", "no spotter.json in this case", src,
                             [f"{n_acc} synthetic accounts in data/synth/accounts.json"] if n_acc else [])]
    queue = sp.get("queue", []) if isinstance(sp, dict) else sp
    rule = sp.get("flag_rule") if isinstance(sp, dict) else None
    scores = (ctx.load("complex.json") or {}).get("scores") or {}
    steps = []
    if n_acc:
        steps.append(step("scanned", "Accounts scanned", "text",
                          {"text": f"{n_acc} accounts scanned → {len(queue)} in the queue",
                           "bullets": [rule] if rule else []},
                          "Every synthetic account is scored on public signals.", ["data/synth/accounts.json", src]))
    kinds = sorted({s["kind"] for q in queue for s in q.get("signals", [])})
    if kinds:
        rows = [[q["account"]] + ["●" if any(s["kind"] == k for s in q.get("signals", [])) else "" for k in kinds]
                for q in queue]
        steps.append(step("heatmap", "Signals per account", "table", table(["account"] + kinds, rows),
                          "Which signal kinds fired for each queued account.", src))
    counts = Counter(len({s["kind"] for s in q.get("signals", [])}) for q in queue)
    if counts:
        ks = list(range(1, max(counts) + 1))
        steps.append(step("kinds", "How many different signal kinds agree", "chart",
                          chart([str(k) for k in ks], [{"label": "accounts", "data": [counts.get(k, 0) for k in ks]}],
                                threshold={"value": None, "label": "cut at 3"}, highlight=[i for i, k in enumerate(ks) if k >= 3],
                                x="signal kinds", y="accounts"),
                          rule or "Flagged only when at least 3 different signal kinds agree (highlighted).", src))
    rows = [[q.get("rank"), q["account"], fmt(q.get("score")), fmt(scores.get(q["account"]))] for q in queue]
    steps.append(step("queue", "Ranked queue", "table", table(["rank", "account", "score", "model"], rows),
                      "Model column from complex.json scores when present.", [src, ctx.src("complex.json")]))
    return steps
