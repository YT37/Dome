"""Night (a-topo): case complex (contract F) and the UniGCN node scorer."""
import json

import pytest

from dome import complex as cx
from dome import config
from dome.case import Case
from dome.schemas import ComplexFile, MoneyBlock, WalletNotesFile
from dome.supervisor import run_scripted

NIGHT = config.SAMPLES / "night"


def test_cells_include_wallets_rooms_and_buildings():
    class R:   # minimal rings stand-in with a money block
        ring_id, members, recruiters, photos = "R-A", ["acct_103", "acct_233"], [], []
        money = MoneyBlock.model_validate_json((NIGHT / "money.json").read_text())
    rings = type("RF", (), {"rings": [R]})
    notes = WalletNotesFile.model_validate_json((NIGHT / "wallet_notes.json").read_text())
    rooms = {"scanA": {"P": 0.68, "property_id": "RL-1", "photos": ["img_1"], "source": "test"}}
    cells = cx.cells_from([(1, "contact", "contact:555", ["acct_103", "acct_233"])], rings, notes,
                          rooms, {"img_1": "acct_103"})
    kinds = {c["kind"] for c in cells}
    assert {"contact", "payment_then_post", "wallet_flow", "wallet_note", "photo_in_room",
            "room_in_building"} <= kinds
    ptp = next(c for c in cells if c["kind"] == "payment_then_post")
    assert ptp["members"] == ["W-1", "acct_103"]
    assert cx.node_type("W-1", {"acct_103"}) == "wallet_cluster"
    assert cx.node_type("room_scanA", set()) == "room"


def test_split_is_stratified_and_fixed():
    uni = [f"a{i}" for i in range(100)]
    pos = {f"a{i}" for i in range(10)}
    tr, va, te = cx._split(uni, pos)
    assert (tr, va, te) == cx._split(uni, pos)
    assert not (tr & va or tr & te or va & te) and len(tr | va | te) == 100
    assert len(tr & pos) == 6 and len(va & pos) == 2 and len(te & pos) == 2


def test_stub_case_complex_validates_without_model(tmp_path):
    case = Case.open("cx", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case)
    out = cx.build(case)
    ComplexFile.model_validate(out)
    assert out["ranks"]["0"] and out["ranks"]["3"][0]["kind"] == "ring"
    assert out["scores"] == {} and "not run" in out["model"]   # never a made-up score


@pytest.mark.skipif(not cx.MODEL_PATH.exists(), reason="no trained complex model")
def test_synth_case_gets_model_scores(tmp_path):
    pytest.importorskip("topomodelx")
    case = Case.open("cxs", scenario="ring_a", root=tmp_path, reset=True, dataset="synth",
                     seed_account="acct_103")
    run_scripted(case)
    out = json.loads(case.path("complex.json").read_text())
    ring = case.selected_ring()
    assert set(out["scores"]) >= set(ring.members)
    assert "eval" in out and out["eval"]["split"]["seed"] == 0


def test_phone_like_keys_are_masked():
    cells = cx.cells_from([(1, "contact", "contact:555-0142", ["a", "b"])])
    assert "0142" not in cells[0]["id"] and "555-…42" in cells[0]["reason"]


def test_room_results_read_case_room_match_first(tmp_path):
    case = Case.open("rm", scenario="ring_a", root=tmp_path, reset=True)
    case.path("room_match.json").write_text(json.dumps({
        "P": {"LqCMcmmVH3d": 0.68, "FQZd6kTpht1": 0.0},
        "scans": {"LqCMcmmVH3d": {"P": 0.68, "evidence": [{"photo": "img_a1", "inliers": 212}]}}}))
    rooms = cx._room_results(case)
    a = rooms["LqCMcmmVH3d"]
    assert a["P"] == 0.68 and a["source"] == "room_match.json" and a["property_id"] == "RL-213304177"
    assert "img_a1" in a["photos"] and rooms["FQZd6kTpht1"]["P"] == 0.0


def test_struct_features_are_within_dataset_percentiles():
    ds = {"accounts": {"a": {"flags": ["x"]}, "b": {}, "c": {}}, "posts": [], "transactions": []}
    cells = [{"rank": 1, "kind": "contact", "id": "k", "members": ["a", "b"]}]
    accts, X, members, names = cx.struct_features(ds, cells)
    assert accts == ["a", "b", "c"] and all(0.0 <= v <= 1.0 for row in X for v in row)
    assert not any("acct" in n or "555" in n for n in names)          # no ids or keys as features
    assert X[2] == [0.0] * len(names)                                  # c shares nothing
