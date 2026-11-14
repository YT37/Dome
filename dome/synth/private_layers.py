"""v2 synthetic private layers: messages.json + transactions.json, with the ring patterns hidden.

ALL SYNTHETIC: 555 numbers, made-up handles and wallets, fictional motels. The generator reads
the answer key to know who is in which ring (it is the generator; agents never read the key)
and writes a separate answer_key_private.json so the Linker's v2 patterns can be scored.

    python -m dome.synth.private_layers --data data/synth --key data/answer_key/answer_key.json
    python -m dome.synth.private_layers --data samples/data/mini --key samples/data/mini/answer_key.json

Ishaan owns the synthetic data: if his generator emits these files, his win. Formats follow
dome/DATA_FORMATS_FOR_ISHAAN.md.

Planted in Ring A (patterns from that file):
  1 shared wallet    workers tell buyers to pay the collector's handle; members pay the collector
  2 DMs              members message the hub and each other with instructions / money talk
  4 chat details     phones, handles, the motel name and "room 214, 9 PM" inside messages
  5 relay race       phone moves X -> Y two days after X stops; Y's wallet moves to Z (X, Z never overlap)
  6 heartbeat        3 accounts take turns by day, same daily rhythm, quiet 3-9 AM local
  7 money shape      1 collector, 1 handler (motel + rideshare + phone top-up), 1 recruiter, 1 hub
  8 echo events      ad -> buyer message -> reply with time/place -> payment -> ride, inside 90 min
  9 same merchant    ring payments go to one motel ~300 m from the true building
Hard negatives: friend group (overlapping DMs, no wallet), rental hosts (own handles), busy
motel (many unrelated accounts pay the same motel), delivery driver (short messages, rides).
Ring C: messages and payments with no place in them (fires the "no location hints" decision).
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

MOTEL = {"name": "Lone Star Motel (synthetic)", "category": "lodging", "area": "Downtown, Houston",
         "lat": 29.7628, "lon": -95.3668}
RIDE = {"name": "Rideshare", "category": "rideshare", "area": "Downtown, Houston",
        "lat": 29.7619, "lon": -95.3655}
TOPUP = {"name": "QuickTop Mobile (synthetic)", "category": "telecom", "area": "", "lat": None,
         "lon": None}
CLEAN = {"name": "SparkleClean Services (synthetic)", "category": "other", "area": "Houston",
         "lat": None, "lon": None}
B_MERCH = [{"name": "Gulf Inn (synthetic)", "category": "lodging", "area": "Midtown, Houston",
            "lat": 29.7440, "lon": -95.3780},
           {"name": "Westside Suites (synthetic)", "category": "lodging", "area": "Galleria, Houston",
            "lat": 29.7370, "lon": -95.4610}]

WALLET = "$sunny_rose5"
RELAY_PHONE = "555-0199"
RELAY_WALLET = "$velvet_k9"


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:00Z")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Gen:
    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self.msgs, self.txs = [], []
        self.n_msg, self.n_tx, self.n_ext = 3000, 5000, 100

    def ext(self) -> str:
        self.n_ext += 1
        return f"ext_{self.n_ext}"

    def msg(self, a, b, t, text) -> str:
        self.n_msg += 1
        mid = f"msg_{self.n_msg}"
        self.msgs.append({"msg_id": mid, "from": a, "to": b, "time": iso(t), "text": text})
        return mid

    def tx(self, a, b, amount, t, merchant=None) -> str:
        self.n_tx += 1
        tid = f"tx_{self.n_tx}"
        self.txs.append({"tx_id": tid, "from": a, "to": b, "amount": round(amount, 2), "time": iso(t),
                         "merchant": dict(merchant) if merchant else None})
        return tid


def load(data: Path, key_path: Path):
    posts = json.loads((data / "posts.json").read_text(encoding="utf-8"))
    accounts = json.loads((data / "accounts.json").read_text(encoding="utf-8"))
    key = json.loads(key_path.read_text(encoding="utf-8"))
    rings = key.get("rings") or {k: v for k, v in key.items() if isinstance(v, dict) and "members" in v}
    hn = key.get("hard_negatives", {})
    acct_ids = [a.get("account_id") or a["handle"] for a in accounts]
    for p in posts:
        p["account"] = p.get("account") or p.get("account_id") or p.get("handle")
    return posts, acct_ids, rings, hn


def plant_ring_a(g: Gen, members: list[str], recruiters: list[str], posts: list[dict],
                 t0: datetime, days: int) -> dict:
    rng = g.rng
    M = sorted(members)
    collector, handler, hub = M[0], M[1], M[2]
    shift = M[3:6]
    rx, ry, rz = M[6], M[7], M[8] if len(M) > 8 else M[-1]
    workers = [m for m in M if m not in (collector, handler)]
    roles = {collector: "collector", handler: "handler", hub: "hub"}
    if recruiters:
        roles[recruiters[0]] = "recruiter"

    # 1 + 2: shared wallet. The collector announces it; workers send buyers to it.
    g.msg(collector, hub, t0 + timedelta(hours=20), f"new payout is cashapp {WALLET}, tell the girls")
    for w in workers[:8]:
        for k in range(3):
            t = t0 + timedelta(days=rng.randint(1, days - 2), hours=rng.randint(18, 23),
                               minutes=rng.randint(0, 59))
            buyer = g.ext()
            g.msg(buyer, w, t, "saw your ad, are you free tonight")
            g.msg(w, buyer, t + timedelta(minutes=4),
                  rng.choice([f"deposit first, then address. cashapp {WALLET}",
                              f"pay first then i send the address. {WALLET}"]))
            g.tx(buyer, WALLET, rng.choice([100, 150, 200]), t + timedelta(minutes=25))
    # members pay the collector directly ("send me the 40"); collector pays nothing out to members
    for w in workers[:6]:
        t = t0 + timedelta(days=rng.randint(2, days - 1), hours=3, minutes=rng.randint(0, 59))
        g.msg(collector, w, t - timedelta(minutes=30), "send me the 40 for the room tonight")
        g.tx(w, collector, rng.choice([40, 60, 80]), t)
    # 2: DMs to the hub (most members report to it), with instructions
    for w in M:
        if w == hub:
            continue
        for k in range(2):
            t = t0 + timedelta(days=rng.randint(0, days - 1), hours=rng.randint(17, 23))
            g.msg(w, hub, t, rng.choice(["new ad up", "done for tonight, sending the deposit",
                                         "room is ready", "need a ride at 9"]))
        g.msg(hub, w, t + timedelta(minutes=6), "ok. send the money to the usual")

    # 7: handler pays the motel, rideshare and a phone top-up
    for d in range(0, days, 3):
        t = t0 + timedelta(days=d, hours=19, minutes=rng.randint(0, 50))
        g.tx(handler, "merch_lonestar", 89.0, t, MOTEL)
        if d % 6 == 0:
            g.tx(handler, "merch_quicktop", 25.0, t + timedelta(hours=1), TOPUP)
    # 7: recruiter messages strangers first
    if recruiters:
        for k in range(6):
            t = t0 + timedelta(days=rng.randint(0, days - 1), hours=15)
            g.msg(recruiters[0], g.ext(), t, "hi! we are a modelling agency hiring now, good pay, "
                                             "travel included")

    # 5: relay race. RELAY_PHONE on X (early), then on Y two days after X stops; then Y's wallet
    # moves to Z. X and Z never overlap.
    span = max(days, 12)
    x_end = t0 + timedelta(days=span * 0.25)
    y_start = x_end + timedelta(days=2)
    y_end = t0 + timedelta(days=span * 0.6)
    z_start = y_end + timedelta(days=2)
    handoffs = []
    for k in range(3):
        g.msg(rx, g.ext(), t0 + timedelta(days=k * (span * 0.25) / 3, hours=21),
              f"text me at {RELAY_PHONE}")
    g.msg(rx, g.ext(), x_end, f"text me at {RELAY_PHONE}")
    for k in range(3):
        g.msg(ry, g.ext(), y_start + timedelta(hours=k * 20), f"new number {RELAY_PHONE}, text me")
    for k in range(3):
        g.msg(ry, g.ext(), y_start + timedelta(hours=10 + k * 30), f"pay {RELAY_WALLET} first")
        g.tx(g.ext(), RELAY_WALLET, 120, y_start + timedelta(hours=10 + k * 30, minutes=20))
    g.msg(ry, g.ext(), y_end, f"pay {RELAY_WALLET} first")
    for k in range(3):
        g.msg(rz, g.ext(), z_start + timedelta(hours=k * 26), f"deposit to {RELAY_WALLET} then address")
        g.tx(g.ext(), RELAY_WALLET, 120, z_start + timedelta(hours=k * 26, minutes=15))
    handoffs = [{"key": f"contact:{RELAY_PHONE}", "from": rx, "to": ry},
                {"key": f"money:{RELAY_WALLET}", "from": ry, "to": rz}]

    # 6: heartbeat. Shift accounts take turns by day; same rhythm, quiet 3-9 AM local (8-14 UTC).
    active_hours = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7]
    n_days = max(days, 15)
    for d in range(n_days * 2):
        who = shift[d % 3]
        day = t0 + timedelta(days=d % n_days)
        for h in active_hours[::2]:   # the same rhythm every shift: 6 PM, 8 PM ... 6 AM UTC
            t = day + timedelta(hours=h, minutes=rng.randint(0, 59))
            buyer = g.ext()
            g.msg(buyer, who, t - timedelta(minutes=2), "you free?")
            g.msg(who, buyer, t, rng.choice(["available tonight", "hey, still looking?",
                                             "yes", "ok see you soon"]))

    # 8: echo events built on real ring ad posts
    ads = sorted((p for p in posts if p["account"] in workers
                  and (p.get("phones") or "555" in p.get("text", ""))),
                 key=lambda p: p["time"])
    picks = ads[1::max(1, len(ads) // 4)][:4] if ads else []
    events = []
    for i, p in enumerate(picks):
        t = parse(p["time"])
        w, buyer = p["account"], g.ext()
        m1 = g.msg(buyer, w, t + timedelta(minutes=3), "saw your ad. tonight?")
        m2 = g.msg(w, buyer, t + timedelta(minutes=7),
                   f"deposit first. {WALLET}. Lone Star Motel, room 214, 9 PM")
        tx1 = g.tx(buyer, WALLET, 150, t + timedelta(minutes=26))
        m3 = g.msg(handler, w, t + timedelta(minutes=35), "ride booked, room 214")
        tx2 = g.tx(handler, "merch_lonestar", 89.0, t + timedelta(minutes=40), MOTEL)
        tx3 = g.tx(handler, "merch_ride", 18.5, t + timedelta(minutes=75), RIDE)
        events.append({"post": p["post_id"], "messages": [m1, m2, m3], "payments": [tx1, tx2],
                       "rides": [tx3]})
    return {"members": M, "roles": roles, "wallets": [WALLET, RELAY_WALLET],
            "handoffs": handoffs, "heartbeat_groups": [shift], "events": events,
            "merchants": [MOTEL["name"]], "hidden_room_account": None}


def plant_ring_b(g: Gen, members, t0, days) -> dict:
    rng, M = g.rng, sorted(members)
    collector, handler = M[0], M[1]
    for w in M[2:]:
        for k in range(2):
            t = t0 + timedelta(days=rng.randint(0, days - 1), hours=21)
            buyer = g.ext()
            g.msg(w, buyer, t, "deposit first. cashapp $bluebell_22")
            g.tx(buyer, "$bluebell_22", 120, t + timedelta(minutes=20))
        g.msg(w, collector, t + timedelta(hours=1), "sent the deposit")
        g.tx(w, collector, 50, t + timedelta(hours=2))
    g.msg(collector, M[2], t0 + timedelta(hours=5), "payout is $bluebell_22")
    for k, m in enumerate(B_MERCH * 3):
        g.tx(handler, "merch_b" + str(k % 2), 79.0, t0 + timedelta(days=k, hours=20), m)
    g.tx(handler, "merch_ride", 15.0, t0 + timedelta(days=1, hours=22), dict(RIDE, lat=29.745, lon=-95.379,
                                                                         area="Midtown, Houston"))
    g.tx(handler, "merch_quicktop", 25.0, t0 + timedelta(days=2), TOPUP)
    return {"members": M, "roles": {collector: "collector", handler: "handler"},
            "wallets": ["$bluebell_22"], "merchants": [m["name"] for m in B_MERCH]}


def plant_ring_c(g: Gen, members, t0, days) -> dict:
    """Messages and payments with NO place in them: no merchant area, no chat place."""
    rng, M = g.rng, sorted(members)
    for w in M[1:]:
        for k in range(2):
            t = t0 + timedelta(days=rng.randint(0, days - 1), hours=22)
            g.msg(w, M[0], t, "sent it, check the app")
            g.tx(w, M[0], 60, t + timedelta(minutes=5))
    return {"members": M, "roles": {M[0]: "collector"}, "wallets": [], "no_place": True}


def plant_negatives(g: Gen, hn: dict, acct_ids: list[str], ring_members: set, t0, days) -> None:
    rng = g.rng
    friends = (hn.get("friend_group") or hn.get("friend_groups") or [])[:8]
    # friend group: chatty, conversational (replies within minutes), overlapping, no wallet
    for d in range(days):
        for k in range(3):
            a, b = rng.sample(friends, 2) if len(friends) >= 2 else (None, None)
            if not a:
                break
            t = t0 + timedelta(days=d, hours=rng.choice([0, 1, 2, 3, 22, 23]), minutes=rng.randint(0, 50))
            g.msg(a, b, t, rng.choice(["lol", "are you coming tonight?", "send me the pics from saturday",
                                       "omw", "haha yes"]))
            g.msg(b, a, t + timedelta(minutes=rng.randint(1, 3)), rng.choice(["yes!", "ok", "lmao", "see you"]))
    # rental hosts: each host has its own handle; guests pay it; host pays a cleaner
    for i, h in enumerate((hn.get("rental_host") or hn.get("rental_hosts") or [])[:8]):
        handle = f"$stays_host{i}"
        for k in range(4):
            t = t0 + timedelta(days=rng.randint(0, days - 1), hours=16)
            guest = g.ext()
            g.msg(h, guest, t, f"booking confirmed. pay {handle} for the cleaning fee")
            g.tx(guest, handle, 60, t + timedelta(minutes=30))
        g.tx(h, "merch_sparkle", 45, t0 + timedelta(days=rng.randint(0, days - 1)), CLEAN)
    # busy motel: many unrelated background accounts pay the same motel
    background = [a for a in acct_ids if a not in ring_members][::7][:30]
    for a in background:
        g.tx(a, "merch_lonestar", 89.0, t0 + timedelta(days=rng.randint(0, days - 1), hours=rng.randint(0, 23)),
             MOTEL)
    # delivery driver: short messages to strangers, lots of rideshare-like payments
    for drv in (hn.get("delivery_driver") or [])[:3]:
        for k in range(12):
            t = t0 + timedelta(days=rng.randint(0, days - 1), hours=rng.randint(9, 18))
            g.msg(drv, g.ext(), t, rng.choice(["here", "outside", "at the gate"]))
            g.tx(drv, "merch_ride", 12.0, t + timedelta(minutes=2), RIDE)


def generate(data: Path, key_path: Path, seed: int = 7) -> dict:
    posts, acct_ids, rings, hn = load(data, key_path)
    times = sorted(p["time"] for p in posts if p.get("time"))
    t0 = parse(times[0]).replace(hour=0, minute=0)
    days = max(3, (parse(times[-1]) - t0).days)
    g = Gen(seed)
    ring_members = {m for r in rings.values() for m in r.get("members", [])}
    key: dict = {"synthetic": True, "rings": {}}
    for name, r in sorted(rings.items()):
        members = [m for m in r.get("members", []) if m not in (r.get("recruiters") or [])]
        if name == "A":
            key["rings"][name] = plant_ring_a(g, members, r.get("recruiters") or [], posts, t0, days)
        elif name == "B":
            key["rings"][name] = plant_ring_b(g, members, t0, days)
        elif name == "C":
            key["rings"][name] = plant_ring_c(g, members, t0, days)
    plant_negatives(g, hn, acct_ids, ring_members, t0, days)
    g.msgs.sort(key=lambda m: (m["time"], m["msg_id"]))
    g.txs.sort(key=lambda t: (t["time"], t["tx_id"]))
    (data / "messages.json").write_text(json.dumps(g.msgs, indent=1), encoding="utf-8")
    (data / "transactions.json").write_text(json.dumps(g.txs, indent=1), encoding="utf-8")
    out_key = key_path.parent / "answer_key_private.json"
    out_key.write_text(json.dumps(key, indent=1), encoding="utf-8")
    return {"messages": len(g.msgs), "transactions": len(g.txs), "answer_key": str(out_key)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="dome.synth.private_layers")
    ap.add_argument("--data", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    print(generate(Path(a.data), Path(a.key), a.seed))
