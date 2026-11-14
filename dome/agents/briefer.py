"""Briefer (Ishaan): how strong is each lead and why?  -> brief.json + summary.html

STUB with the real tier rules and score so the pipeline produces honest tiers end to end.
Tier rules come first; the score never promotes past a rule.
  High:   P >= 0.6 and W >= 0.6 and R >= 0.6
  Medium: P >= 0.6 when anything else falls short (no window check, W < 0.6, or R < 0.6),
          or 0.4 <= P < 0.6 with W >= 0.6
  Low:    everything else (place clues alone are always Low)
A strong room match is the core evidence, so it never drops below Medium on its own; each
shortfall adds a cap line that says why the lead is not High.
Score = 100 * R * (0.15 Z + 0.10 F + 0.45 P + 0.30 W); with no W, drop it and rescale.

The UI and summary show `display_name`, never `address` (no real address leaves the brief).
"""
from __future__ import annotations

import html
from typing import Optional

from .. import config
from ..case import Case


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


def run(case: Case, stop_reason: Optional[str] = None) -> dict:
    ring = case.selected_ring()
    zones, cands, matches = (case.load(n) for n in ("zones.json", "candidates.json", "matches.json"))
    failed = case.failed_steps()
    leads = []

    if ring and zones and matches and not stop_reason:
        zconf = {z.zone_id: z.confidence for z in zones.zones}
        cinfo = {c.property_id: c for cz in (cands.zones if cands else []) for c in cz.candidates}
        for mz in matches.zones:
            for m in mz.matches:
                if m.P < mz.threshold:
                    continue   # no photo match: not a lead
                c = cinfo.get(m.property_id)
                f = {"R": ring.confidence, "Z": zconf.get(mz.zone_id, 0.0), "F": c.fit if c else 0.0,
                     "P": m.P, "W": m.W}
                tier, caps = tier_for(f["R"], m.P, m.W), caps_for(f["R"], m.P, m.W)
                if failed:
                    tier = "Low"
                    caps.append("capped at Low: a pipeline step failed (" + ", ".join(failed) + ")")
                inl = sum(e.inliers for e in m.evidence)
                reasons = [f"R {f['R']:.2f}: " + (ring.links[0].reason if ring.links else "ring links"),
                           f"P {m.P:.2f}: {len(m.evidence)} photo(s) matched scan {m.scan_id}, "
                           f"{inl} matched points (attempt {mz.attempt})"]
                if m.W is not None:
                    ok = [k for k, v in m.window_checks.items() if v]
                    no = [k for k, v in m.window_checks.items() if not v]
                    reasons.append(f"W {m.W:.2f}: agree: {', '.join(ok) or 'none'}; "
                                   f"not seen: {', '.join(no) or 'none'}")
                leads.append({"property_id": m.property_id, "address": c.address if c else "",
                              "zone_id": mz.zone_id, "tier": tier, "score": score_for(**f),
                              "factors": f, "reasons": reasons, "caps": caps,
                              "verify_next": ["confirm unit layout with the building's current listing",
                                              "a human reviewer compares the match images side by side"]})
        order = {"High": 0, "Medium": 1, "Low": 2}
        leads.sort(key=lambda l: (order[l["tier"]], -l["score"], l["property_id"]))
        for i, l in enumerate(leads, 1):
            l["rank"] = i
            # Ishaan's Briefer may name these by case label ("Building A (synthetic case)")
            l["display_name"] = f"Building {i} in {l['zone_id']} (synthetic case)"

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
             "decisions": [f"{d.decision}: {d.message}" for d in case.decisions()],
             "footer": config.FOOTER}
    case.path("summary.html").write_text(render_html(brief, case), encoding="utf-8")
    return brief


def render_html(b: dict, case: Optional[Case] = None) -> str:
    """Summary page. `case` lets the page show the ring and zones without the caller
    re-reading files. Shows display_name, never address."""
    e = html.escape
    ring = case.selected_ring() if case is not None else None
    ring_line = (f" ({len(ring.members)} accounts, R {ring.confidence:.2f}, "
                 f"keys: {', '.join(ring.key_kinds)})" if ring else "")
    rows = "".join(
        f"<tr><td>{l['rank']}</td><td>{e(l['display_name'])}<br><small>{e(l['property_id'])}</small></td>"
        f"<td>{e(l['zone_id'])}</td><td><b>{l['tier']}</b></td><td>{l['score']}</td>"
        f"<td><ul>{''.join(f'<li>{e(r)}</li>' for r in l['reasons'] + l['caps'])}</ul>"
        f"<small>Verify next: {e('; '.join(l['verify_next']))}</small></td></tr>"
        for l in b["leads"]) or "<tr><td colspan=6>No building leads.</td></tr>"
    dec = "".join(f"<li>{e(d)}</li>" for d in b["decisions"]) or "<li>none</li>"
    return (f"<!doctype html><meta charset=utf-8><title>Dome {e(b['case_id'])}</title>"
            "<body style='font-family:system-ui;max-width:960px;margin:2rem auto'>"
            f"<h1>Dome case {e(b['case_id'])}</h1>"
            f"<p>Ring: {e(str(b['ring_id']))}{e(ring_line)} &middot; status: <b>{e(b['status'])}</b> &middot; "
            f"zones: {e(', '.join(b['zones']) or 'none')}</p>"
            + (f"<p>{e(b['summary'])}</p>" if b.get("summary") else "")
            + f"<p><small>Tiers and scores computed by code; wording by "
            f"{'the supervisor LLM' if b.get('text_source') == 'llm' else 'fixed templates'}.</small></p>"
            "<table border=1 cellpadding=6 style='border-collapse:collapse'>"
            "<tr><th>#</th><th>Building</th><th>Zone</th><th>Tier</th><th>Score</th><th>Why</th></tr>"
            f"{rows}</table><h2>Supervisor decisions</h2><ul>{dec}</ul>"
            f"<p>Failed steps: {e(', '.join(b['failed_steps']) or 'none')}</p>"
            f"<p><i>{e(b['footer'])}</i></p></body>")


if __name__ == "__main__":
    from . import cli
    cli("briefer", "brief.json", run, [("--stop-reason", {"default": None, "dest": "stop_reason"})])
