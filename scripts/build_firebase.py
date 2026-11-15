"""Assemble deploy/firebase/functions/ (git-ignored) for `firebase deploy` from deploy/firebase/.

Copies the dome package, the recorded real run (already address-scrubbed) as the site's only case,
the asset images, the synthetic dataset and the saved Gemini answers. Refuses to build if any file
holds an address field value or a key.
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEP = ROOT / "deploy" / "firebase"
FN = DEP / "functions"
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pt")


def main() -> None:
    if FN.exists():
        venv = FN / "venv"
        keep = venv.exists()
        if keep:
            shutil.move(str(venv), str(DEP / ".venv_keep"))
        shutil.rmtree(FN)
        FN.mkdir()
        if keep:
            shutil.move(str(DEP / ".venv_keep"), str(venv))
    FN.mkdir(exist_ok=True)
    pub = DEP / "public"
    if pub.exists():
        shutil.rmtree(pub)
    # static files go straight to Firebase Hosting's CDN: the function runtime's own Flask server
    # claims every /static/... URL before the app sees it
    shutil.copytree(ROOT / "dome" / "ui" / "static", pub / "static", ignore=SKIP)
    shutil.copy(DEP / "main.py", FN / "main.py")
    shutil.copy(DEP / "requirements.txt", FN / "requirements.txt")
    shutil.copytree(ROOT / "dome", FN / "dome", ignore=SKIP)
    for rel in ("data/demo_assets", "data/matches", "data/photos", "data/synth", "samples/night"):
        if (ROOT / rel).exists():
            shutil.copytree(ROOT / rel, FN / rel, ignore=SKIP, symlinks=False)
    rec = ROOT / "samples" / "demo_cases" / "demo-real-a"
    shutil.copytree(rec, FN / "samples" / "demo_cases" / "demo-real-a")
    dag = ROOT / "samples" / "demo_cases" / "demo-deep-agents"     # the Gemini-driven Deep Agents run
    if dag.exists():
        shutil.copytree(dag, FN / "samples" / "demo_cases" / "demo-deep-agents")
    shutil.copytree(rec, FN / "case" / "real-a")                 # the site's "last run" = the scrubbed recording
    gem = ROOT / "cache" / "gemini"
    (FN / "cache" / "gemini").mkdir(parents=True, exist_ok=True)
    for f in gem.glob("*.json"):
        shutil.copy(f, FN / "cache" / "gemini" / f.name)
    bad = []
    key = re.compile(r"AQ\.Ab8|AIza[0-9A-Za-z_-]{20}|vfa_[0-9a-z]|MATTERPORT_TOKEN_SECRET=")
    for f in FN.rglob("*"):
        if f.is_file() and "venv" not in f.parts and f.suffix in (".json", ".jsonl", ".html", ".py", ".txt", ".js"):
            t = f.read_text(errors="ignore")
            street = f.suffix != ".py" and re.search(r'"address":\s*"(?!syn1q)[^"]+"', t)   # syn1q… = fake wallet ids
            if key.search(t) or street or "pierce" in t.lower():
                bad.append(str(f.relative_to(FN)))
    if bad:
        sys.exit(f"refusing: possible key or address in {bad[:10]}")
    size = sum(f.stat().st_size for f in FN.rglob("*") if f.is_file() and "venv" not in f.parts)
    print(f"built {FN} ({size / 1e6:.1f} MB without venv)")


if __name__ == "__main__":
    main()
