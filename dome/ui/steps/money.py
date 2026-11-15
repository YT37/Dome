"""Money layer: computed from data/synth/chain/txs.json + labels.json + data/synth/posts.json.

Steps: payments to the ad platform vs ring posts; minutes from payment to the next ring post against
shuffled post times (fixed seed); clusters by shared inputs; roles and flows from the money block;
decoy wallets left unattributed. If the chain files are absent, the steps say so.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from ._base import chart, not_recorded, step, table

AD_LABELS = {"ad_platform", "adplatform", "ad platform"}


def _t(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _money_block(ctx):
    rings = ctx.load("rings.json") or {}
    return next((r.get("money") for r in rings.get("rings", []) if r.get("money")), None) or rings.get("money")


def build(ctx) -> list:
    txs = ctx.load_data("data/synth/chain/txs.json")
    labels = ctx.load_data("data/synth/chain/labels.json")
    posts = ctx.load_data("data/synth/posts.json")
    money = _money_block(ctx)
    msrc = ctx.src("rings.json")
    steps = []
    rings = ctx.load("rings.json") or {}
    members = set((rings.get("rings") or [{}])[0].get("members", []))

    if not txs or not labels:
        steps.append(not_recorded("chain", "Payments on the public ledger",
                                  "chain data not generated yet (data/synth/chain/txs.json, labels.json)",
                                  "data/synth/chain/"))
    else:
        txs = txs if isinstance(txs, list) else txs.get("txs", [])
        lab = labels if isinstance(labels, dict) else {l.get("address"): l.get("label") for l in labels}
        ad_addrs = {a for a, l in lab.items() if str(l).lower() in AD_LABELS}
        pays = sorted(t for t in (_t(x.get("time")) for x in txs
                                  if set(x.get("outputs", [x.get("to")])) & ad_addrs) if t)
        ring_posts = sorted(t for t in (_t(p.get("time")) for p in (posts or [])
                                        if p.get("account_id") in members) if t)
        if pays and ring_posts:
            days = sorted({t.date().isoformat() for t in pays + ring_posts})[:14]
            steps.append(step("timeline", "Ad-platform payments and ring posts per day", "chart",
                              chart(days, [{"label": "payments to the ad platform", "data": [sum(t.date().isoformat() == d for t in pays) for d in days]},
                                           {"label": "ring posts", "data": [sum(t.date().isoformat() == d for t in ring_posts) for d in days]}]),
                              f"{len(pays)} payments to ad-platform addresses; {len(ring_posts)} ring posts.",
                              ["data/synth/chain/txs.json", "data/synth/chain/labels.json", "data/synth/posts.json"]))

            def gaps(post_times):
                out = []
                for p in pays:
                    nxt = next((q for q in post_times if q >= p), None)
                    if nxt is not None:
                        out.append(min(int((nxt - p).total_seconds() // 60), 240))
                return out
            real = gaps(ring_posts)
            rng = random.Random(7)
            lo, hi = ring_posts[0], ring_posts[-1]
            span = (hi - lo).total_seconds()
            shuffled = sorted(lo + timedelta(seconds=rng.random() * span) for _ in ring_posts)
            fake = gaps(shuffled)
            bins = [0, 5, 10, 15, 30, 60, 120, 241]
            lbl = [f"{a}-{b - 1 if b == 241 else b} min" for a, b in zip(bins, bins[1:])]
            steps.append(step("gaps", "Minutes from payment to the next ring post", "chart",
                              chart(lbl, [{"label": "real post times", "data": [sum(a <= g < b for g in real) for a, b in zip(bins, bins[1:])]},
                                          {"label": "shuffled post times (seed 7)", "data": [sum(a <= g < b for g in fake) for a, b in zip(bins, bins[1:])]}]),
                              "If payments buy ads, real posts follow within minutes far more often than shuffled ones.",
                              ["data/synth/chain/txs.json", "data/synth/posts.json"]))
        else:
            steps.append(not_recorded("timeline", "Payments vs posts", "no ad-platform payments or ring posts found",
                                      "data/synth/chain/txs.json"))

    if money:
        wcs = money.get("wallet_clusters", [])
        steps.append(step("roles", "Wallet clusters and roles", "table",
                          table(["cluster", "role", "addresses", "confidence", "why"],
                                [[w.get("cluster_id") or w.get("id"), w.get("role"), w.get("addresses"), w.get("confidence"),
                                  "; ".join(w.get("reasons") or [w.get("reason") or ""])] for w in wcs]),
                          "Clusters come from shared inputs (common-input heuristic); roles from timing and flows.", msrc))
        fl = money.get("flows", [])
        if fl:
            g_nodes = [{"id": str(w.get("cluster_id") or w.get("id")), "label": f"{w.get('cluster_id') or w.get('id')} · {w.get('role')}",
                        "group": i} for i, w in enumerate(wcs)]
            ids = {n["id"] for n in g_nodes}
            for c in money.get("cash_out", []):
                g_nodes.append({"id": "svc:" + str(c.get("service")), "label": str(c.get("service")), "group": 5})
            edges = [{"source": f["from"], "target": f["to"], "label": f"{f.get('btc')} BTC"} for f in fl
                     if f["from"] in ids and f["to"] in ids]
            edges += [{"source": str(c.get("cluster_id")), "target": "svc:" + str(c.get("service"))}
                      for c in money.get("cash_out", []) if str(c.get("cluster_id")) in ids]
            steps.append(step("flows", "Consolidation and cash-out", "graph", {"nodes": g_nodes, "edges": edges},
                              "; ".join(f"{f['from']} → {f['to']}: {f.get('btc')} BTC in {f.get('txs')} txs" for f in fl), msrc))
        ptp = money.get("payment_then_post", [])
        if ptp:
            steps.append(step("ptp", "Payment, then post", "table",
                              table(["wallet", "paid at", "posted at", "account"],
                                    [[p.get("wallet"), p.get("paid_at"), p.get("post_at"), p.get("account")] for p in ptp]),
                              f"Attribution confidence {money.get('attribution_confidence', '—')}.", msrc))
    else:
        steps.append(not_recorded("roles", "Wallet clusters and roles", "no money block in rings.json", msrc))

    if labels and txs:
        lab = labels if isinstance(labels, dict) else {l.get("address"): l.get("label") for l in labels}
        decoys = [a for a, l in lab.items() if "decoy" in str(l).lower()]
        attributed = {str(w.get("cluster_id")) for w in (money or {}).get("wallet_clusters", [])}
        steps.append(step("decoys", "Decoy wallets stay unattributed", "text",
                          {"text": f"{len(decoys)} decoy wallets in the chain data; none attributed to the ring"
                                   if not (set(decoys) & attributed) else "a decoy wallet was attributed: check"},
                          "Wallets that look busy but never pay the ad platform before ring posts are left out.",
                          ["data/synth/chain/labels.json", msrc]))
    return steps
