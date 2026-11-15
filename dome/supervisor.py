"""Dome supervisor: a LangChain deepagents agent whose tools are the five agents.

    python -m dome.supervisor --case demo-a                # LLM supervisor (Ring A)
    python -m dome.supervisor --case demo-a --scripted     # no LLM (offline/tests)

Design
- The LLM picks the next step and writes the brief's words. Every number comes from code.
- Three safety rules are enforced as GUARDS inside the tools, so they hold even if the LLM
  forgets: a weak ring stops after the Zoner, a wide zone keeps only scanned buildings, and
  no window photo caps a lead at Medium. Each fires a `decision` line in log.jsonl.
- GUARDRAIL: the supervisor has no tool that contacts, dispatches or publishes anything.
  No shell, no HTTP, no email, no file writes. The pipeline stops at the brief.
  Do not add such tools here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Callable, Optional

from pydantic import BaseModel

from . import config
from .agents import briefer, linker, lister, locator, zoner
from .case import Case
from .schemas import load_optional

MAX_STEPS = 40
NO_HINTS = "no_location_hints_use_logins_cap_medium"
ROOM_RERUN = "room_groups_outside_ring_rerun_linker"


_DECIMAL = re.compile(r"(?<![\d.])(?:\d+\.\d+|\.\d+)(?!\d)(?!\.\d)")
_PHONE = re.compile(r"(?:\d[\s\-.()]{0,3}){6,10}\d")


# ---------------------------------------------------------------------- night: events + hooks
EVENTS = "events.jsonl"                     # contract E, one event per line, read by the UI
NIGHT_FILES = (EVENTS, "spotter.json", "wallet_notes.json", "complex.json")
APPROVE = "report_approved"
REJECT = "report_rejected_by_analyst"


def reset_night_files(case: Case) -> None:
    """Fresh run: the night outputs are not in Case.OUTPUTS, so clear them here."""
    for n in NIGHT_FILES:
        case.path(n).unlink(missing_ok=True)


def emit(case: Case, agent: str, phase: str, message: str, refs: Optional[list] = None,
         **extra: Any) -> dict:
    """Append one contract E event to case/<id>/events.jsonl and, inside a LangGraph run,
    send it on the `custom` stream. `t` is seconds since the case's first event."""
    p = case.path(EVENTS)
    now = time.time()
    t0 = now
    if p.exists():
        first = p.read_text(encoding="utf-8").split("\n", 1)[0]
        try:
            t0 = now - 0.0 if not first.strip() else float(json.loads(first).get("_t0", now))
        except Exception:
            t0 = now
    ev = {"t": round(max(0.0, now - t0), 1), "agent": agent, "phase": phase, "message": message,
          "refs": [str(r) for r in (refs or []) if r], **extra}
    line = dict(ev)
    if not p.exists() or not p.read_text(encoding="utf-8").strip():
        line["_t0"] = now      # wall-clock anchor for `t`, kept only on the first line
    case.dir.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, default=str) + "\n")
    try:   # only inside a LangGraph run; elsewhere there is no stream to write to
        from langgraph.config import get_stream_writer
        get_stream_writer()({"event": ev, "case_id": case.case_id})
    except Exception:
        pass
    return ev


def auto_approve(preview: dict) -> dict:
    """Scripted mode and the CLI: no human at the keyboard, so the report is approved
    automatically and the log says so."""
    return {"approved": True, "by": "auto (scripted)", "note": "no analyst in this run"}


def _flag(name: str) -> bool:
    return os.getenv(name) == "1"


class LeadText(BaseModel):
    """The words the supervisor writes for one lead. No numbers of its own."""
    property_id: str
    reasons: list[str]
    verify_next: list[str]


class Supervisor:
    """Deterministic core: status facts, the next required step, guarded run_* steps."""

    def __init__(self, case: Case, actor: str = "supervisor", llm_text: bool = False,
                 approver: Optional[Callable[[dict], Any]] = None):
        self.case = case
        self.actor = actor   # who is driving: "llm" or "scripted"
        # True when an LLM drives: after the Briefer's numbers, it writes the brief's words
        self.llm_text = llm_text
        # Human approval before the report. LangGraph runs pass langgraph's interrupt();
        # scripted/CLI runs auto-approve and log it.
        self.approver = approver or auto_approve

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
                f.update(best_P=m.best_P, above_threshold=m.above_threshold)
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
                "roles": len(ring.roles), "location_hints": len(ring.location_hints),
                "events": len(ring.events), "relay_handoffs": len(ring.relay),
                "topo_score": ring.topo_score},
            "room_groups_with_outside_accounts": self._outside_groups(),
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
        if "briefer" in failed or self._rejected():
            return None
        if c.load("rings.json") is None:
            if "linker" in failed:
                return act("run_briefer", "Linker failed; report it", stop_reason="no_ring")
            return act("run_linker", "no rings.json yet")
        ring = c.selected_ring()
        if ring is None:
            return act("run_briefer", "Linker found no ring", stop_reason="no_ring")
        zones = c.load("zones.json")
        if zones is None:
            if "zoner" in failed:
                return act("run_briefer", "Zoner failed; report it")
            if self._needs_login_fallback(ring):
                return act("run_zoner", "ring has roles from messages/payments but no location "
                           "hints: fall back to login data, cap leads at Medium", fallback="logins")
            return act("run_zoner", "no zones.json yet")
        if ring.confidence < config.RING_MIN_CONFIDENCE:
            return act("run_briefer", f"R {ring.confidence} < {config.RING_MIN_CONFIDENCE}: "
                       "weak ring, stop after the Zoner", stop_reason="weak_ring")
        cands, matches = c.load("candidates.json"), c.load("matches.json")
        listed = {z.zone_id for z in cands.zones} if cands else set()
        located = {z.zone_id for z in matches.zones} if matches else set()
        for z in zones.zones:   # Lister then Locator for each zone
            if z.zone_id not in listed:
                if f"lister:{z.zone_id}" in failed:
                    continue
                return act("run_lister", f"zone {z.zone_id} has no candidates yet",
                           zone_id=z.zone_id, scanned_only=z.wide)
            if z.zone_id not in located and f"locator:{z.zone_id}" not in failed:
                return act("run_locator", f"zone {z.zone_id} not searched yet", zone_id=z.zone_id)
        if self._room_rerun_due():
            return act("run_linker", "the Locator's room groups contain photos from accounts outside "
                       "the ring: re-run the Linker once with same-room links", room_groups=True)
        return act("run_briefer", "all zones processed")

    # ------------------------------------------------------------------ v2 decision facts
    def _needs_login_fallback(self, ring) -> bool:
        # Only meaningful with the private layers (Track 1): money-shape roles came from
        # messages/payments that named no place. With --no-private (Track 2) there are no
        # hints by design, so the Zoner uses public place clues as usual and nothing is capped.
        rings = self.case.load("rings.json")
        if rings is None or not rings.private_layers:
            return False
        money_roles = [r for r in ring.roles if r.role in ("collector", "handler", "hub")]
        return bool(money_roles) and not ring.location_hints

    def _outside_groups(self) -> list[dict]:
        m = self.case.load("matches.json")
        return [{"zone_id": z.zone_id, "group_id": g.group_id, "outside_ring": g.outside_ring}
                for z in (m.zones if m else []) for g in z.room_groups if g.outside_ring]

    def _room_rerun_due(self) -> bool:
        c = self.case
        rings = c.load("rings.json")
        return bool(self._outside_groups()) and rings is not None and not rings.room_links_used \
            and "linker:room" not in c.failed_steps()

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
    def run_linker(self, room_groups: bool = False) -> dict:
        c = self.case
        if room_groups:
            return self._run_linker_room()
        if c.load("rings.json") is not None:
            return self._refuse("linker", "rings.json already exists and is valid")
        self._spotter_hook()
        ok = self._run_step("linker", "rings.json", lambda: linker.run(c),
                            ["flagged_accounts.json"], {})
        ring = c.selected_ring()
        if ok and ring is None:
            self._decide("linker", "no_ring_found", {"rings": 0},
                         "No group of accounts shares two kinds of key; weak hints only.")
        if ok and ring is not None:
            emit(c, "linker", "result",
                 f"{len(ring.members)} accounts form ring {ring.ring_id} (R {ring.confidence}): "
                 f"{', '.join(ring.key_kinds[:4])}", [ring.ring_id] + ring.members[:3])
            self._money_hook()
            ring = c.selected_ring() or ring
        elif ok:
            emit(c, "linker", "result", "No ring: no group shares two different kinds of key")
        else:
            emit(c, "linker", "failed", "Linker failed twice; the Briefer will report it")
        return self._result(ok, "linker", ring_id=ring and ring.ring_id, R=ring and ring.confidence,
                            photos=len(ring.photos) if ring else 0)

    # ------------------------------------------------------------------ night hooks
    def _spotter_hook(self) -> None:
        """DOME_SPOTTER=1: Ishaan's rules-only Spotter writes case/<id>/spotter.json."""
        c = self.case
        if not _flag("DOME_SPOTTER") or c.path("spotter.json").exists():
            return
        try:
            from .agents import spotter   # Ishaan's module; absent until it is merged
        except ImportError:
            self.log_decision("spotter_module_not_available", {"flag": "DOME_SPOTTER"},
                              "spotter module not available")
            return
        try:
            spotter.run(c)
            q = load_optional(c.dir, "spotter.json")
            n = len(q.queue) if q else 0
            c.log(actor="agent", event="tool_result", step="spotter", output_file="spotter.json",
                  evidence={"flagged": n, "valid": q is not None}, message="spotter wrote its queue")
            emit(c, "spotter", "result", f"Spotter flagged {n} account(s) (rules: 3+ signal kinds agree)",
                 [x.account for x in (q.queue[:3] if q else [])])
        except Exception as exc:
            c.log(actor="guard", event="step_failed", step="spotter",
                  evidence={"error": f"{type(exc).__name__}: {exc}"[:300]},
                  message="spotter failed; the case continues without it")

    def _money_hook(self) -> None:
        """DOME_MONEY=1: money.attach(case) adds the money block (contract B) to rings.json and
        writes wallet_notes.json (contract G). DOME_LINK_MONEY=1: then the Linker runs a second
        pass that counts each wallet note as a `money` key (weight 0.9)."""
        c = self.case
        if not _flag("DOME_MONEY"):
            return
        try:
            from .agents import money   # Ishaan's module; absent until it is merged
        except ImportError:
            self.log_decision("money_module_not_available", {"flag": "DOME_MONEY"},
                              "money module not available")
            return
        before = c.path("rings.json").read_text(encoding="utf-8")
        try:
            money.attach(c)
        except Exception as exc:
            c.path("rings.json").write_text(before, encoding="utf-8")
            c.log(actor="guard", event="step_failed", step="money",
                  evidence={"error": f"{type(exc).__name__}: {exc}"[:300]},
                  message="money.attach failed; rings.json restored, the case continues without money")
            return
        if c.load("rings.json") is None:   # attach wrote something the schema rejects
            c.path("rings.json").write_text(before, encoding="utf-8")
            c.log(actor="guard", event="step_failed", step="money",
                  message="money block failed schema validation; rings.json restored")
            return
        ring = c.selected_ring()
        mb = ring.money if ring else None
        c.log(actor="agent", event="tool_result", step="money", output_file="rings.json",
              evidence={"clusters": len(mb.wallet_clusters) if mb else 0,
                        "wallet_notes": c.path("wallet_notes.json").exists()},
              message="money block attached")
        if mb:
            cash = ", ".join(sorted({x.service for x in mb.cash_out})) or "none found"
            emit(c, "linker", "result",
                 f"Money: {len(mb.wallet_clusters)} wallet clusters "
                 f"({', '.join(sorted({w.role or '?' for w in mb.wallet_clusters}))}); cash-out: {cash}",
                 [w.cluster_id for w in mb.wallet_clusters[:3]])
        if _flag("DOME_LINK_MONEY") and c.path("wallet_notes.json").exists():
            self._linker_money_pass()

    def _complex_hook(self) -> None:
        """Case complex (contract F) + UniGCN scores -> complex.json. On by default for
        dataset cases (DOME_COMPLEX=0 turns it off); a failure is logged, never fatal."""
        c = self.case
        if os.getenv("DOME_COMPLEX", "1") == "0" or not c.input.dataset:
            return
        try:
            from . import complex as cx
            out = cx.build(c)
            c.log(actor="agent", event="tool_result", step="complex", output_file="complex.json",
                  evidence={"ranks": {k: len(v) for k, v in out["ranks"].items()},
                            "scores": len(out["scores"]), "disagreements": len(out.get("disagreements", [])),
                            "model": out["model"]},
                  message="case complex built")
            emit(c, "linker", "result", f"Case complex: {len(out['ranks']['0'])} nodes, "
                 f"{len(out['ranks']['1'])} shared notes, {len(out['ranks']['2'])} events; "
                 f"{len(out.get('disagreements', []))} model-vs-rules disagreements to review",
                 [x["id"] for x in out["ranks"].get("3", [])][:3])
        except Exception as exc:
            c.log(actor="guard", event="step_failed", step="complex",
                  evidence={"error": f"{type(exc).__name__}: {exc}"[:300]},
                  message="case complex failed; the brief is unaffected")

    def _linker_money_pass(self) -> None:
        """Second Linker pass with wallet notes as `money` keys. The money block is carried
        over to the ring that keeps the most of its members."""
        c = self.case
        before = c.selected_ring()
        notes = load_optional(c.dir, "wallet_notes.json")
        n = len(notes.notes) if notes else 0
        self._decide("linker:money", "linker_second_pass_with_wallet_notes",
                     {"wallet_notes": n, "ring_id": before.ring_id if before else None},
                     "Wallet notes tie accounts to wallet clusters; re-running the Linker once so a "
                     "shared wallet counts as a money key toward the two-kinds rule.")
        old = c.load("rings.json")
        ok = self._run_step("linker:money", "rings.json", lambda: linker.run(c, wallet_notes=True),
                            ["rings.json", "wallet_notes.json"], {"wallet_notes": True})
        if not ok:
            c.save("rings.json", old)
            return
        new = c.load("rings.json")
        data = new.model_dump(by_alias=True)
        for r_old in old.rings:
            if r_old.money is None:
                continue
            best = max(data["rings"], key=lambda r: len(set(r["members"]) & set(r_old.members)),
                       default=None)
            if best is not None and set(best["members"]) & set(r_old.members):
                best["money"] = r_old.money.model_dump(by_alias=True)
        c.save("rings.json", data)
        after = c.selected_ring()
        if before and after:
            added = sorted(set(after.members) - set(before.members))
            c.log(actor="guard", event="decision", step="linker:money",
                  decision="ring_updated_by_wallet_notes",
                  evidence={"added": added, "removed": sorted(set(before.members) - set(after.members)),
                            "R_before": before.confidence, "R_after": after.confidence},
                  message=f"Wallet notes added {len(added)} account(s) to the ring.")
            emit(c, "linker", "result", f"Second pass with wallet notes: {len(added)} account(s) added; "
                 f"R {before.confidence} -> {after.confidence}", [after.ring_id] + added[:3])

    def _run_linker_room(self) -> dict:
        """v2 decision: room groups hold photos from accounts outside the ring -> re-run the
        Linker ONCE with same-room (note 4) links. Zoner/Lister/Locator do not re-run."""
        c = self.case
        if not self._room_rerun_due():
            return self._refuse("linker:room", "no room group with outside accounts, or the "
                                "Linker already re-ran with room links")
        before = c.selected_ring()
        groups = self._outside_groups()
        self._decide("linker:room", ROOM_RERUN, {"groups": groups, "ring_id": before.ring_id},
                     "Photos of the same room came from accounts outside the ring; re-running the "
                     "Linker once with same-room links.")
        ok = self._run_step("linker:room", "rings.json", lambda: linker.run(c, room_groups=True),
                            ["rings.json", "matches.json"], {"room_groups": True})
        after = c.selected_ring()
        if ok and after is not None:
            added = sorted(set(after.members) - set(before.members))
            removed = sorted(set(before.members) - set(after.members))
            old_roles = {r.account: r.role for r in before.roles}
            changed = sorted(f"{r.account}: {old_roles.get(r.account, 'none')} -> {r.role}"
                             for r in after.roles if old_roles.get(r.account) != r.role)
            c.log(actor="guard", event="decision", step="linker:room", decision="ring_updated_by_room_links",
                  evidence={"added": added, "removed": removed, "roles_changed": changed,
                            "R_before": before.confidence, "R_after": after.confidence},
                  message=f"Same-room links added {len(added)} account(s) to the ring.")
        return self._result(ok, "linker:room", ring_id=after and after.ring_id,
                            members_added=sorted(set(after.members) - set(before.members)) if after else [])

    def run_zoner(self, fallback: Optional[str] = None) -> dict:
        c = self.case
        ring = c.selected_ring()
        if ring is None:
            return self._refuse("zoner", "no ring yet; run the Linker first")
        if c.load("zones.json") is not None:
            return self._refuse("zoner", "zones.json already exists and is valid")
        # Guard: the data decides the fallback, not the caller
        fallback = "logins" if self._needs_login_fallback(ring) else None
        if fallback:
            self._decide("zoner", NO_HINTS, {"ring_id": ring.ring_id, "roles": len(ring.roles),
                                             "location_hints": 0},
                         "The ring has roles from messages and payments but no place in them; the "
                         "Zoner falls back to login data and every lead is capped at Medium.")
        logins = "on" if fallback == "logins" else "off"
        ok = self._run_step("zoner", "zones.json",
                            lambda: zoner.run(c, logins=logins) if logins == "on" else zoner.run(c),
                            ["rings.json"], {"fallback": fallback})
        zones = c.load("zones.json")
        zs = zones.zones if zones else []
        if ok and ring.confidence < config.RING_MIN_CONFIDENCE:
            self._decide("zoner", "stop_after_zoner_weak_ring",
                         {"ring_id": ring.ring_id, "R": ring.confidence,
                          "min_R": config.RING_MIN_CONFIDENCE},
                         "Ring confidence is below the minimum; stopping after the Zoner. "
                         "The brief reports the zone only, no buildings.")
        if ok:
            emit(c, "zoner", "result", "Dome: " + "; ".join(
                f"{z.zone_id} {z.area_km2} km2{' (wide)' if z.wide else ''}" for z in zs),
                [z.zone_id for z in zs])
        else:
            emit(c, "zoner", "failed", "Zoner failed twice; the Briefer will report it")
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
        if b:
            emit(c, "lister", "result", f"{len(b.candidates)} candidate buildings in {zone_id} "
                 f"({sum(x.has_scan for x in b.candidates)} scanned) of {b.total_in_zone} in the zone",
                 [zone_id])
        else:
            emit(c, "lister", "failed", f"Lister failed for {zone_id}", [zone_id])
        return self._result(ok, "lister", zone_id=zone_id, scanned_only=scanned_only,
                            total_in_zone=b.total_in_zone if b else None,
                            candidates=len(b.candidates) if b else None,
                            scanned=sum(x.has_scan for x in b.candidates) if b else None)

    def run_locator(self, zone_id: str) -> dict:
        c = self.case
        ring, cands, matches = c.selected_ring(), c.load("candidates.json"), c.load("matches.json")
        if ring is None or cands is None or not any(z.zone_id == zone_id for z in cands.zones):
            return self._refuse(f"locator:{zone_id}", f"zone {zone_id} has no candidates; run the Lister first")
        if matches is not None and any(z.zone_id == zone_id for z in matches.zones):
            return self._refuse(f"locator:{zone_id}", "this zone was already searched")
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
            unchecked = [x for x in m.matches
                         if x.P >= m.threshold and not x.window_checked and x.window_skipped]
            if m.window_photos > 0 and unchecked:
                self._decide(f"locator:{zone_id}", "window_check_not_run_cap_medium",
                             {"zone_id": zone_id, "property_id": unchecked[0].property_id,
                              "reason": unchecked[0].window_skipped[:160]},
                             "Window photos exist but the window check could not run; W stays "
                             "null and the lead is capped at Medium.")
            if not m.above_threshold:
                self._decide(f"locator:{zone_id}", "no_scan_above_threshold",
                             {"zone_id": zone_id, "best_P": m.best_P, "threshold": m.threshold},
                             "No scan matched above threshold; no building lead for this zone.")
        if m:
            top = max(m.matches, key=lambda x: x.P, default=None)
            if top is not None and m.above_threshold:
                extra = (f"; pin moved {top.geo.pin_moved_m:g} m" if top.geo else "") + \
                        (f"; floor {top.floor_range[0]}-{top.floor_range[1]}" if top.floor_range else "")
                emit(c, "locator", "result", f"Ring photos match {top.property_id}'s scan "
                     f"(P {top.P}{', W ' + str(top.W) if top.W is not None else ''}){extra}",
                     [zone_id, top.property_id, top.scan_id])
            else:
                emit(c, "locator", "result", f"No scan in {zone_id} matched above P {m.threshold} "
                     f"(best {m.best_P})", [zone_id])
        else:
            emit(c, "locator", "failed", f"Locator failed for {zone_id}", [zone_id])
        return self._result(ok, "locator", zone_id=zone_id, best_P=m and m.best_P, above_threshold=m and m.above_threshold,
                            window_photos=m and m.window_photos)

    def run_briefer(self, stop_reason: Optional[str] = None) -> dict:
        c, nxt = self.case, self.next_action()
        if c.check("brief.json") == "valid":
            return self._refuse("briefer", "brief.json is already written")
        if nxt["tool"] != "run_briefer":
            return self._refuse("briefer", "not ready for the brief yet: " + nxt["why"])
        stop_reason = nxt["args"].get("stop_reason")   # the data decides, not the caller
        if not self._approved():
            preview = self.report_preview()
            # LangGraph runs pause here (interrupt) until the analyst answers in the UI.
            answer = self.approver(preview)
            approved, by, note = _parse_approval(answer)
            c.log(actor="guard", event="decision", step="briefer",
                  decision=APPROVE if approved else REJECT,
                  evidence={"by": by, "note": note, "preview": preview},
                  message=("Report approved" if approved else "Analyst held the report") +
                          f" ({by}).")
            emit(c, "supervisor", "decision",
                 ("Report approved" if approved else "Report held by the analyst") + f" ({by})",
                 preview.get("refs", []))
            if not approved:
                return {"ok": False, "step": "briefer", "held": True,
                        "reason": "the analyst did not approve the report", "required_next": None}
        ok = self._run_step("briefer", "brief.json", lambda: briefer.run(c, stop_reason),
                            ["rings.json", "zones.json", "candidates.json", "matches.json"],
                            {"stop_reason": stop_reason})
        b = c.load("brief.json")
        if ok:
            self._complex_hook()
        if b:
            emit(c, "briefer", "result", "Report: " + ("; ".join(
                f"{l.property_id} {l.tier} ({l.score})" for l in b.leads) or f"no building leads ({b.status})"),
                [l.property_id for l in b.leads[:3]])
        else:
            emit(c, "briefer", "failed", "Briefer failed twice")
        return self._result(ok, "briefer", status=b and b.status,
                            leads=[{"rank": l.rank, "property_id": l.property_id, "tier": l.tier,
                                    "score": l.score} for l in b.leads] if b else [])

    # ------------------------------------------------------------------ approval
    def _approved(self) -> bool:
        return any(d.decision == APPROVE for d in self.case.decisions())

    def _rejected(self) -> bool:
        return any(d.decision == REJECT for d in self.case.decisions())

    def report_preview(self) -> dict:
        """What the analyst approves: the best match per zone, straight from matches.json.
        No tier yet: the Briefer computes tiers only after approval."""
        c = self.case
        ring, m = c.selected_ring(), c.load("matches.json")
        tops = []
        for z in (m.zones if m else []):
            top = max(z.matches, key=lambda x: x.P, default=None)
            if top is not None:
                tops.append({"zone_id": z.zone_id, "property_id": top.property_id,
                             "scan_id": top.scan_id, "P": top.P, "W": top.W,
                             "above_threshold": top.P >= z.threshold})
        best = next((t for t in sorted(tops, key=lambda t: -t["P"]) if t["above_threshold"]), None)
        q = (f"Approve {best['property_id']} (P {best['P']}"
             f"{', W ' + str(best['W']) if best['W'] is not None else ''}) as a lead for the report?"
             if best else "Approve the report (no building above threshold)?")
        return {"question": q, "case_id": c.case_id, "ring_id": ring and ring.ring_id,
                "R": ring and ring.confidence, "best_matches": tops,
                "refs": [x for x in ([best["property_id"]] if best else [])]}

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
def _parse_approval(answer: Any) -> tuple[bool, str, str]:
    """The analyst's answer from the UI: True/False, "approve"/"reject", or
    {"approved": bool, "by": ..., "note": ...}."""
    if isinstance(answer, dict):
        ok = answer.get("approved", answer.get("decision") in ("approve", "approved", "yes"))
        return bool(ok), str(answer.get("by") or "analyst"), str(answer.get("note") or "")
    if isinstance(answer, str):
        return answer.strip().lower() in ("approve", "approved", "yes", "y", "ok"), "analyst", ""
    return bool(answer), "analyst", ""


def run_scripted(case: Case, approver: Optional[Callable[[dict], Any]] = None) -> Supervisor:
    """Walk the same tools with the rule-based planner. No LLM (offline demo and tests).
    The report is auto-approved (logged as such) unless an approver is passed."""
    sup = Supervisor(case, actor="scripted", approver=approver)
    case.log(actor="scripted", event="run_start", message="scripted supervisor run")
    inp = case.input
    emit(case, "supervisor", "start", "Case started" + (
        f" from flagged account {inp.seed_account}" if inp.seed_account else ""),
        [inp.seed_account] if inp.seed_account else [])
    for _ in range(MAX_STEPS):
        action = sup.next_action()
        if action is None:
            break
        sup.dispatch(action)
    case.log(actor="scripted", event="run_end", evidence={"done": sup.next_action() is None})
    emit(case, "supervisor", "end", "Run finished" if sup.next_action() is None else "Run stopped")
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
- No scan with P >= 0.4: no building lead for that zone; say so plainly in the brief.
- No window in any photo: the window check is skipped (W = null), lead capped at Medium.
- Ring has roles (from messages/payments) but no location hints: run_zoner(fallback="logins")
  and every lead is capped at Medium.
- The Locator's room groups contain photos from accounts outside the ring: run_linker(
  room_groups=True) once; the Zoner, Lister and Locator do not re-run.

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
    def run_linker(room_groups: bool = False) -> str:
        """Run the Linker: group flagged accounts into rings, with a reason for every link
        (writes rings.json). room_groups=True re-runs it ONCE after the Locator, adding
        same-room links from room groups that hold photos of accounts outside the ring."""
        return js(sup.run_linker(room_groups))

    @tool
    def run_zoner(fallback: Optional[str] = None) -> str:
        """Run the Zoner: turn the ring's place clues into zones (writes zones.json).
        Zones are areas, never addresses. fallback='logins' uses login data when the ring
        has no location hints (leads are then capped at Medium)."""
        return js(sup.run_zoner(fallback))

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


def build_agent(case: Case, model: Any = None, approver: Optional[Callable[[dict], Any]] = None):
    """The deepagents supervisor (a compiled LangGraph graph) bound to one case folder.
    approver: langgraph's interrupt() under `langgraph dev`; auto-approve otherwise."""
    from deepagents import FilesystemMiddleware, FilesystemPermission, create_deep_agent
    from deepagents.backends import FilesystemBackend

    model = _make_model(model or config.MODEL)
    _lock_down(model)
    backend = FilesystemBackend(root_dir=str(case.dir), virtual_mode=True)
    return create_deep_agent(
        model=model,
        tools=build_tools(Supervisor(case, actor="llm", llm_text=True, approver=approver)),
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
    emit(case, "supervisor", "start", f"Case started ({model or config.MODEL})",
         [case.input.seed_account] if case.input.seed_account else [])
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
    emit(case, "supervisor", "end", "Run finished" if sup.next_action() is None else "Run stopped")
    msgs = result.get("messages") or []
    sup.final_message = msgs[-1].text if msgs else ""
    return sup


def build_graph_from_config(config_: Optional[dict] = None):
    """Build the supervisor for the case named in a run's config (blocking: touches files).

    configurable: {"case_id": "demo-a", "scenario": "ring_a", "dataset": "synth",
                   "seed_account": "acct_103", "model": "google_genai:gemini-3.5-flash"}
    """
    from langgraph.types import interrupt
    cfg = (config_ or {}).get("configurable", {}) or {}
    case = Case.open(cfg.get("case_id", "demo-a"), scenario=cfg.get("scenario", "ring_a"),
                     dataset=cfg.get("dataset"), seed_account=cfg.get("seed_account"))
    approver = auto_approve if cfg.get("auto_approve") else interrupt   # one human approval
    return build_agent(case, cfg.get("model"), approver=approver)


async def make_graph(config):
    """Graph factory for LangGraph Studio / `langgraph dev` (see langgraph.json).

    The server calls this on its event loop, so the file work runs in a worker thread.
    """
    import asyncio
    return await asyncio.to_thread(build_graph_from_config, config)


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
    p.add_argument("--layers", default="both", choices=["content", "network", "both"],
                   help="Linker layers (three-way comparison)")
    p.add_argument("--no-private", action="store_true",
                   help="drop messages and payments (kept for tests; the demo never passes it: "
                   "Arlequin allows synthetic private data)")
    a = p.parse_args(argv)

    if not a.scripted:
        _check_key(a.model or config.MODEL)
    seed = a.seed
    if a.data and not seed and not a.ring:   # default: Ring A's seed account in that dataset
        fixture = config.SCENARIOS / a.scenario / "scenario.json"
        if fixture.exists():
            seeds = json.loads(fixture.read_text(encoding="utf-8")).get("seed_account") or {}
            seed = seeds.get(a.data) if isinstance(seeds, dict) else seeds
    case = Case.open(a.case, scenario=a.scenario, ring_id=a.ring, reset=not a.resume,
                     dataset=a.data, seed_account=seed, layers=a.layers,
                     private_layers=not a.no_private)
    if not a.resume:
        reset_night_files(case)
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
