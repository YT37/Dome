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
    steps += relay_heartbeat_echo(ctx, ring, links, src)
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


def _hours(ctx, account):
    from datetime import datetime
    posts = ctx.load_data("data/synth/posts.json") or []
    h = [0] * 24
    for p in posts:
        if p.get("account_id") == account and p.get("time"):
            try:
                h[datetime.fromisoformat(str(p["time"]).replace("Z", "+00:00")).hour] += 1
            except ValueError:
                pass
    return h


def relay_heartbeat_echo(ctx, ring, links, src) -> list:
    """(a) relay family tree, (b) heartbeat strips for one pair, (c) one echo event as a timeline."""
    from datetime import datetime
    out = []
    relay = ring.get("relay") or []
    if relay:
        nodes, edges = {}, []
        for r in relay:
            key = r.get("key", "")
            kid = "key:" + key
            nodes[r["from"]] = {"id": r["from"], "label": r["from"], "group": 0}
            nodes[r["to"]] = {"id": r["to"], "label": r["to"], "group": 0}
            nodes[kid] = {"id": kid, "label": key, "group": 3}
            edges += [{"source": r["from"], "target": kid, "label": "last seen " + str(r.get("from_last_seen", ""))[:10]},
                      {"source": kid, "target": r["to"], "label": "first seen " + str(r.get("to_first_seen", ""))[:10]}]
        out.append(step("relay", "Relay: a phone or wallet handed from one account to the next", "graph",
                        {"nodes": list(nodes.values()), "edges": edges},
                        "; ".join(r.get("reason", "") for r in relay), src))
        out.append(step("relay_table", "Relay dates", "table",
                        table(["key", "from", "last seen there", "to", "first seen there"],
                              [[r.get("key"), r["from"], str(r.get("from_last_seen", ""))[:16], r["to"],
                                str(r.get("to_first_seen", ""))[:16]] for r in relay]),
                        "The key stops on one account and starts on the next a short time later.", src))
    else:
        out.append(step("relay", "Relay", "text", {"text": "not found in this case"}, "No key passed between accounts.", src))
    hb = [l for l in links if any(k.startswith("heartbeat:") for k in l.get("keys", []))]
    if hb:
        l = hb[0]
        why = next((p.strip() for p in l.get("reason", "").split(";") if "rhythm" in p), "")
        ha, hb_ = _hours(ctx, l["a"]), _hours(ctx, l["b"])
        out.append(step("heartbeat", f"Heartbeat: {l['a']} and {l['b']} keep the same daily rhythm", "chart",
                        chart([f"{h:02d}" for h in range(24)], [{"label": l["a"], "data": ha}, {"label": l["b"], "data": hb_}],
                              x="hour of day (UTC)", y="posts"),
                        f"{why}. {len(hb)} heartbeat pairs in this ring. Posts per hour from data/synth/posts.json.",
                        [src, "data/synth/posts.json"]))
    else:
        out.append(step("heartbeat", "Heartbeat", "text", {"text": "not found in this case"}, "No heartbeat pair.", src))
    evs = ring.get("events") or []
    if evs:
        e = max(evs, key=lambda x: len(x.get("items", [])))
        t0 = None
        rows = []
        for it in e.get("items", []):
            try:
                t = datetime.fromisoformat(str(it.get("time")).replace("Z", "+00:00"))
            except ValueError:
                t = None
            t0 = t0 or t
            rows.append([it.get("type"), it.get("ref"), str(it.get("time", ""))[11:16],
                         f"+{int((t - t0).total_seconds() // 60)} min" if t and t0 else "—"])
        out.append(step("echo", f"Echo event {e.get('event_id')}: one booking seen four ways", "table",
                        table(["what", "record", "time (UTC)", "since the ad"], rows),
                        f"{e.get('reason', '')}. Ties {', '.join(e.get('members', []))}; place hint: "
                        f"{e.get('place_hint') or 'none'} (an area, never an address). {len(evs)} echo events in this ring.",
                        src))
    else:
        out.append(step("echo", "Echo event", "text", {"text": "not found in this case"}, "No echo event.", src))
    return out
