"""Spotter (Ishaan): which accounts should an analyst look at first?  -> case/<id>/spotter.json

    spotter.run(case)                                 # supervisor hook (DOME_SPOTTER=1)
    python -m dome.agents.spotter --data synth        # print the top of the queue

Rules only. Scans every account in the dataset and flags one only when at least 3 different
kinds of signal agree. Each signal has a plain reason. The analyst picks who to start a case from;
the Spotter never starts anything itself. Reads the dataset and the case folder, never the
answer key.

Signals (all public except payment-then-post, which comes from the money step's notes):
  lure_offer         a vague, over-paid offer: high weekly pay + no experience / no interview /
                     travel or housing covered + "DM" / "message us"
  repeated_phone     the same phone (after un-disguising) in ads from 3+ accounts
  repeated_photo     the same photo posted by 3+ accounts
  repeated_script    the same ad wording (phones, places and numbers masked) from 3+ accounts
  lookalike_account  no profile photo, created within 6 hours of 4+ other accounts with no photo
  recruiter_pattern  agency / job-offer bio, and most of its reposts and replies go to accounts
                     that share a phone or script
  payment_then_post  tied to a wallet that pays the ad platform minutes before its posts
Score = 1 - prod(1 - w) over the signal kinds present (weights below), for ordering only.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..synth.common import mask_text, normalize_phone

MIN_KINDS = 3
WEIGHTS = {"lure_offer": 0.5, "repeated_phone": 0.6, "repeated_photo": 0.5, "repeated_script": 0.4,
           "lookalike_account": 0.4, "recruiter_pattern": 0.5, "payment_then_post": 0.7}
FLAG_RULE = f"flagged only when at least {MIN_KINDS} different signal kinds agree"

PAY = re.compile(r"\$\s?\d[\d,]{2,}\s*(a|per)\s*week|cash paid|easy money", re.I)
VAGUE = re.compile(r"no experience|no interview|start (this week|today|right away)|travel covered|housing help", re.I)
CONTACT = re.compile(r"\bdm\b|message us|message for", re.I)
RECRUITER_BIO = re.compile(r"modell?ing agency|job offers?|talent|now hiring|casting", re.I)


def _author(p):
    return p.get("account_id") or p.get("account") or p.get("handle")


def _mask_phone(norm: str) -> str:
    return f"{norm[:3]}-…{norm[-2:]}"


def scan(accounts: list, posts: list, interactions: list, gazetteer_names=(), ptp_notes=()) -> dict:
    """Pure function: dataset -> {account: [ {kind, reason} ]}."""
    by_acct = defaultdict(list)
    for p in posts:
        by_acct[_author(p)].append(p)
    signals = defaultdict(dict)                      # account -> kind -> reason

    # repeated phone / photo / script, across accounts
    phone_accts, photo_accts, script_accts = defaultdict(set), defaultdict(set), defaultdict(set)
    phone_ads = Counter()
    for p in posts:
        a = _author(p)
        for raw in p.get("phones", []):
            n = normalize_phone(raw)
            if n:
                phone_accts[n].add(a)
                phone_ads[n] += 1
        for ph in p.get("photo_ids") or [x.get("photo_id") for x in p.get("photos", []) if isinstance(x, dict)]:
            if ph:
                photo_accts[ph].add(a)
        words = mask_text(p.get("text", ""), p.get("phones", []), gazetteer_names)
        if len(words) >= 5:
            script_accts[" ".join(words)].add(a)
    for n, accts in phone_accts.items():
        if len(accts) >= 3:
            for a in accts:
                signals[a]["repeated_phone"] = f"same phone ({_mask_phone(n)}) in {phone_ads[n]} ads across {len(accts)} accounts"
    shared_photo = Counter()
    for ph, accts in photo_accts.items():
        if len(accts) >= 3:
            for a in accts:
                shared_photo[a] += 1
    for a, n in shared_photo.items():
        signals[a]["repeated_photo"] = f"{n} photo(s) also posted by 2+ other accounts"
    shared_script = defaultdict(int)
    for text, accts in script_accts.items():
        if len(accts) >= 3:
            for a in accts:
                shared_script[a] = max(shared_script[a], len(accts))
    for a, n in shared_script.items():
        signals[a]["repeated_script"] = f"same ad wording as {n - 1} other accounts (phones and places masked)"

    # lure offers
    for a, ps in by_acct.items():
        lures = [p for p in ps if PAY.search(p.get("text", "")) and VAGUE.search(p.get("text", "")) and CONTACT.search(p.get("text", ""))]
        if lures:
            signals[a]["lure_offer"] = f"{len(lures)} vague, over-paid offer(s) asking people to message them"

    # batch-created look-alikes with no profile photo
    acct_list = [x for x in accounts if x.get("has_profile_photo") is False and x.get("created")]
    created = sorted((datetime.fromisoformat(x["created"].replace("Z", "+00:00")).timestamp(), x.get("account_id") or x["handle"]) for x in acct_list)
    times = [t for t, _ in created]
    import bisect
    for t, a in created:
        n = bisect.bisect_right(times, t + 6 * 3600) - bisect.bisect_left(times, t - 6 * 3600) - 1
        if n >= 4:
            signals[a]["lookalike_account"] = f"no profile photo, created within 6 hours of {n} other accounts with no photo"

    # recruiter pattern
    shared_key_accts = {a for a, s in signals.items() if "repeated_phone" in s or "repeated_script" in s}
    out_edges = defaultdict(list)
    for it in interactions:
        if it.get("kind") in ("repost", "reply"):
            out_edges[it["from"]].append(it["to"])
    for x in accounts:
        a = x.get("account_id") or x["handle"]
        if RECRUITER_BIO.search(x.get("bio", "") or ""):
            tos = out_edges.get(a, [])
            into = sum(1 for b in tos if b in shared_key_accts)
            if len(tos) >= 5 and into / len(tos) >= 0.6:
                signals[a]["recruiter_pattern"] = f"bio reads like an agency or job offer; {into} of {len(tos)} reposts and replies go to accounts sharing a phone or script"

    # payment-then-post (from the money step's notes, when present)
    for n in ptp_notes:
        signals[n["account"]]["payment_then_post"] = n["reason"]
    return signals


def queue(signals: dict) -> dict:
    rows = []
    for a, s in signals.items():
        if len(s) >= MIN_KINDS:
            score = 1.0
            for k in s:
                score *= 1 - WEIGHTS.get(k, 0.3)
            rows.append({"account": a, "score": round(1 - score, 2),
                         "signals": [{"kind": k, "reason": r} for k, r in sorted(s.items())]})
    rows.sort(key=lambda r: (-r["score"], -len(r["signals"]), r["account"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"queue": [{"account": r["account"], "score": r["score"], "rank": r["rank"], "signals": r["signals"]} for r in rows],
            "flag_rule": FLAG_RULE}


def from_dataset(data_dir: Path, ptp_notes=()) -> dict:
    from ..synth.common import load_gazetteer
    d = Path(data_dir)
    rd = lambda n: json.loads((d / n).read_text(encoding="utf-8"))   # noqa: E731
    accounts = rd("accounts.json")
    accounts = list(accounts.values()) if isinstance(accounts, dict) else accounts
    return queue(scan(accounts, rd("posts.json"), rd("interactions.json"), list(load_gazetteer()), ptp_notes))


def run(case) -> Optional[dict]:
    """Supervisor hook (DOME_SPOTTER=1): writes case/<id>/spotter.json."""
    data = case.dataset_dir()
    if data is None:
        return None
    notes_path = case.path("wallet_notes.json")
    notes = json.loads(notes_path.read_text(encoding="utf-8"))["notes"] if notes_path.exists() else []
    out = from_dataset(data, notes)
    case.path("spotter.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    try:
        case.log(actor="agent", event="tool_result", step="spotter", output_file="spotter.json",
                 evidence={"flagged": len(out["queue"])}, message=f"spotter: {len(out['queue'])} accounts flagged ({FLAG_RULE})")
    except Exception:
        pass
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Spotter queue")
    ap.add_argument("--data", default="data/synth")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    from .linker import resolve_dataset
    q = from_dataset(resolve_dataset(a.data))
    print(f"{len(q['queue'])} flagged ({q['flag_rule']})")
    for r in q["queue"][: a.top]:
        print(f"  #{r['rank']} {r['account']} {r['score']}  " + ", ".join(s["kind"] for s in r["signals"]))
