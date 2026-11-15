"""Money (Ishaan): follow the ring's money on a synthetic ledger.  -> rings.json["rings"][i]["money"]

    money.attach(case)        # called by the supervisor when DOME_MONEY=1

Reads only the case folder and the dataset (`<dataset>/chain/`); never the answer key.
Writes the money block (contract B) into the selected ring in rings.json, a copy in
case/<id>/money.json, and case/<id>/wallet_notes.json (contract G) for the Linker's second pass.

How (all deterministic, every number has a plain reason):
  1. Clusters: addresses spent together as inputs of one transaction belong to one owner.
     Labelled services (ad platform, exchanges, payment processor, merchant) never join a cluster,
     so a busy exchange can't glue strangers together.
  2. Payment-then-post: a cluster that pays the ad platform 2-15 minutes before an account posts,
     again and again, is tied to that account. Chance level = the same count after shifting the
     account's posting times at random (50 shuffles). Scored over ALL accounts' posts.
  3. Roles from the shape of the money:
       advertiser   pays the ad platform right before ring posts
       collector    receives many payments at a few repeated amounts during the ring's active hours
       aggregator   receives consolidations from collector clusters
       cash_out     receives from the aggregator and deposits at an exchange
  4. A cluster counts only at confidence >= 0.7.
No wallet is ever read from a post: like a real investigation, wallets are found from behaviour.
"""
from __future__ import annotations

import bisect
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MIN_CONFIDENCE = 0.7
WINDOW_MIN = (2, 15)            # payment 2-15 min before a post
ACTIVE_MIN = (30, 180)          # buyer payments 0.5-3 h after a ring post
SHUFFLES = 50
MIN_TIES = 3                    # an account needs 3+ payment-then-post hits to be tied to a cluster


def _t(s: str) -> float:
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def _author(p: dict) -> str:
    return p.get("account_id") or p.get("account") or p.get("handle")


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def _within(t: float, sorted_times: list[float], lo: float, hi: float) -> bool:
    """Is there a time in [t + lo, t + hi]? (binary search on a sorted list)"""
    i = bisect.bisect_left(sorted_times, t + lo)
    return i < len(sorted_times) and sorted_times[i] <= t + hi


def _hits(pay_times: list[float], post_times: list[float], lo: float, hi: float) -> int:
    """How many payments are followed by a post within [lo, hi] seconds."""
    posts = sorted(post_times)
    return sum(1 for t in pay_times if _within(t, posts, lo, hi))


def _chance(pay_times, post_times, lo, hi, rng) -> float:
    if not post_times:
        return 0.0
    week = 7 * 86400
    total = 0
    for _ in range(SHUFFLES):
        shift = rng.uniform(-week, week)
        total += _hits(pay_times, [p + shift for p in post_times], lo, hi)
    return total / SHUFFLES


def analyse(txs: list, services: dict, posts: list, ring: set, seed: int = 37) -> dict:
    """Pure function: ledger + posts + ring members -> (money block, wallet notes)."""
    rng = random.Random(seed)
    uf = _UF()
    for x in txs:
        ins = [i["address"] for i in x["inputs"] if i["address"] not in services]
        for a in ins:
            uf.find(a)
        for a in ins[1:]:
            uf.union(ins[0], a)
        for o in x["outputs"]:
            if o["address"] not in services:
                uf.find(o["address"])
    members = defaultdict(set)
    for a in list(uf.p):
        members[uf.find(a)].add(a)
    cl = lambda a: uf.find(a) if a not in services else None   # noqa: E731

    post_times = defaultdict(list)
    for p in posts:
        post_times[_author(p)].append(_t(p["time"]))
    ring_posts = sorted(t for a in ring for t in post_times.get(a, []))
    lo, hi = WINDOW_MIN[0] * 60, WINDOW_MIN[1] * 60

    # ad payments, incoming payments and flows per cluster
    ad_pay = defaultdict(list)
    incoming = defaultdict(list)                     # cluster -> [(time, amount, sender cluster)]
    flows = defaultdict(lambda: [0.0, 0])            # (from, to) -> [btc, txs]
    to_service = defaultdict(Counter)                # cluster -> Counter(service)
    for x in txs:
        t = _t(x["time"])
        senders = {cl(i["address"]) for i in x["inputs"]} - {None}
        src = next(iter(senders)) if len(senders) == 1 else None
        for o in x["outputs"]:
            a = o["address"]
            if a in services:
                if src:
                    to_service[src][services[a]] += 1
                    if services[a] == "AdPlatform":
                        ad_pay[src].append(t)
                continue
            dst = cl(a)
            if src and dst != src:
                incoming[dst].append((t, o["btc"], src, not any(i["address"] in services for i in x["inputs"])))
                flows[(src, dst)][0] += o["btc"]
                flows[(src, dst)][1] += 1

    found = {}       # cluster root -> dict
    notes, ptp = [], []

    # 1. advertisers: payment-then-post against every account
    for c, pays in ad_pay.items():
        if len(pays) < 3:
            continue
        tied = []
        for acct, times in post_times.items():
            h = _hits(pays, times, lo, hi)
            if h >= MIN_TIES:
                ch = _chance(pays, times, lo, hi, rng)
                if h >= 3 * ch + 1:
                    tied.append((acct, h, ch))
        if not tied:
            continue
        h_ring = _hits(pays, ring_posts, lo, hi)
        ch_ring = _chance(pays, ring_posts, lo, hi, rng)
        if h_ring == 0:
            continue
        conf = max(0.0, 1 - ch_ring / h_ring) * min(1.0, 0.5 + h_ring / (2 * len(pays)))
        found[c] = {"role": "advertiser", "confidence": round(conf, 2),
                    "reasons": [f"paid the ad platform 2-15 min before {h_ring} ring posts (chance level: {ch_ring:.1f})"]}
        for acct, h, ch in sorted(tied, key=lambda x: -x[1]):
            notes.append({"account": acct, "cluster_id": c, "kind": "money",
                          "reason": f"paid the ad platform 2-15 min before this account posted, {h} times (chance level {ch:.1f})"})
        for t in sorted(pays):
            post = min(((p, a) for a in ring for p in post_times.get(a, []) if lo <= p - t <= hi), default=None) \
                if _within(t, ring_posts, lo, hi) else None
            if post:
                ptp.append({"wallet": c, "paid_at": _iso(t), "post_at": _iso(post[0]), "account": post[1]})

    # 2. collectors: many payments, a few repeated amounts, during the ring's active hours
    alo, ahi = ACTIVE_MIN[0] * 60, ACTIVE_MIN[1] * 60
    for c, ins in incoming.items():
        pays = [(t, v) for t, v, src, from_wallet in ins if from_wallet and src not in found]
        if len(pays) < 5 or c in found:
            continue
        amounts = Counter(round(v, 6) for _, v in pays)
        repeated = sum(n for v, n in amounts.items() if n >= 3) / len(pays)
        times = [t for t, _ in pays]
        # payment t is "timed" if some ring post p has t - p in [alo, ahi], i.e. p in [t - ahi, t - alo]
        timed = sum(1 for t in times if _within(t, ring_posts, -ahi, -alo))
        shuffled = []
        for _ in range(SHUFFLES):
            s = rng.uniform(-7 * 86400, 7 * 86400)
            shifted = [p + s for p in ring_posts]
            shuffled.append(sum(1 for t in times if _within(t, shifted, -ahi, -alo)))
        chance = sum(shuffled) / SHUFFLES
        if timed == 0:
            continue
        conf = max(0.0, 1 - chance / timed) * repeated
        if conf >= MIN_CONFIDENCE:
            found[c] = {"role": "collector", "confidence": round(conf, 2),
                        "reasons": [f"{timed} of {len(pays)} incoming payments arrive during the ring's active hours "
                                    f"(chance level {chance:.1f}), at {sum(1 for n in amounts.values() if n >= 3)} repeated amounts"]}

    # 3. aggregator: receives consolidations from collector clusters
    collectors = {c for c, v in found.items() if v["role"] == "collector"}
    for c, ins in incoming.items():
        if c in found:
            continue
        from_coll = [x for x in ins if x[2] in collectors]
        if len(from_coll) >= 2:
            share = sum(x[1] for x in from_coll) / sum(x[1] for x in ins)
            found[c] = {"role": "aggregator", "confidence": round(min(0.99, share), 2),
                        "reasons": [f"receives {len(from_coll)} consolidations from {len({x[2] for x in from_coll})} collector cluster(s)"]}

    # 4. cash-out: receives from the aggregator, deposits at an exchange
    aggs = {c for c, v in found.items() if v["role"] == "aggregator"}
    cash = []
    for c, ins in incoming.items():
        if c in found:
            continue
        from_agg = [x for x in ins if x[2] in aggs]
        ex = {s: n for s, n in to_service[c].items() if "Exchange" in s and "P2P" not in s}
        if from_agg and ex:
            svc, n = max(ex.items(), key=lambda kv: kv[1])
            if n >= 2:
                found[c] = {"role": "cash_out", "confidence": round(min(0.99, 0.6 + 0.1 * n), 2),
                            "reasons": [f"receives from the aggregator {len(from_agg)} times and sends to {svc} deposit {n} times"]}
                cash.append((c, svc, n))

    # name clusters W-1, W-2, ... in role order; keep only confidence >= 0.7
    order = ["advertiser", "collector", "aggregator", "cash_out"]
    kept = sorted((c for c, v in found.items() if v["confidence"] >= MIN_CONFIDENCE),
                  key=lambda c: (order.index(found[c]["role"]), sorted(members[c])[0]))
    name = {c: f"W-{i}" for i, c in enumerate(kept, 1)}
    block = {
        "wallet_clusters": [{"cluster_id": name[c], "role": found[c]["role"], "addresses": len(members[c]),
                             "confidence": found[c]["confidence"], "reasons": found[c]["reasons"]} for c in kept],
        "flows": [{"from": name[a], "to": name[b], "btc": round(v[0], 4), "txs": v[1]}
                  for (a, b), v in sorted(flows.items(), key=lambda kv: (name.get(kv[0][0], ""), name.get(kv[0][1], "")))
                  if a in name and b in name],
        "cash_out": [{"cluster_id": name[c], "service": s, "times": n} for c, s, n in cash if c in name],
        "payment_then_post": [dict(x, wallet=name[x["wallet"]]) for x in ptp if x["wallet"] in name][:10],
        "attribution_confidence": round(sum(found[c]["confidence"] for c in kept) / len(kept), 2) if kept else 0.0,
    }
    wallet_notes = {"notes": [dict(n, cluster_id=name[n["cluster_id"]]) for n in notes if n["cluster_id"] in name]}
    addresses = {name[c]: sorted(members[c]) for c in kept}   # for eval only; not written to the case
    return {"money": block, "wallet_notes": wallet_notes, "addresses": addresses}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def load_chain(data_dir: Path) -> Optional[tuple[list, dict]]:
    chain = Path(data_dir) / "chain"
    if not (chain / "transactions.json").exists():
        return None
    txs = json.loads((chain / "transactions.json").read_text(encoding="utf-8"))
    services = {s["address"]: s["service"] for s in json.loads((chain / "services.json").read_text(encoding="utf-8"))}
    return txs, services


def attach(case) -> Optional[dict]:
    """Supervisor hook (DOME_MONEY=1). Returns the money block, or None if there is no ledger/ring."""
    ring = case.selected_ring()
    data = case.dataset_dir()
    chain = load_chain(data) if data else None
    if ring is None or chain is None:
        return None
    txs, services = chain
    posts = json.loads((data / "posts.json").read_text(encoding="utf-8"))
    out = analyse(txs, services, posts, set(ring.members))

    # rings.json: add the block to the selected ring (schema field added by Avishek)
    path = case.path("rings.json")
    rings = json.loads(path.read_text(encoding="utf-8"))
    for r in rings.get("rings", []):
        if r["ring_id"] == ring.ring_id:
            r["money"] = out["money"]
    path.write_text(json.dumps(rings, indent=2), encoding="utf-8")
    case.path("money.json").write_text(json.dumps(out["money"], indent=2), encoding="utf-8")
    case.path("wallet_notes.json").write_text(json.dumps(out["wallet_notes"], indent=2), encoding="utf-8")
    try:
        case.log(actor="agent", event="tool_result", step="money", output_file="rings.json",
                 evidence={"clusters": len(out["money"]["wallet_clusters"]), "notes": len(out["wallet_notes"]["notes"])},
                 message=f"money: {len(out['money']['wallet_clusters'])} wallet clusters, "
                         f"{len(out['wallet_notes']['notes'])} payment-then-post notes")
    except Exception:
        pass
    return out["money"]


if __name__ == "__main__":
    import argparse
    from ..case import Case
    ap = argparse.ArgumentParser(description="Attach the money block to a case")
    ap.add_argument("--case", required=True)
    a = ap.parse_args()
    print(json.dumps(attach(Case(a.case)), indent=2))
