import json

import pytest

from dome.agents import spotter
from dome.case import Case
from dome.synth.generate import generate


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("spotter")
    generate(root / "synth", root / "key", seed=37)
    return root


def key(world):
    return json.loads((world / "key" / "spotter_key.json").read_text())


def test_flags_only_with_three_kinds_and_finds_the_ring(world):
    q = spotter.from_dataset(world / "synth")
    assert q["queue"] and all(len(r["signals"]) >= 3 for r in q["queue"])
    pos = set(key(world)["positives"])
    top10 = [r["account"] for r in q["queue"][:10]]
    assert sum(a in pos for a in top10) == 10                         # precision@10
    assert {r["account"] for r in q["queue"]} == pos                  # the ring and its recruiters, nobody else


def test_hard_negatives_and_honest_accounts_stay_unflagged(world):
    flagged = {r["account"] for r in spotter.from_dataset(world / "synth")["queue"]}
    negatives = {a for ids in key(world)["negatives"].values() for a in ids}
    assert not flagged & negatives


def test_every_signal_has_a_reason_and_no_full_phone(world):
    for r in spotter.from_dataset(world / "synth")["queue"]:
        for s in r["signals"]:
            assert s["reason"] and s["kind"] in spotter.WEIGHTS
            assert "555-01" not in s["reason"]                         # phones are masked (555-…42)


def test_lure_rule_is_bland_and_precise():
    lure = [{"account_id": "x", "text": "Easy money, cash paid weekly, travel covered, no interview needed. Message us today.", "phones": []}]
    honest = [{"account_id": "y", "text": "Hiring a cashier in Midtown, $17/hr, uniform provided. Apply in person Mon-Fri.", "phones": []}]
    s = spotter.scan([], lure + honest, [])
    assert "lure_offer" in s["x"] and "lure_offer" not in s.get("y", {})


def test_payment_then_post_notes_add_a_signal(world, tmp_path):
    case = Case.open("s", dataset=str(world / "synth"), root=tmp_path, reset=True)
    acct = key(world)["positives"][0]
    case.path("wallet_notes.json").write_text(json.dumps({"notes": [
        {"account": acct, "cluster_id": "W-1", "kind": "money", "reason": "paid 7 min before posting, 11 times"}]}))
    out = spotter.run(case)
    row = next(r for r in out["queue"] if r["account"] == acct)
    assert "payment_then_post" in {s["kind"] for s in row["signals"]}
    assert json.loads(case.path("spotter.json").read_text()) == out
