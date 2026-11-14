"""The real Linker on the mini synthetic dataset, scored against the answer key."""
from __future__ import annotations

import pytest

pytest.importorskip("numpy")

from dome.agents import linker
from dome.case import Case
from dome.eval import score
from dome.supervisor import run_scripted


@pytest.fixture(scope="module", params=["mini", "synth"])
def result(request):
    """Scored on the mini stand-in and on Ishaan's full synthetic dataset."""
    return score(request.param)


def test_disguised_phone_numbers():
    k = linker.extract_contacts
    assert k("call five5five 0142 now") == {"contact:555-0142"}
    assert k("text four1five 555 0142") == {"contact:555-0142"}
    assert k("(713) 555 0142") == k("5 5 5 - 0 1 4 2") == {"contact:555-0142"}
    assert k("my phone is off, someone call") == set()        # ordinary words are left alone
    assert k("deposit to $bcash77, ask @lena_k") == {"contact:$bcash77", "contact:@lena_k"}


def test_common_keys_count_for_almost_nothing():
    assert linker.rarity(2) == 1.0 and linker.rarity(12) > 0.75
    assert linker.rarity(50) < 0.2 and linker.rarity(200) < 0.02


def test_rings_found_exactly(result):
    assert result["precision"] == 1.0 and result["recall"] == 1.0
    for name, x in result["per_ring"].items():
        assert x["found"] == x["true"] and not x["extra"] and not x["missed"], (name, x)
        assert x["R"] >= 0.6


def test_recall_at_10(result):
    assert all(v >= 0.9 for v in result["recall_at_10"].values()), result["recall_at_10"]


def test_hard_negatives_stay_unlinked(result):
    assert len(result["hard_negatives"]) >= 4
    for kind, x in result["hard_negatives"].items():
        assert x["pulled_into_a_ring"] == [], kind


def test_recruiters_flagged_with_a_reason(result):
    rec = result["recruiters"]
    assert not rec["missed"] and not rec["wrong"]
    assert all("go to ring accounts" in why for why in rec["flagged"].values())


def test_embeddings_catch_a_rewording_minhash_missed(result):
    c = result["embedding_catch"]
    assert c and c["jaccard"] < 0.5 <= c["cosine"]
    assert result["reworded_link"], "the reworded catch must actually link two ring accounts"
    assert "reworded" in result["reworded_link"]["reason"]


@pytest.mark.parametrize("data", ["mini", "synth"])
def test_every_link_has_two_kinds_and_a_reason(data):
    rings = linker.link_accounts(linker.load_dataset(data)).rings_file
    for r in rings["rings"]:
        for l in r["links"]:
            assert len([k for k in l["kinds"] if k != "place"]) >= 2 and l["reason"]
    assert all(h["reason"] for h in rings["weak_hints"])


@pytest.mark.parametrize("scenario,seed,tier", [("ring_a", "acct_017", "High"),
                                                ("ring_b", "acct_501", "High"),
                                                ("ring_c", "acct_701", "Medium")])
def test_pipeline_on_the_real_linker(tmp_path, scenario, seed, tier):
    case = Case.open("real", scenario=scenario, dataset="mini", seed_account=seed,
                     root=tmp_path, reset=True)
    run_scripted(case)
    ring = case.selected_ring()
    assert seed in ring.members
    brief = case.load("brief.json")
    assert brief.status == "complete" and brief.leads[0].tier == tier
    if scenario == "ring_c":   # weak-hint photos pulled in, Locator retried once
        assert ring.photo_expansion_used
        assert {p.photo_id for p in ring.photos if p.link_strength == "weak"} >= {"img_850", "img_851"}
        assert case.load("matches.json").zones[0].attempt == 2
