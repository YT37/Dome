"""Money layer, computed from data/synth/chain/transactions.json + services.json + data/synth/posts.json.

Steps: ad-platform payments vs ring posts per day; minutes from payment to the next ring post against
shifted post times (fixed seed); clusters by shared inputs; roles, flows and payment-then-post from
the ring's money block (rings.json); clusters that pay the ad platform but do not line up with ring
posts stay unattributed. If the chain files are absent, the steps say so.
"""
from __future__ import annotations

import bisect
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone

from ._base import chart, not_recorded, step, table

CHAIN = "data/synth/chain/transactions.json"
SERVICES = "data/synth/chain/services.json"
POSTS = "data/synth/posts.json"
WINDOW = (2, 15)          # minutes, as dome/agents/money.py
SEED = 37


def _ts(s) -> float | None:
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _mask(addr: str) -> str:
    return f"{addr[:5]}…{addr[-4:]}" if addr and len(addr) > 12 else str(addr)


def _money_block(ctx):
    rings = ctx.load("rings.json") or {}
    return next((r.get("money") for r in rings.get("rings", []) if r.get("money")), None) or rings.get("money")


def _clusters(txs, services):
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for tx in txs:
        ins = [i["address"] for i in tx.get("inputs", []) if i["address"] not in services]
        for a in ins:
            find(a)
        for a in ins[1:]:
            parent[find(a)] = find(ins[0])
    groups = defaultdict(set)
    for a in list(parent):
        groups[find(a)].add(a)
    return groups


def _next_gap(t, sorted_posts):
    i = bisect.bisect_left(sorted_posts, t)
    return (sorted_posts[i] - t) / 60 if i < len(sorted_posts) else None


def build(ctx) -> list:
    txs = ctx.load_data(CHAIN)
    services_l = ctx.load_data(SERVICES)
    posts = ctx.load_data(POSTS) or []
    money = _money_block(ctx)
    msrc = ctx.src("rings.json") + " (ring money block)"
    rings = ctx.load("rings.json") or {}
    members = set((rings.get("rings") or [{}])[0].get("members", []))
    steps = []

    if not txs or not services_l:
        steps.append(not_recorded("chain", "Payments on the public ledger",
                                  "chain data not generated (data/synth/chain/transactions.json, services.json)",
                                  "data/synth/chain/"))
    else:
        services = {s["address"]: s["service"] for s in services_l}
        ad = {a for a, s in services.items() if s == "AdPlatform"}
        pay_t = sorted(t for t in (_ts(tx["time"]) for tx in txs
                                   if any(o["address"] in ad for o in tx.get("outputs", []))) if t)
        ring_t = sorted(t for t in (_ts(p.get("time")) for p in posts if p.get("account_id") in members) if t)
        srcs = [CHAIN, SERVICES, POSTS, ctx.src("rings.json")]
        if pay_t and ring_t:
            day = lambda t: datetime.fromtimestamp(t, timezone.utc).date().isoformat()  # noqa: E731
            days = sorted({day(t) for t in pay_t + ring_t})
            pc, rc = Counter(day(t) for t in pay_t), Counter(day(t) for t in ring_t)
            steps.append(step("timeline", "Ad-platform payments and ring posts per day", "chart",
                              chart(days, [{"label": "payments to the ad platform", "data": [pc[d] for d in days]},
                                           {"label": "ring posts", "data": [rc[d] for d in days]}], ctype="line"),
                              f"{len(pay_t)} ledger payments to the {len(ad)} ad-platform addresses; {len(ring_t)} posts "
                              f"by the {len(members)} ring accounts.", srcs))
            bins = [0, 2, 15, 30, 60, 120, 240, 10**9]
            names = ["0-2 min", "2-15 min", "15-30 min", "30-60 min", "1-2 h", "2-4 h", "later / none"]

            def hist(post_times):
                out = [0] * (len(bins) - 1)
                for t in pay_t:
                    g = _next_gap(t, post_times)
                    g = 10**8 if g is None else g
                    out[next(i for i in range(len(bins) - 1) if bins[i] <= g < bins[i + 1])] += 1
                return out
            real = hist(ring_t)
            rng = random.Random(SEED)
            span = 7 * 86400
            shifted = sorted(t + rng.uniform(-span, span) for t in ring_t)
            fake = hist(shifted)
            steps.append(step("gaps", "Minutes from each ad payment to the next ring post", "chart",
                              chart(names, [{"label": "real ring post times", "data": real},
                                            {"label": f"ring posts shifted at random (seed {SEED})", "data": fake}],
                                    highlight=[1]),
                              f"{real[1]} payments are followed by a ring post within {WINDOW[0]}-{WINDOW[1]} minutes, "
                              f"against {fake[1]} when the same posts are shifted at random.", srcs))
            groups = _clusters(txs, services)
            multi = sorted((g for g in groups.values() if len(g) > 1), key=len, reverse=True)
            pays_by_addr = Counter(i["address"] for tx in txs if any(o["address"] in ad for o in tx.get("outputs", []))
                                   for i in tx.get("inputs", []))
            nodes, edges = [], []
            for gi, g in enumerate(multi[:8]):
                addrs = sorted(g)
                for a in addrs:
                    nodes.append({"id": a, "label": _mask(a), "group": gi})
                edges += [{"source": addrs[0], "target": a} for a in addrs[1:]]
            steps.append(step("clusters", "Clusters from shared inputs", "graph", {"nodes": nodes, "edges": edges},
                              f"Addresses spent together in one transaction belong to one owner: {len(groups)} clusters, "
                              f"{len(multi)} with more than one address (largest 8 shown). Service addresses never join a "
                              f"cluster.", [CHAIN, SERVICES]))
            paying = [g for g in groups.values() if any(pays_by_addr[a] for a in g)]
            lined = 0
            for g in paying:
                ts = sorted(_ts(tx["time"]) for tx in txs if any(i["address"] in g for i in tx.get("inputs", []))
                            and any(o["address"] in ad for o in tx.get("outputs", [])))
                hits = sum(1 for t in ts if (gap := _next_gap(t, ring_t)) is not None and WINDOW[0] <= gap <= WINDOW[1])
                lined += hits >= 3
            steps.append(step("decoys", "Busy wallets that do not line up stay unattributed", "text",
                              {"text": f"{len(paying)} clusters pay the ad platform; {lined} line up with ring posts "
                                       f"3+ times; {len(paying) - lined} stay unattributed"},
                              "Paying the ad platform is normal; only repeated payment-then-post timing ties a wallet to "
                              "the ring.", srcs))
        else:
            steps.append(not_recorded("timeline", "Payments vs posts", "no ad-platform payments or ring posts found", CHAIN))

    if money:
        wcs = money.get("wallet_clusters", [])
        steps.append(step("roles", "Wallet clusters and roles", "table",
                          table(["cluster", "role", "addresses", "confidence", "why"],
                                [[w.get("cluster_id") or w.get("id"), w.get("role"), w.get("addresses"), w.get("confidence"),
                                  "; ".join(w.get("reasons") or [w.get("reason") or ""])] for w in wcs]),
                          f"Roles from the shape of the money; attribution confidence "
                          f"{money.get('attribution_confidence', '—')}. A cluster counts only at confidence ≥ 0.7.", msrc))
        fl = money.get("flows", [])
        if fl:
            ids = [str(w.get("cluster_id") or w.get("id")) for w in wcs]
            g_nodes = [{"id": i, "label": f"{i} · {w.get('role')}", "group": k} for k, (i, w) in enumerate(zip(ids, wcs))]
            for c in money.get("cash_out", []):
                g_nodes.append({"id": "svc:" + str(c.get("service")), "label": str(c.get("service")), "group": 5})
            edges = [{"source": f["from"], "target": f["to"]} for f in fl if f["from"] in ids and f["to"] in ids]
            edges += [{"source": str(c.get("cluster_id")), "target": "svc:" + str(c.get("service"))}
                      for c in money.get("cash_out", []) if str(c.get("cluster_id")) in ids]
            steps.append(step("flows", "Consolidation and cash-out", "graph", {"nodes": g_nodes, "edges": edges},
                              "; ".join(f"{f['from']} → {f['to']}: {f.get('btc')} BTC in {f.get('txs')} txs" for f in fl)
                              + "; " + "; ".join(f"{c.get('cluster_id')} → {c.get('service')} {c.get('times')} times"
                                                 for c in money.get("cash_out", [])), msrc))
        ptp = money.get("payment_then_post", [])
        if ptp:
            steps.append(step("ptp", "Payment, then post", "table",
                              table(["wallet", "paid at", "posted at", "account"],
                                    [[p.get("wallet"), p.get("paid_at"), p.get("post_at"), p.get("account")] for p in ptp[:40]]),
                              f"{len(ptp)} payment-then-post pairs recorded.", msrc))
    else:
        steps.append(not_recorded("roles", "Wallet clusters and roles", "no money block in rings.json", ctx.src("rings.json")))
    return steps
