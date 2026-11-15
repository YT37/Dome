"""Linker: notes per kind, key fan-out, candidate pairs, the two-kinds rule, clusters, money second pass.

Reads rings.json (whatever fields it has) and case/<id>/wallet_notes.json.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from ._base import chart, not_recorded, step, table


def build(ctx) -> list:
    rings = ctx.load("rings.json")
    src = ctx.src("rings.json")
    if not rings or not rings.get("rings"):
        return [not_recorded("final", "Linker", "no ring found", src)]
    ring = rings["rings"][0]
    links, hints = ring.get("links", []), rings.get("weak_hints", [])
    steps = []

    kc = ring.get("kind_counts") or dict(Counter(k for l in links for k in l.get("kinds", [])))
    if kc:
        ks = sorted(kc, key=lambda k: -kc[k])
        steps.append(step("kinds", "Notes per kind inside the ring", "chart",
                          chart(ks, [{"label": "links using this kind", "data": [kc[k] for k in ks]}]),
                          f"{ring.get('ring_id')}: {len(ring.get('members', []))} accounts, {len(links)} links. Kinds: "
                          + ", ".join(ring.get("key_kinds", [])) + ".", src))

    fan = defaultdict(set)
    for l in links + hints:
        for key in l.get("keys", []):
            fan[key].update([l["a"], l["b"]])
    shared = {}
    for l in links:
        for m in re.finditer(r"\(shared by (\d+) accounts, down-weighted\)", l.get("reason", "")):
            shared[l["reason"][:m.start()].rstrip().split(";")[-1].strip()] = int(m.group(1))
    if fan:
        top = sorted(fan.items(), key=lambda kv: -len(kv[1]))[:15]
        rows = [[k.split(":", 1)[0], k.split(":", 1)[1][:28], len(v)] for k, v in top]
        steps.append(step("fanout", "Key fan-out: common keys count for little", "table",
                          table(["kind", "key", "accounts sharing it (in this file)"], rows),
                          "A key shared by many accounts is down-weighted by inverse frequency"
                          + (f" (rings.json notes: {', '.join(f'{k} shared by {n}' for k, n in list(shared.items())[:3])})"
                             if shared else "") + ". Fan-out counted from the links and hints in rings.json.", src))

    nodes = sorted({a for l in links + hints for a in (l["a"], l["b"])})
    members = set(ring.get("members", []))
    g_nodes = [{"id": a, "label": a, "group": 0 if a in members else 6} for a in nodes]
    g_edges = [{"source": l["a"], "target": l["b"], "style": "strong"} for l in links] + \
              [{"source": l["a"], "target": l["b"], "style": "dashed"} for l in hints[:150]]
    steps.append(step("pairs", "Candidate pairs: links and one-kind hints", "graph",
                      {"nodes": g_nodes, "edges": g_edges},
                      f"Solid: {len(links)} pairs sharing two or more kinds of key. Dashed: {len(hints)} pairs sharing "
                      f"only one kind (a hint, never a link).", src))
    nk = Counter(len(set(l.get("kinds", []))) for l in links + hints)
    ks = sorted(nk)
    steps.append(step("two_kinds", "The two-kinds rule", "chart",
                      chart([str(k) for k in ks], [{"label": "pairs", "data": [nk[k] for k in ks]}],
                            highlight=[i for i, k in enumerate(ks) if k >= 2], x="different kinds shared", y="pairs"),
                      "Two accounts link only if they share at least two different kinds of key (highlighted).", src))
    roles = {r["account"]: r for r in ring.get("roles", []) + ring.get("recruiters", [])}
    rows = [[a, roles.get(a, {}).get("role") or ("recruiter" if a in roles else "member"),
             roles.get(a, {}).get("reason", "")] for a in ring.get("members", [])]
    steps.append(step("clusters", f"{ring.get('ring_id')}: the cluster", "table",
                      table(["account", "role", "why"], rows),
                      f"Leiden clustering over the links; ring confidence R {ring.get('confidence')}.", src))
    wn = ctx.load("wallet_notes.json")
    if wn and wn.get("notes"):
        rows = [[n.get("account"), n.get("cluster_id"), n.get("reason")] for n in wn["notes"]]
        steps.append(step("money_pass", "Money second pass: wallet notes", "table",
                          table(["account", "wallet cluster", "reason"], rows),
                          "Wallet notes add a money kind of key to accounts, then the two-kinds rule runs again.",
                          ctx.src("wallet_notes.json")))
    else:
        mk = kc.get("money")
        steps.append(not_recorded("money_pass", "Money second pass",
                                  f"money key used in {mk} links" if mk else "no money links", ctx.src("wallet_notes.json")))
    return steps
