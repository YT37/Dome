"""v2: messages + payments, the 10 sticky notes, the four patterns and the two new decisions.

Data is synthetic (dome/synth/private_layers.py plants the patterns; answer_key_private.json
scores them). Agents never read the answer key; only these tests and dome/eval.py do.
"""
from __future__ import annotations

import json
from itertools import combinations

import pytest

from dome import config
from dome.agents import linker
from dome.data_tools import _stub
from dome.case import Case
from dome.eval import three_way
from dome.supervisor import NO_HINTS, ROOM_RERUN, run_scripted

SYNTH_KEY = config.ROOT / "data" / "answer_key"


@pytest.fixture
def ring_a_variant(monkeypatch):
    """Serve a tweaked copy of Ring A from the stub data tools (same as test_dome.py)."""
    import copy
    base = _stub._load("ring_a")

    def make(edit):
        data = copy.deepcopy(base)
        edit(data)
        monkeypatch.setattr(_stub, "scenario", lambda: data)
    return make


@pytest.fixture(scope="module")
def synth():
    ds = linker.load_dataset("synth")
    if not ds["messages"]:
        pytest.skip("no messages.json in data/synth")
    key = json.loads((SYNTH_KEY / "answer_key.json").read_text(encoding="utf-8"))
    pk = json.loads((SYNTH_KEY / "answer_key_private.json").read_text(encoding="utf-8"))["rings"]["A"]
    linked = linker.link_accounts(ds)
    members = set(key["A"]["members"])
    ring = max(linked.rings_file["rings"], key=lambda r: len(members & set(r["members"])))
    return {"ds": ds, "key": key, "pk": pk, "linked": linked, "ring": ring, "members": members}


def test_shared_wallet_and_dms_link_ring_a(synth):
    r = synth["ring"]
    assert set(r["members"]) == synth["members"]
    assert r["kind_counts"].get("money", 0) > 0 and r["kind_counts"].get("dm", 0) > 0
    reasons = " ".join(l["reason"] for l in r["links"])
    assert "same wallet" in reasons and "direct messages" in reasons


def test_no_private_drops_money_dm_merchant():
    ds = linker.load_dataset("synth")
    rf = linker.link_accounts(ds, private=False).rings_file
    assert rf["private_layers"] is False
    for r in rf["rings"]:
        assert not {"money", "dm", "merchant", "echo"} & set(r["kind_counts"])
        assert r["events"] == [] and r["location_hints"] == []


def test_relay_race_chain(synth):
    got = {(h["key"], h["from"], h["to"]) for h in synth["ring"]["relay"]}
    want = [(h["key"], h["from"], h["to"]) for h in synth["pk"]["handoffs"]]
    assert len(want) >= 2 and all(h in got for h in want)


def test_heartbeat_links_shift_accounts_not_friends(synth):
    hb = {tuple(sorted(p[:2])) for p in synth["linked"].stats["heartbeat_pairs"]}
    for g in synth["pk"]["heartbeat_groups"]:
        assert all(tuple(sorted(p)) in hb for p in combinations(g, 2))
    friends = set(synth["key"]["hard_negatives"]["friend_group"])
    assert not any(a in friends or b in friends for a, b in hb)


def test_echo_event_spans_three_data_types_with_a_place(synth):
    events = synth["ring"]["events"]
    assert any(len({i["type"] for i in e["items"]}) >= 3 and len(e["items"]) >= 3 and e["place_hint"]
               for e in events)
    assert any(h["kind"] == "echo" for h in synth["ring"]["location_hints"])


def test_money_shape_roles(synth):
    got = {x["account"]: x["role"] for x in synth["ring"]["roles"]}
    for acct, role in synth["pk"]["roles"].items():
        assert got.get(acct) == role, (acct, role, got.get(acct))


def test_hard_negatives_stay_unlinked_with_private_layers(synth):
    in_ring = {m for r in synth["linked"].rings_file["rings"] for m in r["members"]}
    for kind, accts in synth["key"]["hard_negatives"].items():
        assert not set(accts) & in_ring, kind


def test_three_way_comparison_runs():
    out = three_way("synth")
    assert set(out) == {"content", "network", "both"}
    assert out["both"]["recall"] >= out["network"]["recall"]
    assert out["both"]["negatives_linked"] == 0


# ---------------------------------------------------------------- supervisor decisions (v2)
def test_no_hints_decision_falls_back_to_logins_and_caps_medium(tmp_path):
    """Mini Ring C: messages and payments with no place in them."""
    case = Case.open("noh", scenario="ring_a", root=tmp_path, reset=True, dataset="mini",
                     seed_account="acct_701")
    run_scripted(case)
    d = [x for x in case.decisions() if x.decision == NO_HINTS]
    assert d and d[0].evidence["location_hints"] == 0
    brief = case.load("brief.json")
    assert brief.leads and all(l.tier != "High" for l in brief.leads)


def test_room_groups_with_outside_account_rerun_linker_once(tmp_path, ring_a_variant):
    def edit(data):
        data["rings"]["weak_hints"] = [{
            "a": "acct_017", "b": "acct_404", "keys": ["contact:@x"], "kinds": ["contact"],
            "strength": 0.5, "reason": "one key kind is a hint, not a link"}]
        data["weak_photos"] = [{"photo_id": "img_977", "path": "data/photos/img_977.jpg",
                                "account": "acct_404"}]
        data["photo_groups"] = [{"group_id": "RG-1", "photos": ["img_311", "img_977"], "scan_id": "mp_4471",
                                 "details": ["same two-pin socket left of bed", "same carpet stain"]}]
    ring_a_variant(edit)
    case = Case.open("room", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case)
    names = [x.decision for x in case.decisions()]
    assert names.count(ROOM_RERUN) == 1 and "ring_updated_by_room_links" in names
    ring = case.selected_ring()
    assert "acct_404" in ring.members and "room" in ring.key_kinds
    assert case.load("rings.json").room_links_used
    assert case.load("brief.json").status == "complete"


def test_lister_hint_boost_ranks_true_building(tmp_path):
    case = Case.open("boost", scenario="ring_a", root=tmp_path, reset=True, dataset="synth",
                     seed_account="acct_103")
    run_scripted(case)
    zone = case.load("candidates.json").zones[0]
    ids = [c.property_id for c in zone.candidates]
    assert "CS-88412" in ids
    true = next(c for c in zone.candidates if c.property_id == "CS-88412")
    assert any("hint" in r for r in true.fit_reasons)


# ---------------------------------------------------------------- topological scorer (optional)
def test_topological_scorer_is_optional_and_scores_ring_a(monkeypatch):
    from dome.agents import topo
    ds = linker.load_dataset("synth")
    monkeypatch.setattr(config, "TOPO_SCORE", False)
    off = linker.link_accounts(ds).rings_file
    assert all(r["topo_score"] is None for r in off["rings"])
    if not (topo.available() and topo.MODEL_PATH.exists()):
        pytest.skip("topological model not installed")
    monkeypatch.setattr(config, "TOPO_SCORE", True)
    on = linker.link_accounts(ds).rings_file
    # the rules are untouched: same rings, same confidence
    assert [(r["members"], r["confidence"]) for r in on["rings"]] == \
           [(r["members"], r["confidence"]) for r in off["rings"]]
    key = json.loads((SYNTH_KEY / "answer_key.json").read_text(encoding="utf-8"))
    ring_a = max(on["rings"], key=lambda r: len(set(key["A"]["members"]) & set(r["members"])))
    assert ring_a["topo_score"] >= 0.9


def test_track2_no_private_runs_to_a_high_lead_without_the_hints_cap(tmp_path):
    """Arlequin Track 2: public data only. No messages/payments -> no 'no hints' cap."""
    case = Case.open("t2", scenario="ring_a", root=tmp_path, reset=True, dataset="synth",
                     seed_account="acct_103", private_layers=False)
    run_scripted(case)
    rings = case.load("rings.json")
    assert rings.private_layers is False
    assert not {"money", "dm", "merchant", "echo"} & set(case.selected_ring().key_kinds)
    assert NO_HINTS not in [d.decision for d in case.decisions()]
    lead = case.load("brief.json").leads[0]
    assert (lead.property_id, lead.tier) == ("CS-88412", "High")
