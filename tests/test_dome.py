"""Samples validate, every supervisor decision fires, and the deepagents wiring is locked down."""
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from dome import config
from dome.agents import lister
from dome.case import Case
from dome.schemas import FILE_MODELS, LogEntry
from dome.supervisor import EXCLUDED_BUILTINS, Supervisor, build_agent, run_llm, run_scripted


def scripted(tmp_path, scenario, case_id="t"):
    case = Case.open(case_id, scenario=scenario, root=tmp_path, reset=True)
    run_scripted(case)
    return case


def decisions(case):
    return {d.decision: d for d in case.decisions()}


# ---------------------------------------------------------------- Task 1: the contract
def test_every_sample_validates():
    names = [n for n in FILE_MODELS if n != "input.json"]
    for name in names:
        FILE_MODELS[name].model_validate_json((config.SAMPLES / name).read_text(encoding="utf-8"))
    lines = (config.SAMPLES / "log.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines and all(LogEntry.model_validate_json(l) for l in lines)


# ---------------------------------------------------------------- Task 2: the five decisions
def test_ring_a_high_lead(tmp_path):
    case = scripted(tmp_path, "ring_a")
    brief = case.load("brief.json")
    lead = brief.leads[0]
    assert brief.status == "complete" and lead.property_id == "CS-88412"
    assert (lead.tier, lead.score) == ("High", 68)      # the handoff's worked example
    assert lead.factors.P >= 0.6 and lead.factors.W >= 0.6
    assert case.path("summary.html").exists()
    assert not case.load("candidates.json").zones[0].scanned_only


def test_weak_ring_stops_after_zoner(tmp_path):
    case = scripted(tmp_path, "weak_ring")
    d = decisions(case)["stop_after_zoner_weak_ring"]
    assert d.actor == "guard" and d.evidence["R"] == 0.35 and d.evidence["min_R"] == 0.4
    assert case.load("brief.json").status == "weak_ring_zone_only"
    assert case.load("brief.json").leads == []
    assert case.check("candidates.json") == "missing" and case.check("matches.json") == "missing"


def test_wide_zone_keeps_scanned_only(tmp_path):
    case = scripted(tmp_path, "ring_c")
    d = decisions(case)["scanned_buildings_only_wide_zone"]
    assert d.evidence["wide"] is True
    block = case.load("candidates.json").zones[0]
    assert block.scanned_only and block.total_in_zone == 7
    assert len(block.candidates) == 3 and all(c.has_scan for c in block.candidates)


def test_two_zones_run_per_zone(tmp_path):
    case = scripted(tmp_path, "ring_b")
    assert decisions(case)["run_lister_and_locator_per_zone"].evidence["zones"] == ["Z-B1", "Z-B2"]
    assert [z.zone_id for z in case.load("candidates.json").zones] == ["Z-B1", "Z-B2"]
    assert [z.zone_id for z in case.load("matches.json").zones] == ["Z-B1", "Z-B2"]
    assert {l.zone_id for l in case.load("brief.json").leads} == {"Z-B1", "Z-B2"}


def test_no_match_expands_photos_and_retries_once(tmp_path):
    case = scripted(tmp_path, "ring_c")
    d = decisions(case)["expand_weak_photos_and_retry"]
    assert d.evidence == {"zone_id": "Z-C1", "best_P": 0.31, "threshold": 0.4, "attempt": 1}
    ring = case.selected_ring()
    assert ring.photo_expansion_used and any(p.link_strength == "weak" for p in ring.photos)
    mz = case.load("matches.json").zones[0]
    assert mz.attempt == 2 and mz.above_threshold and mz.best_P == 0.62
    calls = [e.step for e in case.read_log() if e.event == "tool_call"]
    assert calls.count("locator:Z-C1") == 2 and calls.count("linker:expand") == 1
    # a third search is refused
    assert Supervisor(case).run_locator("Z-C1")["refused"]


def test_no_window_skips_check_and_caps_medium(tmp_path):
    case = scripted(tmp_path, "ring_c")
    assert decisions(case)["skip_window_check_cap_medium"].evidence["window_photos"] == 0
    m = case.load("matches.json").zones[0].matches[0]
    assert m.W is None and not m.window_checked
    lead = case.load("brief.json").leads[0]
    assert lead.tier == "Medium" and lead.factors.W is None and lead.caps


# ---------------------------------------------------------------- guards, retry, determinism
def test_guards_refuse_out_of_order_calls(tmp_path):
    case = Case.open("g", scenario="ring_a", root=tmp_path, reset=True)
    sup = Supervisor(case)
    assert sup.run_briefer()["refused"]                      # nothing to brief yet
    assert sup.run_linker(expand_weak_photos=True)["refused"]  # no failed Locator run yet
    sup.run_linker()
    sup.run_zoner()
    assert sup.run_briefer()["refused"]                      # zones not processed
    assert sup.run_locator("Z-A1")["refused"]                # Lister first
    assert any(e.event == "refused" for e in case.read_log())

    weak = Case.open("w", scenario="weak_ring", root=tmp_path, reset=True)
    ws = Supervisor(weak)
    ws.run_linker(), ws.run_zoner()
    assert ws.run_lister("Z-W1")["refused"]                  # weak ring stops after the Zoner


def test_invalid_output_retries_once_then_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(lister, "run", lambda *a, **k: {"case_id": "t", "zones": "garbage"})
    case = scripted(tmp_path, "ring_a")
    log = case.read_log()
    bad = [e for e in log if e.event == "validation_failed" and e.step == "lister:Z-A1"]
    assert [e.evidence["attempt"] for e in bad] == [1, 2]
    assert case.failed_steps() == ["lister:Z-A1"]
    assert case.check("candidates.json") == "missing"        # invalid output is never written
    brief = case.load("brief.json")
    assert brief.status == "partial" and brief.failed_steps == ["lister:Z-A1"]


def test_same_case_in_same_scores_out(tmp_path):
    a, b = scripted(tmp_path, "ring_c", "one"), scripted(tmp_path, "ring_c", "two")
    for name in ("candidates.json", "matches.json", "brief.json"):
        da, db = (json.loads(c.path(name).read_text(encoding="utf-8")) for c in (a, b))
        da.pop("case_id"), db.pop("case_id")
        assert da == db


# ---------------------------------------------------------------- the deepagents supervisor
def _planner_model(case):
    """A fake chat model that calls whatever tool the data requires next. It drives the real
    deepagents graph offline, so the tool wiring and lock-down are tested without an API key."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    offered: list[str] = []

    class PlannerFake(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "planner-fake"

        def bind_tools(self, tools: Any, **kwargs: Any):
            offered[:] = [getattr(t, "name", None) or t.get("name") or t["function"]["name"]
                          for t in tools]
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if tools := kwargs.get("tools"):
                offered[:] = [t.get("name") or t["function"]["name"] for t in tools]
            action = Supervisor(case).next_action()
            if action is None:
                msg = AIMessage(content="Done. Leads are for human verification.")
            else:
                msg = AIMessage(content="", tool_calls=[{
                    "name": action["tool"], "args": action["args"],
                    "id": uuid.uuid4().hex, "type": "tool_call"}])
            return ChatResult(generations=[ChatGeneration(message=msg)])

    return PlannerFake(), offered


def test_deep_agent_runs_and_is_locked_down(tmp_path):
    case = Case.open("llm", scenario="ring_c", root=tmp_path, reset=True)
    model, offered = _planner_model(case)
    run_llm(case, model)

    assert case.load("brief.json").leads[0].tier == "Medium"
    assert "expand_weak_photos_and_retry" in decisions(case)
    assert any(e.actor == "llm" and e.event == "tool_call" for e in case.read_log())

    names = set(offered)
    assert {"case_status", "run_linker", "run_zoner", "run_lister", "run_locator",
            "run_briefer", "log_decision"} <= names
    assert {"ls", "read_file", "glob", "grep"} <= names       # read-only file tools
    assert not names & EXCLUDED_BUILTINS, names               # no shell, no writes, no subagent
    assert not any(k in n for n in names for k in ("http", "email", "send", "post", "shell"))


def test_graph_is_a_langgraph_graph(tmp_path):
    case = Case.open("graph", scenario="ring_a", root=tmp_path, reset=True)
    model, _ = _planner_model(case)
    graph = build_agent(case, model)
    assert hasattr(graph, "invoke") and hasattr(graph, "stream") and graph.get_graph().nodes
