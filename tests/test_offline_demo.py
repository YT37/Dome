"""The offline demo (DOME_OFFLINE=1) reproduces the real run from the private bundle, with no network.

Skips cleanly when DOME_BUNDLE is not set, so the public repository's tests stay green. Run with:
    DOME_BUNDLE=~/DomeDemoBundle pytest -q tests/test_offline_demo.py
Everything runs in a subprocess, because offline mode is set up when the `dome` package is first
imported (keys and `.env` ignored, socket guard installed).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = os.environ.get("DOME_BUNDLE")
pytestmark = pytest.mark.skipif(not BUNDLE or not (Path(BUNDLE).expanduser() / "MANIFEST.json").exists(),
                                reason="no offline bundle (set DOME_BUNDLE)")

CHECK = textwrap.dedent('''
    import json, math, re, sys
    sys.path.insert(0, ".")
    import dome
    from dome import offline
    from dome.ui.app import app
    from dome.ui.steps import AGENTS
    out = {}
    # 1. the full pipeline, scripted, from the bundle
    sys.argv = ["dome.supervisor", "--case", "offline-check", "--data", "synth", "--scripted"]
    import runpy
    try:
        runpy.run_module("dome.supervisor", run_name="__main__")
    except SystemExit:
        pass
    from dome import config
    d = config.CASE_ROOT / "offline-check"
    brief = json.load(open(d / "brief.json")); lead = brief["leads"][0]
    out["lead"] = [lead["property_id"], lead["tier"], lead["score"]]
    m = json.load(open(d / "matches.json"))["zones"][0]
    P = {x["scan_id"]: x["P"] for x in m["matches"]}
    best = next(x for x in m["matches"] if x["property_id"] == lead["property_id"])
    out["P_A"], out["P_D"] = P.get("LqCMcmmVH3d"), P.get("FQZd6kTpht1", 0.0)
    out["W"], out["floor"] = best["W"], best["floor_range"]
    cands = json.load(open(d / "candidates.json"))["zones"][0]["candidates"]
    c = next(x for x in cands if x["property_id"] == lead["property_id"])
    g = best["geo"]
    p1, p2 = math.radians(c["lat"]), math.radians(g["lat"])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(g["lon"] - c["lon"]) / 2) ** 2
    out["pin_moved_m"] = round(2 * 6371000 * math.asin(math.sqrt(h)), 1)
    # 2. every UI route and steps endpoint on the recorded case (the bundle's case folder)
    import os, pathlib
    import dome.ui.app as _ui
    config.CASE_ROOT = pathlib.Path(os.environ["DOME_BUNDLE"]) / "case"; _ui.CASES = config.CASE_ROOT
    cl = app.test_client(); codes = {}; bodies = []
    urls = ["/", "/globe", "/env.js", "/ui-flags", "/flow?case=real-a", "/cases", "/case/real-a/log?since=0",
            "/graph?case=real-a", "/flight?case=real-a", "/ask?case=demo-real-a"] + \\
           [f"/steps?case=real-a&agent={a}" for a in AGENTS]
    for u in urls:
        r = cl.get(u); codes[u] = r.status_code
        if r.is_json: bodies.append(r.get_data(as_text=True))
    a = cl.post("/ask", json={"case": "real-a", "question": "Why is Building A a High lead?"})
    codes["POST /ask"] = a.status_code; bodies.append(a.get_data(as_text=True))
    out["ask_recorded"] = a.get_json().get("answerable")
    out["ask_new"] = cl.post("/ask", json={"case": "real-a", "question": "anything new?"}).get_json().get("reason")
    out["codes"] = codes
    street = re.compile(r"\\b\\d{1,6}\\s+(?:[A-Z][A-Za-z0-9'.-]*\\s+){1,4}(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane|Way|Ct|Pl)\\b")
    out["address_hits"] = sum(1 for b in bodies if street.search(b) or "pierce" in b.lower())
    out["blocked"] = offline.BLOCKED
    print("RESULT " + json.dumps(out))
''')


@pytest.fixture(scope="module")
def offline_result(tmp_path_factory):
    case_root = tmp_path_factory.mktemp("offline_case")
    bundle = str(Path(BUNDLE).expanduser())
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DOME_", "GOOGLE_", "GEMINI_", "LANGSMITH_",
                                                                     "MATTERPORT_", "VEXCEL_", "ANTHROPIC_"))}
    env.update(DOME_OFFLINE="1", DOME_BUNDLE=bundle, DOME_CASE_ROOT=str(case_root), DOME_GLOBE="1",
               DOME_STEPS="1", DOME_ASK="1", DOME_MONEY="1", DOME_SPOTTER="1")
    # the scripted run writes to a temp case root; the UI then reads the bundle's recorded case
    script = CHECK
    subprocess.run([sys.executable, "-m", "dome.offline", "link"], cwd=ROOT, env=env, check=True, capture_output=True)
    r = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line, f"offline check failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}"
    return json.loads(line[len("RESULT "):])


def test_offline_run_reproduces_the_real_result(offline_result):
    r = offline_result
    assert r["lead"] == ["RL-213304177", "High", 59]
    assert r["P_A"] == 0.68 and r["P_D"] == 0.0
    assert r["W"] == 0.6 and r["floor"] == [3, 3]
    assert r["pin_moved_m"] == 22.8


def test_every_route_and_steps_endpoint_answers(offline_result):
    bad = {u: c for u, c in offline_result["codes"].items() if c != 200}
    assert not bad, bad


def test_no_network_and_no_addresses(offline_result):
    assert offline_result["blocked"] == []
    assert offline_result["address_hits"] == 0


def test_ask_answers_the_recorded_question_only(offline_result):
    assert offline_result["ask_recorded"] is True
    assert "wasn't recorded in the offline demo" in (offline_result["ask_new"] or "")
