"""Scores the Linker against answer_key.json. Solo demo for the Arlequin track.

    python -m dome.eval --data mini

The answer key is read HERE ONLY. No agent ever sees it.
Prints: ring precision/recall, recall@10, hard negatives, one reworded-script link that
MinHash missed and embeddings caught, and the recruiter flags.
"""
from __future__ import annotations

import argparse
import json
from itertools import combinations

from .agents.linker import link_accounts, load_dataset, resolve_dataset


def _pairs(groups) -> set:
    return {p for g in groups for p in combinations(sorted(g), 2)}


def score(data: str) -> dict:
    ds = load_dataset(data)
    key = json.loads((resolve_dataset(data) / "answer_key.json").read_text(encoding="utf-8"))
    linked = link_accounts(ds)
    rings = linked.rings_file["rings"]
    truth = {name: set(r["members"]) for name, r in key["rings"].items()}
    pred = [set(r["members"]) for r in rings]

    tp = len(_pairs(pred) & _pairs(truth.values()))
    precision = tp / max(1, len(_pairs(pred)))
    recall = tp / max(1, len(_pairs(truth.values())))

    per_ring = {}
    for name, members in truth.items():
        best = max(rings, key=lambda r: len(members & set(r["members"])), default=None)
        got = set(best["members"]) if best else set()
        per_ring[name] = {"ring_id": best and best["ring_id"], "R": best and best["confidence"],
                          "true": len(members), "found": len(members & got),
                          "extra": sorted(got - members), "missed": sorted(members - got),
                          "kinds": best and best["key_kinds"]}

    # recall@10: seed one account, rank every other account by link strength,
    # share of its true ring found in the top 10
    def s(a, b):
        return linked.strength.get((min(a, b), max(a, b)), 0.0)

    r10 = {}
    for name, members in truth.items():
        vals = []
        for seed in sorted(members):
            ranked = sorted((a for a in ds["accounts"] if a != seed), key=lambda a: (-s(seed, a), a))
            vals.append(len(set(ranked[:10]) & members) / min(10, len(members) - 1))
        r10[name] = round(sum(vals) / len(vals), 3)

    in_ring = set().union(*pred) if pred else set()
    negatives = {kind: {"accounts": len(accts), "pulled_into_a_ring": sorted(set(accts) & in_ring)}
                 for kind, accts in key.get("hard_negatives", {}).items()}

    true_recruiters = {a for r in key["rings"].values() for a in r.get("recruiters", [])}
    flagged = {x["account"]: x["reason"] for r in rings for x in r["recruiters"]}

    reworded = None
    for r in rings:
        for l in r["links"]:
            if "reworded" in l["reason"]:
                reworded = {"a": l["a"], "b": l["b"], "reason": l["reason"]}
                break
        if reworded:
            break
    catch = max(linked.embedding_catches, key=lambda c: c["cosine"] - c["jaccard"], default=None)

    return {"stats": linked.stats, "embed_backend": linked.embed_backend,
            "precision": round(precision, 3), "recall": round(recall, 3), "per_ring": per_ring,
            "recall_at_10": r10, "hard_negatives": negatives,
            "recruiters": {"flagged": flagged, "true": sorted(true_recruiters),
                           "missed": sorted(true_recruiters - set(flagged)),
                           "wrong": sorted(set(flagged) - true_recruiters)},
            "reworded_link": reworded, "embedding_catch": catch}


def main() -> None:
    ap = argparse.ArgumentParser(prog="dome.eval")
    ap.add_argument("--data", default="mini")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = score(a.data)
    if a.json:
        print(json.dumps(r, indent=2))
        return
    st = r["stats"]
    print(f"Dataset '{a.data}' (synthetic): {st['accounts']} accounts, {st['posts']} posts")
    print(f"Pairs sharing any key: {st['pairs_with_any_key']}  ->  links (two kinds): {st['links']}"
          f"  ->  rings: {st['rings']}")
    print(f"\nRing membership   precision {r['precision']:.2f}   recall {r['recall']:.2f}")
    for name, x in r["per_ring"].items():
        print(f"  Ring {name}: found {x['found']}/{x['true']} as {x['ring_id']}  R {x['R']}  "
              f"kinds {x['kinds']}  extra {x['extra']}  missed {x['missed']}")
    print("\nrecall@10 (seed one account, rank the rest by link strength)")
    for name, v in r["recall_at_10"].items():
        print(f"  Ring {name}: {v:.2f}")
    print("\nHard negatives (must stay out of every ring)")
    for kind, x in r["hard_negatives"].items():
        bad = x["pulled_into_a_ring"]
        print(f"  {kind:<16} {x['accounts']:>2} accounts   " + ("unlinked" if not bad else f"LINKED: {bad}"))
    rec = r["recruiters"]
    print(f"\nRecruiter flags: {len(rec['flagged'])} flagged, {len(rec['missed'])} missed, "
          f"{len(rec['wrong'])} wrong")
    for acct, why in list(rec["flagged"].items())[:3]:
        print(f"  {acct}: {why}")
    print(f"\nReworded script (text backend: {r['embed_backend']})")
    if r["reworded_link"]:
        print(f"  link {r['reworded_link']['a']} - {r['reworded_link']['b']}: {r['reworded_link']['reason']}")
    if r["embedding_catch"]:
        c = r["embedding_catch"]
        print(f"  MinHash Jaccard {c['jaccard']:.2f} (missed)   embedding cosine {c['cosine']:.2f} (caught)")
        print(f"    A: {c['a'][:90]}")
        print(f"    B: {c['b'][:90]}")
    print("\nAll accounts are synthetic. Rings are leads for human review.")


if __name__ == "__main__":
    main()
