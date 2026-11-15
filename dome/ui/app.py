"""Dome demo UI: one page that runs a case and shows the dome shrinking to one building.

    python -m dome.ui.app            # http://127.0.0.1:5000

The page starts the supervisor (a subprocess) and polls the case folder.
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

# One case: Ring A, run live as "real-a" or replayed from the recorded "demo-real-a".
PRESETS = {
    "ring_a": {"label": "Ring A", "case": "real-a", "replay": "demo-real-a", "data": "synth", "seed": "acct_103",
               "note": "Flagged accounts → one ring → a dome over its area → one building to verify."},
}
HIDDEN_CASES = {"demo-a", "demo-c"}          # older stub replays; the UI never loads them

app = Flask(__name__, static_folder=None)

from . import globe  # noqa: E402  (globe flight, link chart, panels; all behind DOME_GLOBE=1)

app.register_blueprint(globe.bp)
_run = {"proc": None, "preset": None, "case": None, "started": None, "scripted": None}
_lock = threading.Lock()
_cache: dict = {}


# ---------------------------------------------------------------------- helpers
def case_dir(case_id: str) -> Path:
    """The live case folder, else the recorded backup. 404 on a bad id."""
    if not CASE_ID.match(case_id or ""):
        abort(404)
    live, rec = CASES / case_id, RECORDED / case_id
    clicks_only = live.exists() and all(p.name == "ui_actions.jsonl" for p in live.iterdir())
    if live.exists() and not (clicks_only and rec.exists()):
        return live                       # a folder holding only UI click records never hides a recording
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
               "--data", preset["data"]]
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
                        and d.name not in HIDDEN_CASES \
                        and d.name not in {c["case"] for c in out}:
                    out.append({"case": d.name, "kind": kind,
                                "complete": (d / "brief.json").exists()})
    return jsonify(out)


# ---------------------------------------------------------------------- dataset views
@app.get("/graph")
def graph():
    """Flagged accounts and the reposts/replies/follows between them. Handles only.

    With DOME_GLOBE=1 and ?case=<id>: the link chart for that case (see globe.build_graph).
    """
    if request.args.get("case") and globe.enabled():
        return jsonify(globe.build_graph(request.args["case"]))
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
    """The Linker's combinatorial complex, for the topology view.

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


def _j(d: Path, name: str):
    p = d / name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


@app.get("/flow")
def flow():
    """The six agents as a data flow for the Homepage: input -> what it did -> output file, with the key
    number. Every number is read from the case files at request time; nothing is computed or hard-coded."""
    d = case_dir(request.args.get("case", ""))
    spot, rings, zones = _j(d, "spotter.json"), _j(d, "rings.json"), _j(d, "zones.json")
    cands, rm, matches, brief = _j(d, "candidates.json"), _j(d, "room_match.json"), _j(d, "matches.json"), _j(d, "brief.json")
    accounts = None
    try:
        from ..agents.linker import load_dataset   # noqa: PLC0415
        accounts = len(load_ds("synth")["accounts"])
    except Exception:
        pass
    queue = (spot or {}).get("queue") if isinstance(spot, dict) else spot
    ring = ((rings or {}).get("rings") or [None])[0]
    money = (ring or {}).get("money") or {}
    zs = (zones or {}).get("zones") or []
    cz = (cands or {}).get("zones") or []
    best = None
    for z in (matches or {}).get("zones", []):
        for m in z.get("matches", []):
            if best is None or (m.get("P") or 0) > (best.get("P") or 0):
                best = m
    lead = ((brief or {}).get("leads") or [None])[0]
    P = (rm or {}).get("P") or {}
    stages = [
        {"step": "spotter", "agent": "Spotter", "work": "spotter",
         "input": f"{accounts} accounts" if accounts else "accounts", "did": (spot or {}).get("flag_rule") if isinstance(spot, dict) else "scores public signals",
         "output": "spotter.json", "key": f"{len(queue)} flagged" if queue is not None else None},
        {"step": "linker", "agent": "Linker + money", "work": "linker",
         "input": f"{len(queue)} flagged accounts" if queue else "flagged accounts", "did": "two kinds of shared key make a link; money second pass",
         "output": "rings.json", "key": (f"{len((rings or {}).get('rings', []))} ring · {len(ring['members'])} accounts · R {ring['confidence']}"
                                        + (f" · {len(money.get('wallet_clusters', []))} wallet clusters" if money else "")) if ring else None},
        {"step": "zoner", "agent": "Zoner", "work": "zoner", "input": "place clues in the ads", "did": "area, never an address",
         "output": "zones.json", "key": f"dome {sum(z.get('area_km2') or 0 for z in zs):g} km²" if zs else None},
        {"step": "lister", "agent": "Lister", "work": "lister", "input": "CoStar buildings in the dome", "did": "fit to the photo cues",
         "output": "candidates.json", "key": (f"{sum(len(z.get('candidates', [])) for z in cz)} buildings "
                                             f"({sum(1 for z in cz for c in z.get('candidates', []) if c.get('has_scan'))} scanned)") if cz else None},
        {"step": "locator", "agent": "Locator", "work": "locator", "input": "ring photos + Matterport scans", "did": "room match, pin fix, window check",
         "output": "matches.json", "key": (f"{len((rm or {}).get('coarse') or P)} scans → {len((rm or {}).get('shortlist') or [])} → "
                                          f"{re.sub(r' *[(]synthetic case[)]', '', (lead or {}).get('display_name') or '') or (best or {}).get('property_id')}, "
                                          f"P {(best or {}).get('P')}") if best else None},
        {"step": "briefer", "agent": "Briefer", "work": "briefer", "input": "all four files", "did": "tier rules, then the score",
         "output": "brief.json", "key": f"{lead['tier']} {lead['score']}" if lead else None},
    ]
    for st in stages:
        st["done"] = (d / st["output"]).exists()
    return jsonify({"case": d.name, "stages": stages, "globe": globe.enabled(), "steps": globe.steps_enabled()})


@app.get("/steps")
def steps_view():
    """"Show the work" for one agent (DOME_STEPS=1): {agent, title, steps: [{id, title, kind, data, caption,
    source}]}, built by dome/ui/steps/ from files the code wrote. No address key ever leaves."""
    if not globe.steps_enabled():
        abort(404)
    from . import steps
    agent = request.args.get("agent", "")
    if agent not in steps.AGENTS:
        abort(404)
    return jsonify(steps.build(case_dir(request.args.get("case", "")), agent))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Dome demo UI")
    ap.add_argument("--port", type=int, default=5000)
    a = ap.parse_args()
    print(f"Dome UI on http://127.0.0.1:{a.port}  (synthetic data; leads for human verification)")
    app.run(host="127.0.0.1", port=a.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
