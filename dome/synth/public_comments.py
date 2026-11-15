"""Synthetic PUBLIC comments (comments.json) with shared code words planted. Track 2 safe.

ALL SYNTHETIC. Comments are public, like captions, so the "shared keyword" sticky note works
with --no-private (Arlequin Track 2). The generator reads the answer key to know who is in
which ring (it is the generator; agents never read the key) and writes
answer_key_keywords.json for scoring.

    python -m dome.synth.public_comments --data data/synth --key data/answer_key/answer_key.json
    python -m dome.synth.public_comments --data samples/data/mini --key samples/data/mini/answer_key.json

Planted:
  ring code words  every Ring A member (and its recruiters) uses #tapin and the rose emoji
                   ("roses" = money) 2-4 times each in comments on ring ads
  Ring B           its own code word, #sugarline
  common tags      ~100 background accounts, including the friend group, use #tbt, #love,
                   #houston and 😍 a lot: so common they count for almost nothing
  one-off          a few unrelated accounts use #tapin once (one use is not a habit)
Comment format: {comment_id, post_id, account, time, text}
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

RING_WORDS = {"A": ["#tapin", "\U0001F339"], "B": ["#sugarline"], "C": []}
RING_LINES = ["{w} new girls this week {e}", "{w} ask about the specials {e}", "dm for {w} {e}",
              "{w} booking now {e}", "so true {w} {e}"]
COMMON = ["#tbt", "#love", "#houston", "\U0001F60D"]
COMMON_LINES = ["{t} great pic", "miss this {t}", "{t} {t2}", "omg {t}", "{t} weekend vibes"]


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:00Z")


def generate(data: Path, key_path: Path, seed: int = 11) -> dict:
    rng = random.Random(seed)
    posts = json.loads((data / "posts.json").read_text(encoding="utf-8"))
    accounts = json.loads((data / "accounts.json").read_text(encoding="utf-8"))
    key = json.loads(key_path.read_text(encoding="utf-8"))
    rings = key.get("rings") or {k: v for k, v in key.items() if isinstance(v, dict) and "members" in v}
    hn = key.get("hard_negatives", {})
    acct_ids = [a.get("account_id") or a["handle"] for a in accounts]
    for p in posts:
        p["account"] = p.get("account") or p.get("account_id") or p.get("handle")
    comments, n = [], 0

    def add(acct, post, text):
        nonlocal n
        n += 1
        t = parse(post["time"]) + timedelta(minutes=rng.randint(5, 600))
        comments.append({"comment_id": f"cmt_{n:05d}", "post_id": post["post_id"], "account": acct,
                         "time": iso(t), "text": text})

    planted = {}
    ring_members = set()
    for name, r in sorted(rings.items()):
        words = RING_WORDS.get(name, [])
        group = sorted(set(r.get("members", [])) | set(r.get("recruiters", [])))
        ring_members |= set(group)
        if not words:
            continue
        ring_posts = [p for p in posts if p["account"] in group] or posts
        for a in group:
            for _ in range(rng.randint(2, 4)):
                w, e = words[0], (words[1] if len(words) > 1 else "")
                add(a, rng.choice(ring_posts), rng.choice(RING_LINES).format(w=w, e=e).strip())
        planted[name] = {"keywords": words, "accounts": group}

    friends = hn.get("friend_group") or hn.get("friend_groups") or []
    background = [a for a in acct_ids if a not in ring_members]
    common_users = sorted(set(friends) | set(rng.sample(background, min(len(background), 100))))
    for a in common_users:
        for _ in range(rng.randint(2, 5)):
            t, t2 = rng.sample(COMMON, 2)
            add(a, rng.choice(posts), rng.choice(COMMON_LINES).format(t=t, t2=t2))
    one_off = rng.sample([a for a in background if a not in common_users] or background, 4)
    for a in one_off:
        add(a, rng.choice(posts), "what does #tapin mean")
    comments.sort(key=lambda c: (c["time"], c["comment_id"]))
    (data / "comments.json").write_text(json.dumps(comments, indent=1, ensure_ascii=False), encoding="utf-8")
    out = key_path.parent / "answer_key_keywords.json"
    out.write_text(json.dumps({"synthetic": True, "rings": planted, "common_tags": COMMON,
                               "common_users": common_users, "one_off_tapin": one_off},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    return {"comments": len(comments), "answer_key": str(out)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="dome.synth.public_comments")
    ap.add_argument("--data", required=True)
    ap.add_argument("--key", required=True)
    a = ap.parse_args()
    print(generate(Path(a.data), Path(a.key)))
