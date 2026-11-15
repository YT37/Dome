"""Gemini photo cues and window check, driven by a fake Gemini (no key, no quota needed).

Checks: answers are parsed and cached (same photos -> no second call), W is computed by code
from fixed items, and every fallback is honest (stub only without image files; neutral cues
or W = None when Gemini cannot run on real photos).
"""
from __future__ import annotations

import json

import pytest
from PIL import Image

from dome.agents import lister
from dome.case import Case
from dome.data_tools import gemini_vision as gv
from dome.data_tools import vision
from dome.supervisor import Supervisor, run_scripted

STUB_CUES = {"setting": "apartment", "window_floor_est": [3, 5], "features": ["balcony"]}


@pytest.fixture
def gem(tmp_path, monkeypatch):
    """A fake Gemini: answers[task] is the JSON it returns; calls records every call."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("DOME_STUBS", "0")         # exercise the real Gemini path (oblique is faked per test)
    monkeypatch.setenv("DOME_VISION_CACHE", str(tmp_path / "cache"))
    calls, answers = [], {}

    def fake(task, model, prompt, images):
        calls.append(task)
        a = answers[task]
        return a if isinstance(a, str) else json.dumps(a)

    monkeypatch.setattr(gv, "GENERATE", fake)
    return calls, answers


def img(tmp_path, name, color=(120, 160, 200)):
    p = tmp_path / name
    Image.new("RGB", (64, 48), color).save(p)
    return str(p)


VIEW_OK = {"road_front": "yes", "parking_front": "yes", "building_across": "no", "trees": "yes",
           "open_sky": "yes", "height_above_street": "low"}
OBL_OK = {"road_front": "yes", "parking_front": "yes", "building_across": "yes", "trees": "yes",
          "open_sky": "yes", "facade_floors": 6}


# ---------------------------------------------------------------- photo cues
def test_cues_without_image_files_use_the_stub(gem):
    calls, _ = gem
    out = gv.photo_cues(["data/photos/does_not_exist.jpg"], stub=lambda: dict(STUB_CUES))
    assert out["source"] == "stub" and out["setting"] == "apartment" and calls == []


def test_cues_from_gemini_are_parsed_cleaned_and_cached(gem, tmp_path):
    calls, answers = gem
    answers["photo_cues"] = {"setting": "apartment", "window_visible": True, "window_floor_lo": 5,
                             "window_floor_hi": 3, "features": ["Balcony!", "street trees",
                                                                "balcony", "brick facade"]}
    photos = [img(tmp_path, "a.jpg"), img(tmp_path, "b.jpg", (10, 20, 30))]
    out = gv.photo_cues(photos, stub=lambda: {})
    assert out == {"setting": "apartment", "window_floor_est": [3, 5],
                   "features": ["balcony", "street trees", "brick facade"], "source": "gemini"}
    assert gv.photo_cues(list(reversed(photos)), stub=lambda: {}) == out   # order-independent
    assert calls == ["photo_cues"]                                        # second call: cache


def test_cues_malformed_twice_or_no_key_give_neutral_cues(gem, tmp_path, monkeypatch):
    calls, answers = gem
    answers["photo_cues"] = "not json at all"
    photo = img(tmp_path, "a.jpg")
    assert gv.photo_cues([photo], stub=lambda: {})["source"] == "none"
    assert calls == ["photo_cues", "photo_cues"]                          # retried once
    monkeypatch.delenv("GOOGLE_API_KEY")
    out = gv.photo_cues([img(tmp_path, "c.jpg", (1, 2, 3))], stub=lambda: {})
    assert out == gv.NEUTRAL_CUES                                         # never the fixture


# ---------------------------------------------------------------- window check
def oblique(path):
    return lambda lat, lon, heading: path


def test_window_check_w_is_the_share_of_items_that_agree(gem, tmp_path):
    calls, answers = gem
    answers.update(window_box={"window_visible": True, "box": [100, 200, 700, 800]},
                   window_view=VIEW_OK, oblique_view=OBL_OK)
    out = gv.window_check(img(tmp_path, "win.jpg"), 29.76, -95.36, 212, stub=lambda: {},
                          oblique_view=oblique(img(tmp_path, "obl.jpg")))
    # 6 items decided; building_across disagrees -> 5 of 6
    assert out["checks"] == {"road_front": True, "parking_front": True, "building_across": False,
                             "trees": True, "open_sky": True, "height_above_street": True}
    assert out["W"] == round(5 / 6, 2) and out["floor_range"] == [2, 4] and out["cropped"]
    assert any("building across: window no, oblique yes" in r for r in out["reasons"])
    assert calls == ["window_box", "window_view", "oblique_view"]
    gv.window_check(img(tmp_path, "win.jpg"), 29.76, -95.36, 212, stub=lambda: {},
                    oblique_view=oblique(img(tmp_path, "obl.jpg")))
    assert len(calls) == 3                                                # all cached


def test_window_check_unclear_items_do_not_count(gem, tmp_path):
    _, answers = gem
    answers.update(window_box={"window_visible": True, "box": None},
                   window_view={**VIEW_OK, "trees": "unclear", "open_sky": "unclear",
                                "parking_front": "unclear", "height_above_street": "unclear"},
                   oblique_view=OBL_OK)
    out = gv.window_check(img(tmp_path, "w.jpg"), 0, 0, 0, stub=lambda: {},
                          oblique_view=oblique(img(tmp_path, "o.jpg")))
    assert out["W"] is None and "only 2 items" in out["skipped"]          # too little to judge


@pytest.mark.parametrize("case", ["no_oblique", "no_window", "no_key"])
def test_window_check_never_invents_a_score(gem, tmp_path, monkeypatch, case):
    _, answers = gem
    answers.update(window_box={"window_visible": case != "no_window", "box": None},
                   window_view=VIEW_OK, oblique_view=OBL_OK)
    if case == "no_key":
        monkeypatch.delenv("GOOGLE_API_KEY")
    obl = str(tmp_path / "missing.jpg") if case == "no_oblique" else img(tmp_path, "o.jpg")
    out = gv.window_check(img(tmp_path, "w.jpg"), 0, 0, 0, stub=lambda: {"W": 0.99},
                          oblique_view=oblique(obl))
    assert out["W"] is None and out["skipped"]


def test_window_check_without_photo_files_uses_the_stub(gem):
    calls, _ = gem
    out = vision.window_check("data/photos/img_311.jpg", 29.7612, -95.3671, 212)
    assert out["W"] == 0.67 and calls == []                               # Ring A fixture


# ---------------------------------------------------------------- pipeline behaviour
def test_unrunnable_window_check_caps_medium_with_a_logged_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "window_check", lambda *a: {
        "W": None, "checks": {}, "floor_range": None, "skipped": "no oblique image at x.jpg"})
    case = Case.open("t", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case)
    m = case.load("matches.json").zones[0].matches[0]
    assert m.W is None and not m.window_checked and "no oblique" in m.window_skipped
    assert tuple(m.floor_range) == (3, 5)                                 # from the geo fix
    d = {x.decision: x for x in case.decisions()}["window_check_not_run_cap_medium"]
    assert d.evidence["property_id"] == "CS-88412"
    lead = case.load("brief.json").leads[0]
    assert lead.tier == "Medium" and "could not run" in lead.caps[0]


def test_costar_types_are_mapped_to_domes_three(tmp_path, monkeypatch):
    from dome.data_tools import costar
    real = costar.properties_in_polygon
    monkeypatch.setattr(lister.costar, "properties_in_polygon", lambda poly, types: [
        {**b, "type": {"multifamily": "residential_condo", "hospitality": "hotel"}.get(b["type"], b["type"])}
        for b in real(poly, types)])
    case = Case.open("t", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case)
    c = {x.property_id: x for x in case.load("candidates.json").zones[0].candidates}
    assert c["CS-88412"].type == "multifamily" and c["CS-87990"].type == "hospitality"
    assert c["CS-88412"].fit == 0.8                                       # unchanged by the mapping
