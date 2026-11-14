import json

import pytest

from dome.agents import zoner
from dome.synth.common import load_buildings
from dome.synth.generate import generate
from dome.synth.make_case import make_case


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    """Fresh synthetic data + a case folder with ideal rings (test stand-in for the Linker)."""
    root = tmp_path_factory.mktemp("zoner")
    generate(root / "synth", root / "answer_key", seed=37)
    case_dir = make_case(root / "case", root / "answer_key" / "answer_key.json")
    result = zoner.run(case_dir, root / "synth")
    return root, case_dir, {r["ring_id"]: r for r in result}


BUILDINGS = {b["label"]: b for b in load_buildings()}


def inside(zone, label):
    return zoner.point_in_zone(zone, BUILDINGS[label]["lat"], BUILDINGS[label]["lon"])


def test_ring_a_building_inside_its_zone(case):
    zones = case[2]["R-A"]["zones"]
    assert len(zones) == 1
    assert inside(zones[0], "A")
    assert not zones[0]["wide"]


def test_ring_b_gets_two_zones_one_per_building(case):
    zones = case[2]["R-B"]["zones"]
    assert len(zones) == 2
    assert {lab for lab in ("B1", "B2") for z in zones if inside(z, lab)} == {"B1", "B2"}
    assert not any(inside(z, "B1") and inside(z, "B2") for z in zones)


def test_ring_c_is_wide(case):
    zones = case[2]["R-C"]["zones"]
    assert zones and all(z["wide"] for z in zones)
    assert zones[0]["confidence"] < 0.05


def test_confidence_formula(case):
    for ring in case[2].values():
        for z in ring["zones"]:
            assert z["confidence"] == pytest.approx(z["weight_share"] / (1 + z["area_km2"] / 10), abs=0.011)


def test_zones_json_written_and_deterministic(case):
    root, case_dir, _ = case
    first = (case_dir / "zones.json").read_bytes()
    zoner.run(case_dir, root / "synth")
    assert (case_dir / "zones.json").read_bytes() == first
    assert json.loads(first)[0]["zones"][0]["reasons"][-1] == "login layer off"


def test_logins_on_adds_login_reason(case):
    root, case_dir, _ = case
    result = zoner.run(case_dir, root / "synth", logins=True)
    reasons = result[0]["zones"][0]["reasons"]
    assert any("logins fall inside" in r for r in reasons)
    zoner.run(case_dir, root / "synth")   # restore default output


def test_true_building_inside_dome_score(case, capsys):
    root, case_dir, zones = case
    hits, n, median = zoner.score_against_answer_key(
        list(zones.values()), zoner.read_rings(case_dir), root / "answer_key" / "answer_key.json")
    print(f"true building inside the dome: {hits} of {n} rings; median zone area {median:.1f} km2")
    assert hits == n == 3
