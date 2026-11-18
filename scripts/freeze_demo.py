"""Freeze a private offline demo bundle from the real run (run once, while the cache still holds it).

    python scripts/freeze_demo.py --case real-a --out ~/DomeDemoBundle

What it does
1. Re-runs the real case (scripted, real data tools) under `strace` and records every file the run
   opens. Those cache files, and nothing else from the 9 GB cache, go into the bundle. Any network
   connection the run makes is reported (expected: none besides Hugging Face update checks).
2. Copies the case outputs (the real run's case folder and its "Show the work" step files), the
   asset packs, ad photos and match images for buildings A and D, every saved Gemini answer, the
   model weights, the LangSmith trace export and a trimmed CoStar SQLite (the properties in Ring A's
   dome only, no addresses, owners or names; the unit number kept in its own column).
3. Scrubs every text file: `address` fields blanked, street-address text removed, phones and
   wallet strings masked. Then fails if any street address, phone number or wallet string remains.
4. Writes MANIFEST.json: path, sha256, size, source, date, licensed flag. Verifies every sha256.

The bundle holds licensed CoStar, Matterport and Vexcel data (and images rendered from it). It is
private: never commit it, never upload it anywhere public. See docs/OFFLINE_DEMO.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = sys.executable
SCANS = {"A": "LqCMcmmVH3d", "D": "FQZd6kTpht1"}
STREET_RE = re.compile(r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][A-Za-z0-9'.-]*\s+){1,4}"
                       r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Way|Pkwy|Parkway|Ct|"
                       r"Court|Pl|Place|Hwy|Fwy)\b\.?")
PHONE_RE = re.compile(r"(?<![\d-])(?:\(?\d{3}\)?[\s.-]?)?555[\s.-]?\d{4}(?![\d-])")
WALLET_RE = re.compile(r"\b(?:bc1|0x|syn1q)[A-Za-z0-9]{16,}\b")
ADDRESS_KEYS = {"address", "street", "address1", "address2", "streetaddress", "formattedaddress"}
TEXT_SUFFIXES = {".json", ".jsonl", ".txt", ".html", ".md", ".csv"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


DOWNLOAD_RE = re.compile(r"download=[^&\"\s]*")      # signed URLs name the file after the street address


def mask_address(s: str) -> str:
    return DOWNLOAD_RE.sub("download=removed", STREET_RE.sub("[address removed]", s))


def mask(s: str) -> str:
    s = mask_address(s)
    s = PHONE_RE.sub(lambda m: "555-…" + re.sub(r"\D", "", m.group())[-2:], s)
    return WALLET_RE.sub(lambda m: m.group()[:4] + "…" + m.group()[-4:], s)


def scrub(obj, mask_strings: bool):
    """mask_strings=True: case files (addresses, phones, wallets). False: API cache responses
    (addresses only, so ids and keys inside the data are never altered)."""
    if isinstance(obj, dict):
        return {k: ("" if k.lower() in ADDRESS_KEYS else scrub(v, mask_strings)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, mask_strings) for v in obj]
    if isinstance(obj, str):
        return mask(obj) if mask_strings else mask_address(obj)
    return obj


def copy_text(src: Path, dst: Path, mask_strings: bool) -> None:
    """Copy a JSON/JSONL file through the scrubber (other text files: regex masking only)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    raw = src.read_text(encoding="utf-8", errors="replace")
    if src.suffix == ".json":
        try:
            dst.write_text(json.dumps(scrub(json.loads(raw), mask_strings), indent=1), encoding="utf-8")
            return
        except ValueError:
            pass
    if src.suffix == ".jsonl":
        out = []
        for line in raw.splitlines():
            try:
                out.append(json.dumps(scrub(json.loads(line), mask_strings)))
            except ValueError:
                out.append(mask(line) if mask_strings else mask_address(line))
        dst.write_text("\n".join(out) + "\n", encoding="utf-8")
        return
    dst.write_text(mask(raw) if mask_strings else mask_address(raw), encoding="utf-8")


def copy_any(src: Path, dst: Path, mask_strings: bool = True) -> None:
    if src.suffix in TEXT_SUFFIXES:
        copy_text(src, dst, mask_strings)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


# ---------------------------------------------------------------------- 1. trace the run
def trace_real_run() -> tuple[set[Path], list[str]]:
    """Files the real scripted run opens, and the network connections it makes."""
    if not shutil.which("strace"):
        sys.exit("strace is required to trace the run (sudo pacman -S strace / apt install strace)")
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "strace.log"
        env = {**os.environ, "DOME_STUBS": "0", "DOME_MONEY": "1", "DOME_SPOTTER": "1",
               "DOME_CASE_ROOT": str(Path(td) / "case")}
        cmd = ["strace", "-f", "-qq", "-e", "trace=openat,connect,newfstatat,statx,stat,lstat,access,faccessat2", "-o", str(log),
               PY, "-m", "dome.supervisor", "--case", "freeze-trace", "--data", "synth", "--scripted"]
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        if r.returncode != 0 or "High" not in r.stdout:
            sys.exit(f"the traced run failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
        print("traced run:", next((l.strip() for l in r.stdout.splitlines() if l.strip().startswith("#1")), "?"))
        files, conns = set(), []
        for line in log.read_text().splitlines():
            # files opened, and files only checked for existence (the code skips a download when the
            # file is there, so those must be in the bundle too)
            m = re.search(r'(?:openat|newfstatat|statx|faccessat2)\([^,]+, "([^"]+)"', line) or \
                re.search(r'(?:stat|lstat|access)\("([^"]+)"', line)
            if m and "ENOENT" not in line and "O_DIRECTORY" not in line:
                files.add(Path(os.path.realpath(m.group(1))))
            if "connect(" in line and ("AF_INET" in line) and "htons(53)" not in line:
                conns.append(re.sub(r"^\d+\s+", "", line)[:160])
    return files, conns


# ---------------------------------------------------------------------- 2. trimmed CoStar
def trim_costar(src: Path, dst: Path, zone_polygon: list) -> int:
    """Properties inside the zone's bounding box (plus buildings A and D), with no address, owner or
    name. The unit number a residential listing's address carried is kept in its own `unit` column."""
    lats = [p[0] for p in zone_polygon]
    lons = [p[1] for p in zone_polygon]
    s, n, w, e = min(lats), max(lats), min(lons), max(lons)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    con = sqlite3.connect(dst)
    con.execute(f"ATTACH DATABASE '{src}' AS src")
    con.execute("""CREATE TABLE properties (property_id TEXT PRIMARY KEY, address TEXT, lat REAL, lon REAL,
                   type TEXT, floors INTEGER, units INTEGER, year_built INTEGER, name TEXT, unit TEXT)""")
    con.execute("CREATE TABLE scans (property_id TEXT, scan_id TEXT, rank INTEGER, PRIMARY KEY (property_id, scan_id))")
    keep_ids = {r[0] for r in con.execute("SELECT property_id FROM src.scans WHERE scan_id IN (?, ?)",
                                          (SCANS["A"], SCANS["D"]))}
    rows = con.execute("SELECT property_id, address, lat, lon, type, floors, units, year_built FROM src.properties "
                       "WHERE (lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?) OR property_id IN (%s)"
                       % ",".join("?" * len(keep_ids)), (s, n, w, e, *keep_ids)).fetchall()
    unit_re = re.compile(r"\b(?:unit|apt|#)\s*([A-Za-z]?\d+[A-Za-z]?)\b", re.I)
    for pid, addr, lat, lon, typ, floors, units, year in rows:
        m = unit_re.search(addr or "")
        con.execute("INSERT INTO properties VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, "", lat, lon, typ, floors, units, year, "", m.group(1) if m else None))
    ids = [r[0] for r in rows]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        con.execute("INSERT INTO scans SELECT * FROM src.scans WHERE property_id IN (%s)" % ",".join("?" * len(chunk)), chunk)
    con.execute("CREATE INDEX idx_latlon ON properties (lat, lon)")
    con.execute("CREATE INDEX idx_scan ON scans (scan_id)")
    con.commit()
    con.execute("DETACH DATABASE src")
    con.execute("VACUUM")
    con.close()
    return len(rows)


# ---------------------------------------------------------------------- 2b. live room-match index
LIVE_SCANS = ("LqCMcmmVH3d", "FQZd6kTpht1", "LSC8b9yW8H6", "JjwZkYjXJsw", "6ThoBJdrVYf", "puFxU9VY5Xf")
LIVE_KP = 768          # DISK keypoints kept per view (evenly spaced: DISK stores them in raster order)


def build_live_index(cache: Path, out: Path) -> float:
    """Room-match index for 6 scans (A, D and the 4 other scans of the real run's shortlist): every view's
    DINOv2 embedding, and DISK keypoints/descriptors subsampled to LIVE_KP per view, so the offline demo
    can recompute a real match live on CPU. Returns MB written."""
    import numpy as np
    dst = out / "live_index"
    dst.mkdir(parents=True, exist_ok=True)
    total = 0
    for scan in LIVE_SCANS:
        z = np.load(cache / "vision" / f"{scan}_v3.npz", allow_pickle=True)
        n = len(z["view_ids"])
        pts = np.zeros((n, LIVE_KP, 2), np.float32)        # plain arrays, padded; `count` says how many are real
        des = np.zeros((n, LIVE_KP, 128), np.float16)
        count = np.zeros(n, np.int32)
        for i, (p, d) in enumerate(zip(z["pts"], z["des"])):
            p = np.asarray(p, np.float32).reshape(-1, 2)
            d = np.asarray(d, np.float16).reshape(-1, 128)
            idx = np.linspace(0, len(p) - 1, num=min(LIVE_KP, len(p)), dtype=int) if len(p) else np.zeros(0, int)
            pts[i, :len(idx)], des[i, :len(idx)], count[i] = p[idx], d[idx], len(idx)
        f = dst / f"{scan}.npz"
        np.savez(f, view_ids=z["view_ids"], sweep_ids=z["sweep_ids"], headings=z["headings"], emb=z["emb"],
                 pts=pts, des=des, count=count, hw=z["hw"], view_scale=z["view_scale"])
        total += f.stat().st_size
    return total / 1e6


# ---------------------------------------------------------------------- 2c. geometry for the imageless mode
def plan_outlines(out: Path) -> int:
    """The matched unit's floor-plan outline (model metres) and sweep positions for A and D, so the
    imageless mode can draw the inside view as a line drawing without any floor-plan image."""
    from dome.data_tools import floorplan, matterport as mp
    dst = out / "derived"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for scan in SCANS.values():
        try:
            plans = floorplan.load(scan)
        except Exception as exc:
            print(f"  outline for {scan} skipped ({type(exc).__name__})")
            continue
        floors = {}
        for fid, fp in plans.items():
            poly = fp.outline_polygon()
            if poly is None:
                continue
            floors[fid] = [[round(x, 3), round(y, 3)] for x, y in poly.exterior.coords]
        sweeps = [{"sweep_id": l["id"], "x": round(l["position"]["x"], 3), "y": round(l["position"]["y"], 3)}
                  for l in mp._panos(scan) if l.get("position")]
        (dst / f"plan_outline_{scan}.json").write_text(json.dumps({"scan_id": scan, "floors": floors, "sweeps": sweeps}))
        n += 1
    return n


# ---------------------------------------------------------------------- 3. LangSmith export
def export_trace(out: Path, share_link: str) -> int:
    """The public Deep Agents trace as JSON (runs of one trace: name, type, inputs, outputs, times)."""
    try:
        from dome import config  # noqa: F401  (loads .env for the LangSmith key)
        from langsmith import Client
        run_id = share_link.rstrip("/").split("/r/")[1].split("?")[0]
        c = Client()
        root = c.read_run(run_id)
        runs = list(c.list_runs(project_name=os.getenv("LANGSMITH_PROJECT", "dome"), trace_id=root.trace_id))
    except Exception as exc:          # no key or no network: say so, keep the link
        out.mkdir(parents=True, exist_ok=True)
        (out / "trace_link.txt").write_text(share_link + "\n")
        print("LangSmith export skipped:", type(exc).__name__)
        return 0
    rows = [{"id": str(r.id), "parent": str(r.parent_run_id) if r.parent_run_id else None, "name": r.name,
             "run_type": r.run_type, "start": r.start_time.isoformat() if r.start_time else None,
             "end": r.end_time.isoformat() if r.end_time else None, "inputs": r.inputs, "outputs": r.outputs,
             "error": r.error} for r in sorted(runs, key=lambda r: r.start_time or dt.datetime.min)]
    out.mkdir(parents=True, exist_ok=True)
    (out / "trace.json").write_text(json.dumps(scrub(rows, True), indent=1, default=str))
    (out / "trace_link.txt").write_text(share_link + "\n")
    return len(rows)


# ---------------------------------------------------------------------- 4. manifest + leak check
def source_of(rel: str) -> tuple[str, bool]:
    r = rel.replace("\\", "/")
    if r.startswith("cache/matterport") or "/sweep_f" in r or r.endswith("floorplan.png") or r.startswith("data/photos"):
        return "Matterport", True
    if r.startswith("cache/vexcel") or "/ortho" in r or "/oblique" in r:
        return "Vexcel", True
    if r.startswith("cache/costar") or "costar" in r:
        return "CoStar", True
    if r.startswith("cache/gemini"):
        return "Gemini", False
    if r.startswith(("cache/vision", "cache/geo", "cache/windows", "data/matches", "live_index", "derived")) or r.startswith("data/demo_assets"):
        return "derived", True
    if r.startswith("models/"):
        return "open model weights", False
    if r.startswith(("case/", "langsmith/")):
        return "derived", False
    return "synthetic", False


def leak_check(bundle: Path, addresses: set[str]) -> list[str]:
    bad = []
    low = [a for a in addresses if len(a) > 8]
    for f in bundle.rglob("*"):
        if not f.is_file() or f.suffix not in TEXT_SUFFIXES or f.relative_to(bundle).parts[0] == "models":
            continue
        t = f.read_text(encoding="utf-8", errors="ignore")
        tl = t.lower()
        hit = (STREET_RE.search(t) or PHONE_RE.search(t) or WALLET_RE.search(t)
               or "pierce" in tl or any(a in tl for a in low))
        if hit:
            bad.append(str(f.relative_to(bundle)))
    for f in bundle.rglob("*.sqlite"):
        con = sqlite3.connect(f)
        n = con.execute("SELECT count(*) FROM properties WHERE address != '' OR name != ''").fetchone()[0]
        con.close()
        if n:
            bad.append(f"{f.relative_to(bundle)} ({n} rows with address or name)")
    return bad


def write_manifest(bundle: Path) -> dict:
    files = []
    for f in sorted(bundle.rglob("*")):
        if not f.is_file() or f.name == "MANIFEST.json":
            continue
        rel = str(f.relative_to(bundle))
        src, lic = source_of(rel)
        files.append({"path": rel, "sha256": sha256(f), "size": f.stat().st_size, "source": src,
                      "date": dt.datetime.fromtimestamp(f.stat().st_mtime).date().isoformat(), "licensed": lic})
    man = {"name": "Dome offline demo bundle", "case": "real-a", "recorded": "2026-11-15",
           "frozen": dt.date.today().isoformat(), "private": True,
           "note": "Contains licensed CoStar, Matterport and Vexcel data and images derived from it. "
                   "Never commit or upload publicly.",
           "files": files, "total_bytes": sum(x["size"] for x in files)}
    (bundle / "MANIFEST.json").write_text(json.dumps(man, indent=1))
    return man


def verify(bundle: Path) -> int:
    man = json.loads((bundle / "MANIFEST.json").read_text())
    bad = [f["path"] for f in man["files"] if not (bundle / f["path"]).is_file() or sha256(bundle / f["path"]) != f["sha256"]]
    if bad:
        sys.exit(f"manifest mismatch in {len(bad)} files, e.g. {bad[:5]}")
    return len(man["files"])


# ---------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default="real-a")
    ap.add_argument("--out", default=str(Path.home() / "DomeDemoBundle"))
    ap.add_argument("--trace-link", default="https://smith.langchain.com/public/ccdd3df0-49d8-4328-8a80-38f9b21f29d8/"
                                            "r/01a1df42-57b6-70a8-844c-21601db2bdde")
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()
    out = Path(a.out).expanduser().resolve()
    if out.is_relative_to(ROOT):
        sys.exit("the bundle must live outside the repository")
    if a.verify_only:
        print("verified", verify(out), "files")
        return
    from dome.data_tools._common import cache_dir
    cache = cache_dir().resolve()
    case = ROOT / "case" / a.case
    if not (case / "brief.json").exists():
        sys.exit(f"no finished case at {case}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    files, conns = trace_real_run()
    print("network connections during the traced run:", len(conns), conns[:3])
    home = Path.home()
    hf, torch_ck = home / ".cache" / "huggingface", home / ".cache" / "torch"
    n_cache = 0
    for f in sorted(files):
        if not f.is_file():
            continue
        if f.is_relative_to(cache):
            rel = f.relative_to(cache)
            if rel.parts[0] == "costar_index_v1.sqlite":
                continue                                  # trimmed copy below
            copy_any(f, out / "cache" / rel, mask_strings=False)
            n_cache += 1
    # the full cube-face folders of A and D (the Locator and the inside view use them)
    for scan in SCANS.values():
        for f in sorted((cache / "matterport" / scan).glob("*")):
            dst = out / "cache" / "matterport" / scan / f.name
            if f.is_file() and not dst.exists():
                copy_any(f, dst, mask_strings=False)
                n_cache += 1
    print("cache files copied:", n_cache)

    # models: the Hugging Face entries the run used, and the Kornia weights
    for model_dir in ("models--facebook--dinov2-small", "models--sentence-transformers--all-MiniLM-L6-v2"):
        src = hf / "hub" / model_dir
        if src.exists():
            shutil.copytree(src, out / "models" / "huggingface" / "hub" / model_dir, symlinks=False)
    ck = out / "models" / "torch" / "hub" / "checkpoints"
    ck.mkdir(parents=True, exist_ok=True)
    for f in (torch_ck / "hub" / "checkpoints").glob("*"):
        if f.is_file():
            shutil.copy2(f, ck / f.name)

    # trimmed CoStar
    zones = json.loads((case / "zones.json").read_text())
    n_props = trim_costar(cache / "costar_index_v1.sqlite", out / "cache" / "costar_index_v1.sqlite",
                          zones["zones"][0]["polygon"])
    print("CoStar properties kept (no addresses):", n_props)

    # case outputs + steps
    for f in sorted(case.glob("*")):
        if f.is_file() and f.suffix in (".json", ".jsonl"):
            copy_text(f, out / "case" / a.case / f.name, mask_strings=True)
    rec_steps = ROOT / "samples" / "demo_cases" / "demo-real-a" / "steps"
    for f in sorted(rec_steps.glob("*.json")):
        copy_text(f, out / "case" / a.case / "steps" / f.name, mask_strings=True)

    # data: photos, match images and summary, asset packs for A and D
    for sub in ("photos", "matches"):
        for f in sorted((ROOT / "data" / sub).glob("*")):
            if f.is_file():
                copy_any(f, out / "data" / sub / f.name, mask_strings=True)
    for scan in SCANS.values():
        for f in sorted((ROOT / "data" / "demo_assets" / scan).glob("*")):
            copy_any(f, out / "data" / "demo_assets" / scan / f.name, mask_strings=True)

    # every saved Gemini answer
    for f in sorted((cache / "gemini").glob("*.json")):
        copy_any(f, out / "cache" / "gemini" / f.name, mask_strings=False)

    print(f"live room-match index: {build_live_index(cache, out):.0f} MB for {len(LIVE_SCANS)} scans")
    print("floor-plan outlines for the imageless mode:", plan_outlines(out))
    n_trace = export_trace(out / "langsmith", a.trace_link)
    print("LangSmith runs exported:", n_trace)

    # leak check against every address in the original CoStar index
    con = sqlite3.connect(cache / "costar_index_v1.sqlite")
    addresses = {(r[0] or "").lower().strip() for r in con.execute("SELECT address FROM properties")}
    con.close()
    bad = leak_check(out, addresses)
    if bad:
        sys.exit(f"leak check failed in {len(bad)} files: {bad[:10]}")
    man = write_manifest(out)
    n = verify(out)
    lic = sum(f["size"] for f in man["files"] if f["licensed"])
    print(f"bundle: {out}  {man['total_bytes'] / 1e6:.1f} MB in {n} files "
          f"({lic / 1e6:.1f} MB licensed); manifest verified; leak check passed")


if __name__ == "__main__":
    main()
