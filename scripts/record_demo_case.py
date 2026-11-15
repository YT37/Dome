"""Copy a finished case into samples/demo_cases/<name>/ (committed, public) for UI replay,
with every `address` field blanked: real runs carry CoStar street addresses internally.

Usage: python scripts/record_demo_case.py <case_id> <demo_name>   e.g. real-a demo-real-a
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scrub(x):
    if isinstance(x, dict):
        return {k: ("" if k == "address" else scrub(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    return x


def main(case_id: str, name: str) -> None:
    src, dst = ROOT / "case" / case_id, ROOT / "samples" / "demo_cases" / name
    addresses = set()
    for f in src.glob("*.json"):
        for m in re.finditer(r'"address":\s*"([^"]+)"', f.read_text()):
            addresses.add(m.group(1))
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in sorted(src.iterdir()):
        if f.suffix == ".json":
            (dst / f.name).write_text(json.dumps(scrub(json.loads(f.read_text())), indent=1) + "\n")
        elif f.suffix in (".jsonl", ".html"):
            text = f.read_text()
            for a in addresses:
                text = text.replace(a, "")
            (dst / f.name).write_text(text)
    leaked = [f.name for f in dst.iterdir() for a in addresses if a and a in f.read_text()]
    if leaked:
        raise SystemExit(f"address still present in {leaked}")
    print(f"recorded {src} -> {dst} ({len(addresses)} addresses removed)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
