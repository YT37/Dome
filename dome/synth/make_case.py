"""Build a test case with an ideal rings.json, taken straight from the answer key.

    python -m dome.synth.make_case --case <case_id> [--data synth]

TEST AND DEMO TOOLING ONLY. This reads the answer key, so it stands in for a perfect Linker
(e.g. to test the Zoner without the Linker's model download). No agent may call it.
"""
from __future__ import annotations

import argparse

from ..case import Case
from .common import load_json


def make_case(case: Case, answer_key_path="data/answer_key/answer_key.json") -> Case:
    key = load_json(answer_key_path)
    rings = []
    for label, ring in key.items():
        if label in ("hard_negatives", "decoy_buildings"):
            continue
        rings.append({
            "ring_id": f"R-{label}",
            "members": ring["members"],
            "confidence": 0.9,
            "key_kinds": ["contact", "text", "interaction"],
            "recruiters": [{"account": a, "reason": "from answer key (test case)"} for a in ring["recruiters"]],
        })
    case.save("rings.json", {"case_id": case.case_id, "rings": rings})
    return case


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", required=True)
    ap.add_argument("--data", default="synth")
    ap.add_argument("--ring", default=None, help="ring to select, e.g. R-A")
    ap.add_argument("--answer-key", default="data/answer_key/answer_key.json")
    args = ap.parse_args()
    case = Case.open(args.case, dataset=args.data, ring_id=args.ring, reset=True)
    make_case(case, args.answer_key)
    print(f"wrote {case.path('rings.json')}")


if __name__ == "__main__":
    main()
