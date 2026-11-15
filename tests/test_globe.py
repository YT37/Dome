"""Globe flight, link chart, panels and the asset route (DOME_GLOBE=1)."""
import json
import os
import shutil

import pytest

from dome.ui import app as ui
from dome.ui import globe

REAL = ui.RECORDED / "demo-real-a"
NODE_TYPES = {"account", "phone", "script", "photo", "room", "building", "wallet_cluster", "service", "place"}
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
    c = ui.app.test_client()
    for path in ("/globe", "/flight?case=demo-real-a", "/panels?case=demo-real-a", "/events?case=demo-real-a",
                 "/asset/data/demo_assets/LqCMcmmVH3d/ortho.jpg"):
        assert c.get(path).status_code == 404, path
    assert c.post("/approve", json={"case": "demo-real-a"}).status_code == 404
    assert c.get("/ui-flags").get_json() == {"globe": False}
    assert c.get("/").status_code == 200          # the classic console is still the default


def test_globe_page_and_flag(client):
    page = client.get("/globe").get_data(as_text=True)
    assert "Synthetic case." in page and "Public data only." in page
    assert "maplibre-gl@5.6.0" in page            # pinned CDN versions
    assert client.get("/ui-flags").get_json() == {"globe": True}


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
def test_graph_from_rings_and_matches(client):
    r = client.get("/graph?case=demo-real-a")
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
    wallet = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"

    def patch(rings):
        members = rings["rings"][0]["members"]
        rings["money"] = {
            "wallet_clusters": [{"id": "W1", "masked_label": "bc1q…0wlh", "members": members[:3], "role": "collector",
                                 "reason": f"pays from {wallet} then posts"}],
            "flows": [{"from": members[0], "to": "W1", "time": "2026-10-01T10:00:00Z", "kind": "payment", "reason": "payment"}],
            "cash_out": [{"cluster": "W1", "service": "exchange_1", "masked_label": "Exchange (masked)", "reason": "cash-out"}]}
    make_case(tmp_path, "money-case", rings_patch=patch)
    r = client.get("/graph?case=money-case")
    g = r.get_json()
    types = {n["type"] for n in g["nodes"]}
    assert {"wallet_cluster", "service"} <= types
    assert any(e["layer"] == "money" for e in g["edges"])
    assert wallet not in r.get_data(as_text=True)
    panels = client.get("/panels?case=money-case")
    assert panels.get_json()["money"]["wallet_clusters"] and wallet not in panels.get_data(as_text=True)


# ---------------------------------------------------------------- panels + recorded actions
def test_panels_hide_when_files_are_missing(client):
    p = client.get("/panels?case=demo-real-a").get_json()
    assert p["spotter"] is None and p["topology"] is None and p["money"] is None


def test_spotter_and_approval_only_record(client, tmp_path):
    spot = [{"account": "acct_103", "score": 0.91, "rank": 1, "signals": [{"kind": "contact", "reason": "shared 555-0142"}]}]
    make_case(tmp_path, "spot-case", extra={"spotter.json": spot})
    p = client.get("/panels?case=spot-case")
    assert p.get_json()["spotter"][0]["account"] == "acct_103"
    assert "555-0142" not in p.get_data(as_text=True)
    assert client.post("/spotter/choose", json={"case": "spot-case", "account": "acct_103"}).get_json()["recorded"]
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
    assert {e["phase"] for e in evs} <= {"start", "result", "decision", "interrupt"}
    assert any(e["phase"] == "decision" for e in evs)


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
    "/asset/data/photos/img.jpg",
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
    assert globe.mask_text("send to bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh") == "send to bc1q…0wlh"
    assert globe.mask_text("created 2026-09-02") == "created 2026-09-02"
