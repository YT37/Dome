"""LangGraph streaming for the UI: run a case on the LangGraph server and yield contract E events.

    langgraph dev                       # serves the graphs in langgraph.json on :2024
    DOME_GRAPH=1 python -m dome.ui.app  # the UI calls stream_run / resume below

Two graphs (langgraph.json):
  dome        the deepagents supervisor (an LLM plans; needs DOME_MODEL's API key)
  dome_rules  the same Supervisor tools walked by the rule-based planner as a LangGraph
              StateGraph (no LLM; runs anywhere)

Both stop ONCE before the report: `interrupt()` with the best match per zone, and the analyst
answers with "Approve for report" in the UI (`resume(thread_id, "approve")`). Scripted CLI runs
(python -m dome.supervisor --scripted) auto-approve and log it.

Events (contract E): {"t", "agent", "phase", "message", "refs"}. They come from the
Supervisor's own steps (dome.supervisor.emit -> get_stream_writer()), so every message is built
from the case files the step just wrote. An interrupt arrives as phase "interrupt" with the
question and `thread_id`.

No server? DOME_GRAPH_URL=inproc (or a failed connection) runs the same `dome_rules` graph in
this process with an in-memory checkpointer, so the interrupt and resume still work.

GUARDRAIL: like the supervisor, nothing here contacts, dispatches or publishes anything.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Iterator, Optional, TypedDict

from . import supervisor as sv
from .case import Case

DEFAULT_URL = "http://127.0.0.1:2024"
MAX_STEPS = sv.MAX_STEPS


# ---------------------------------------------------------------------- the rules graph
class CaseState(TypedDict, total=False):
    case: dict          # {case_id, dataset, seed_account, scenario, ring_id, reset, auto_approve}
    steps: int
    done: bool
    last: dict


def _case_args(case_input: dict) -> dict:
    ci = dict(case_input or {})
    ci.setdefault("case_id", "demo-a")
    if not ci.get("dataset") and not ci.get("scenario"):
        ci["scenario"] = "ring_a"
    return ci


def _root(ci: dict):
    from pathlib import Path
    return Path(ci["root"]) if ci.get("root") else None   # tests use a temp case root


def _open_node(state: CaseState) -> dict:
    ci = _case_args(state.get("case") or {})
    case = Case.open(ci["case_id"], root=_root(ci), scenario=ci.get("scenario") or "ring_a",
                     ring_id=ci.get("ring_id"), reset=ci.get("reset", True),
                     dataset=ci.get("dataset"), seed_account=ci.get("seed_account"))
    if ci.get("reset", True):
        sv.reset_night_files(case)
    case.log(actor="scripted", event="run_start", message="LangGraph rules-graph run")
    seed = case.input.seed_account
    sv.emit(case, "supervisor", "start", "Case started" + (f" from flagged account {seed}" if seed else ""),
            [seed] if seed else [])
    return {"case": ci, "steps": 0, "done": False}


def _approver(ci: dict):
    if ci.get("auto_approve"):
        return sv.auto_approve
    from langgraph.types import interrupt
    return interrupt


def _step_node(state: CaseState) -> dict:
    """One planner step per graph step, so a resume after the interrupt repeats only the
    Briefer call (the earlier steps are already checkpointed)."""
    ci = state["case"]
    case = Case(ci["case_id"], _root(ci))
    sup = sv.Supervisor(case, actor="scripted", approver=_approver(ci))
    action = sup.next_action()
    if action is None or state.get("steps", 0) >= MAX_STEPS:
        return {"done": True}
    res = sup.dispatch(action)
    return {"steps": state.get("steps", 0) + 1, "last": {"tool": action["tool"], "ok": res.get("ok")},
            "done": sup.next_action() is None}


def _end_node(state: CaseState) -> dict:
    case = Case(state["case"]["case_id"], _root(state["case"]))
    sup = sv.Supervisor(case)
    case.log(actor="scripted", event="run_end", evidence={"done": sup.next_action() is None})
    b = case.load("brief.json")
    sv.emit(case, "supervisor", "end", f"Run finished: {b.status}" if b else "Run stopped without a report")
    return {"done": True}


def build_rules_graph(checkpointer: Any = None):
    from langgraph.graph import END, START, StateGraph
    g = StateGraph(CaseState)
    g.add_node("open_case", _open_node)
    g.add_node("step", _step_node)
    g.add_node("finish", _end_node)
    g.add_edge(START, "open_case")
    g.add_edge("open_case", "step")
    g.add_conditional_edges("step", lambda s: "finish" if s.get("done") else "step",
                            {"finish": "finish", "step": "step"})
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer, name="dome-rules")


def make_rules_graph(config: Any = None):
    """Factory for langgraph.json (the server supplies its own checkpointer)."""
    return build_rules_graph()


# ---------------------------------------------------------------------- streaming API
def _url() -> str:
    return os.getenv("DOME_GRAPH_URL", DEFAULT_URL)


def _assistant() -> str:
    return os.getenv("DOME_GRAPH_ASSISTANT", "dome_rules")


def _interrupt_event(value: Any, thread_id: str, t: float = 0.0) -> dict:
    v = value if isinstance(value, dict) else {"question": str(value)}
    return {"t": t, "agent": "supervisor", "phase": "interrupt",
            "message": v.get("question") or "Approve for report?", "refs": v.get("refs", []),
            "thread_id": thread_id, "preview": v}


def _from_chunk(event: str, data: Any, thread_id: str, last_t: float) -> list[dict]:
    """langgraph_sdk stream parts -> contract E events."""
    out = []
    if event.startswith("custom") and isinstance(data, dict) and "event" in data:
        out.append({**data["event"], "thread_id": thread_id})
    elif event.startswith("updates") and isinstance(data, dict) and "__interrupt__" in data:
        for it in data["__interrupt__"] or []:
            out.append(_interrupt_event(it.get("value") if isinstance(it, dict) else it,
                                        thread_id, last_t))
    elif event == "error":
        out.append({"t": last_t, "agent": "supervisor", "phase": "failed",
                    "message": f"graph error: {str(data)[:200]}", "refs": [], "thread_id": thread_id})
    return out


def _server_stream(thread_id: Optional[str], case_input: dict, command: Optional[dict]) -> Iterator[dict]:
    from langgraph_sdk import get_sync_client
    client = get_sync_client(url=_url())
    if thread_id is None:
        thread_id = client.threads.create()["thread_id"]
    assistant = _assistant()
    ci = _case_args(case_input)
    kwargs: dict = {"stream_mode": ["updates", "custom"]}
    if command is not None:
        kwargs["command"] = command
    elif assistant == "dome":   # the deepagents supervisor reads the case from its config
        kwargs["input"] = {"messages": [{"role": "user", "content":
                                         f"Investigate case '{ci['case_id']}'. Run the pipeline to the brief."}]}
        kwargs["config"] = {"configurable": ci, "recursion_limit": 150}
    else:
        kwargs["input"] = {"case": ci}
        kwargs["config"] = {"recursion_limit": 4 * MAX_STEPS}
    last_t = 0.0
    for part in client.runs.stream(thread_id, assistant, **kwargs):
        for ev in _from_chunk(part.event, part.data, thread_id, last_t):
            last_t = ev.get("t", last_t)
            yield ev


# in-process fallback: one graph + in-memory checkpointer shared by stream_run and resume
_INPROC: dict = {}


def _inproc_graph():
    if "g" not in _INPROC:
        from langgraph.checkpoint.memory import InMemorySaver
        _INPROC["g"] = build_rules_graph(InMemorySaver())
    return _INPROC["g"]


def _inproc_stream(thread_id: Optional[str], case_input: dict, command: Any) -> Iterator[dict]:
    from langgraph.types import Command
    g = _inproc_graph()
    thread_id = thread_id or f"inproc-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 4 * MAX_STEPS}
    inp = Command(resume=command["resume"]) if command is not None else {"case": _case_args(case_input)}
    last_t = 0.0
    for mode, data in g.stream(inp, cfg, stream_mode=["updates", "custom"]):
        for ev in _from_chunk(mode, data if mode != "updates" else _norm_updates(data), thread_id, last_t):
            last_t = ev.get("t", last_t)
            yield ev


def _norm_updates(data: Any) -> Any:
    if isinstance(data, dict) and "__interrupt__" in data:
        return {"__interrupt__": [{"value": getattr(i, "value", i)} for i in data["__interrupt__"]]}
    return data


def _use_inproc() -> bool:
    if _url() == "inproc":
        return True
    try:
        import urllib.request
        urllib.request.urlopen(_url().rstrip("/") + "/ok", timeout=1.5)
        return False
    except Exception:
        return True


def stream_run(case_input: dict, thread_id: Optional[str] = None) -> Iterator[dict]:
    """Start a case and yield contract E events until the run ends or pauses for approval.

    case_input: {"case_id": "real-a", "dataset": "synth", "seed_account": "acct_103"}
    (the seed is the account the analyst picked in the Spotter queue). Every event carries
    `thread_id`; pass it to resume() when the "interrupt" event arrives.
    """
    if _use_inproc():
        yield from _inproc_stream(thread_id, case_input, None)
    else:
        yield from _server_stream(thread_id, case_input, None)


def resume(thread_id: str, decision: Any = "approve") -> Iterator[dict]:
    """Answer the report interrupt ("approve" / "reject" or {"approved": bool, "note": ...})
    and yield the remaining events."""
    cmd = {"resume": decision}
    if thread_id.startswith("inproc-") or _use_inproc():
        yield from _inproc_stream(thread_id, {}, cmd)
    else:
        yield from _server_stream(thread_id, {}, cmd)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="dome.graph_stream",
                                 description="stream a case through LangGraph and print events")
    ap.add_argument("--case", required=True)
    ap.add_argument("--data", default=None)
    ap.add_argument("--seed", default=None)
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--approve", choices=["approve", "reject"], default="approve",
                    help="answer to the report interrupt (a human clicks this in the UI)")
    a = ap.parse_args(argv)
    ci = {"case_id": a.case, "dataset": a.data, "seed_account": a.seed, "scenario": a.scenario}
    tid = None
    paused = False
    t0 = time.time()
    for ev in stream_run(ci):
        tid = ev.get("thread_id", tid)
        print(json.dumps({k: v for k, v in ev.items() if k not in ("preview",)}))
        paused = paused or ev["phase"] == "interrupt"
    if paused and tid:
        print(f"# interrupt: answering '{a.approve}'")
        for ev in resume(tid, a.approve):
            print(json.dumps({k: v for k, v in ev.items() if k not in ("preview",)}))
    print(f"# {time.time() - t0:.1f}s, thread {tid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
