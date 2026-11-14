"""Build a test case folder with an ideal rings.json, taken straight from the answer key.

    python -m dome.synth.make_case case/demo

TEST AND DEMO TOOLING ONLY. This reads the answer key, so it stands in for a perfect Linker
while the real one is being built. No agent may call it.
"""

import argparse
from pathlib import Path

from dome.synth.common import load_json, save_json


def make_case(case_dir, answer_key_path="data/answer_key/answer_key.json"):
    key = load_json(answer_key_path)
    rings = []
    for label, ring in key.items():
        if label in ("hard_negatives", "decoy_buildings"):
            continue
        rings.append({
            "ring_id": f"R-{label}",
            "members": ring["members"],
            "confidence": 0.9,
            "links": [],
            "recruiters": [{"account": a, "reason": "from answer key (test case)"} for a in ring["recruiters"]],
            "place_keys": [],
            "photo_ids": [],
        })
    case_dir = Path(case_dir)
    save_json(case_dir / "rings.json", rings)
    return case_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("case_dir")
    ap.add_argument("--answer-key", default="data/answer_key/answer_key.json")
    args = ap.parse_args()
    print(f"wrote {make_case(args.case_dir, args.answer_key) / 'rings.json'}")


if __name__ == "__main__":
    main()
