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
