"""Copy a finished case into samples/demo_cases/<name>/ (committed, public) for UI replay,
with every `address` field blanked: real runs carry CoStar street addresses internally.

Usage: python scripts/record_demo_case.py <case_id> <demo_name>   e.g. real-a demo-real-a
       python scripts/record_demo_case.py --steps <demo_name>        only (re)write steps/ for a recorded case

It also writes samples/demo_cases/<name>/steps/<agent>.json ("Show the work", dome/ui/steps/) by
running the UI's adapters on the recorded folder, and passes every steps file through the same
address scrub and leak check (plus a street-text check).
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


def write_steps(dst: Path, addresses: set) -> list:
    """Run every Show-the-work adapter on the recorded folder; scrub and write steps/<agent>.json."""
    sys.path.insert(0, str(ROOT))
    from dome.ui import globe, steps   # noqa: PLC0415
    out_dir = dst / "steps"
    out_dir.mkdir(exist_ok=True)
    written = []
    for agent in steps.AGENTS:
        text = json.dumps(scrub(steps.build(dst, agent)), indent=1) + "\n"
        for a in addresses:
            text = text.replace(a, "")
        if globe.STREET_RE.search(text):
            raise SystemExit(f"street text in steps/{agent}.json: {globe.STREET_RE.search(text).group()!r}")
        (out_dir / f"{agent}.json").write_text(text)
        written.append(agent)
    return written


def leak_check(dst: Path, addresses: set) -> None:
    leaked = [str(f.relative_to(dst)) for f in dst.rglob("*") if f.is_file()
              for a in addresses if a and a in f.read_text()]
    leaked += [str(f.relative_to(dst)) for f in (dst / "steps").glob("*.json") if '"address": "' in f.read_text()
               and re.search(r'"address":\s*"[^"]+"', f.read_text())]
    if leaked:
        raise SystemExit(f"address still present in {leaked}")


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
    agents = write_steps(dst, addresses)
    leak_check(dst, addresses)
    print(f"recorded {src} -> {dst} ({len(addresses)} addresses removed; steps for {', '.join(agents)})")


def steps_only(name: str) -> None:
    dst = ROOT / "samples" / "demo_cases" / name
    agents = write_steps(dst, set())
    leak_check(dst, set())
    print(f"steps for {', '.join(agents)} -> {dst / 'steps'}")


if __name__ == "__main__":
    if sys.argv[1] == "--steps":
        steps_only(sys.argv[2])
    else:
        main(*sys.argv[1:3])
