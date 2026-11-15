"""Synthetic Bitcoin-style ledger for Ring A (contract A).

    python -m dome.synth.chain --data data/synth --key data/answer_key

Writes data/synth/chain/{services.json, transactions.json} and data/answer_key/chain_key.json.
Built from Ring A's real posting times in posts.json, so payment timing lines up with the ads.

ALL SYNTHETIC. Addresses use an obviously fake format, `syn1q` + random hex (not valid bech32),
so nothing can ever match a real wallet. No wallet appears in any post: like a real
investigation, wallets are found from behaviour (payment timing, spending inputs together).

Planted patterns (labels in chain_key.json; only eval reads them):
  advertiser   2 addresses (one owner: spent together), pay the ad platform 2-15 min before ring posts
  entry        the advertiser is topped up from a P2P exchange (prepaid-to-crypto)
  collectors   3 addresses receive buyer payments at fixed price points 0.5-3 h after ring posts
  aggregator   collectors consolidate to it every few days (inputs spent together)
  cash_out     the aggregator forwards to it; it deposits at Exchange X
Decoys: 5 honest advertisers paying the ad platform at random times, 18 ordinary users of a busy
exchange, a merchant with random customers.
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .common import load_json, save_json

SEED = 37 + 1000
PRICE_POINTS = [0.0025, 0.0040, 0.0060]          # BTC, the ring's fixed "rates"
SERVICES = {"AdPlatform": 3, "Exchange X": 4, "P2P Exchange": 2, "PayProcessor": 2, "Merchant": 1}


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Ledger:
    def __init__(self, rng: random.Random):
        self.rng, self.txs, self.used = rng, [], set()

    def addr(self) -> str:
        while True:
            a = "syn1q" + "".join(self.rng.choice("0123456789abcdef") for _ in range(32))
            if a not in self.used:
                self.used.add(a)
                return a

    def tx(self, t: datetime, inputs: list, outputs: list) -> None:
        """inputs/outputs: [(address, btc)]."""
        self.txs.append({"time": iso(t),
                         "inputs": [{"address": a, "btc": round(v, 8)} for a, v in inputs],
                         "outputs": [{"address": a, "btc": round(v, 8)} for a, v in outputs]})


def build(data_dir: Path, key_dir: Path, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    key = load_json(key_dir / "answer_key.json")
    ring = set(key["A"]["members"])
    posts = sorted((p for p in load_json(data_dir / "posts.json") if p["account_id"] in ring),
                   key=lambda p: p["time"])
    L = Ledger(rng)
    services = {name: [L.addr() for _ in range(n)] for name, n in SERVICES.items()}
    role = {a: f"service:{name}" for name, addrs in services.items() for a in addrs}

    adv = [L.addr(), L.addr()]
    collectors = [L.addr() for _ in range(3)]
    aggregator, cash_out = L.addr(), L.addr()
    for a in adv:
        role[a] = "advertiser"
    for a in collectors:
        role[a] = "collector"
    role[aggregator], role[cash_out] = "aggregator", "cash_out"
    start = parse(posts[0]["time"]) - timedelta(days=2)

    # entry: the advertiser is topped up from the P2P exchange every ~10 days
    t = start
    while t < parse(posts[-1]["time"]):
        L.tx(t, [(rng.choice(services["P2P Exchange"]), 0.05)], [(adv[0], 0.02), (adv[1], 0.02)])
        t += timedelta(days=rng.randint(8, 12))

    # advertiser pays the ad platform 2-15 min before about 60% of ring posts
    paid_posts = []
    for p in posts:
        if rng.random() < 0.6:
            pt = parse(p["time"]) - timedelta(minutes=rng.randint(2, 15))
            fee = rng.choice([0.0004, 0.0006, 0.0008])
            if rng.random() < 0.3:      # sometimes both addresses are spent together (one owner)
                L.tx(pt, [(adv[0], fee), (adv[1], 0.0005)], [(rng.choice(services["AdPlatform"]), fee), (adv[0], 0.0005)])
            else:
                a = rng.choice(adv)
                L.tx(pt, [(a, fee + 0.0001)], [(rng.choice(services["AdPlatform"]), fee), (a, 0.0001)])
            paid_posts.append({"post_id": p["post_id"], "account": p["account_id"], "paid_at": iso(pt), "post_at": p["time"]})

    # buyers pay collectors at fixed price points, 0.5-3 h after ring posts (the ring's active hours)
    buyers = [L.addr() for _ in range(14)]
    for a in buyers:
        role[a] = "buyer"
    for p in posts:
        if rng.random() < 0.55:
            bt = parse(p["time"]) + timedelta(minutes=rng.randint(30, 180))
            price = rng.choice(PRICE_POINTS)
            b = rng.choice(buyers)
            L.tx(bt, [(b, price + 0.0002)], [(rng.choice(collectors), price), (b, 0.0002)])

    # collectors consolidate to the aggregator every 3-5 days (inputs spent together)
    t = start + timedelta(days=4)
    end = parse(posts[-1]["time"]) + timedelta(days=2)
    while t < end:
        picks = rng.sample(collectors, rng.choice([2, 3]))
        amt = [round(rng.uniform(0.01, 0.03), 6) for _ in picks]
        L.tx(t, list(zip(picks, amt)), [(aggregator, sum(amt) - 0.0002)])
        t += timedelta(days=rng.randint(3, 5))

    # aggregator -> cash_out -> Exchange X, four times
    for i in range(4):
        ct = start + timedelta(days=9 + 9 * i, hours=rng.randint(0, 20))
        amt = round(rng.uniform(0.15, 0.25), 6)
        L.tx(ct, [(aggregator, amt)], [(cash_out, amt - 0.0002)])
        L.tx(ct + timedelta(hours=rng.randint(2, 10)), [(cash_out, amt - 0.0002)],
             [(rng.choice(services["Exchange X"]), amt - 0.0004)])

    # decoys: honest advertisers paying the ad platform at random times
    span = (end - start).total_seconds()
    for _ in range(5):
        d = L.addr()
        role[d] = "decoy_advertiser"
        L.tx(start, [(rng.choice(services["P2P Exchange"]), 0.03)], [(d, 0.03)])
        for _ in range(rng.randint(10, 16)):
            dt = start + timedelta(seconds=rng.uniform(0, span))
            fee = rng.choice([0.0004, 0.0006, 0.0008])
            L.tx(dt, [(d, fee + 0.0001)], [(rng.choice(services["AdPlatform"]), fee), (d, 0.0001)])
    # busy exchange: ordinary users depositing and withdrawing
    for _ in range(18):
        u = L.addr()
        role[u] = "user"
        for _ in range(rng.randint(3, 6)):
            ut = start + timedelta(seconds=rng.uniform(0, span))
            v = round(rng.uniform(0.001, 0.05), 6)
            if rng.random() < 0.5:
                L.tx(ut, [(rng.choice(services["Exchange X"]), v)], [(u, v)])
            else:
                L.tx(ut, [(u, v)], [(rng.choice(services["Exchange X"]), v - 0.0001)])
    # merchant with random customers (some through the payment processor)
    for _ in range(20):
        mt = start + timedelta(seconds=rng.uniform(0, span))
        c = L.addr()
        role[c] = "customer"
        v = round(rng.uniform(0.0005, 0.004), 6)
        via = rng.choice(services["PayProcessor"] + services["Merchant"])
        L.tx(mt, [(c, v)], [(via, v)])

    L.txs.sort(key=lambda x: x["time"])
    for i, x in enumerate(L.txs, start=1):
        x["txid"] = f"syntx{i:04d}"
    txs = [{"txid": x["txid"], **{k: x[k] for k in ("time", "inputs", "outputs")}} for x in L.txs]

    chain = data_dir / "chain"
    save_json(chain / "services.json", [{"service": n, "address": a} for n, addrs in services.items() for a in addrs])
    save_json(chain / "transactions.json", txs)
    # Agents must never read this. Scoring only (dome/eval_night.py).
    save_json(key_dir / "chain_key.json", {
        "ring": "A",
        "clusters": {"advertiser": adv, "collector": collectors, "aggregator": [aggregator], "cash_out": [cash_out]},
        "roles": role,
        "payment_then_post": paid_posts,
        "decoys": sorted(a for a, r in role.items() if r in ("decoy_advertiser", "user", "customer")),
    })
    return {"transactions": len(txs), "wallets": len(role) - sum(SERVICES.values()),
            "services": sum(SERVICES.values()), "paid_posts": len(paid_posts)}


def main():
    ap = argparse.ArgumentParser(description="Synthetic ledger for Ring A")
    ap.add_argument("--data", default="data/synth")
    ap.add_argument("--key", default="data/answer_key")
    a = ap.parse_args()
    print(build(Path(a.data), Path(a.key)))


if __name__ == "__main__":
    main()
