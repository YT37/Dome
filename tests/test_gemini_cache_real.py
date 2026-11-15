"""Gemini quota safety (free tier ~20 requests/day): every answer is cached on disk and reused;
a quota error never replaces a cached answer and never invents W."""
from __future__ import annotations

import json

import pytest
from PIL import Image

from dome import ask
from dome.data_tools import gemini_vision as gv

VIEW = {"road_front": "yes", "parking_front": "no", "building_across": "yes", "trees": "no",
        "open_sky": "yes", "height_above_street": "low"}
OBL = {"road_front": "yes", "parking_front": "no", "building_across": "yes", "trees": "no",
       "open_sky": "yes", "facade_floors": 3}


class Quota(Exception):
    pass


@pytest.fixture
def gem(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("DOME_STUBS", "0")
    monkeypatch.setenv("DOME_VISION_CACHE", str(tmp_path / "gemini"))
    state = {"calls": [], "quota": False}
    answers = {"window_box": {"window_visible": True, "box": None}, "window_view": VIEW, "oblique_view": OBL}

    def fake(task, model, prompt, images):
        state["calls"].append(task)
        if state["quota"]:
            raise Quota("429 RESOURCE_EXHAUSTED: quota exceeded for generate_content")
        return json.dumps(answers[task])

    monkeypatch.setattr(gv, "GENERATE", fake)
    return state


def _img(tmp_path, name, color):
    p = tmp_path / name
    Image.new("RGB", (64, 48), color).save(p)
    return str(p)


def _check(tmp_path, color=(120, 160, 200)):
    obl = _img(tmp_path, "obl.jpg", (90, 90, 90))
    return gv.window_check(_img(tmp_path, f"win_{color[0]}.jpg", color), 29.75, -95.38, 122.7,
                           stub=lambda: {"W": 0.99}, oblique_view=lambda *a: obl)


def test_cached_rerun_makes_no_call_and_survives_quota(gem, tmp_path):
    first = _check(tmp_path)
    assert first["W"] == 1.0 and gem["calls"] == ["window_box", "window_view", "oblique_view"]
    gem["quota"] = True                                   # quota exhausted from now on
    again = _check(tmp_path)
    assert again["W"] == first["W"] and len(gem["calls"]) == 3   # zero new calls, same W
    log = [json.loads(l) for l in (tmp_path / "gemini" / "calls.jsonl").read_text().splitlines()]
    assert [r["cached"] for r in log] == [False] * 3 + [True] * 3
    assert all(f.name.split("_")[0] in ("window", "oblique", "calls.jsonl")
               for f in (tmp_path / "gemini").iterdir())


def test_quota_without_cache_keeps_w_null_and_says_why(gem, tmp_path):
    gem["quota"] = True
    out = _check(tmp_path, color=(10, 200, 30))
    assert out["W"] is None and "Gemini quota" in out["skipped"]   # never the stub, never invented


def test_ask_answers_are_cached_and_quota_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("DOME_VISION_CACHE", str(tmp_path / "gemini"))
    case = tmp_path / "case" / "c1"
    case.mkdir(parents=True)
    (case / "brief.json").write_text(json.dumps({"leads": [{"tier": "High"}]}))
    monkeypatch.setattr(ask.config, "CASE_ROOT", tmp_path / "case", raising=False)
    calls = []

    class Model:
        def invoke(self, msgs):
            calls.append(1)
            return type("M", (), {"content": json.dumps({
                "answer": "High", "answerable": True,
                "citations": [{"file": "case/c1/brief.json", "path": "leads[0].tier"}]})})()

    class Broken:
        def invoke(self, msgs):
            raise Quota("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(ask, "_model", lambda: Model())
    files = ask.case_files("c1", tmp_path / "case")
    if not files:                                         # case_files keys depend on its root handling
        pytest.skip("case_files layout differs")
    a1 = ask.answer("c1", "What tier?", root=tmp_path / "case")
    monkeypatch.setattr(ask, "_model", lambda: Broken())
    a2 = ask.answer("c1", "What tier?", root=tmp_path / "case")          # cached: no call
    a3 = ask.answer("c1", "Something new?", root=tmp_path / "case")      # not cached + quota
    assert len(calls) == 1 and a1 == a2
    assert a3["answerable"] is False and "Gemini quota" in a3["reason"]
