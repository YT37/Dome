import json
import re

import pytest

from dome.agents import money
from dome.case import Case
from dome.synth.chain import build as build_chain
from dome.synth.generate import generate
from dome.synth.make_case import make_case


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("money")
    generate(root / "synth", root / "key", seed=37)
    build_chain(root / "synth", root / "key")
    return root


def load(p):
    return json.loads(p.read_text())


def test_ledger_is_obviously_fake_and_never_in_posts(world):
    txs = load(world / "synth" / "chain" / "transactions.json")
    addrs = {x["address"] for t in txs for side in ("inputs", "outputs") for x in t[side]}
    assert addrs and all(re.fullmatch(r"syn1q[0-9a-f]{32}", a) for a in addrs)
    posts = (world / "synth" / "posts.json").read_text()
    assert "syn1q" not in posts


def test_finds_every_role_with_exact_addresses(world):
    txs, services = money.load_chain(world / "synth")
    posts = load(world / "synth" / "posts.json")
    key = load(world / "key" / "answer_key.json")
    ck = load(world / "key" / "chain_key.json")
    out = money.analyse(txs, services, posts, set(key["A"]["members"]))
    roles = {c["role"]: c["cluster_id"] for c in out["money"]["wallet_clusters"]}
    assert set(roles) == {"advertiser", "collector", "aggregator", "cash_out"}
    for role, addrs in ck["clusters"].items():
        assert set(out["addresses"][roles[role]]) == set(addrs)
    decoys = set(ck["decoys"])
    assert not any(set(a) & decoys for a in out["addresses"].values())
    assert all(c["confidence"] >= 0.7 and c["reasons"] for c in out["money"]["wallet_clusters"])
    assert out["money"]["cash_out"][0]["service"] == "Exchange X"


def test_wallet_notes_tie_ring_accounts_only(world):
    txs, services = money.load_chain(world / "synth")
    posts = load(world / "synth" / "posts.json")
    ring = set(load(world / "key" / "answer_key.json")["A"]["members"])
    notes = money.analyse(txs, services, posts, ring)["wallet_notes"]["notes"]
    noted = {n["account"] for n in notes}
    assert noted and noted <= ring                        # scored over all accounts, only ring members tie
    assert all(n["kind"] == "money" and n["cluster_id"] == "W-1" for n in notes)


def test_attach_writes_contract_b_and_g(world, tmp_path):
    case = Case.open("m", dataset=str(world / "synth"), ring_id="R-A", root=tmp_path, reset=True)
    make_case(case, world / "key" / "answer_key.json")
    block = money.attach(case)
    rings = load(case.path("rings.json"))
    ring = next(r for r in rings["rings"] if r["ring_id"] == "R-A")
    assert ring["money"] == block
    assert set(block) == {"wallet_clusters", "flows", "cash_out", "payment_then_post", "attribution_confidence"}
    notes = load(case.path("wallet_notes.json"))
    assert notes["notes"] and {"account", "cluster_id", "kind", "reason"} <= set(notes["notes"][0])


def test_no_ledger_means_no_money(tmp_path):
    case = Case.open("stub", scenario="ring_a", root=tmp_path, reset=True)
    case.save("rings.json", {"case_id": "stub", "rings": [
        {"ring_id": "R-A", "members": ["a", "b"], "confidence": 0.8, "key_kinds": ["contact"]}]})
    assert money.attach(case) is None
