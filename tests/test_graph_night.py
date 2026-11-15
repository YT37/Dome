"""Night (a-graph): integration hooks, contract samples, events, the report interrupt."""
import json
import sys
import types

import pytest

from dome.case import Case
from dome.schemas import load_optional
from dome.schemas import ComplexFile, GraphFile, MoneyBlock, RingsFile, SpotterFile, StreamEvent, WalletNotesFile
from dome.supervisor import APPROVE, REJECT, run_scripted
from dome import config

NIGHT = config.SAMPLES / "night"


def test_night_samples_validate():
    MoneyBlock.model_validate_json((NIGHT / "money.json").read_text())
    SpotterFile.model_validate_json((NIGHT / "spotter.json").read_text())
    GraphFile.model_validate_json((NIGHT / "graph.json").read_text())
    ComplexFile.model_validate_json((NIGHT / "complex.json").read_text())
    WalletNotesFile.model_validate_json((NIGHT / "wallet_notes.json").read_text())
    for line in (NIGHT / "events.jsonl").read_text().splitlines():
        StreamEvent.model_validate_json(line)
    assert json.loads((NIGHT / "ask.json").read_text())["answerable"] is True


def test_old_rings_still_validate_and_money_is_optional():
    rf = RingsFile.model_validate_json((config.SAMPLES / "rings.json").read_text())
    assert all(r.money is None for r in rf.rings)
    d = rf.model_dump(by_alias=True)
    d["rings"][0]["money"] = json.loads((NIGHT / "money.json").read_text())
    assert RingsFile.model_validate(d).rings[0].money.flows[0].from_ == "W-2"


def _events(case):
    return [json.loads(l) for l in case.path("events.jsonl").read_text().splitlines()]


def test_scripted_run_auto_approves_and_writes_events(tmp_path):
    case = Case.open("ev", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case)
    assert case.load("brief.json") is not None
    d = [x for x in case.decisions() if x.decision == APPROVE]
    assert len(d) == 1 and d[0].evidence["by"].startswith("auto")
    evs = _events(case)
    for e in evs:
        StreamEvent.model_validate(e)
    agents = [e["agent"] for e in evs]
    assert agents[0] == "supervisor" and "locator" in agents and "briefer" in agents
    assert any(e["phase"] == "decision" and "approved" in e["message"] for e in evs)


def test_rejected_report_stops_without_brief(tmp_path):
    case = Case.open("rej", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case, approver=lambda preview: "reject")
    assert case.load("brief.json") is None
    assert any(x.decision == REJECT for x in case.decisions())


def test_money_and_spotter_hooks_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DOME_MONEY", raising=False)
    monkeypatch.delenv("DOME_SPOTTER", raising=False)
    case = Case.open("off", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case)
    assert not case.path("spotter.json").exists()
    assert all(r.money is None for r in case.load("rings.json").rings)


def test_missing_modules_are_logged_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv("DOME_MONEY", "1")
    monkeypatch.setenv("DOME_SPOTTER", "1")
    monkeypatch.setitem(sys.modules, "dome.agents.money", None)    # import fails
    monkeypatch.setitem(sys.modules, "dome.agents.spotter", None)
    import dome.agents as pkg   # once the real modules are merged they may already be imported
    monkeypatch.delattr(pkg, "money", raising=False)
    monkeypatch.delattr(pkg, "spotter", raising=False)
    case = Case.open("miss", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case)
    names = {d.decision for d in case.decisions()}
    assert {"money_module_not_available", "spotter_module_not_available"} <= names
    assert case.load("brief.json") is not None


def test_money_hook_and_linker_second_pass_with_fake_modules(tmp_path, monkeypatch):
    """Ishaan's modules are faked here with the sample files; the hooks are what is tested."""
    money_sample = json.loads((NIGHT / "money.json").read_text())

    def attach(case):
        d = json.loads(case.path("rings.json").read_text())
        for r in d["rings"]:
            r["money"] = money_sample
        case.path("rings.json").write_text(json.dumps(d))
        members = case.selected_ring().members
        notes = [{"account": members[0], "cluster_id": "W-1", "kind": "money", "reason": "test"},
                 {"account": members[1], "cluster_id": "W-1", "kind": "money", "reason": "test"}]
        case.path("wallet_notes.json").write_text(json.dumps({"notes": notes}))

    def spot(case):
        case.path("spotter.json").write_text((NIGHT / "spotter.json").read_text())

    monkeypatch.setitem(sys.modules, "dome.agents.money", types.SimpleNamespace(attach=attach))
    monkeypatch.setitem(sys.modules, "dome.agents.spotter", types.SimpleNamespace(run=spot))
    import dome.agents as pkg
    monkeypatch.setattr(pkg, "money", sys.modules["dome.agents.money"], raising=False)
    monkeypatch.setattr(pkg, "spotter", sys.modules["dome.agents.spotter"], raising=False)
    for f in ("DOME_MONEY", "DOME_SPOTTER", "DOME_LINK_MONEY"):
        monkeypatch.setenv(f, "1")
    case = Case.open("money", scenario="ring_a", root=tmp_path, reset=True)
    run_scripted(case)
    ring = case.selected_ring()
    assert ring.money is not None and ring.money.wallet_clusters[0].cluster_id == "W-1"
    assert any("money:wallet_W-1" in l.keys for l in ring.links)
    assert "linker_second_pass_with_wallet_notes" in {d.decision for d in case.decisions()}
    assert load_optional(case.dir, "spotter.json").queue[0].account == "acct_103"
    assert case.load("brief.json") is not None


def test_rules_graph_interrupts_before_report_and_resumes(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    monkeypatch.setenv("DOME_GRAPH_URL", "inproc")
    from dome import graph_stream as gs
    ci = {"case_id": "g1", "scenario": "ring_a", "root": str(tmp_path)}
    evs = list(gs.stream_run(ci))
    assert evs[-1]["phase"] == "interrupt" and "Approve" in evs[-1]["message"]
    case = Case("g1", tmp_path)
    assert case.load("brief.json") is None          # held until the analyst answers
    tid = evs[-1]["thread_id"]
    rest = list(gs.resume(tid, "approve"))
    assert any(e["agent"] == "briefer" and e["phase"] == "result" for e in rest)
    assert case.load("brief.json") is not None
    assert sum(d.decision == APPROVE for d in case.decisions()) == 1
