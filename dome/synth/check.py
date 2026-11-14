"""Checks the synthetic data against the rules it must satisfy.

    python -m dome.synth.check [--data data/synth] [--answer-key data/answer_key/answer_key.json]

1. Counts per group.
2. One-key-kind rule: no hard negative shares more than one KIND of key (contact, photo, text,
   interaction) with any ring, or with any other hard negative.
3. Every ring photo comes from a building listed for that ring in the answer key.
4. Every phone is a 555 number; no banned words anywhere; ring place clues sit near ring buildings.

Exits non-zero if anything fails.
"""

import argparse
import re
import sys
from collections import defaultdict
from itertools import combinations

from dome.synth.common import (BANNED_WORDS, TEXT_KEY_JACCARD, jaccard, km_between, load_buildings,
                               load_gazetteer, load_json, mask_text, normalize_phone, trigrams)

KEY_KINDS = ("contact", "photo", "text", "interaction")
RING_CLUE_RADIUS_KM = 1.5


class Keys:
    """Per-account key material: normalized phones, photo IDs, post trigram sets, partners."""

    def __init__(self, posts, interactions, gazetteer):
        self.phones = defaultdict(set)
        self.photos = defaultdict(set)
        self.texts = defaultdict(list)
        self.partners = defaultdict(set)
        names = list(gazetteer)
        for p in posts:
            a = p["account_id"]
            self.phones[a] |= {normalize_phone(x) for x in p["phones"]}
            self.photos[a] |= set(p["photo_ids"])
            self.texts[a].append(trigrams(mask_text(p["text"], p["phones"], names)))
        for it in interactions:
            self.partners[it["from"]].add(it["to"])
            self.partners[it["to"]].add(it["from"])

    def shared_kinds(self, group_a, group_b):
        """Which kinds of key link any account in group_a to any account in group_b."""
        a_phones = set().union(*(self.phones[x] for x in group_a))
        b_phones = set().union(*(self.phones[x] for x in group_b))
        a_photos = set().union(*(self.photos[x] for x in group_a))
        b_photos = set().union(*(self.photos[x] for x in group_b))
        kinds = set()
        if a_phones & b_phones:
            kinds.add("contact")
        if a_photos & b_photos:
            kinds.add("photo")
        if any(self.partners[x] & set(group_b) for x in group_a):
            kinds.add("interaction")
        a_texts = [t for x in group_a for t in self.texts[x]]
        b_texts = [t for x in group_b for t in self.texts[x]]
        if any(jaccard(s, t) >= TEXT_KEY_JACCARD for s in a_texts for t in b_texts):
            kinds.add("text")
        return kinds


def run_checks(data_dir, answer_key_path):
    accounts = load_json(f"{data_dir}/accounts.json")
    posts = load_json(f"{data_dir}/posts.json")
    interactions = load_json(f"{data_dir}/interactions.json")
    renders = load_json(f"{data_dir}/renders.json")
    key = load_json(answer_key_path)
    gaz = load_gazetteer()
    failures = []

    ring_labels = [k for k in key if k not in ("hard_negatives", "decoy_buildings")]
    rings = {lab: key[lab]["members"] + key[lab]["recruiters"] + key[lab]["amplifiers"] for lab in ring_labels}
    hard = {acct: kind for kind, ids in key["hard_negatives"].items() for acct in ids}

    # 1. Counts
    posts_by = defaultdict(list)
    for p in posts:
        posts_by[p["account_id"]].append(p)
    print(f"accounts {len(accounts)}  posts {len(posts)}  interactions {len(interactions)}  photos {len(renders)}")
    for lab in ring_labels:
        r = key[lab]
        n_posts = sum(len(posts_by[a]) for a in r["members"])
        print(f"  ring {lab}: {len(r['members'])} accounts, {n_posts} posts, "
              f"{len(r['recruiters'])} recruiters, {len(r['amplifiers'])} amplifiers, "
              f"buildings {[b['label'] for b in r['buildings']]}")
    for kind, ids in key["hard_negatives"].items():
        print(f"  hard negative {kind}: {len(ids)}")
    labelled = set(hard) | {a for ids in rings.values() for a in ids}
    print(f"  background: {sum(1 for a in accounts if a['account_id'] not in labelled)}")

    # 2. One-key-kind rule
    keys = Keys(posts, interactions, gaz)
    worst = defaultdict(lambda: defaultdict(int))   # hard kind -> key kind -> pair count
    for h in hard:
        for lab, members in rings.items():
            kinds = keys.shared_kinds([h], members)
            if len(kinds) > 1:
                failures.append(f"{h} ({hard[h]}) shares {sorted(kinds)} with ring {lab}")
            for k in kinds:
                worst[hard[h]][f"{k} with a ring"] += 1
    for h1, h2 in combinations(sorted(hard), 2):
        kinds = keys.shared_kinds([h1], [h2])
        if len(kinds) > 1:
            failures.append(f"{h1} ({hard[h1]}) and {h2} ({hard[h2]}) share {sorted(kinds)}")
        for k in kinds:
            worst[hard[h1]][k] += 1
            worst[hard[h2]][k] += 1
    print("one-key-kind rule (pairs sharing each kind):")
    for kind in key["hard_negatives"]:
        shown = dict(worst[kind]) or "nothing shared"
        print(f"  {kind:<16} {shown}")

    # 3. Ring photos come from the ring's buildings
    for lab in ring_labels:
        scans = {b["scan_id"] for b in key[lab]["buildings"]}
        for a in key[lab]["members"]:
            for p in posts_by[a]:
                for ph in p["photo_ids"]:
                    if renders.get(ph, {}).get("scan_id") not in scans:
                        failures.append(f"ring {lab} photo {ph} has no building in the answer key")

    # 4a. Phones are 555 only
    for p in posts:
        for raw in p["phones"]:
            norm = normalize_phone(raw)
            if not norm or not norm.startswith("555-"):
                failures.append(f"{p['post_id']} phone {raw!r} is not a 555 number")

    # 4b. Banned words
    banned = re.compile(r"\b(" + "|".join(BANNED_WORDS) + r")\b", re.IGNORECASE)
    for a in accounts:
        for field in ("handle", "display_name", "bio"):
            if banned.search(a[field]):
                failures.append(f"{a['account_id']} {field} contains a banned word")
    for p in posts:
        if banned.search(p["text"]):
            failures.append(f"{p['post_id']} text contains a banned word")

    # 4c. Ring place clues (not city-wide ones) sit within RING_CLUE_RADIUS_KM of a ring building
    buildings = {b["label"]: b for b in load_buildings()}
    for lab in ring_labels:
        pts = [(buildings[b["label"]]["lat"], buildings[b["label"]]["lon"]) for b in key[lab]["buildings"]]
        for a in key[lab]["members"]:
            for p in posts_by[a]:
                for name in ([p["stated_area"]] if p["stated_area"] else []) + p["landmarks"]:
                    g = gaz[name]
                    if g["kind"] == "city":
                        continue
                    if min(km_between(g["lat"], g["lon"], la, lo) for la, lo in pts) > RING_CLUE_RADIUS_KM:
                        failures.append(f"ring {lab} clue {name!r} in {p['post_id']} is far from its buildings")
        print(f"  ring {lab} photos all from answer-key buildings; clues within {RING_CLUE_RADIUS_KM} km")

    return failures


def main():
    ap = argparse.ArgumentParser(description="Check Dome's synthetic data.")
    ap.add_argument("--data", default="data/synth")
    ap.add_argument("--answer-key", default="data/answer_key/answer_key.json")
    args = ap.parse_args()
    failures = run_checks(args.data, args.answer_key)
    if failures:
        print(f"\nFAILED: {len(failures)} problem(s)")
        for f in failures[:50]:
            print("  " + f)
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
