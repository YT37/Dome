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
from typing import Optional

from .agents.linker import link_accounts, load_dataset, resolve_dataset


def _pairs(groups) -> set:
    return {p for g in groups for p in combinations(sorted(g), 2)}


def score(data: str, layers: str = "both", private: bool = True) -> dict:
    ds = load_dataset(data)
    d = resolve_dataset(data)
    key_file = next(p for p in (d / "answer_key.json", d.parent / "answer_key" / "answer_key.json")
                    if p.exists())
    key = json.loads(key_file.read_text(encoding="utf-8"))
    linked = link_accounts(ds, layers=layers, private=private)
    rings = linked.rings_file["rings"]
    # Both answer-key shapes: {"rings": {A: ...}} (mini) and {A: ..., B: ...} (Ishaan's synth).
    ring_key = key.get("rings") or {k: v for k, v in key.items()
                                    if isinstance(v, dict) and "members" in v}
    # truth = the posting accounts; recruiters and amplifiers belong to the ring too, so a
    # predicted ring that includes them is not penalised (precision), but recall is measured
    # on the core members.
    truth = {name: set(r["members"]) for name, r in ring_key.items()}
    allowed = {name: truth[name] | set(r.get("recruiters", [])) | set(r.get("amplifiers", []))
               for name, r in ring_key.items()}
    pred = [set(r["members"]) for r in rings]

    pred_pairs = _pairs(pred)
    ok_pairs = _pairs(allowed.values())
    precision = len(pred_pairs & ok_pairs) / max(1, len(pred_pairs))
    recall = len(pred_pairs & _pairs(truth.values())) / max(1, len(_pairs(truth.values())))

    per_ring = {}
    for name, members in truth.items():
        best = max(rings, key=lambda r: len(members & set(r["members"])), default=None)
        got = set(best["members"]) if best else set()
        per_ring[name] = {"ring_id": best and best["ring_id"], "R": best and best["confidence"],
                          "true": len(members), "found": len(members & got),
                          "associates": len(got & (allowed[name] - members)),
                          "extra": sorted(got - allowed[name]), "missed": sorted(members - got),
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
                 for kind, accts in key.get("hard_negatives", {}).items()
                 if isinstance(accts, list)}

    negatives = {kind: v for kind, v in negatives.items() if v["accounts"]}
    true_recruiters = {a for r in ring_key.values() for a in r.get("recruiters", [])}
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
            "reworded_link": reworded, "embedding_catch": catch,
            "v2": score_v2(d, key_file, ring_key, rings, linked) if private else None}


def score_v2(d, key_file, ring_key, rings, linked) -> Optional[dict]:
    """Patterns vs answer_key_private.json (the synthetic generator's planted instances)."""
    pk_file = key_file.parent / "answer_key_private.json"
    if not pk_file.exists():
        return None
    pk = json.loads(pk_file.read_text(encoding="utf-8"))["rings"]
    out = {}
    for name, planted in pk.items():
        members = set(ring_key.get(name, {}).get("members", []))
        ring = max(rings, key=lambda r: len(members & set(r["members"])), default=None)
        if ring is None:
            continue
        got_roles = {x["account"]: x["role"] for x in ring.get("roles", [])}
        role_hits = {a: (want, got_roles.get(a)) for a, want in planted.get("roles", {}).items()}
        handoffs = {(h["key"], h["from"], h["to"]) for h in ring.get("relay", [])}
        want_h = [(h["key"], h["from"], h["to"]) for h in planted.get("handoffs", [])]
        hb = {tuple(sorted(p[:2])) for p in linked.stats.get("heartbeat_pairs", [])}
        hb_groups = [{"group": g, "linked_pairs": sum(tuple(sorted(p)) in hb for p in combinations(g, 2)),
                      "pairs": len(list(combinations(g, 2)))} for g in planted.get("heartbeat_groups", [])]
        best_event = max(ring.get("events", []), key=lambda e: (len({i["type"] for i in e["items"]}),
                                                                 bool(e.get("place_hint"))), default=None)
        out[name] = {"ring_id": ring["ring_id"], "kind_counts": ring.get("kind_counts", {}),
                     "roles": role_hits, "roles_right": sum(w == g for w, g in role_hits.values()),
                     "handoffs_found": [h for h in want_h if h in handoffs], "handoffs_planted": want_h,
                     "relay_chain": [f"{h['from']} -> {h['to']} ({h['key']})" for h in ring.get("relay", [])],
                     "heartbeat": hb_groups, "events": len(ring.get("events", [])),
                     "best_event": best_event, "location_hints": len(ring.get("location_hints", []))}
    return out


def three_way(data: str, private: bool = True) -> dict:
    """Precision/recall for content only, network only and both (the Arlequin slide)."""
    out = {}
    for layers in ("content", "network", "both"):
        r = score(data, layers=layers, private=private)
        out[layers] = {"precision": r["precision"], "recall": r["recall"], "rings": r["stats"]["rings"],
                       "negatives_linked": sum(len(x["pulled_into_a_ring"]) for x in r["hard_negatives"].values())}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="dome.eval")
    ap.add_argument("--data", default="mini")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--layers", default="both", choices=["content", "network", "both"])
    ap.add_argument("--no-private", action="store_true",
                    help="drop messages and payments (Track 2: public data only)")
    ap.add_argument("--three-way", action="store_true", help="also run content / network / both")
    a = ap.parse_args()
    r = score(a.data, layers=a.layers, private=not a.no_private)
    if a.json:
        print(json.dumps(r, indent=2))
        return
    st = r["stats"]
    print(f"Dataset '{a.data}' (synthetic): {st['accounts']} accounts, {st['posts']} posts")
    print(f"Pairs sharing any key: {st['pairs_with_any_key']}  ->  links (two kinds): {st['links']}"
          f"  ->  rings: {st['rings']}")
    print(f"\nRing membership   precision {r['precision']:.2f}   recall {r['recall']:.2f}")
    for name, x in r["per_ring"].items():
        print(f"  Ring {name}: found {x['found']}/{x['true']} as {x['ring_id']} "
              f"(+{x['associates']} recruiters/amplifiers)  R {x['R']}  kinds {x['kinds']}  "
              f"extra {x['extra']}  missed {x['missed']}")
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
    for name, v in (r.get("v2") or {}).items():
        print(f"\nv2 patterns, Ring {name} ({v['ring_id']})")
        print("  sticky notes per kind: " + ", ".join(f"{k} {n}" for k, n in v["kind_counts"].items()))
        print(f"  money shape: {v['roles_right']}/{len(v['roles'])} planted roles right  " +
              ", ".join(f"{a} {w}->{g}" for a, (w, g) in v["roles"].items()))
        print(f"  relay race: {len(v['handoffs_found'])}/{len(v['handoffs_planted'])} planted handoffs found;"
              f" chain: {' | '.join(v['relay_chain']) or 'none'}")
        for g in v["heartbeat"]:
            print(f"  heartbeat: {g['linked_pairs']}/{g['pairs']} pairs of {g['group']} linked")
        e = v["best_event"]
        if e:
            print(f"  echo: {v['events']} events; e.g. {e['event_id']} at {e.get('place_hint') or 'no place'}: "
                  + " -> ".join(f"{i['type']} {i['ref']} {i['time'][11:16]}" for i in e["items"]))
        print(f"  location hints for the Zoner: {v['location_hints']}")
    if a.three_way:
        print("\nThree-way comparison (" + ("public only" if a.no_private else "with messages + payments") + ")")
        for layers, x in three_way(a.data, private=not a.no_private).items():
            print(f"  {layers:<8} precision {x['precision']:.2f}  recall {x['recall']:.2f}  rings {x['rings']}"
                  f"  hard negatives linked {x['negatives_linked']}")
    if a.three_way and not a.no_private:
        from .agents import topo
        if topo.available() and topo.MODEL_PATH.exists():
            print("\nFour-way, account level: is this account in a ring? (topological = UniGCN on the "
                  "combinatorial complex, trained on mini only)")
            for name, x in topo.evaluate(a.data).items():
                extra = f"  AUC {x['auc']:.2f}" if "auc" in x else ""
                print(f"  {name:<12} precision {x['precision']:.2f}  recall {x['recall']:.2f}{extra}")
        else:
            print("\n(topological model not installed: pip install -r requirements-topo.txt, "
                  "then python -m dome.agents.topo --train)")
    print("\nAll accounts are synthetic. Rings are leads for human review.")


if __name__ == "__main__":
    main()
