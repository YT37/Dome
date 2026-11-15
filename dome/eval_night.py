"""Night eval (Ishaan): money and Spotter against the answer keys.  SCORING ONLY.

    python -m dome.eval_night [--data data/synth] [--key data/answer_key]

The only code (besides dome/eval.py) that reads data/answer_key/. Prints:
  money    wallet precision / recall (addresses in the ring's clusters), role accuracy,
           and which ring accounts the payment-then-post notes tie (precision / recall)
  spotter  precision@10, recall, and how many negatives were flagged
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agents import money, spotter


def money_eval(data: Path, key: Path) -> dict:
    ring = set(json.loads((key / "answer_key.json").read_text())["A"]["members"])
    ck = json.loads((key / "chain_key.json").read_text())
    chain = money.load_chain(data)
    if chain is None:
        return {"status": "no ledger"}
    out = money.analyse(*chain, json.loads((data / "posts.json").read_text()), ring)
    truth = {a: r for r, addrs in ck["clusters"].items() for a in addrs}
    found = {a: c["role"] for c in out["money"]["wallet_clusters"] for a in out["addresses"][c["cluster_id"]]}
    tp = len(set(found) & set(truth))
    roles_right = sum(1 for a, r in found.items() if truth.get(a) == r)
    noted = {n["account"] for n in out["wallet_notes"]["notes"]}
    paid_accts = {p["account"] for p in ck["payment_then_post"]}
    return {
        "wallet_precision": round(tp / len(found), 2) if found else 0.0,
        "wallet_recall": round(tp / len(truth), 2),
        "role_accuracy": round(roles_right / len(found), 2) if found else 0.0,
        "clusters": [f"{c['cluster_id']} {c['role']} ({c['addresses']} addr, conf {c['confidence']})" for c in out["money"]["wallet_clusters"]],
        "notes_precision": round(len(noted & ring) / len(noted), 2) if noted else 0.0,
        "notes_recall": round(len(noted & paid_accts) / len(paid_accts), 2) if paid_accts else 0.0,
        "decoy_addresses_in_clusters": len(set(found) & set(ck["decoys"])),
    }


def spotter_eval(data: Path, key: Path) -> dict:
    sk = json.loads((key / "spotter_key.json").read_text())
    pos = set(sk["positives"])
    neg = {a for ids in sk["negatives"].values() for a in ids}
    q = spotter.from_dataset(data)["queue"]
    flagged = [r["account"] for r in q]
    top = flagged[:10]
    return {
        "flagged": len(flagged),
        "precision_at_10": round(sum(a in pos for a in top) / len(top), 2) if top else 0.0,
        "recall": round(len(pos & set(flagged)) / len(pos), 2),
        "negatives_flagged": len(neg & set(flagged)),
        "negatives_total": len(neg),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="data/synth")
    ap.add_argument("--key", default="data/answer_key")
    a = ap.parse_args()
    data, key = Path(a.data), Path(a.key)
    m, s = money_eval(data, key), spotter_eval(data, key)
    print("money   ", json.dumps({k: v for k, v in m.items() if k != "clusters"}))
    for c in m.get("clusters", []):
        print("         ", c)
    print("spotter ", json.dumps(s))


if __name__ == "__main__":
    main()
