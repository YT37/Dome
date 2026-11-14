"""Dome supervisor: a LangChain deepagents agent whose tools are the five agents.

    python -m dome.supervisor --case demo-a --scenario ring_a            # LLM supervisor
    python -m dome.supervisor --case demo-c --scenario ring_c --scripted # no LLM (offline/tests)

Design
- The LLM picks the next step and writes reasons. Every number comes from deterministic code.
- The five data-driven decisions are enforced as GUARDS inside the tools, so they hold even
  if the LLM forgets. Each fires a `decision` line in log.jsonl with the evidence behind it.
- GUARDRAIL: the supervisor has no tool that contacts, dispatches or publishes anything.
  No shell, no HTTP, no email, no file writes. The pipeline stops at the brief.
  Do not add such tools here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Callable, Optional

from pydantic import BaseModel

from . import config
from .agents import briefer, linker, lister, locator, zoner
from .case import Case

MAX_STEPS = 40


_DECIMAL = re.compile(r"(?<![\d.])(?:\d+\.\d+|\.\d+)(?!\d)(?!\.\d)")
_PHONE = re.compile(r"(?:\d[\s\-.()]{0,3}){6,10}\d")


class LeadText(BaseModel):
    """The words the supervisor writes for one lead. No numbers of its own."""
    property_id: str
    reasons: list[str]
    verify_next: list[str]


class Supervisor:
    """Deterministic core: status facts, the next required step, guarded run_* steps."""

    def __init__(self, case: Case, actor: str = "supervisor", llm_text: bool = False):
        self.case = case
        self.actor = actor   # who is driving: "llm" or "scripted"
        # True when an LLM drives: after the Briefer's numbers, it writes the brief's words
        self.llm_text = llm_text

    # ------------------------------------------------------------------ facts
    def status(self) -> dict:
        c = self.case
        ring, zones = c.selected_ring(), c.load("zones.json")
        cands, matches = c.load("candidates.json"), c.load("matches.json")
        cz = {z.zone_id: z for z in cands.zones} if cands else {}
        mz = {z.zone_id: z for z in matches.zones} if matches else {}
        zone_facts = []
        for z in (zones.zones if zones else []):
            f: dict[str, Any] = {"zone_id": z.zone_id, "wide": z.wide, "area_km2": z.area_km2,
                                 "confidence": z.confidence, "listed": z.zone_id in cz,
                                 "located": z.zone_id in mz}
            if z.zone_id in cz:
                f["candidates"] = len(cz[z.zone_id].candidates)
                f["scanned_candidates"] = sum(x.has_scan for x in cz[z.zone_id].candidates)
            if z.zone_id in mz:
                m = mz[z.zone_id]
                f.update(attempt=m.attempt, best_P=m.best_P, above_threshold=m.above_threshold)
            zone_facts.append(f)
        nxt = self.next_action()
        return {
            "case_id": c.case_id,
            "files": {n: c.check(n) for n in ("rings.json", "zones.json", "candidates.json",
                                              "matches.json", "brief.json")},
            "ring": None if ring is None else {
                "ring_id": ring.ring_id, "R": ring.confidence, "members": len(ring.members),
                "photos": len(ring.photos),
                "window_photos": sum(p.has_window for p in ring.photos),
                "photo_expansion_used": ring.photo_expansion_used},
            "zones": zone_facts,
            "thresholds": {"ring_min_R": config.RING_MIN_CONFIDENCE,
                           "match_P": config.MATCH_THRESHOLD},
            "failed_steps": c.failed_steps(),
            "done": nxt is None,
            "required_next": nxt,
        }

    def next_action(self) -> Optional[dict]:
        """The one step the data requires next (None when the brief is written).

        This is both the scripted planner and the guard the LLM's calls are checked against.
        """
        c = self.case
        failed = set(c.failed_steps())

        def act(tool: str, why: str, **args) -> dict:
            return {"tool": tool, "args": args, "why": why}

        if c.check("brief.json") == "valid":
            if (self.llm_text and c.load("brief.json").text_source == "template"
                    and "brief_text" not in failed):
                return act("write_brief_text", "the brief has its numbers; write its reasons, "
                           "next checks and summary in plain language")
            return None
        if "briefer" in failed:
            return None
        if c.load("rings.json") is None:
            if "linker" in failed:
                return act("run_briefer", "Linker failed; report it", stop_reason="no_ring")
            return act("run_linker", "no rings.json yet", expand_weak_photos=False)
        ring = c.selected_ring()
        if ring is None:
            return act("run_briefer", "Linker found no ring", stop_reason="no_ring")
        zones = c.load("zones.json")
        if zones is None:
            if "zoner" in failed:
                return act("run_briefer", "Zoner failed; report it")
            return act("run_zoner", "no zones.json yet")
        if ring.confidence < config.RING_MIN_CONFIDENCE:
            return act("run_briefer", f"R {ring.confidence} < {config.RING_MIN_CONFIDENCE}: "
                       "weak ring, stop after the Zoner", stop_reason="weak_ring")
        cands, matches = c.load("candidates.json"), c.load("matches.json")
        listed = {z.zone_id for z in cands.zones} if cands else set()
        located = {z.zone_id: z for z in matches.zones} if matches else {}
        need_expand = False
        for z in zones.zones:   # two or more zones: Lister and Locator once per zone
            if z.zone_id not in listed:
                if f"lister:{z.zone_id}" in failed:
                    continue
                return act("run_lister", f"zone {z.zone_id} has no candidates yet",
                           zone_id=z.zone_id, scanned_only=z.wide)
            m = located.get(z.zone_id)
            if f"locator:{z.zone_id}" in failed:
                continue
            if m is None:
                return act("run_locator", f"zone {z.zone_id} not searched yet", zone_id=z.zone_id)
            if not m.above_threshold and m.attempt == 1:
                if ring.photo_expansion_used:
                    return act("run_locator", f"retry zone {z.zone_id} once with expanded photos",
                               zone_id=z.zone_id)
                need_expand = True
        if need_expand and "linker:expand" not in failed:
            return act("run_linker", "no scan matched above threshold; pull weak-link photos",
                       expand_weak_photos=True)
        return act("run_briefer", "all zones processed")

    # ------------------------------------------------------------------ logging helpers
    def _decide(self, step: str, decision: str, evidence: dict, message: str) -> None:
        for d in self.case.decisions():
            if d.actor == "guard" and d.decision == decision and d.evidence == evidence:
                return   # already recorded for this exact evidence
        self.case.log(actor="guard", event="decision", step=step, decision=decision,
                      evidence=evidence, message=message)

    def _refuse(self, step: str, why: str) -> dict:
        nxt = self.next_action()
        self.case.log(actor="guard", event="refused", step=step, message=why,
                      evidence={"required_next": nxt})
        return {"ok": False, "refused": True, "reason": why, "required_next": nxt}

    def log_decision(self, decision: str, evidence: dict, reason: str) -> dict:
        self.case.log(actor=self.actor, event="decision", decision=decision,
                      evidence=evidence or {}, message=reason)
        return {"ok": True}

    def _run_step(self, key: str, out_file: str, fn: Callable[[], Any],
                  inputs: list[str], args: dict) -> bool:
        """Hash inputs, run, validate against the schema, retry once, else mark failed."""
        c = self.case
        h = c.hash_inputs(["input.json"] + inputs, args)
        c.log(actor=self.actor, event="tool_call", step=key, input_hash=h, evidence=args,
              message=f"run {key}")
        for attempt in (1, 2):
            try:
                c.save(out_file, fn())   # save() validates first; invalid output is never written
                c.log(actor="agent", event="tool_result", step=key, input_hash=h,
                      output_file=out_file, evidence={"attempt": attempt},
                      message=f"{key} wrote a valid {out_file}")
                return True
            except Exception as exc:   # agent error or schema validation error
                c.log(actor="guard", event="validation_failed", step=key, input_hash=h,
                      evidence={"attempt": attempt, "error": f"{type(exc).__name__}: {exc}"[:400]},
                      message=f"{key} attempt {attempt} failed" + ("; retrying once" if attempt == 1 else ""))
        c.log(actor="guard", event="step_failed", step=key, input_hash=h,
              message=f"{key} failed twice; marked failed, the Briefer will report it")
        return False

    def _result(self, ok: bool, step: str, **facts) -> dict:
        return {"ok": ok, "step": step, **({} if ok else {"failed": True}), **facts,
                "required_next": self.next_action()}

    # ------------------------------------------------------------------ steps
    def run_linker(self, expand_weak_photos: bool = False) -> dict:
        c, nxt = self.case, self.next_action()
        if expand_weak_photos:
            # Guard: expansion only when the data shows a no-match Locator result, and only once.
            if not (nxt and nxt["tool"] == "run_linker" and nxt["args"].get("expand_weak_photos")):
                return self._refuse("linker:expand", "photo expansion is only allowed once, after a "
                                    "Locator run found no scan above threshold")
            ok = self._run_step("linker:expand", "rings.json",
                                lambda: linker.run(c, expand_weak_photos=True), ["rings.json"],
                                {"expand_weak_photos": True})
        else:
            if c.load("rings.json") is not None:
                return self._refuse("linker", "rings.json already exists and is valid")
            ok = self._run_step("linker", "rings.json", lambda: linker.run(c),
                                ["flagged_accounts.json"], {"expand_weak_photos": False})
        ring = c.selected_ring()
        if ok and ring is None:
            self._decide("linker", "no_ring_found", {"rings": 0},
                         "No group of accounts shares two kinds of key; weak hints only.")
        return self._result(ok, "linker", ring_id=ring and ring.ring_id, R=ring and ring.confidence,
                            photos=len(ring.photos) if ring else 0,
                            photo_expansion_used=bool(ring and ring.photo_expansion_used))

    def run_zoner(self) -> dict:
        c = self.case
        ring = c.selected_ring()
        if ring is None:
            return self._refuse("zoner", "no ring yet; run the Linker first")
        if c.load("zones.json") is not None:
            return self._refuse("zoner", "zones.json already exists and is valid")
        ok = self._run_step("zoner", "zones.json", lambda: zoner.run(c), ["rings.json"], {})
        zones = c.load("zones.json")
        zs = zones.zones if zones else []
        if ok and ring.confidence < config.RING_MIN_CONFIDENCE:
            self._decide("zoner", "stop_after_zoner_weak_ring",
                         {"ring_id": ring.ring_id, "R": ring.confidence,
                          "min_R": config.RING_MIN_CONFIDENCE},
                         "Ring confidence is below the minimum; stopping after the Zoner. "
                         "The brief reports the zone only, no buildings.")
        elif ok and len(zs) >= 2:
            self._decide("zoner", "run_lister_and_locator_per_zone",
                         {"zones": [z.zone_id for z in zs]},
                         f"{len(zs)} zones found; running Lister and Locator once per zone.")
        return self._result(ok, "zoner", zones=[{"zone_id": z.zone_id, "wide": z.wide,
                                                 "area_km2": z.area_km2} for z in zs])

    def run_lister(self, zone_id: str, scanned_only: bool = False) -> dict:
        c = self.case
        ring, zones = c.selected_ring(), c.load("zones.json")
        zone = next((z for z in zones.zones if z.zone_id == zone_id), None) if zones else None
        if ring is None or zone is None:
            return self._refuse(f"lister:{zone_id}", f"zone {zone_id} not found; run Linker and Zoner first")
        if ring.confidence < config.RING_MIN_CONFIDENCE:
            return self._refuse(f"lister:{zone_id}", "weak ring: the pipeline stops after the Zoner")
        # Guard: the zone's `wide` flag decides scanned_only, not the caller.
        scanned_only = zone.wide
        if zone.wide:
            self._decide(f"lister:{zone_id}", "scanned_buildings_only_wide_zone",
                         {"zone_id": zone_id, "wide": True, "area_km2": zone.area_km2},
                         "Zone is wide; the Lister keeps only buildings with a Matterport scan.")
        ok = self._run_step(f"lister:{zone_id}", "candidates.json",
                            lambda: lister.run(c, zone_id, scanned_only),
                            ["rings.json", "zones.json"],
                            {"zone_id": zone_id, "scanned_only": scanned_only})
        cands = c.load("candidates.json")
        b = next((z for z in cands.zones if z.zone_id == zone_id), None) if cands else None
        return self._result(ok, "lister", zone_id=zone_id, scanned_only=scanned_only,
                            total_in_zone=b.total_in_zone if b else None,
                            candidates=len(b.candidates) if b else None,
                            scanned=sum(x.has_scan for x in b.candidates) if b else None)

    def run_locator(self, zone_id: str) -> dict:
        c = self.case
        ring, cands, matches = c.selected_ring(), c.load("candidates.json"), c.load("matches.json")
        if ring is None or cands is None or not any(z.zone_id == zone_id for z in cands.zones):
            return self._refuse(f"locator:{zone_id}", f"zone {zone_id} has no candidates; run the Lister first")
        prev = next((z for z in matches.zones if z.zone_id == zone_id), None) if matches else None
        if prev is not None:
            # Guard: one retry only, and only after photo expansion changed the inputs.
            if prev.attempt == 2 or prev.above_threshold or not ring.photo_expansion_used:
                return self._refuse(f"locator:{zone_id}", "this zone was already searched; a second "
                                    "search is allowed once, only after photo expansion")
        ok = self._run_step(f"locator:{zone_id}", "matches.json", lambda: locator.run(c, zone_id),
                            ["rings.json", "candidates.json"], {"zone_id": zone_id})
        matches = c.load("matches.json")
        m = next((z for z in matches.zones if z.zone_id == zone_id), None) if matches else None
        if ok and m:
            if m.window_photos == 0:
                self._decide(f"locator:{zone_id}", "skip_window_check_cap_medium",
                             {"zone_id": zone_id, "window_photos": 0},
                             "No window in any photo; window check skipped (W = null), "
                             "leads in this zone are capped at Medium.")
            ev = {"zone_id": zone_id, "best_P": m.best_P, "threshold": m.threshold, "attempt": m.attempt}
            if not m.above_threshold and m.attempt == 1 and not ring.photo_expansion_used:
                self._decide(f"locator:{zone_id}", "expand_weak_photos_and_retry", ev,
                             "No scan matched above threshold; asking Linker for weak-link photos "
                             "and searching once more.")
            elif not m.above_threshold:
                self._decide(f"locator:{zone_id}", "no_match_after_retry", ev,
                             "Still no scan above threshold after the one retry; no lead for this zone.")
        return self._result(ok, "locator", zone_id=zone_id, attempt=m and m.attempt,
                            best_P=m and m.best_P, above_threshold=m and m.above_threshold,
                            window_photos=m and m.window_photos)

    def run_briefer(self, stop_reason: Optional[str] = None) -> dict:
        c, nxt = self.case, self.next_action()
        if c.check("brief.json") == "valid":
            return self._refuse("briefer", "brief.json is already written")
        if nxt["tool"] != "run_briefer":
            return self._refuse("briefer", "not ready for the brief yet: " + nxt["why"])
        stop_reason = nxt["args"].get("stop_reason")   # the data decides, not the caller
        ok = self._run_step("briefer", "brief.json", lambda: briefer.run(c, stop_reason),
                            ["rings.json", "zones.json", "candidates.json", "matches.json"],
                            {"stop_reason": stop_reason})
        b = c.load("brief.json")
        return self._result(ok, "briefer", status=b and b.status,
                            leads=[{"rank": l.rank, "property_id": l.property_id, "tier": l.tier,
                                    "score": l.score} for l in b.leads] if b else [])

    def write_brief_text(self, summary: str, leads: list) -> dict:
        """The LLM's words go into brief.json; every number stays the Briefer's.

        Guards: the brief must exist; every lead gets reasons and next checks; no unknown
        property ids; any decimal in the text must be one of that lead's factors (or a
        threshold); no phone numbers (data minimisation). Tier, score, caps and footer are
        never touched.
        """
        c = self.case
        brief = c.load("brief.json")
        if brief is None:
            return self._refuse("brief_text", "no brief yet; run the Briefer first")
        texts = [LeadText.model_validate(x.model_dump() if isinstance(x, BaseModel) else x)
                 for x in leads]
        by_id = {t.property_id: t for t in texts}
        known = {l.property_id for l in brief.leads}
        problems = []
        if set(by_id) - known:
            problems.append(f"unknown property ids: {sorted(set(by_id) - known)}")
        if known - set(by_id):
            problems.append(f"every lead needs text; missing: {sorted(known - set(by_id))}")
        if not summary.strip():
            problems.append("summary is empty")

        thresholds = {config.MATCH_THRESHOLD, config.TIER_STRONG, config.RING_MIN_CONFIDENCE}
        all_factors = set(thresholds)
        for l in brief.leads:
            all_factors |= {v for v in l.factors.model_dump().values() if v is not None}
        ring = c.selected_ring()
        if ring:
            all_factors.add(ring.confidence)
        zones = c.load("zones.json")
        if zones:
            all_factors |= {z.confidence for z in zones.zones} | {z.area_km2 for z in zones.zones}

        def bad_numbers(text: str, allowed: set) -> list[str]:
            ok = {round(v, 2) for v in allowed}
            return [m for m in _DECIMAL.findall(text) if round(float(m), 2) not in ok]

        for l in brief.leads:
            t = by_id.get(l.property_id)
            if t is None:
                continue
            if not t.reasons or not t.verify_next:
                problems.append(f"{l.property_id}: needs at least one reason and one next check")
            allowed = {v for v in l.factors.model_dump().values() if v is not None} | thresholds
            for line in t.reasons + t.verify_next:
                if bad := bad_numbers(line, allowed):
                    problems.append(f"{l.property_id}: numbers not in this lead's factors: {bad}")
                if _PHONE.search(line):
                    problems.append(f"{l.property_id}: no phone numbers in the brief")
                if l.address and l.address.lower() in line.lower():
                    problems.append(f"{l.property_id}: no street address; use its display_name")
        if bad := bad_numbers(summary, all_factors):
            problems.append(f"summary: numbers not in the brief: {bad}")
        if _PHONE.search(summary):
            problems.append("summary: no phone numbers in the brief")
        if any(l.address and l.address.lower() in summary.lower() for l in brief.leads):
            problems.append("summary: no street address; refer to buildings by display_name")
        if problems:
            return self._refuse("brief_text", "; ".join(problems))

        data = brief.model_dump()
        for l in data["leads"]:
            t = by_id[l["property_id"]]
            l["reasons"] = [r.strip() for r in t.reasons]
            l["verify_next"] = [v.strip() for v in t.verify_next]
        data.update(summary=summary.strip(), text_source="llm", footer=config.FOOTER)
        h = c.hash_inputs(["brief.json"], {"summary": summary})
        c.log(actor=self.actor, event="tool_call", step="brief_text", input_hash=h,
              message="supervisor writes the brief's words")
        obj = c.save("brief.json", data)
        c.path("summary.html").write_text(briefer.render_html(obj.model_dump(), c), encoding="utf-8")
        c.log(actor="agent", event="tool_result", step="brief_text", input_hash=h,
              output_file="brief.json", message="brief reasons and summary written; numbers unchanged")
        return self._result(True, "brief_text", leads=len(texts))

    def dispatch(self, action: dict) -> dict:
        return getattr(self, action["tool"])(**action["args"])


# ---------------------------------------------------------------------- scripted mode
def run_scripted(case: Case) -> Supervisor:
    """Walk the same tools with the rule-based planner. No LLM (offline demo and tests)."""
    sup = Supervisor(case, actor="scripted")
    case.log(actor="scripted", event="run_start", message="scripted supervisor run")
    for _ in range(MAX_STEPS):
        action = sup.next_action()
        if action is None:
            break
        sup.dispatch(action)
    case.log(actor="scripted", event="run_end", evidence={"done": sup.next_action() is None})
    return sup


# ---------------------------------------------------------------------- deepagents supervisor
SYSTEM_PROMPT = """You are the Dome supervisor. Dome turns a set of already-flagged SYNTHETIC \
social accounts into a ranked, explained list of buildings for HUMAN VERIFICATION.

You coordinate five agents through tools: Linker -> Zoner -> Lister -> Locator -> Briefer.
Each writes one JSON file in the case folder (rings, zones, candidates, matches, brief).

How to work
1. Call case_status() first, and again whenever you are unsure. It returns facts and
   `required_next`, the step the data calls for.
2. Before each step that follows from a data-driven rule, call log_decision() with the
   decision, the evidence (numbers from case_status or the last tool result) and a one
   sentence plain-language reason.
3. Run the step. Read its JSON result. Repeat until `done` is true.
4. You are also the Briefer's voice. run_briefer computes every tier, score and cap. Then
   read brief.json and call write_brief_text with the plain-language reasons, next checks
   and a case summary. Cite only numbers that are in brief.json; if the tool refuses your
   text, fix exactly what it names and call it again.
5. Finish with a short chat summary: status, each lead's tier and score, and the decisions.

Rules the data decides (the tools enforce them; a refused call tells you what is required)
- Ring confidence R < 0.4: stop after the Zoner; the brief reports "weak ring, zone only".
- A zone with wide = true: the Lister keeps only buildings that have a scan.
- Two or more zones: run Lister and Locator once per zone.
- Locator finds no scan with P >= 0.4: run_linker(expand_weak_photos=True), then run the
  Locator for that zone once more. Never a third time.
- No window in any photo: the window check is skipped (W = null), lead capped at Medium.

Hard limits
- Never invent or adjust a number. Scores, tiers, P, W and R come only from the tools.
- You may read case files (ls, read_file, glob, grep). You cannot write files.
- You have no way to contact, dispatch or publish anything, and must not try. Every output
  is a lead for a human to verify. It is not proof that anyone is in a building.
"""


def build_tools(sup: Supervisor) -> list:
    from langchain_core.tools import tool

    def js(d: dict) -> str:
        return json.dumps(d, default=str)

    @tool
    def case_status() -> str:
        """Facts about the case: which files exist and validate, ring confidence R, zones and
        their `wide` flag, best P per zone, window photo count, failed steps, and
        `required_next` (the step the data calls for). Call this first."""
        return js(sup.status())

    @tool
    def run_linker(expand_weak_photos: bool = False) -> str:
        """Run the Linker: group flagged accounts into rings (writes rings.json).
        Set expand_weak_photos=True only after a Locator run found no scan above threshold;
        it adds photos from weakly linked accounts and is allowed once."""
        return js(sup.run_linker(expand_weak_photos))

    @tool
    def run_zoner() -> str:
        """Run the Zoner: turn the ring's place clues into zones (writes zones.json).
        Zones are areas, never addresses."""
        return js(sup.run_zoner())

    @tool
    def run_lister(zone_id: str, scanned_only: bool = False) -> str:
        """Run the Lister for one zone: list buildings inside it and rate how well each fits
        the ring's photos (writes candidates.json). For a wide zone only scanned buildings
        are kept."""
        return js(sup.run_lister(zone_id, scanned_only))

    @tool
    def run_locator(zone_id: str) -> str:
        """Run the Locator for one zone: match ring photos to building scans (P) and check the
        window view (W) (writes matches.json)."""
        return js(sup.run_locator(zone_id))

    @tool
    def run_briefer(stop_reason: Optional[str] = None) -> str:
        """Run the Briefer: write brief.json and summary.html with tiered, explained leads.
        This is the last step. stop_reason may be 'weak_ring' or 'no_ring'."""
        return js(sup.run_briefer(stop_reason))

    @tool
    def write_brief_text(summary: str, leads: list[LeadText]) -> str:
        """Last step, after run_briefer: write the brief's words. You are the Briefer's voice.
        `summary`: 2-4 plain sentences for a trust-and-safety reviewer: ring strength, where
        the leads are, how strong each is, what was capped or skipped and why.
        `leads`: one entry per lead in brief.json: property_id, `reasons` (one short line per
        factor, citing its value, e.g. "P 0.78: 2 room photos match the unit scan") and
        `verify_next` (what a human should check to confirm or rule it out).
        Use only numbers already in brief.json; any other number is refused. Refer to
        buildings by display_name, never a street address. Never change a tier or score,
        never name a person, never include a phone number."""
        return js(sup.write_brief_text(summary, leads))

    @tool
    def log_decision(decision: str, evidence: dict, reason: str) -> str:
        """Record why you chose a path: a short decision name, the evidence (facts and numbers
        from the data) and a one-sentence reason. Appends to log.jsonl."""
        return js(sup.log_decision(decision, evidence, reason))

    return [case_status, run_linker, run_zoner, run_lister, run_locator, run_briefer,
            write_brief_text, log_decision]


# Built-in deepagents tools the supervisor must never be offered.
EXCLUDED_BUILTINS = frozenset({"execute", "write_file", "edit_file", "delete", "task"})
READ_ONLY_FILE_TOOLS = ("ls", "read_file", "glob", "grep")


def _lock_down(model: Any) -> None:
    """Register a harness profile: no shell, no file writes, no general-purpose subagent."""
    from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
    from deepagents._models import get_model_provider

    key = model.split(":", 1)[0] if isinstance(model, str) else get_model_provider(model)
    if not key:
        raise RuntimeError("cannot resolve the model provider; refusing to build an unlocked agent")
    profile = HarnessProfile(excluded_tools=EXCLUDED_BUILTINS,
                             general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False))
    register_harness_profile(key, profile)
    if key == "google_genai":   # deepagents may key Gemini models under either name
        register_harness_profile("google", profile)


def _make_model(model: Any) -> Any:
    """A model string becomes a chat model paced to the provider's rate limit, with retries."""
    if not isinstance(model, str):
        return model
    from langchain.chat_models import init_chat_model
    from langchain_core.rate_limiters import InMemoryRateLimiter

    provider = model.split(":", 1)[0]
    kwargs: dict[str, Any] = {"max_retries": 6}
    rpm = config.max_rpm(provider)
    if rpm:
        kwargs["rate_limiter"] = InMemoryRateLimiter(
            requests_per_second=rpm / 60.0, check_every_n_seconds=0.5, max_bucket_size=1)
    return init_chat_model(model, **kwargs)


def build_agent(case: Case, model: Any = None):
    """The deepagents supervisor (a compiled LangGraph graph) bound to one case folder."""
    from deepagents import FilesystemMiddleware, FilesystemPermission, create_deep_agent
    from deepagents.backends import FilesystemBackend

    model = _make_model(model or config.MODEL)
    _lock_down(model)
    backend = FilesystemBackend(root_dir=str(case.dir), virtual_mode=True)
    return create_deep_agent(
        model=model,
        tools=build_tools(Supervisor(case, actor="llm", llm_text=True)),
        system_prompt=SYSTEM_PROMPT,
        backend=backend,
        # Three layers: (1) the file tools are replaced by a READ-ONLY set, so execute,
        # write_file, edit_file and delete are never registered; (2) every write is denied
        # by permission anyway; (3) the harness profile hides them and drops the subagent.
        middleware=[FilesystemMiddleware(backend=backend, tools=list(READ_ONLY_FILE_TOOLS))],
        permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        name="dome-supervisor",
    )


def run_llm(case: Case, model: Any = None) -> Supervisor:
    """Run the deepagents supervisor. If the LLM stops early, the rule-based planner finishes
    the remaining steps, so a brief is always written."""
    agent = build_agent(case, model)
    case.log(actor="llm", event="run_start", evidence={"model": str(model or config.MODEL)},
             message="deepagents supervisor run")
    result: dict = {}
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content":
                           f"Investigate case '{case.case_id}'. Run the pipeline to the brief."}]},
            {"recursion_limit": 150})
    except Exception as exc:   # model/API failure: the case still finishes, and it is logged
        err = f"{type(exc).__name__}: {exc}"
        quota = re.search(r"quotaId'?:\s*'([^']+)'", err)   # e.g. per-minute vs per-day limit
        case.log(actor="guard", event="decision", decision="llm_error_finish_with_scripted_planner",
                 evidence={"error": err[:300], "quota": quota.group(1) if quota else None},
                 message="The model call failed; the rule-based planner finishes the run.")
    sup = Supervisor(case, actor="scripted")
    if sup.next_action() is not None:
        case.log(actor="guard", event="decision", decision="finish_with_scripted_planner",
                 evidence={"required_next": sup.next_action()},
                 message="The LLM stopped before the brief; the rule-based planner finishes the run.")
        for _ in range(MAX_STEPS):
            action = sup.next_action()
            if action is None:
                break
            sup.dispatch(action)
    brief = case.load("brief.json")
    if brief is not None and brief.text_source == "template":
        case.log(actor="guard", event="decision", decision="brief_text_left_as_template",
                 evidence={"text_source": "template"},
                 message="The LLM did not write the brief's words; the Briefer's fixed wording stays.")
    case.log(actor="llm", event="run_end", evidence={"done": sup.next_action() is None})
    msgs = result.get("messages") or []
    sup.final_message = msgs[-1].text if msgs else ""
    return sup


def make_graph(config_: Optional[dict] = None):
    """Graph factory for LangGraph Studio / `langgraph dev` (see langgraph.json).

    Pick the case with configurable: {"case_id": "demo-c", "scenario": "ring_c"}.
    """
    cfg = (config_ or {}).get("configurable", {}) or {}
    case = Case.open(cfg.get("case_id", "demo-a"), scenario=cfg.get("scenario", "ring_a"),
                     dataset=cfg.get("dataset"), seed_account=cfg.get("seed_account"))
    return build_agent(case, cfg.get("model"))


# ---------------------------------------------------------------------- CLI
KEY_FOR_PROVIDER = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                    "google_genai": "GOOGLE_API_KEY", "groq": "GROQ_API_KEY"}


def _check_key(model: str) -> None:
    """Fail early with a clear message instead of a stack trace from the provider SDK."""
    import os
    provider = model.split(":", 1)[0]
    key = KEY_FOR_PROVIDER.get(provider)
    if key and not os.environ.get(key):
        sys.exit(f"{key} is not set. Add it to {config.ROOT / '.env'} for model '{model}', "
                 "or run with --scripted (no LLM).")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="dome.supervisor", description=__doc__.split("\n")[0])
    p.add_argument("--case", required=True, help="case id (folder under case/)")
    p.add_argument("--scenario", default="ring_a", help="stub scenario in samples/scenarios/")
    p.add_argument("--ring", default=None, help="ring id to investigate (default: highest R)")
    p.add_argument("--data", default=None, help="dataset folder (or name under samples/data/): "
                   "runs the real Linker on it instead of the stub")
    p.add_argument("--seed", default=None, help="investigate the ring containing this account")
    p.add_argument("--scripted", action="store_true", help="rule-based planner, no LLM")
    p.add_argument("--model", default=None, help="e.g. openai:gpt-5.5 (default: DOME_MODEL)")
    p.add_argument("--resume", action="store_true", help="keep earlier outputs in the case folder")
    a = p.parse_args(argv)

    if not a.scripted:
        _check_key(a.model or config.MODEL)
    seed = a.seed
    if a.data and not seed and not a.ring:   # default: the ring this scenario's fixtures describe
        fixture = config.SCENARIOS / a.scenario / "scenario.json"
        if fixture.exists():
            seed = json.loads(fixture.read_text(encoding="utf-8")).get("seed_account")
    case = Case.open(a.case, scenario=a.scenario, ring_id=a.ring, reset=not a.resume,
                     dataset=a.data, seed_account=seed)
    sup = run_scripted(case) if a.scripted else run_llm(case, a.model)

    brief = case.load("brief.json")
    print(f"\nCase {case.case_id}  ({'scripted' if a.scripted else a.model or config.MODEL})")
    print(f"Folder: {case.dir}")
    if brief is None:
        print("No valid brief.json. Failed steps:", case.failed_steps())
        return 1
    print(f"Status: {brief.status}   ring: {brief.ring_id}   zones: {', '.join(brief.zones) or '-'}")
    for l in brief.leads:
        f = l.factors
        print(f"  #{l.rank} {l.property_id}  {l.tier:<6} score {l.score:>3}  zone {l.zone_id}  "
              f"R {f.R} Z {f.Z} F {f.F} P {f.P} W {f.W}")
    if not brief.leads:
        print("  (no building leads)")
    print("Decisions:")
    for d in case.decisions():
        print(f"  [{d.actor}] {d.decision}  {json.dumps(d.evidence)}")
    if brief.failed_steps:
        print("Failed steps:", brief.failed_steps)
    if getattr(sup, "final_message", ""):
        print("\nSupervisor summary:\n" + sup.final_message)
    print("\n" + brief.footer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
