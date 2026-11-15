"""Dome demo UI: one page that runs a case and shows the dome shrinking to one building.

    python -m dome.ui.app            # http://127.0.0.1:5000

The page starts the supervisor (a subprocess, Track 2: --no-private) and polls the case folder.
It reads files the agents wrote; it never computes a tier or a score. It has no tool that
contacts, dispatches or publishes anything, and no chat. Everything shown is synthetic.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from .. import config

ROOT = config.ROOT
CASES = Path(config.CASE_ROOT)
RECORDED = ROOT / "samples" / "demo_cases"          # replay backups, committed
STATIC = Path(__file__).resolve().parent / "static"
FILES = {"rings.json", "zones.json", "candidates.json", "matches.json", "brief.json"}
CASE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PHONE = re.compile(r"(?:\d[\s\-.()]{0,3}){6,10}\d")

# Two presets, both Track 2 (public data only).
PRESETS = {
    "ring_a": {"label": "Ring A · one High lead", "case": "demo-a", "data": "synth", "seed": None,
               "note": "12 accounts, 90 ads. The dome shrinks to one building."},
    "ring_c": {"label": "Ring C · the supervisor decides", "case": "demo-c", "data": "mini",
               "seed": "acct_701",
               "note": "City-wide clues and no window photos: two guard decisions fire."},
}

app = Flask(__name__, static_folder=None)
_run = {"proc": None, "preset": None, "case": None, "started": None, "scripted": None}
_lock = threading.Lock()
_cache: dict = {}


# ---------------------------------------------------------------------- helpers
def case_dir(case_id: str) -> Path:
    """The live case folder, else the recorded backup. 404 on a bad id."""
    if not CASE_ID.match(case_id or ""):
        abort(404)
    live = CASES / case_id
    if live.exists():
        return live
    rec = RECORDED / case_id
    if rec.exists():
        return rec
    abort(404)


def running() -> bool:
    p = _run["proc"]
    return p is not None and p.poll() is None


def load_ds(name: str) -> dict:
    from ..agents.linker import load_dataset
    if name not in {p["data"] for p in PRESETS.values()}:
        abort(404)
    if ("ds", name) not in _cache:
        _cache[("ds", name)] = load_dataset(name)
    return _cache[("ds", name)]


# ---------------------------------------------------------------------- pages
@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/static/<path:name>")
def static_file(name):
    return send_from_directory(STATIC, name)


@app.get("/presets")
def presets():
    return jsonify(PRESETS)   # all synthetic: case ids, dataset names, a seed account id


# ---------------------------------------------------------------------- run
@app.post("/run")
def run():
    body = request.get_json(silent=True) or {}
    preset = PRESETS.get(body.get("preset", "ring_a"))
    if preset is None:
        return jsonify({"error": "unknown preset"}), 400
    with _lock:
        if running():
            return jsonify({"error": "a run is already going", "case": _run["case"]}), 409
        cmd = [sys.executable, "-m", "dome.supervisor", "--case", preset["case"],
               "--data", preset["data"], "--no-private"]
        if preset["seed"]:
            cmd += ["--seed", preset["seed"]]
        if body.get("scripted"):
            cmd.append("--scripted")
        out_dir = CASES / preset["case"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "log.jsonl").unlink(missing_ok=True)   # the supervisor resets the rest
        out = open(out_dir / "run.out", "w", encoding="utf-8")
        _run.update(proc=subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT),
                    preset=body.get("preset", "ring_a"), case=preset["case"],
                    started=time.time(), scripted=bool(body.get("scripted")))
    return jsonify({"case": preset["case"], "started": True})


@app.get("/status")
def status():
    p = _run["proc"]
    return jsonify({"running": running(), "case": _run["case"], "preset": _run["preset"],
                    "scripted": _run["scripted"],
                    "returncode": None if p is None or running() else p.returncode,
                    "elapsed": round(time.time() - _run["started"], 1) if _run["started"] else None})


# ---------------------------------------------------------------------- case files
@app.get("/case/<case_id>/log")
def case_log(case_id):
    since = max(0, request.args.get("since", default=0, type=int))
    path = case_dir(case_id) / "log.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    rows = []
    for line in lines[since:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            break   # a line still being written; pick it up next poll
    return jsonify({"since": since, "next": since + len(rows), "rows": rows})


@app.get("/case/<case_id>/file/<path:name>")
def case_file(case_id, name):
    if name not in FILES:          # whitelist only; no paths, no other files
        abort(404)
    path = case_dir(case_id) / name
    if not path.exists():
        abort(404)
    data = json.loads(path.read_text(encoding="utf-8"))
    if name == "candidates.json":  # addresses never leave the server
        for z in data.get("zones", []):
            for c in z.get("candidates", []):
                c.pop("address", None)
    if name == "brief.json":
        for lead in data.get("leads", []):
            lead.pop("address", None)
    return jsonify(data)


@app.get("/case/<case_id>/summary")
def case_summary(case_id):
    path = case_dir(case_id) / "summary.html"
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="text/html")


@app.get("/case/<case_id>/log.jsonl")
def case_log_raw(case_id):
    path = case_dir(case_id) / "log.jsonl"
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="text/plain")


@app.get("/cases")
def cases():
    """Case folders the page can replay (live first, then recorded backups)."""
    out = []
    for root, kind in ((CASES, "live"), (RECORDED, "recorded")):
        if root.exists():
            for d in sorted(root.iterdir()):
                if d.is_dir() and CASE_ID.match(d.name) and (d / "log.jsonl").exists() \
                        and d.name not in {c["case"] for c in out}:
                    out.append({"case": d.name, "kind": kind,
                                "complete": (d / "brief.json").exists()})
    return jsonify(out)


# ---------------------------------------------------------------------- dataset views
@app.get("/graph")
def graph():
    """Flagged accounts and the reposts/replies/follows between them. Handles only."""
    name = request.args.get("data", "synth")
    key = ("graph", name)
    if key not in _cache:
        ds = load_ds(name)
        nodes = {a: acc for a, acc in ds["accounts"].items() if acc.get("flags")}
        posts = Counter(p["account"] for p in ds["posts"])
        edges = defaultdict(Counter)
        for it in ds["interactions"]:
            a, b = it.get("from"), it.get("to")
            if a in nodes and b in nodes and a != b:
                edges[tuple(sorted((a, b)))][it.get("kind", "interaction")] += 1
        _cache[key] = {
            "data": name,
            "nodes": [{"id": a, "handle": acc.get("handle", a), "flags": acc.get("flags", []),
                       "posts": posts[a], "created": (acc.get("created") or "")[:10]}
                      for a, acc in sorted(nodes.items())],
            "edges": [{"a": a, "b": b, "count": sum(c.values()), "kinds": dict(c)}
                      for (a, b), c in sorted(edges.items())],
        }
    return jsonify(_cache[key])


@app.get("/complex")
def complex_():
    """The Linker's combinatorial complex (Track 2, public keys only), for the topology view.

    rank 0 = accounts, rank 1 = one cell per key shared by 2+ accounts. Per account: how many
    cells of each kind it sits in (the topological model's input), and the model's P(in a ring)
    when TopoModelX is installed. Keys are never sent (they can be phone numbers): only kinds.
    Computed once in the background; the page polls until it is ready.
    """
    name = request.args.get("data", "synth")
    key = ("complex", name)
    state = _cache.get(key)
    if state is None:
        _cache[key] = {"status": "computing"}
        threading.Thread(target=_build_complex, args=(name, key), daemon=True).start()
        return jsonify(_cache[key])
    return jsonify(state)


def _build_complex(name: str, key) -> None:
    try:
        from ..agents import linker, topo
        ds = load_ds(name)
        linked = linker.link_accounts(ds, private=False)
        cells = [c for c in linked.cells if len(c[3]) >= 2]
        per = defaultdict(Counter)
        out_cells = []
        for i, (rank, kind, _key, accounts) in enumerate(cells):
            accts = sorted(accounts)
            for a in accts:
                per[a][kind] += 1
            out_cells.append({"id": f"c{i}", "rank": rank, "kind": kind, "size": len(accts),
                              "members": accts})
        prob = topo.predict(ds, linked.cells, private=False) if topo.available() else None
        rings = linked.rings_file["rings"]
        _cache[key] = {
            "status": "ready", "data": name,
            "model": "UniGCN (TopoModelX), public-data model" if prob else None,
            "model_missing": prob is None,
            "kinds": dict(Counter(c["kind"] for c in out_cells)),
            "cells": out_cells,
            "accounts": [{"id": a, "kinds": dict(k), "cells": sum(k.values()),
                          "p": prob.get(a) if prob else None} for a, k in sorted(per.items())],
            "rings": [{"ring_id": r["ring_id"], "members": r["members"],
                       "confidence": r["confidence"], "topo_score": r.get("topo_score")}
                      for r in rings],
        }
    except Exception as exc:   # the view is optional; never break the page
        _cache[key] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Dome demo UI")
    ap.add_argument("--port", type=int, default=5000)
    a = ap.parse_args()
    print(f"Dome UI on http://127.0.0.1:{a.port}  (synthetic data; leads for human verification)")
    app.run(host="127.0.0.1", port=a.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
