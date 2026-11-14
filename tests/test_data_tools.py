"""data_tools: stub dispatch (always runs) and real data (skips without kit / keys).

Real tests read from the shared cache (cache/ -> ~/Desktop/Dome/cache), so they make
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
