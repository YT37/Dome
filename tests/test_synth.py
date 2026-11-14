import json

import pytest

from dome.synth.check import run_checks
from dome.synth.common import load_buildings, load_gazetteer, km_between, normalize_phone
from dome.synth.generate import generate


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    root = tmp_path_factory.mktemp("synth")
    generate(root / "synth", root / "answer_key", seed=37)
    return root


def load(root, name):
    return json.loads((root / name).read_text())


def test_checker_passes(synth):
    assert run_checks(synth / "synth", synth / "answer_key" / "answer_key.json") == []


def test_same_seed_same_bytes(synth, tmp_path):
    generate(tmp_path / "synth", tmp_path / "answer_key", seed=37)
    for name in ["accounts.json", "posts.json", "interactions.json", "renders.json"]:
        assert (tmp_path / "synth" / name).read_bytes() == (synth / "synth" / name).read_bytes()


def test_group_sizes(synth):
    key = load(synth, "answer_key/answer_key.json")
    assert len(key["A"]["members"]) == 12 and len(key["A"]["recruiters"]) == 3
    assert len(key["A"]["amplifiers"]) == 5
    assert len(key["B"]["members"]) == 8 and len(key["C"]["members"]) == 6
    assert sum(len(v) for v in key["hard_negatives"].values()) == 150
    assert 750 <= len(load(synth, "synth/accounts.json")) <= 850


def test_ring_a_clues_near_building_a(synth):
    key = load(synth, "answer_key/answer_key.json")
    gaz = load_gazetteer()
    a = next(b for b in load_buildings() if b["label"] == "A")
    members = set(key["A"]["members"])
    posts = [p for p in load(synth, "synth/posts.json") if p["account_id"] in members]
    assert len(posts) == 90
    for p in posts:
        for name in ([p["stated_area"]] if p["stated_area"] else []) + p["landmarks"]:
            g = gaz[name]
            assert km_between(g["lat"], g["lon"], a["lat"], a["lon"]) < 1.2


def test_ring_c_is_city_wide_only(synth):
    key = load(synth, "answer_key/answer_key.json")
    gaz = load_gazetteer()
    members = set(key["C"]["members"])
    renders = load(synth, "synth/renders.json")
    for p in load(synth, "synth/posts.json"):
        if p["account_id"] in members:
            assert p["landmarks"] == []
            assert gaz[p["stated_area"]]["kind"] == "city"
            assert all(renders[ph]["view"] != "window" for ph in p["photo_ids"])


def test_disguised_phones_normalize():
    assert normalize_phone("five5five-0142") == "555-0142"
    assert normalize_phone("555 O142") == "555-0142"
    assert normalize_phone("5 5 5 - 0 1 4 2") == "555-0142"
    assert normalize_phone("(555) 0142") == "555-0142"
