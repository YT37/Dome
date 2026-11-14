import pytest

from dome.agents import zoner
from dome.case import Case
from dome.schemas import ZonesFile
from dome.synth.common import load_buildings
from dome.synth.generate import generate
from dome.synth.make_case import make_case

BUILDINGS = {b["label"]: b for b in load_buildings()}


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    root = tmp_path_factory.mktemp("zoner")
    generate(root / "synth", root / "answer_key", seed=37)
    return root


def zones_for(synth, ring_id, logins="off"):
    """Case on the synthetic dataset with ideal rings (test stand-in for the Linker)."""
    case = Case.open(f"z-{ring_id}", dataset=str(synth / "synth"), ring_id=ring_id,
                     root=synth / "cases", reset=True)
    make_case(case, synth / "answer_key" / "answer_key.json")
    out = ZonesFile.model_validate(zoner.run(case, logins=logins))   # the supervisor's check
    return case, out.model_dump()["zones"]


def inside(zone, label):
    return zoner.point_in_zone(zone, BUILDINGS[label]["lat"], BUILDINGS[label]["lon"])


def test_ring_a_building_inside_its_zone(synth):
    _, zones = zones_for(synth, "R-A")
    assert len(zones) == 1
    assert inside(zones[0], "A")
    assert not zones[0]["wide"]


def test_ring_b_gets_two_zones_one_per_building(synth):
    _, zones = zones_for(synth, "R-B")
    assert len(zones) == 2
    assert {lab for lab in ("B1", "B2") for z in zones if inside(z, lab)} == {"B1", "B2"}
    assert not any(inside(z, "B1") and inside(z, "B2") for z in zones)


def test_ring_c_is_wide(synth):
    _, zones = zones_for(synth, "R-C")
    assert zones and all(z["wide"] for z in zones)
    assert zones[0]["confidence"] < 0.05


def test_confidence_formula(synth):
    for ring_id in ("R-A", "R-B", "R-C"):
        for z in zones_for(synth, ring_id)[1]:
            assert z["confidence"] == pytest.approx(z["weight_share"] / (1 + z["area_km2"] / 10), abs=0.011)


def test_deterministic(synth):
    assert zones_for(synth, "R-A")[1] == zones_for(synth, "R-A")[1]


def test_login_layer(synth):
    assert zones_for(synth, "R-A")[1][0]["reasons"][-1] == "login layer off"
    assert any("logins fall inside" in r for r in zones_for(synth, "R-A", logins="on")[1][0]["reasons"])


def test_stub_scenario_keeps_fixture_zones(tmp_path):
    case = Case.open("stub", scenario="ring_b", root=tmp_path, reset=True)
    case.save("rings.json", {"case_id": "stub", "rings": [
        {"ring_id": "R-B", "members": ["a", "b"], "confidence": 0.8, "key_kinds": ["contact"]}]})
    assert [z["zone_id"] for z in zoner.run(case)["zones"]] == ["Z-B1", "Z-B2"]


def test_true_building_inside_dome_score(synth):
    results = []
    for ring_id in ("R-A", "R-B", "R-C"):
        case, zones = zones_for(synth, ring_id)
        results.append((case.selected_ring().members, zones))
    hits, n, median = zoner.score_against_answer_key(results, synth / "answer_key" / "answer_key.json")
    print(f"true building inside the dome: {hits} of {n} rings; median zone area {median:.1f} km2")
    assert hits == n == 3
