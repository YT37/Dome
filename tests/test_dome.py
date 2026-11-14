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
            action = Supervisor(case, llm_text=True).next_action()
            if action and action["tool"] == "write_brief_text":
                brief = case.load("brief.json")
                action["args"] = {
                    "summary": f"Ring confidence {brief.leads[0].factors.R if brief.leads else 'n/a'}; "
                               f"{len(brief.leads)} lead(s) for human verification.",
                    "leads": [{"property_id": l.property_id,
                               "reasons": [f"P {l.factors.P}: room photos match the unit scan"],
                               "verify_next": ["compare the match images side by side"]}
                              for l in brief.leads]}
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

    brief = case.load("brief.json")
    assert brief.text_source == "llm" and brief.summary
    assert brief.leads[0].reasons == ["P 0.62: room photos match the unit scan"]
    assert (brief.leads[0].tier, brief.leads[0].score) == ("Medium", 40)   # numbers untouched

    names = set(offered)
    assert {"case_status", "run_linker", "run_zoner", "run_lister", "run_locator",
            "run_briefer", "write_brief_text", "log_decision"} <= names
    assert {"ls", "read_file", "glob", "grep"} <= names       # read-only file tools
    assert not names & EXCLUDED_BUILTINS, names               # no shell, no writes, no subagent
    assert not any(k in n for n in names for k in ("http", "email", "send", "post", "shell"))


def test_brief_text_guard(tmp_path):
    """The LLM writes the words; it cannot invent a number, drop a lead or add a phone."""
    case = scripted(tmp_path, "ring_a")
    sup = Supervisor(case, actor="llm", llm_text=True)
    assert sup.next_action()["tool"] == "write_brief_text"
    before = case.load("brief.json").leads[0]

    def lead(reasons, verify=("check the listing",), pid="CS-88412"):
        return [{"property_id": pid, "reasons": list(reasons), "verify_next": list(verify)}]

    r = sup.write_brief_text("Strong ring.", lead(["P 0.93: nearly every photo matches"]))
    assert r["refused"] and "0.93" in r["reason"]                      # invented number
    assert sup.write_brief_text("Strong ring.", [])["refused"]         # lead left out
    assert sup.write_brief_text("x", lead(["P 0.78"], pid="CS-00000"))["refused"]
    assert sup.write_brief_text("Call 555-0142.", lead(["P 0.78"]))["refused"]   # phone
    assert sup.write_brief_text("Ring R 0.99.", lead(["P 0.78"]))["refused"]

    ok = sup.write_brief_text("Strong ring (R 0.91); one High lead in zone Z-A1.",
                              lead(["P 0.78: room photos match the unit scan",
                                    "W 0.67: road and parking agree with the window view"]))
    assert ok["ok"] and sup.next_action() is None
    after = case.load("brief.json").leads[0]
    assert (after.tier, after.score, after.factors, after.caps) == (
        before.tier, before.score, before.factors, before.caps)
    assert after.reasons[0].startswith("P 0.78") and case.load("brief.json").text_source == "llm"
    assert "Strong ring" in case.path("summary.html").read_text(encoding="utf-8")
    # scripted mode never asks for LLM text
    assert Supervisor(scripted(tmp_path, "ring_a", "s2")).next_action() is None


def _registered_tools(graph) -> set:
    names = set()
    for node in graph.nodes.values():
        names |= set(getattr(getattr(node, "bound", None), "tools_by_name", None) or {})
    return names


@pytest.mark.parametrize("R,P,W,tier,capped", [
    (0.91, 0.78, 0.67, "High", False),
    (0.91, 0.78, None, "Medium", True),     # no window check
    (0.91, 0.78, 0.45, "Medium", True),     # window check ran but is weak (team rule)
    (0.50, 0.78, 0.67, "Medium", True),     # ring confidence between 0.4 and 0.6 (team rule)
    (0.91, 0.50, 0.70, "Medium", False),    # middling room match, strong window
    (0.91, 0.50, 0.40, "Low", False),
    (0.91, 0.30, 0.90, "Low", False),       # no photo match never beats Low
])
def test_tier_rules(R, P, W, tier, capped):
    from dome.agents.briefer import caps_for, tier_for
    assert tier_for(R, P, W) == tier
    assert bool(caps_for(R, P, W)) == capped


def test_summary_shows_display_name_never_address(tmp_path):
    case = scripted(tmp_path, "ring_a")
    lead = case.load("brief.json").leads[0]
    page = case.path("summary.html").read_text(encoding="utf-8")
    assert lead.display_name in page and lead.address not in page
    assert "4 accounts, R 0.91" in page                       # ring card from the case
    sup = Supervisor(case, actor="llm", llm_text=True)
    r = sup.write_brief_text(f"Top lead is {lead.address}.", [
        {"property_id": lead.property_id, "reasons": ["P 0.78"], "verify_next": ["check it"]}])
    assert r["refused"] and "address" in r["reason"]


def test_graph_is_a_langgraph_graph(tmp_path):
    case = Case.open("graph", scenario="ring_a", root=tmp_path, reset=True)
    model, _ = _planner_model(case)
    graph = build_agent(case, model)
    assert hasattr(graph, "invoke") and hasattr(graph, "stream") and graph.get_graph().nodes


@pytest.mark.parametrize("model", ["google_genai:gemini-3.5-flash", "anthropic:claude-sonnet-5-5"])
def test_forbidden_tools_not_even_registered(tmp_path, monkeypatch, model):
    """Not hidden, absent: the executor has no shell, write, edit or delete tool to dispatch to."""
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    case = Case.open("locked", scenario="ring_a", root=tmp_path, reset=True)
    names = _registered_tools(build_agent(case, model))
    assert "run_linker" in names and "write_brief_text" in names
    assert not names & EXCLUDED_BUILTINS, names
    assert names - {"case_status", "run_linker", "run_zoner", "run_lister", "run_locator",
                    "run_briefer", "write_brief_text", "log_decision"} == {"ls", "read_file",
                                                                         "glob", "grep"}
