"""Briefer: score parts per lead, the tier rules, and the decoy below threshold.

Score = 100 · R · (0.15 Z + 0.10 F + 0.45 P + 0.30 W); without W, drop it and rescale the rest to 1.
Parts are recomputed from brief.json's own factors and checked against its score.
"""
from __future__ import annotations

from ._base import chart, fmt, not_recorded, step, table

WEIGHTS = {"Z": 0.15, "F": 0.10, "P": 0.45, "W": 0.30}


def parts(f: dict) -> dict:
    w = {k: v for k, v in WEIGHTS.items() if f.get(k) is not None}
    tot = sum(w.values()) or 1
    R = f.get("R") or 0
    return {k: round(100 * R * f[k] * v / tot, 1) for k, v in w.items()}


def build(ctx) -> list:
    brief = ctx.load("brief.json")
    src = ctx.src("brief.json")
    if not brief or not brief.get("leads"):
        return [not_recorded("final", "Briefer", f"status: {(brief or {}).get('status', 'no brief.json')}", src)]
    leads = brief["leads"]
    steps = []
    labels = [l.get("display_name") or l.get("property_id") for l in leads]
    ps = [parts(l.get("factors") or {}) for l in leads]
    steps.append(step("parts", "Score parts per lead", "chart",
                      chart(labels, [{"label": f"{k} ({v:.2f} · R)", "data": [p.get(k, 0) for p in ps]}
                                     for k, v in WEIGHTS.items()], stacked=True, y="score points"),
                      "Each bar is 100 · R · (0.15 Z + 0.10 F + 0.45 P + 0.30 W); a missing W is dropped and the rest "
                      "rescaled. Recorded scores: " + ", ".join(f"{lab} {l.get('score')}" for lab, l in zip(labels, leads))
                      + ".", src))
    rows = []
    for l in leads:
        f = l.get("factors") or {}
        P, W, R = f.get("P") or 0, f.get("W"), f.get("R") or 0
        high = P >= 0.6 and W is not None and W >= 0.6 and R >= 0.6
        med = (P >= 0.6 and W is None) or (0.4 <= P < 0.6 and W is not None and W >= 0.6)
        rule = "High" if high else "Medium" if med else "Low"
        rows.append([l.get("display_name") or l.get("property_id"), fmt(P), fmt(W), fmt(R),
                     "✓" if P >= 0.6 else "✗", "✓" if (W is not None and W >= 0.6) else ("not checked" if W is None else "✗"),
                     "✓" if R >= 0.6 else "✗", rule, l.get("tier")])
    steps.append(step("rules", "Tier rules", "table",
                      table(["lead", "P", "W", "R", "P ≥ 0.6", "W ≥ 0.6", "R ≥ 0.6", "rule says", "brief says"], rows),
                      "High needs P ≥ 0.6, W ≥ 0.6 and R ≥ 0.6. The score never promotes past a rule. "
                      + ("; ".join(c for l in leads for c in l.get("caps", [])) or "No caps."), src))
    # decoy: other scans below threshold
    best, zone = ctx.best_match()
    rm, rm_src = ctx.room_match()
    P = (rm or {}).get("P") or {}
    if P and best:
        thr = (zone or {}).get("threshold", 0.4)
        others = sorted(((k, v) for k, v in P.items() if k != best.get("scan_id")), key=lambda kv: -(kv[1] or 0))[:5]
        steps.append(step("decoy", "Other buildings stay below the threshold", "chart",
                          chart([best["scan_id"]] + [k for k, _ in others],
                                [{"label": "P", "data": [best.get("P") or 0] + [v or 0 for _, v in others]}],
                                threshold={"value": thr, "label": f"threshold {thr}"}, highlight=[0], y="P"),
                          f"The lead's scan against the next {len(others)} scans by P; anything under {thr} cannot "
                          f"beat Low.", [rm_src, ctx.src("matches.json")]))
    else:
        steps.append(not_recorded("decoy", "Other buildings", "only the lead's match was recorded", ctx.src("matches.json")))
    return steps
