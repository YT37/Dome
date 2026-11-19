"""data_tools: stub dispatch (always runs) and real data (skips without kit / keys).

Real tests read from the shared cache (cache/ -> ../private/cache), so they make
no API calls once it is warm.
"""
import json
import os
from pathlib import Path

import pytest

from dome.data_tools import costar, geo, matterport, vexcel

DOWNTOWN = [(29.74, -95.39), (29.74, -95.35), (29.78, -95.35), (29.78, -95.39)]
KEYS = {"property_id", "address", "lat", "lon", "type", "floors", "units", "year_built", "has_scan", "scan_id"}
HANDCHECKED = "6WjHU7zCbLh"


def _kit():
    try:
        costar.kit_dir()
        return True
    except RuntimeError:
        return False


def _keys():
    from dome.data_tools._common import REAL_KEYS, load_env
    load_env()
    return all(os.environ.get(k) for k in REAL_KEYS)


needs_kit = pytest.mark.skipif(not _kit(), reason="CoStar kit not unzipped (costar_kit/)")
needs_keys = pytest.mark.skipif(not _keys(), reason="Vexcel/Matterport keys not set")


# --- stub dispatch -----------------------------------------------------------------------

def test_stub_mode_answers_from_scenario():
    rows = costar.properties_in_polygon([(29.0, -96.0), (29.0, -95.0), (30.0, -95.0), (30.0, -96.0)], [])
    assert rows and all(r["property_id"].startswith("CS-") for r in rows)
    fix = geo.fix_scan_location("mp_4471", 29.76, -95.37)
    assert fix["building_id"] == "CS-88412"
    assert vexcel.building_outlines(29.76, -95.37, 100) == []
    assert isinstance(vexcel.oblique_view(29.76, -95.37, 90), str)
    assert isinstance(matterport.sweep_views("mp_4471"), list)


# --- real ----------------------------------------------------------------------------------

@pytest.mark.real
@needs_kit
def test_properties_in_polygon_real():
    rows = costar.properties_in_polygon(DOWNTOWN, ["multifamily"])
    assert rows
    for r in rows:
        assert set(r) == KEYS
        assert r["type"] == "multifamily"
        assert 29.74 <= r["lat"] <= 29.78 and -95.39 <= r["lon"] <= -95.35
        assert r["has_scan"] == (r["scan_id"] is not None)
    assert rows == costar.properties_in_polygon(DOWNTOWN, ["multifamily"])  # deterministic
    everything = costar.properties_in_polygon(DOWNTOWN, [])
    assert len(everything) > len(rows)  # types=[] means all
    assert {r["type"] for r in everything} <= set(costar.COMMERCIAL_TYPES.values()) | {
        "residential_" + v for v in costar.RESIDENTIAL_TYPES.values()}  # raw words
    tri = DOWNTOWN[:2] + DOWNTOWN[3:]
    assert len(costar.properties_in_polygon(tri, [])) < len(everything)


@pytest.mark.real
@needs_kit
def test_type_filters():
    res = costar.properties_in_polygon(DOWNTOWN, ["residential"])
    assert res and all(r["type"].startswith("residential_") for r in res)


@pytest.mark.real
@needs_kit
def test_scan_links_and_unit_floors():
    p = costar.property_for_scan("NLpW1UAp1HJ")
    assert p and p["property_id"] == "CS-23347"
    assert "NLpW1UAp1HJ" in costar.scans_for_property("CS-23347")
    uf = costar.unit_floors_for_scan(HANDCHECKED)
    assert uf["floors"] == [5, 6, 7] and uf["level"] == "model"
    assert costar._floor_from_unit("1204", None, 20) == 12
    assert costar._floor_from_unit("5004", None, 7) == 5


@pytest.mark.real
@needs_keys
def test_sweep_views_real():
    views = matterport.sweep_views(HANDCHECKED)
    assert views
    for v in views[:8]:
        assert set(v) == {"view_id", "image_path", "heading_deg", "floor", "sweep_id"}
        assert Path(v["image_path"]).is_file() and 0 <= v["heading_deg"] < 360


@pytest.mark.real
@needs_keys
def test_vexcel_real():
    out = vexcel.building_outlines(29.7686352, -95.3960015, 60)
    assert out and set(out[0]) == {"outline", "height_m", "building_id"}
    assert out[0]["outline"].startswith("POLYGON") or out[0]["outline"].startswith("MULTIPOLYGON")


@pytest.mark.real
@needs_keys
@needs_kit
def test_fix_scan_location_real_contract():
    from dome.tools.handcheck import rough_location
    loc = rough_location(HANDCHECKED)
    r = geo.fix_scan_location(HANDCHECKED, loc["lat"], loc["lon"])
    assert set(r) == set(geo.CONTRACT_KEYS)
    assert r["building_id"] == "vx_9d2da3eb1f"          # matches Yug's hand-check
    assert r["floor_range"] == [5, 7]                   # CoStar unit numbers 5004/6004/7004
    notes = next(e for e in r["evidence"] if e.endswith("_notes.json"))
    assert "geocoordinates_patch" in json.loads(Path(notes).read_text())["result"]


# --- real room match (renders + cached scan indexes required) ------------------------------------

RING_A_SCAN, DECOY_D_SCAN = "LqCMcmmVH3d", "FQZd6kTpht1"


def _ring_a_photos() -> list[str]:
    root = Path(__file__).resolve().parents[1]
    renders = json.loads((root / "data/synth/renders.json").read_text())
    return [str(root / "data/photos" / f"{pid}.jpg") for pid, v in sorted(renders.items())
            if v["scan_id"] == RING_A_SCAN and (root / "data/photos" / f"{pid}.jpg").exists()]


needs_renders = pytest.mark.skipif(len(_ring_a_photos()) < 20, reason="ad photos not rendered (data/photos/)")


@pytest.mark.real
@needs_keys
@needs_renders
def test_room_match_ring_a_above_decoy_d_below():
    from dome.data_tools import vision
    res = {r["scan_id"]: r for r in vision.room_match(_ring_a_photos(), [RING_A_SCAN, DECOY_D_SCAN])}
    assert res[RING_A_SCAN]["P"] >= 0.6
    assert res[DECOY_D_SCAN]["P"] < 0.4
    ev = res[RING_A_SCAN]["evidence"]
    assert ev and all(e["view_id"].startswith(RING_A_SCAN + "/") and e["inliers"] > 0 for e in ev)
    assert all(Path(e["match_img"]).name.startswith(e["photo"]) for e in ev)


@pytest.mark.real
@needs_keys
def test_room_match_never_indexes_holdout_sweeps():
    from dome.data_tools import render, room_match
    _, hold = render.split_sweeps(RING_A_SCAN)
    idx = room_match.scan_index(RING_A_SCAN)
    assert hold and not set(map(str, idx["sweep_ids"])) & set(hold)


def test_room_match_coarse_pass_keeps_only_top_scans(monkeypatch, tmp_path):
    """Many candidates: only the coarse top COARSE_KEEP get the full check; the rest get P 0
    with their rank recorded (never a made-up score)."""
    import numpy as np
    from dome.data_tools import room_match as rm
    scans = [f"s{i:02d}" for i in range(20)]
    checked = []
    monkeypatch.setattr(rm, "_load_photo", lambda p: np.zeros((8, 8, 3), np.uint8))
    monkeypatch.setattr(rm, "embed", lambda ims: np.ones((len(ims), 384), np.float32))
    monkeypatch.setattr(rm, "coarse_rank", lambda e, s: [(x, 1.0 - i / 100) for i, x in enumerate(sorted(s, reverse=True))])

    def fake_scores(paths, full):
        checked.extend(full)
        return {"names": ["p1"], "images": [None], "emb": None, "groups": [[0]],
                "scores": {"p1": {s: {"inliers": 0, "view_id": None} for s in full}}}
    monkeypatch.setattr(rm, "photo_scores", fake_scores)
    out = {r["scan_id"]: r for r in rm.room_match(["x.jpg"], scans, save_images=False)}
    assert checked == sorted(scans, reverse=True)[:rm.COARSE_KEEP]
    assert len(out) == 20 and all(out[s]["P"] == 0.0 for s in scans)
    assert out["s00"]["stage"] == "coarse" and "rank 20 of 20" in out["s00"]["note"]
