"""Night UI: globe flight, link chart, panels, asset route, events, Show the work (DOME_GLOBE / DOME_STEPS)."""
import json
import os
import shutil

import pytest

from dome.ui import app as ui
from dome.ui import globe

REAL = ui.RECORDED / "demo-real-a"
NODE_TYPES = {"account", "phone", "script", "photo", "room", "building", "wallet_cluster", "service", "place", "cell"}
LAYERS = {"content", "network", "money", "place"}


def walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_keys(v)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DOME_GLOBE", "1")
    monkeypatch.setenv("DOME_STEPS", "1")
    monkeypatch.delenv("DOME_GRAPH", raising=False)
    monkeypatch.delenv("DOME_ASK", raising=False)          # .env may set it; ask tests set it themselves
    monkeypatch.setattr(ui, "CASES", tmp_path / "case")
    (tmp_path / "case").mkdir()
    return ui.app.test_client()


def make_case(tmp_path, name, extra=None, rings_patch=None):
    d = tmp_path / "case" / name
    shutil.copytree(REAL, d)
    for fname, data in (extra or {}).items():
        (d / fname).write_text(json.dumps(data))
    if rings_patch:
        rings = json.loads((d / "rings.json").read_text())
        rings_patch(rings)
        (d / "rings.json").write_text(json.dumps(rings))
    return d


# ---------------------------------------------------------------- flag
def test_everything_new_is_off_without_the_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("DOME_GLOBE", raising=False)
    monkeypatch.delenv("DOME_STEPS", raising=False)
    monkeypatch.delenv("DOME_ASK", raising=False)
    c = ui.app.test_client()
    for path in ("/globe", "/flight?case=demo-real-a", "/panels?case=demo-real-a", "/events?case=demo-real-a",
                 "/asset/data/demo_assets/LqCMcmmVH3d/ortho.jpg", "/steps?case=demo-real-a&agent=locator"):
        assert c.get(path).status_code == 404, path
    assert c.post("/approve", json={"case": "demo-real-a"}).status_code == 404
    assert c.get("/ui-flags").get_json() == {"globe": False}
    assert c.get("/").status_code == 200          # the classic console is still the default


def test_globe_page_and_flag(client):
    page = client.get("/globe").get_data(as_text=True)
    assert "synthetic" not in page.lower() and "demo location" not in page.lower()
    assert "Illustrative case. No real activity at this location." in client.get("/static/globe.js").get_data(as_text=True)
    assert "Chart.js/4.4.1/chart.umd.min.js" in page
    assert "maplibre-gl@5.6.0" in page            # pinned CDN versions
    flags = client.get("/ui-flags").get_json()
    assert flags["globe"] is True and "locator" in flags["steps"]


# ---------------------------------------------------------------- flight
def test_flight_payload_for_the_real_run(client):
    f = client.get("/flight?case=demo-real-a").get_json()
    assert f["zones"] and f["candidates"] and f["best"]["scan_id"] == "LqCMcmmVH3d"
    assert sum(c["top"] for c in f["candidates"]) == 1
    inside = f["inside"]
    assert len(inside["sweep"]["faces"]) == 6
    assert all(u.startswith("/asset/data/demo_assets/") for u in inside["sweep"]["faces"])
    assert inside["rough_pin"] and inside["fixed_pin"]["moved_m"] > 0
    assert inside["ortho"]["bounds"] and inside["obliques"]


# ---------------------------------------------------------------- link chart
def test_graph_from_rings_and_matches(client, tmp_path):
    d = make_case(tmp_path, "rings-only")
    (d / "complex.json").unlink()
    r = client.get("/graph?case=rings-only")
    assert r.status_code == 200
    g = r.get_json()
    assert g["source"] == "rings.json"
    ids = {n["id"] for n in g["nodes"]}
    assert {n["type"] for n in g["nodes"]} <= NODE_TYPES
    assert {"account", "building", "room", "photo", "phone"} <= {n["type"] for n in g["nodes"]}
    assert all(e["layer"] in LAYERS and e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert all(n["layer"] in LAYERS for n in g["nodes"])
    text = r.get_data(as_text=True)
    assert "555-0187" not in text                             # masked only
    assert any(n["label"] == "555-…87" for n in g["nodes"] if n["type"] == "phone")
    rec = [n for n in g["nodes"] if n.get("role") == "recruiter"]
    assert rec and all(n["reason"] for n in rec)


def test_graph_uses_complex_json_when_present(client, tmp_path):
    cx = {"ranks": {
        "0": [{"id": "a1", "rank": 0, "kind": "account", "members": ["a1"], "masked_label": "acct_1", "reason": "flagged"},
              {"id": "a2", "rank": 0, "kind": "account", "members": ["a2"], "masked_label": "acct_2", "reason": "flagged"},
              {"id": "p1", "rank": 0, "kind": "phone", "members": ["p1"], "masked_label": "555-…42", "reason": "phone"}],
        "1": [{"id": "e1", "rank": 1, "kind": "interaction", "members": ["a1", "a2"], "masked_label": "reposts", "reason": "3 reposts"}],
        "2": [{"id": "c1", "rank": 2, "kind": "contact", "members": ["a1", "a2", "p1"], "masked_label": "shared phone", "reason": "same phone"}],
        "3": []},
        "incidence": {}, "features": {}, "scores": {"a1": 0.9}, "reasons": {}}
    make_case(tmp_path, "cx-case", extra={"complex.json": cx})
    g = client.get("/graph?case=cx-case").get_json()
    assert g["source"] == "complex.json"
    assert {"a1", "a2", "p1", "c1"} <= {n["id"] for n in g["nodes"]}
    assert any(e["type"] == "interaction" and e["reason"] == "3 reposts" for e in g["edges"])
    assert next(n for n in g["nodes"] if n["id"] == "a1")["score"] == 0.9
    t = client.get("/panels?case=cx-case").get_json()["topology"]
    assert set(t["ranks"]) == {"0", "1", "2", "3"}


def test_money_block_becomes_masked_wallet_and_service_nodes(client, tmp_path):
    wallet = "bc1qfakefakefakefakefakefakefakefake0wlh"

    def patch(rings):
        members = rings["rings"][0]["members"]
        money = json.loads((ui.ROOT / "samples" / "night" / "money.json").read_text())
        money["wallet_clusters"][0]["reasons"].append(f"pays from {wallet} then posts")
        money["payment_then_post"][0]["account"] = members[0]
        rings["rings"][0]["money"] = money
    (make_case(tmp_path, "money-case", rings_patch=patch) / "complex.json").unlink()
    r = client.get("/graph?case=money-case")
    g = r.get_json()
    types = {n["type"] for n in g["nodes"]}
    assert {"wallet_cluster", "service"} <= types
    assert any(e["layer"] == "money" for e in g["edges"])
    assert wallet not in r.get_data(as_text=True)
    panels = client.get("/panels?case=money-case")
    pm = panels.get_json()["money"]
    assert pm["wallet_clusters"] and pm["sample"] is False and wallet not in panels.get_data(as_text=True)
    assert any(e["type"] == "payment_then_post" for e in g["edges"])
    assert any(e["type"] == "cash_out" for e in g["edges"])


# ---------------------------------------------------------------- panels + recorded actions
def test_panels_fall_back_to_marked_samples(client, tmp_path):
    d = make_case(tmp_path, "no-panels")
    for f in ("spotter.json", "complex.json"):
        (d / f).unlink()
    rings = json.loads((d / "rings.json").read_text())
    for r in rings["rings"]:
        r.pop("money", None)
    (d / "rings.json").write_text(json.dumps(rings))
    p = client.get("/panels?case=no-panels").get_json()
    assert p["spotter"]["sample"] and p["topology"]["sample"] and p["money"]["sample"]
    assert p["spotter"]["flag_rule"] and p["spotter"]["queue"][0]["model"] == 0.97      # sample complex scores


def test_panels_use_the_real_case_files(client):
    p = client.get("/panels?case=demo-real-a").get_json()
    assert not p["spotter"]["sample"] and not p["topology"]["sample"] and not p["money"]["sample"]
    assert len(p["spotter"]["queue"]) == 15 and all(q["model"] is not None for q in p["spotter"]["queue"])
    roles = {w["cluster_id"]: w["role"] for w in p["money"]["wallet_clusters"]}
    assert roles["W-1"] == "advertiser" and p["money"]["attribution_confidence"] == 0.94
    t = p["topology"]
    assert len(t["disagreements"]) == 5 and t["fresh_test"]["ring_found"] == "15/15"
    wallets = [c for c in t["ranks"]["0"] if c["kind"] == "wallet_cluster"]
    assert wallets and all(c["score"] is None for c in wallets)            # wallets are not scored


def test_link_chart_from_real_complex_scores_no_wallets(client):
    g = client.get("/graph?case=demo-real-a").get_json()
    assert g["source"] == "complex.json"
    w = [n for n in g["nodes"] if n["type"] == "wallet_cluster"]
    assert w and all(n["score"] is None for n in w)
    assert all(n["layer"] in LAYERS for n in g["nodes"])


def test_spotter_and_approval_only_record(client, tmp_path):
    spot = {"queue": [{"account": "acct_103", "score": 0.91, "rank": 1,
                       "signals": [{"kind": "contact", "reason": "shared 555-0142"}]}], "flag_rule": "3 kinds"}
    make_case(tmp_path, "spot-case", extra={"spotter.json": spot})
    p = client.get("/panels?case=spot-case")
    sp = p.get_json()["spotter"]
    assert sp["queue"][0]["account"] == "acct_103" and sp["sample"] is False and sp["flag_rule"] == "3 kinds"
    assert "555-0142" not in p.get_data(as_text=True)
    chose = client.post("/spotter/choose", json={"case": "spot-case", "account": "acct_103"}).get_json()
    assert chose["recorded"] and chose["live"] is False                  # no DOME_GRAPH: the page replays
    assert client.post("/approve", json={"case": "spot-case", "property_id": "RL-1"}).get_json()["recorded"]
    rows = [json.loads(l) for l in (tmp_path / "case" / "spot-case" / "ui_actions.jsonl").read_text().splitlines()]
    assert [r["action"] for r in rows] == ["start_case_from_account", "approve_for_report"]
    assert client.post("/approve", json={"case": "../etc"}).status_code == 404


# ---------------------------------------------------------------- events
def test_events_replay_log_as_contract_e(client):
    r = client.get("/events?case=demo-real-a&pace=0")
    assert r.mimetype == "text/event-stream"
    evs = [json.loads(l[6:]) for l in r.get_data(as_text=True).splitlines() if l.startswith("data: {\"")]
    assert evs and all({"t", "agent", "phase", "message", "refs"} <= set(e) for e in evs)
    assert {e["phase"] for e in evs} <= {"start", "result", "decision", "interrupt", "end"}
    assert all(e["source"] == "events.jsonl" and e["sample"] is False for e in evs)   # recorded run has events.jsonl


# ---------------------------------------------------------------- asset route
@pytest.fixture()
def assets(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "data" / "demo_assets" / "S1").mkdir(parents=True)
    (root / "data" / "matches").mkdir(parents=True)
    (root / "data" / "photos").mkdir(parents=True)
    (root / "data" / "demo_assets" / "S1" / "ortho.jpg").write_bytes(b"\xff\xd8jpeg")
    (root / "data" / "demo_assets" / "S1" / "assets.json").write_text("{}")
    (root / "data" / "matches" / "m.png").write_bytes(b"\x89PNGpng")
    (root / "data" / "photos" / "img.jpg").write_bytes(b"\xff\xd8x")
    (root / "secret.jpg").write_bytes(b"\xff\xd8secret")
    (root / ".env").write_text("KEY=1")
    os.symlink(root / "secret.jpg", root / "data" / "demo_assets" / "S1" / "link.jpg")
    monkeypatch.setattr(globe, "ROOT", root)
    return root


def test_asset_route_serves_only_the_two_folders(client, assets):
    r = client.get("/asset/data/demo_assets/S1/ortho.jpg")
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.data == b"\xff\xd8jpeg"
    assert client.get("/asset/data/matches/m.png").status_code == 200


@pytest.mark.parametrize("path", [
    "/asset/data/demo_assets/../../secret.jpg",
    "/asset/data/demo_assets/S1/../../../secret.jpg",
    "/asset/data/demo_assets/%2e%2e/%2e%2e/secret.jpg",
    "/asset/data/demo_assets/..%2F..%2Fsecret.jpg",
    "/asset/data/demo_assets/S1/..%5C..%5Csecret.jpg",
    "/asset/..%2F.env",
    "/asset//etc/passwd",
    "/asset/%2Fetc%2Fpasswd",
    "/asset/secret.jpg",
    "/asset/data/synth/img.jpg",                    # not a served folder
    "/asset/data/demo_assets/S1/assets.json",
    "/asset/data/demo_assets/S1/link.jpg",            # symlink out of the folder
    "/asset/data/demo_assets/S1/missing.jpg",
    "/asset/data/demo_assets/S1/ortho.jpg%00.png",
])
def test_asset_route_refuses_traversal(client, assets, path):
    assert client.get(path, follow_redirects=True).status_code == 404


# ---------------------------------------------------------------- no addresses anywhere
def test_no_response_contains_an_address_key(client, tmp_path):
    d = make_case(tmp_path, "addr-case")
    cands = json.loads((d / "candidates.json").read_text())
    for z in cands["zones"]:
        for c in z["candidates"]:
            c["address"] = "100 Example St"
    (d / "candidates.json").write_text(json.dumps(cands))
    brief = json.loads((d / "brief.json").read_text())
    for lead in brief["leads"]:
        lead["address"] = "100 Example St"
    (d / "brief.json").write_text(json.dumps(brief))
    for case in ("demo-real-a", "addr-case"):
        for path in (f"/flight?case={case}", f"/graph?case={case}", f"/panels?case={case}",
                     f"/case/{case}/file/candidates.json", f"/case/{case}/file/brief.json",
                     f"/case/{case}/file/matches.json", f"/case/{case}/file/rings.json"):
            r = client.get(path)
            assert r.status_code == 200, path
            assert "address" not in set(walk_keys(r.get_json())), path
            assert "100 Example St" not in r.get_data(as_text=True), path


def test_mask_text():
    assert globe.mask_text("call 555-0142 or (713) 555-0199") == "call 555-…42 or 555-…99"
    assert globe.mask_text("send to bc1qfakefakefakefakefakefakefakefake0wlh") == "send to bc1q…0wlh"
    assert globe.mask_text("created 2026-09-02") == "created 2026-09-02"


# ---------------------------------------------------------------- night samples, graph.json, events fallback
NIGHT_FILES = ["money.json", "spotter.json", "graph.json", "events.jsonl", "complex.json", "wallet_notes.json", "ask.json"]


@pytest.mark.parametrize("name", NIGHT_FILES)
def test_night_samples_parse_and_end_with_one_newline(name):
    raw = (ui.ROOT / "samples" / "night" / name).read_text(encoding="utf-8")
    assert raw.endswith("}\n") and not raw.endswith("\n\n")
    if name.endswith(".jsonl"):
        assert all(json.loads(l) for l in raw.splitlines())
    else:
        json.loads(raw)


def test_graph_prefers_case_graph_json(client, tmp_path):
    g = json.loads((ui.ROOT / "samples" / "night" / "graph.json").read_text())
    make_case(tmp_path, "g-case", extra={"graph.json": g})
    out = client.get("/graph?case=g-case").get_json()
    assert out["source"] == "graph.json" and len(out["nodes"]) == 7


def test_graph_falls_back_to_sample_without_rings(client, tmp_path):
    d = tmp_path / "case" / "bare"
    d.mkdir()
    (d / "log.jsonl").write_text("")
    out = client.get("/graph?case=bare").get_json()
    assert out["sample"] is True and out["source"] == "samples/night/graph.json"


def test_events_prefer_case_events_then_samples(client, tmp_path):
    d = make_case(tmp_path, "ev-case")
    (d / "events.jsonl").write_text(json.dumps({"t": 0.0, "agent": "linker", "phase": "result",
                                                "message": "call 555-0142", "refs": []}) + "\n")
    body = client.get("/events?case=ev-case&speed=0").get_data(as_text=True)
    ev = json.loads(body.split("data: ", 1)[1].split("\n", 1)[0])
    assert ev["source"] == "events.jsonl" and "555-0142" not in body
    bare = tmp_path / "case" / "bare2"
    bare.mkdir()
    evs = [json.loads(l[6:]) for l in client.get("/events?case=bare2&speed=0").get_data(as_text=True).splitlines()
           if l.startswith('data: {"')]
    assert len(evs) == 8 and all(e["sample"] for e in evs) and evs[-1]["agent"] == "briefer"


def test_live_run_falls_back_without_graph_stream(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DOME_GRAPH", "1")
    monkeypatch.setattr(globe, "_graph_stream", lambda: None)
    make_case(tmp_path, "live-fallback")
    r = client.post("/spotter/choose", json={"case": "live-fallback", "account": "acct_103"}).get_json()
    assert r["live"] is False


def test_live_run_uses_graph_stream_and_resume(client, tmp_path, monkeypatch):
    calls = {}

    class FakeGS:
        @staticmethod
        def stream_run(ci):
            calls["run"] = ci
            yield {"t": 0, "agent": "supervisor", "phase": "interrupt", "message": "Approve?", "refs": [],
                   "thread_id": "th-1"}

        @staticmethod
        def resume(tid, decision):
            calls["resume"] = (tid, decision)
            yield {"t": 1, "agent": "briefer", "phase": "result", "message": "done", "refs": [], "thread_id": tid}

    monkeypatch.setenv("DOME_GRAPH", "1")
    monkeypatch.setenv("DOME_GRAPH_ASSISTANT", "dome_rules")
    monkeypatch.setattr(globe, "_graph_stream", lambda: FakeGS)
    make_case(tmp_path, "live-case")
    r = client.post("/spotter/choose", json={"case": "live-case", "account": "acct_103"}).get_json()
    assert r["live"] and r["assistant"] == "dome_rules" and calls["run"]["seed_account"] == "acct_103"
    body = client.get(f"/events?run={r['run']}").get_data(as_text=True)
    assert '"phase": "interrupt"' in body
    client.post("/approve", json={"case": "live-case", "run": r["run"]})
    import time as _t
    for _ in range(50):
        if "resume" in calls:
            break
        _t.sleep(0.02)
    assert calls["resume"] == ("th-1", "approve")


# ---------------------------------------------------------------- matterport embed
@pytest.mark.parametrize("params", ["qs=1&title=0&brand=0&mls=2&help=0&hr=0&dh=0&search=0", "", "title=1&mls=0",
                                    "title=1&evil=<script>"])
def test_matterport_url_always_hides_title_and_details(params):
    url = globe.matterport_url({"model_id": "LqCMcmmVH3d", "ss": 9, "params": params})
    assert url.startswith("https://my.matterport.com/show/?m=LqCMcmmVH3d&ss=9&")
    q = url.split("?", 1)[1].split("&")
    assert "title=0" in q and "mls=2" in q and "play=1" in q and "title=1" not in q and "<" not in url


def test_flight_carries_the_safe_embed_url(client):
    url = client.get("/flight?case=demo-real-a").get_json()["inside"]["matterport_url"]
    assert "title=0" in url and "mls=2" in url
    assert globe.matterport_url(None) is None and globe.matterport_url({"model_id": "../x"}) is None


# ---------------------------------------------------------------- show the work
from dome.ui import steps as steps_pkg   # noqa: E402

STREET = globe.STREET_RE


@pytest.mark.parametrize("agent", list(steps_pkg.AGENTS))
@pytest.mark.parametrize("case", ["demo-real-a", "case-folder"])
def test_steps_shape_sources_and_no_addresses(client, tmp_path, agent, case):
    if case == "case-folder":
        make_case(tmp_path, case)
    r = client.get(f"/steps?case={case}&agent={agent}")
    assert r.status_code == 200
    j = r.get_json()
    assert j["agent"] == agent and j["steps"]
    for s in j["steps"]:
        assert {"id", "title", "kind", "data", "caption", "source"} <= set(s)
        assert s["kind"] in {"image", "chart", "table", "graph", "map", "text"}
        assert s["source"], s["id"]
        assert "answer_key" not in s["source"]
    assert "address" not in set(walk_keys(j))
    assert not STREET.search(r.get_data(as_text=True))


def test_steps_unknown_agent_and_flag(client, monkeypatch):
    assert client.get("/steps?case=demo-real-a&agent=nope").status_code == 404
    assert client.get("/steps?case=../x&agent=locator").status_code == 404
    monkeypatch.delenv("DOME_STEPS")
    assert client.get("/steps?case=demo-real-a&agent=locator").status_code == 404


def test_steps_scrub_street_text_and_address_keys(client, tmp_path):
    d = make_case(tmp_path, "street-case")
    m = json.loads((d / "matches.json").read_text())
    m["zones"][0]["matches"][0]["address"] = "1200 Main Street"
    m["zones"][0]["matches"][0]["geo"]["note"] = "near 1200 Main Street, Houston"
    (d / "matches.json").write_text(json.dumps(m))
    for agent in steps_pkg.AGENTS:
        body = client.get(f"/steps?case=street-case&agent={agent}").get_data(as_text=True)
        assert "1200 Main" not in body and '"address"' not in body


def test_locator_steps_use_room_match_numbers(client):
    j = client.get("/steps?case=demo-real-a&agent=locator").get_json()
    ids = [s["id"] for s in j["steps"]]
    assert ids[:2] == ["groups", "scans_map"] and "coarse" in ids and "P" in ids
    coarse = next(s for s in j["steps"] if s["id"] == "coarse")
    assert coarse["data"]["labels"][0] == "LqCMcmmVH3d" and coarse["data"]["highlight"] == [0]


def test_window_fingerprint_is_shown_as_recorded(client):
    j = client.get("/steps?case=demo-real-a&agent=window").get_json()
    fp = next(s for s in j["steps"] if s["id"] == "fingerprint")
    assert "for analyst review" in fp["title"] and "1 of 4" in fp["caption"]


def test_geo_unscored_footprints_say_not_scored(client):
    j = client.get("/steps?case=demo-real-a&agent=geo").get_json()
    fit = next(s for s in j["steps"] if s["id"] == "fit")
    assert any("not scored" in row for row in fit["data"]["rows"]) and fit["data"]["highlight"]
    assert not any(s["id"] == "heading" for s in j["steps"])


def test_missing_in_between_data_says_not_recorded(client, tmp_path):
    d = make_case(tmp_path, "thin-case")
    (d / "room_match.json").unlink()
    j = steps_pkg.build(d, "locator", root=tmp_path)      # no data/matches/summary.json under this root
    assert j["steps"][0]["data"]["note"] == "in-between data not recorded"


def test_recorder_writes_scrubbed_steps(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("record_demo_case", ui.ROOT / "scripts" / "record_demo_case.py")
    rec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rec)
    dst = tmp_path / "rec"
    shutil.copytree(REAL, dst)
    cands = json.loads((dst / "candidates.json").read_text())
    cands["zones"][0]["candidates"][0]["address"] = "4100 Fannin Street"
    (dst / "candidates.json").write_text(json.dumps(cands))
    agents = rec.write_steps(dst, {"4100 Fannin Street"})
    assert set(agents) == set(steps_pkg.AGENTS)
    for f in (dst / "steps").glob("*.json"):
        text = f.read_text()
        assert "Fannin" not in text and '"address"' not in text
        assert all(s["source"] for s in json.loads(text)["steps"])


# ---------------------------------------------------------------- real-data steps
def test_complex_steps_show_held_out_and_no_wallet_scores(client):
    j = client.get("/steps?case=demo-real-a&agent=complex").get_json()
    by = {s["id"]: s for s in j["steps"]}
    assert "15/15" in json.dumps(by["heldout"]["data"]) and "held-out" in by["heldout"]["caption"]
    assert not any(l.startswith("W-") for l in by["scores"]["data"]["labels"])
    assert len(by["disagreements"]["data"]["rows"]) == 5


def test_money_steps_computed_from_the_chain(client):
    j = client.get("/steps?case=demo-real-a&agent=money").get_json()
    by = {s["id"]: s for s in j["steps"]}
    assert {"timeline", "gaps", "clusters", "roles", "flows"} <= set(by)
    real, shifted = by["gaps"]["data"]["datasets"][0]["data"][1], by["gaps"]["data"]["datasets"][1]["data"][1]
    assert real > shifted
    assert all(len(n["label"]) <= 12 for n in by["clusters"]["data"]["nodes"])     # addresses masked


def test_linker_uses_real_wallet_notes(client):
    j = client.get("/steps?case=demo-real-a&agent=linker").get_json()
    mp = next(s for s in j["steps"] if s["id"] == "money_pass")
    assert mp["kind"] == "table" and mp["source"].endswith("wallet_notes.json")


# ---------------------------------------------------------------- ask (DOME_ASK=1)
def test_ask_is_off_without_the_flag(client, monkeypatch):
    monkeypatch.delenv("DOME_ASK", raising=False)
    assert client.post("/ask", json={"case": "demo-real-a", "question": "x"}).status_code == 404


def test_ask_answers_with_citations(client, monkeypatch):
    monkeypatch.setenv("DOME_ASK", "1")
    import dome.ask as ask_mod
    seen = {}

    def fake(case_id, question, root=None, model=None):
        seen.update(case=case_id, root=root)
        return {"answer": "High because P 0.68 and W 0.6.", "answerable": True,
                "citations": [{"file": f"case/{case_id}/brief.json", "path": "leads[0].reasons[2]"}]}
    monkeypatch.setattr(ask_mod, "answer", fake)
    a = client.post("/ask", json={"case": "demo-real-a", "question": "Why High?"}).get_json()
    assert a["answerable"] and a["citations"][0]["path"] == "leads[0].reasons[2]" and seen["case"] == "demo-real-a"
    cite = client.get("/ask/cite?case=demo-real-a&file=case/demo-real-a/brief.json&path=leads[0].reasons[2]").get_json()
    assert cite["value"].startswith("P 0.68")
    assert client.get("/ask/cite?case=demo-real-a&file=../../.env&path=").status_code == 404
    assert client.get("/ask/cite?case=demo-real-a&file=brief.json&path=leads[9]").status_code == 404
    assert client.get("/ask/cite?case=demo-real-a&file=brief.json&path=leads[0].address").status_code == 404


@pytest.mark.parametrize("behaviour", ["raise", "unanswerable"])
def test_ask_falls_back_to_not_in_case(client, monkeypatch, behaviour):
    monkeypatch.setenv("DOME_ASK", "1")
    import dome.ask as ask_mod

    def fake(case_id, question, root=None, model=None):
        if behaviour == "raise":
            raise RuntimeError("no key")
        return {"answer": "guess", "citations": [], "answerable": False}
    monkeypatch.setattr(ask_mod, "answer", fake)
    a = client.post("/ask", json={"case": "demo-real-a", "question": "Who lives there?"}).get_json()
    assert a == {"answer": "That isn't in this case's files.", "citations": [], "answerable": False} or \
        (a["answer"] == "That isn't in this case's files." and not a["answerable"])


def test_ask_recorded_label(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DOME_ASK", "1")
    monkeypatch.setattr(ui, "RECORDED", tmp_path / "rec")
    shutil.copytree(REAL, tmp_path / "rec" / "demo-real-a")
    (tmp_path / "rec" / "demo-real-a" / "ask.json").write_text(json.dumps(
        {"answer": "Because P 0.68.", "citations": [], "answerable": True}))
    r = client.get("/ask?case=demo-real-a").get_json()
    assert r["recorded"] is True and r["answer"] == "Because P 0.68."


def test_assistant_defaults_to_dome_rules(monkeypatch):
    monkeypatch.delenv("DOME_GRAPH_ASSISTANT", raising=False)
    assert globe.assistant_name() == "dome_rules"
    monkeypatch.setenv("DOME_GRAPH_ASSISTANT", "dome")
    assert globe.assistant_name() == "dome"
