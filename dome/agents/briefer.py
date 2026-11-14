"""Briefer (Ishaan): how strong is each lead and why?  -> brief.json + summary.html

    python -m dome.agents.briefer --case <case_id>
    python -m dome.agents.briefer --case <case_id> --score data/answer_key/answer_key.json   (scoring only)

Reads rings.json, zones.json, candidates.json and matches.json from the case folder.

1. TIER FIRST (rules). The score only orders leads inside a tier; it never promotes past a rule.
     High:   P >= 0.6 and W >= 0.6 and R >= 0.6
     Medium: P >= 0.6 when anything else falls short (no window check, W < 0.6, or R < 0.6),
             or 0.4 <= P < 0.6 with W >= 0.6
     Low:    everything else.
   Only buildings with a photo match (P >= the Locator threshold) become leads. Buildings that
   were checked but did not match, or had no reference photos, are counted on the summary page.
   Each shortfall of a strong room match adds a cap line saying why it is not High.
2. SCORE = 100 * R * (0.15 Z + 0.10 F + 0.45 P + 0.30 W). With no W, drop it and rescale.
   (weights: config.SCORE_WEIGHTS)
3. One plain-language reason per factor, and "verify next": which records to request through
   legal process and what would confirm or rule the lead out. Never an entry or access plan.
4. A missing or failed input still gives a brief and a summary page: the failed step is named
   and every lead is capped at Low.

The supervisor LLM may later rewrite the reasons and next checks (write_brief_text), but never a
tier, score or cap. The page shows display names ("Building A (synthetic case)"), never an address.
"""
from __future__ import annotations

import re
import string
from collections import Counter
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import config
from ..case import Case

TIER_ORDER = {"High": 0, "Medium": 1, "Low": 2}
PHONE = re.compile(r"(?:\d[\s\-.()]{0,3}){6,10}\d")


# ---- rules and score (shared with the supervisor's tests) -------------------------------------

def tier_for(R: float, P: float, W: Optional[float]) -> str:
    s, t = config.TIER_STRONG, config.MATCH_THRESHOLD
    if P >= s and W is not None and W >= s and R >= s:
        return "High"
    if P >= s or (t <= P < s and W is not None and W >= s):
        return "Medium"
    return "Low"


def caps_for(R: float, P: float, W: Optional[float]) -> list[str]:
    """Why a lead with a strong room match is not High (no cap lines for any other lead)."""
    s, caps = config.TIER_STRONG, []
    if P < s:
        return caps
    if W is None:
        caps.append("capped at Medium: no window photo, window check skipped")
    elif W < s:
        caps.append(f"capped at Medium: window check W {W:.2f} is below {s}")
    if R < s:
        caps.append(f"capped at Medium: ring confidence R {R:.2f} is below {s}")
    return caps


def score_for(R: float, Z: float, F: float, P: float, W: Optional[float]) -> int:
    w = dict(config.SCORE_WEIGHTS)
    vals = {"Z": Z, "F": F, "P": P, "W": W}
    if W is None:
        w.pop("W")
    total = sum(w.values())
    return round(100 * R * sum(w[k] * vals[k] for k in w) / total)


# ---- reasons ----------------------------------------------------------------------------------

def scrub(text: str) -> str:
    """No phone numbers in the brief (data minimisation)."""
    return PHONE.sub("[phone]", text)


def ring_reason(ring) -> str:
    kinds = Counter(k for link in ring.links for k in link.kinds if k != "place")
    if kinds:
        what = ", ".join(f"{k} ({n} link{'s' * (n != 1)})" for k, n in kinds.most_common(3))
    else:
        what = ", ".join(ring.key_kinds) or "shared keys"
    return f"R {ring.confidence:.2f}: {len(ring.members)} accounts linked by {what}"


def zone_reason(zone) -> str:
    if zone is None:
        return "Z 0.00: building is not inside any zone"
    first = f"; {zone.reasons[0]}" if zone.reasons else ""
    wide = ", wide zone" if zone.wide else ""
    return (f"Z {zone.confidence:.2f}: inside {zone.zone_id} ({zone.area_km2:g} km2{wide}, "
            f"{zone.weight_share:.0%} of place-clue weight){first}")


def fit_reason(cand) -> str:
    if cand is None:
        return "F 0.00: building not in the candidate list"
    why = "; ".join(cand.fit_reasons[:2]) or f"{cand.type}, {cand.floors or '?'} floors"
    return f"F {cand.fit:.2f}: {why}"


def photo_reason(m, mz) -> str:
    if m is None:
        return "P 0.00: no photo match (no reference photos for this building)"
    if m.P < mz.threshold:
        return f"P {m.P:.2f}: room photos do not match this building's scan (below {mz.threshold})"
    inliers = sum(e.inliers for e in m.evidence)
    return (f"P {m.P:.2f}: {len(m.evidence)} of {mz.photos_used} room photos match the unit scan, "
            f"{inliers} matched points")


def window_reason(m) -> Optional[str]:
    if m is None or m.P < config.MATCH_THRESHOLD:
        return None
    if m.W is None:
        return "W missing: no window photo, so the window view was not checked"
    ok = [k.replace("_", " ") for k, v in m.window_checks.items() if v]
    no = [k.replace("_", " ") for k, v in m.window_checks.items() if not v]
    return f"W {m.W:.2f}: window view agrees on {', '.join(ok) or 'nothing'}; not seen: {', '.join(no) or 'none'}"


def verify_next(tier, m, cand, dates) -> list[str]:
    """Records to request through legal process, and what would confirm or rule the lead out."""
    if m is None or m.P < config.MATCH_THRESHOLD:
        if cand is not None and not cand.has_scan:
            return ["No reference photos: find out whether a scan or listing photos exist for this "
                    "building before anything else",
                    "Not a lead on its own: place clues and fit never justify a records request"]
        return ["Not a lead on its own: no room match, so no records request is justified"]
    floors = f"floors {m.floor_range[0]}-{m.floor_range[1]}" if m.floor_range else "the matched unit type"
    when = f" for {dates[0]} to {dates[1]}" if dates else " for the dates of the ads"
    steps = [
        f"Through legal process, request lease and short-term booking records for units on {floors}{when}",
        "Through legal process, request the payment records behind any such booking",
        "Confirms: a lease or booking on those floors overlapping the ad dates, with a unit layout "
        "that matches the photos",
        "Rules out: no occupancy in those dates, or unit layouts that differ from the matched rooms",
        "A human reviewer compares each matched photo with its scan view side by side",
    ]
    if m.W is None:
        steps.insert(3, "A window photo from the ads, if one turns up, would allow the window check")
    if tier == "Low":
        steps.insert(0, "Capped at Low because a pipeline step failed; re-run it before any request")
    return steps


def ad_dates(case: Case, members) -> Optional[tuple[str, str]]:
    """First and last ad date of the ring, from the dataset (None for stub runs)."""
    data = case.dataset_dir()
    if data is None or not (data / "posts.json").exists():
        return None
    import json
    members = set(members)
    times = sorted(p["time"][:10] for p in json.loads((data / "posts.json").read_text(encoding="utf-8"))
                   if (p.get("account_id") or p.get("account") or p.get("handle")) in members)
    return (times[0], times[-1]) if times else None


def display_name(i: int) -> str:
    """1 -> 'Building A (synthetic case)', 27 -> 'Building AA (synthetic case)'."""
    letters, n = "", i
    while n:
        n, r = divmod(n - 1, 26)
        letters = string.ascii_uppercase[r] + letters
    return f"Building {letters} (synthetic case)"


# ---- main step --------------------------------------------------------------------------------

def missing_inputs(case: Case, stop_reason: Optional[str]) -> list[str]:
    """Inputs the brief needed but could not read, e.g. 'locator (matches.json missing)'."""
    if stop_reason or case.selected_ring() is None:
        return []
    need = [("zoner", "zones.json"), ("lister", "candidates.json"), ("locator", "matches.json")]
    return [f"{step} ({name} {case.check(name)})" for step, name in need if case.check(name) != "valid"]


def build_leads(case: Case, ring, zones, cands, matches, low_only: str = "") -> list[dict]:
    zone_by_id = {z.zone_id: z for z in zones.zones} if zones else {}
    cand_zone = {}
    for cz in (cands.zones if cands else []):
        for c in cz.candidates:
            cand_zone.setdefault(c.property_id, (c, cz.zone_id))
    dates = ad_dates(case, ring.members)

    found = {}   # property_id -> lead; the best match per building across zones
    for mz in (matches.zones if matches else []):
        for m in mz.matches:
            if m.P < mz.threshold:
                continue   # no photo match: not a lead (counted on the page instead)
            c, _ = cand_zone.get(m.property_id, (None, mz.zone_id))
            lead = make_lead(ring, zone_by_id.get(mz.zone_id), mz.zone_id, c, m, mz, dates, low_only)
            if m.property_id not in found or lead["score"] > found[m.property_id]["score"]:
                found[m.property_id] = lead


    leads = sorted(found.values(), key=lambda l: (TIER_ORDER[l["tier"]], -l["score"], l["property_id"]))
    for i, lead in enumerate(leads, 1):
        lead["rank"] = i
        lead["display_name"] = display_name(i)
    return leads


def make_lead(ring, zone, zone_id, cand, m, mz, dates, low_only):
    P = m.P if m else 0.0
    W = m.W if m and P >= config.MATCH_THRESHOLD else None
    f = {"R": ring.confidence, "Z": zone.confidence if zone else 0.0,
         "F": cand.fit if cand else 0.0, "P": P, "W": W}
    tier, caps = tier_for(f["R"], P, W), caps_for(f["R"], P, W)
    if low_only and tier != "Low":
        tier = "Low"
        caps.append(f"capped at Low: {low_only}")
    reasons = [ring_reason(ring), photo_reason(m, mz), window_reason(m), zone_reason(zone), fit_reason(cand)]
    return {"property_id": cand.property_id if cand else m.property_id,
            "address": cand.address if cand else "",          # internal only, never rendered
            "zone_id": zone_id, "tier": tier, "score": score_for(**f), "factors": f,
            "reasons": [scrub(r) for r in reasons if r], "caps": caps,
            "verify_next": verify_next(tier, m, cand, dates)}


def run(case: Case, stop_reason: Optional[str] = None) -> dict:
    ring = case.selected_ring()
    zones, cands, matches = (case.load(n) for n in ("zones.json", "candidates.json", "matches.json"))
    # Failed steps from the log; if none were logged but an input is missing or invalid
    # (e.g. an agent run by hand), name that input instead.
    failed = case.failed_steps() or missing_inputs(case, stop_reason)

    leads = []
    if ring and not stop_reason:
        low_only = ("a pipeline step failed (" + ", ".join(failed) + ")") if failed else ""
        leads = build_leads(case, ring, zones, cands, matches, low_only)

    if ring is None or stop_reason == "no_ring":
        status = "no_ring"
    elif stop_reason == "weak_ring":
        status = "weak_ring_zone_only"
    elif failed:
        status = "partial"
    else:
        status = "complete"

    brief = {"case_id": case.case_id, "ring_id": ring.ring_id if ring else None, "status": status,
             "leads": leads, "zones": [z.zone_id for z in zones.zones] if zones else [],
             "failed_steps": failed,
             "decisions": [scrub(f"{d.decision}: {d.message}") for d in case.decisions()],
             "footer": config.FOOTER}
    case.path("summary.html").write_text(render_html(brief, case), encoding="utf-8")
    return brief


# ---- summary page -----------------------------------------------------------------------------

def checked_not_leads(case: Case, lead_ids) -> list[str]:
    """Per zone: how many other candidate buildings were checked and why none became a lead.
    Counts only: these buildings get no name on the page."""
    cands, matches = case.load("candidates.json"), case.load("matches.json")
    if cands is None:
        return []
    by_zone = {mz.zone_id: mz for mz in (matches.zones if matches else [])}
    lines = []
    for cz in cands.zones:
        others = [c for c in cz.candidates if c.property_id not in lead_ids]
        if not others:
            continue
        mz = by_zone.get(cz.zone_id)
        p = {m.property_id: m.P for m in (mz.matches if mz else [])}
        no_ref = sum(not c.has_scan for c in others)
        tried = [p[c.property_id] for c in others if c.property_id in p]
        not_run = len(others) - no_ref - len(tried)
        parts = []
        if tried:
            parts.append(f"{len(tried)} had room photos that did not match (best P {max(tried):.2f})")
        if no_ref:
            parts.append(f"{no_ref} had no reference photos")
        if not_run:
            parts.append(f"{not_run} were not photo-checked")
        lines.append(f"{cz.zone_id}: {len(others)} other buildings checked, none is a lead: "
                     + "; ".join(parts))
    return lines


_env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "ui" / "templates"),
                   autoescape=select_autoescape(["html", "j2"]), trim_blocks=True, lstrip_blocks=True)


def render_html(b: dict, case: Optional[Case] = None) -> str:
    """Summary page. `case` adds the ring card and zones. Shows display_name, never address."""
    ring = case.selected_ring() if case is not None else None
    zones = case.load("zones.json") if case is not None else None
    ring_card = None
    if ring is not None:
        kinds = Counter(k for link in ring.links for k in link.kinds)
        ring_card = {
            "line": f"{len(ring.members)} accounts, R {ring.confidence:.2f}",
            "key_kinds": ring.key_kinds,
            "links": [f"{k}: {n} link{'s' * (n != 1)}" for k, n in kinds.most_common()],
            "recruiters": [{"account": r.account, "reason": scrub(r.reason)} for r in ring.recruiters],
            "photos": len(ring.photos),
        }
    zone_rows = [z.model_dump() for z in zones.zones] if zones else []
    return _env.get_template("summary.html.j2").render(
        b=b, ring=ring_card, zones=zone_rows,
        not_leads=checked_not_leads(case, {l["property_id"] for l in b["leads"]}) if case else [],
        wording="the supervisor LLM" if b.get("text_source") == "llm" else "fixed templates")


# ---- scoring (never part of the pipeline) -----------------------------------------------------

def false_positives(brief: dict, members, answer_key_path) -> dict:
    """SCORING ONLY: buildings at High/Medium that are not the ring's true buildings.

    The ring is matched to an answer-key ring by member overlap. Never called by the pipeline.
    """
    import json
    key = json.loads(Path(answer_key_path).read_text(encoding="utf-8"))
    labels = [k for k in key if k not in ("hard_negatives", "decoy_buildings")]
    best = max(labels, key=lambda k: len(set(members) & set(key[k]["members"])))
    true_ids = {b["property_id"] for b in key[best]["buildings"]}
    hard = {a for ids in key.get("hard_negatives", {}).values() for a in ids}
    wrong = [l for l in brief["leads"] if l["property_id"] not in true_ids]
    return {"ring": best,
            "true_building_rank": next((l["rank"] for l in brief["leads"] if l["property_id"] in true_ids), None),
            "wrong_at_high": sum(l["tier"] == "High" for l in wrong),
            "wrong_at_medium": sum(l["tier"] == "Medium" for l in wrong),
            "hard_negative_accounts_in_ring": sorted(set(members) & hard)}


def _score_cli(argv) -> None:
    import argparse
    import json
    p = argparse.ArgumentParser(prog="dome.agents.briefer --score")
    p.add_argument("--case", required=True)
    p.add_argument("--score", required=True, metavar="ANSWER_KEY")
    a = p.parse_args(argv)
    case = Case(a.case)
    brief, ring = case.load("brief.json"), case.selected_ring()
    if brief is None or ring is None:
        raise SystemExit("run the pipeline first: no valid brief.json or rings.json")
    print(json.dumps(false_positives(brief.model_dump(), ring.members, a.score), indent=2))


if __name__ == "__main__":
    import sys
    if "--score" in sys.argv:
        _score_cli(sys.argv[1:])
    else:
        from . import cli
        cli("briefer", "brief.json", run, [("--stop-reason", {"default": None, "dest": "stop_reason"})])
