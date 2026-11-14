"""v2 Linker helpers (Avishek): private sticky notes and the four patterns.

ELI5: the basic rule looks at two accounts at one moment. These look at the whole ring over
time. Every number here is deterministic code; nothing asks an LLM.

  notes   money (shared wallet / direct payment), dm (direct messages), merchant (same motel),
          room (same room, from the Locator's room groups), contact found inside messages
  relay   a phone or wallet leaves one account and shows up on another within 7 days
  heartbeat  same daily rhythm but never active at the same time (one person, many accounts)
  echo    one real event leaves traces in ads, messages, payments and rides within 90 minutes
  roles   who pays whom: collector, handler, recruiter, hub, worker

Merchant and chat places only shape the search AREA and rank buildings. They never pin a
person, and a lead still needs a photo match to beat Low. All data is synthetic.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Callable, Optional

from .. import config

MONEY_TALK = re.compile(r"\b(deposit|send|sent|pay|paid|payout|cashapp|room|ride|money|the \d+)\b", re.I)
RECRUIT_TALK = re.compile(config.RECRUITER_BIO + r"|hiring|good pay|travel included", re.I)
RIDE_CATS = {"rideshare"}
PLACE_CATS = {"lodging", "rental", "rideshare"}
HANDLER_CATS = {"lodging", "rideshare", "telecom"}


def t_(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_private(d: Path) -> tuple[list, list]:
    """messages.json and transactions.json next to accounts.json, if present (synthetic)."""
    msgs = json.loads((d / "messages.json").read_text(encoding="utf-8")) if (d / "messages.json").exists() else []
    txs = json.loads((d / "transactions.json").read_text(encoding="utf-8")) if (d / "transactions.json").exists() else []
    return msgs, txs


def money_handles(txs: list, accounts: dict) -> set[str]:
    """Handles/wallets that receive money (not accounts, not merchants), lower-case."""
    return {t["to"].lower() for t in txs
            if t["to"] not in accounts and not t.get("merchant") and not t["to"].startswith("merch_")}


# ------------------------------------------------------------------ notes from the private layers
def private_notes(ds: dict, index: dict, key_times: dict, add: Callable, extract_contacts: Callable,
                  rarity: Callable) -> dict:
    """Adds contact/money/merchant keys to `index` and dm/money pair links via `add`.
    Returns facts the patterns reuse."""
    W = config.KEY_WEIGHTS
    accounts, msgs, txs = ds["accounts"], ds.get("messages") or [], ds.get("transactions") or []
    handles = money_handles(txs, accounts)
    owners = defaultdict(set)            # handle -> accounts that tell people to pay it

    def note(kind, key, acct, when):
        index[(kind, key)].add(acct)
        key_times[key][acct].append(when)

    for m in msgs:
        a = m["from"]
        if a not in accounts:
            continue
        for k in extract_contacts(m.get("text", "")):
            h = k.split(":", 1)[1]
            if h in handles:
                note("money", "money:" + h, a, m["time"])
                owners[h].add(a)
            else:
                note("contact", k, a, m["time"])
    for p in ds["posts"]:
        if p["account"] not in accounts:
            continue
        for k in extract_contacts(p.get("text", ""), p.get("phones") or []):
            h = k.split(":", 1)[1]
            if h in handles:
                note("money", "money:" + h, p["account"], p["time"])
                owners[h].add(p["account"])
    for t in txs:
        mer = t.get("merchant")
        if mer and t["from"] in accounts and (mer.get("lat") is not None or mer.get("category") in PLACE_CATS):
            note("merchant", "merchant:" + re.sub(r"\W+", "_", mer["name"].lower()).strip("_"),
                 t["from"], t["time"])
        if t["from"] in accounts and t["to"] in accounts:   # a direct payment between flagged accounts
            add(t["from"], t["to"], "money", W["money"], f"money:direct_{t['tx_id']}",
                "paid each other directly")

    # direct messages: repeated, or any message with instructions/money talk
    pair_msgs = defaultdict(list)
    partners = defaultdict(set)
    for m in msgs:
        a, b = m["from"], m["to"]
        if a in accounts and b in accounts and a != b:
            pair_msgs[(min(a, b), max(a, b))].append(m)
            partners[a].add(b)
            partners[b].add(a)
    for (a, b), ms in sorted(pair_msgs.items()):
        talk = [m for m in ms if MONEY_TALK.search(m.get("text", ""))]
        if len(ms) < 2 and not talk:
            continue
        scale = min(rarity(len(partners[a])), rarity(len(partners[b])))
        w = W["dm"] * (1.0 if talk else 0.5) * scale
        why = f"{len(ms)} direct messages" + (f", {len(talk)} with instructions or money talk" if talk else "")
        add(a, b, "dm", w, f"dm:{a}~{b}", why)
    return {"handles": handles, "owners": owners, "dm_pairs": pair_msgs}


# ------------------------------------------------------------------ heartbeat
def account_events(ds: dict, private: bool) -> dict[str, list[datetime]]:
    ev = defaultdict(list)
    for p in ds["posts"]:
        if p.get("time"):
            ev[p["account"]].append(t_(p["time"]))
    if private:
        for m in ds.get("messages") or []:
            ev[m["from"]].append(t_(m["time"]))
        for t in ds.get("transactions") or []:
            ev[t["from"]].append(t_(t["time"]))
    return {a: sorted(v) for a, v in ev.items() if a in ds["accounts"]}


def heartbeat_links(ds: dict, private: bool, add: Callable) -> list[tuple[str, str, float, float]]:
    """Same 24-hour rhythm (cosine >= 0.9) but almost never active in the same 10 minutes."""
    ev = {a: v for a, v in account_events(ds, private).items() if len(v) >= config.HEARTBEAT_MIN_EVENTS}
    hist, buckets = {}, {}
    for a, ts in ev.items():
        h = [0.0] * 24
        for t in ts:
            h[t.hour] += 1
        n = math.sqrt(sum(x * x for x in h)) or 1.0
        hist[a] = [x / n for x in h]
        buckets[a] = {int(t.timestamp() // 600) for t in ts}
    found = []
    for a, b in combinations(sorted(ev), 2):
        cos = sum(x * y for x, y in zip(hist[a], hist[b]))
        if cos < config.HEARTBEAT_COSINE:
            continue
        overlap = len(buckets[a] & buckets[b]) / max(1, min(len(buckets[a]), len(buckets[b])))
        if overlap < config.HEARTBEAT_MAX_OVERLAP:
            add(a, b, "heartbeat", config.KEY_WEIGHTS["heartbeat"], f"heartbeat:{a}~{b}",
                f"same daily rhythm (cosine {cos:.2f}) but active together in only "
                f"{overlap:.0%} of 10-minute slots: takes turns")
            found.append((a, b, round(cos, 3), round(overlap, 3)))
    return found


# ------------------------------------------------------------------ echo events
def echo_events(ds: dict, is_ad: Callable, handles: set) -> list[dict]:
    """Group ads, messages, payments and rides within 90 minutes that share a participant.
    Keep groups with >= 3 items from >= 2 data types."""
    accounts = ds["accounts"]
    items = []
    for p in ds["posts"]:
        if p.get("time") and p["account"] in accounts and is_ad(p):
            items.append((t_(p["time"]), "ad", p["post_id"], {p["account"]}, None, ""))
    for m in ds.get("messages") or []:
        items.append((t_(m["time"]), "message", m["msg_id"], {m["from"], m["to"]}, None, m.get("text", "")))
    for t in ds.get("transactions") or []:
        mer = t.get("merchant")
        kind = "ride" if mer and mer.get("category") in RIDE_CATS else "payment"
        items.append((t_(t["time"]), kind, t["tx_id"], {t["from"], t["to"].lower()}, mer, ""))
    items.sort(key=lambda x: (x[0], x[2]))
    merchant_names = {(t.get("merchant") or {}).get("name", "").lower(): t["merchant"]
                      for t in ds.get("transactions") or [] if t.get("merchant")}
    merchant_names.pop("", None)

    events, used = [], set()
    win = timedelta(minutes=config.ECHO_WINDOW_MIN)
    for i, (t0, typ, ref, parts, _, _) in enumerate(items):
        if typ != "ad" or ref in used:
            continue
        people = set(parts)
        group = [items[i]]
        for it in items[i + 1:]:
            if it[0] - t0 > win:
                break
            if it[3] & people:
                group.append(it)
                people |= {x for x in it[3] if x not in handles}
        types = {g[1] for g in group}
        if len(group) < 3 or len(types) < 2:
            continue
        used |= {g[2] for g in group}
        place = None
        for g in group:
            if g[4] and g[4].get("lat") is not None:
                place = g[4]
                break
            low = g[5].lower()
            for name, mer in merchant_names.items():
                if name.split(" (")[0] in low and mer.get("lat") is not None:
                    place = mer
        members = sorted({x for g in group for x in g[3] if x in accounts})
        mins = int((group[-1][0] - t0).total_seconds() // 60)
        events.append({
            "start": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": group[-1][0].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "members": members,
            "items": [{"type": g[1], "ref": g[2], "time": g[0].strftime("%Y-%m-%dT%H:%M:%SZ")} for g in group],
            "place_hint": (place.get("area") or place.get("name")) if place else None,
            "_place": place,
            "reason": f"{', '.join(sorted(types))} within {mins} minutes, sharing "
                      f"{len(members)} flagged account(s)"})
    return events


def echo_links(events: list[dict], add: Callable) -> None:
    together = Counter()
    for e in events:
        for a, b in combinations(e["members"], 2):
            together[(a, b)] += 1
    for (a, b), n in sorted(together.items()):
        if n >= 2:
            add(a, b, "echo", config.KEY_WEIGHTS["echo"], f"echo:{a}~{b}",
                f"appear together in {n} echo events (ad, message, payment, ride)")


# ------------------------------------------------------------------ per ring
def relay(members: set, key_times: dict) -> list[dict]:
    out = []
    for key, per in sorted(key_times.items()):
        if not key.startswith(("contact:", "money:")):
            continue
        users = sorted(((min(ts), max(ts), a) for a, ts in per.items()
                        if a in members and len(ts) >= 2))   # once is chance, not a habit
        for (f1, l1, a), (f2, l2, b) in zip(users, users[1:]):
            gap = t_(f2) - t_(l1)
            # a handoff: the key goes quiet on `a`, then starts on `b`, and nobody else in the
            # ring is using it in between (a wallet shared by everyone is not a relay)
            busy = any(u[2] not in (a, b) and u[0] <= f2 and u[1] >= l1 for u in users)
            if timedelta(0) < gap <= timedelta(days=config.RELAY_MAX_DAYS) and not busy:
                out.append({"key": key, "from": a, "to": b, "from_last_seen": l1, "to_first_seen": f2,
                            "reason": f"{key.split(':', 1)[1]} left {a} and appeared on {b} "
                                      f"{gap.days} day(s) {gap.seconds // 3600} h later"})
    return sorted(out, key=lambda h: h["to_first_seen"])


def roles(members: set, ds: dict, bio_recruiters: list[dict]) -> list[dict]:
    accounts, msgs, txs = ds["accounts"], ds.get("messages") or [], ds.get("transactions") or []
    paid_by, pays_members, cats = defaultdict(set), defaultdict(int), defaultdict(set)
    for t in txs:
        a, b = t["from"], t["to"]
        if a in members and b in members:
            paid_by[b].add(a)
            pays_members[a] += 1
        mer = t.get("merchant")
        if a in members and mer and mer.get("category") in HANDLER_CATS:
            cats[a].add(mer["category"])
    first_contact, dm_in = defaultdict(set), defaultdict(set)
    seen_pairs = set()
    for m in sorted(msgs, key=lambda m: m["time"]):
        a, b = m["from"], m["to"]
        pair = (min(a, b), max(a, b))
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            if a in members and b not in accounts and RECRUIT_TALK.search(m.get("text", "")):
                first_contact[a].add(b)
        if a in members and b in members:
            dm_in[b].add(a)
    out, taken = [], set()
    for a in sorted(members):
        if len(paid_by[a]) >= 3 and pays_members[a] == 0:
            out.append({"account": a, "role": "collector",
                        "reason": f"receives payments from {len(paid_by[a])} members; pays none out"})
            taken.add(a)
    for a in sorted(members - taken):
        if len(cats[a]) >= 2:
            out.append({"account": a, "role": "handler",
                        "reason": "pays " + ", ".join(sorted(cats[a])) + " (motel, rides, phone top-ups)"})
            taken.add(a)
    others = len(members) - 1
    for a in sorted(members - taken):
        if others and len(dm_in[a]) >= max(3, others / 2):
            out.append({"account": a, "role": "hub",
                        "reason": f"{len(dm_in[a])} of {others} members message it"})
            taken.add(a)
    for a in sorted(set(first_contact) - taken):
        if len(first_contact[a]) >= 5:
            out.append({"account": a, "role": "recruiter",
                        "reason": f"messages {len(first_contact[a])} strangers first with job offers"})
            taken.add(a)
    for r in bio_recruiters:
        if r["account"] not in taken:
            out.append({"account": r["account"], "role": "recruiter", "reason": r["reason"]})
            taken.add(r["account"])
    if msgs or txs:   # roles only mean something with the private layers
        for a in sorted(members - taken):
            out.append({"account": a, "role": "worker", "reason": "posts ads; no collector, handler or hub pattern"})
    return out


def location_hints(members: set, ds: dict, events: list[dict]) -> list[dict]:
    """Areas and named businesses for the Zoner and Lister. Never a person's address."""
    by_name = defaultdict(list)
    for t in ds.get("transactions") or []:
        mer = t.get("merchant")
        if t["from"] in members and mer and mer.get("lat") is not None and mer.get("category") in PLACE_CATS:
            by_name[mer["name"]].append((t["tx_id"], mer))
    hints = []
    for name, txs in sorted(by_name.items()):
        mer = txs[0][1]
        base = 0.3 if mer.get("category") in RIDE_CATS else 0.4
        hints.append({"kind": "merchant", "text": f"{name}, {mer.get('area') or ''}".strip(", "),
                      "lat": mer["lat"], "lon": mer["lon"], "weight": round(min(0.9, base + 0.05 * len(txs)), 2),
                      "source": [x for x, _ in txs][:10]})
    for e in events:
        p = e.get("_place")
        if p and set(e["members"]) & members:
            hints.append({"kind": "echo", "text": e["place_hint"] or p.get("name", ""), "lat": p["lat"],
                          "lon": p["lon"], "weight": 0.5, "source": [e["event_id"]]})
    names = {mer.get("name", "").split(" (")[0].lower(): mer for _, mers in by_name.items() for _, mer in mers}
    chat = defaultdict(list)
    for m in ds.get("messages") or []:
        if m["from"] in members:
            low = m.get("text", "").lower()
            for n, mer in names.items():
                if n and n in low:
                    chat[mer["name"]].append(m["msg_id"])
    for name, ids in sorted(chat.items()):
        mer = next(mm for _, mers in by_name.items() for _, mm in mers if mm["name"] == name)
        hints.append({"kind": "chat_place", "text": f"{name} named in chat", "lat": mer["lat"],
                      "lon": mer["lon"], "weight": 0.4, "source": ids[:10]})
    return hints
