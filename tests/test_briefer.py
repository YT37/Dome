import json

import pytest

from dome.agents import briefer
from dome.case import Case
from dome.schemas import Brief


def make_case(tmp_path, P=0.78, W=0.67, R=0.91, with_matches=True, has_scan=True, extra=(),
              extra_matches=()):
    """Hand-built case: the plan's worked example (R 0.91, Z 0.74, F 0.8, P 0.78, W 0.67)."""
    case = Case.open("b", root=tmp_path, reset=True)
    case.save("rings.json", {"case_id": "b", "rings": [{
        "ring_id": "R-A", "members": ["acct_017", "acct_102", "acct_233"], "confidence": R,
        "key_kinds": ["contact", "text"],
        "links": [{"a": "acct_017", "b": "acct_102", "keys": ["contact:555-0142"],
                   "kinds": ["contact", "text"], "strength": 0.9,
                   "reason": "same phone 555-0142 in 14 ads, reworded script"}],
        "recruiters": [{"account": "acct_233", "reason": "bio says modelling agency"}]}]})
    case.save("zones.json", {"case_id": "b", "ring_id": "R-A", "zones": [{
        "zone_id": "Z-A1", "polygon": [[29.74, -95.38], [29.75, -95.38], [29.75, -95.37]],
        "area_km2": 2.4, "weight_share": 0.81, "confidence": 0.74, "wide": False,
        "reasons": ["34 ads name Midtown or a Midtown landmark"]}]})
    cands = [{"property_id": "CS-88412", "address": "123 Real Street", "lat": 29.745, "lon": -95.375,
              "type": "multifamily", "floors": 6, "fit": 0.8, "has_scan": has_scan,
              "scan_id": "mp_4471" if has_scan else None, "fit_reasons": ["multifamily, 6 floors"]}]
    cands += [dict(c) for c in extra]
    case.save("candidates.json", {"case_id": "b", "ring_id": "R-A", "zones": [{
        "zone_id": "Z-A1", "total_in_zone": 40, "photo_cues": {"setting": "apartment"},
        "candidates": cands}]})
    if with_matches:
        m = {"property_id": "CS-88412", "scan_id": "mp_4471", "P": P, "W": W,
             "window_checked": W is not None, "floor_range": [3, 5],
             "evidence": [{"photo": f"img_{i}", "view": f"mp_4471/sweep_{i}/az_0", "inliers": 30}
                          for i in range(7)],
             "window_checks": {"road_front": True, "building_across": False} if W is not None else {}}
        case.save("matches.json", {"case_id": "b", "ring_id": "R-A", "zones": [{
            "zone_id": "Z-A1", "threshold": 0.4, "best_P": P, "above_threshold": P >= 0.4,
            "photos_used": 9, "window_photos": 3 if W is not None else 0,
            "matches": ([m] if has_scan else []) + list(extra_matches)}]})
    return case


def brief_of(case):
    return Brief.model_validate(briefer.run(case)).model_dump()


def test_worked_example_is_68_and_high(tmp_path):
    lead = brief_of(make_case(tmp_path))["leads"][0]
    assert (lead["score"], lead["tier"]) == (68, "High")
    assert lead["display_name"] == "Building A (synthetic case)"
    assert lead["reasons"][1].startswith("P 0.78: 7 of 9 room photos match the unit scan, 210 matched points")
    assert [r.split(" ")[0] for r in lead["reasons"]] == ["R", "P", "W", "Z", "F"]


def test_building_with_no_photo_match_is_not_a_lead(tmp_path):
    from dome.agents.briefer import tier_for
    assert tier_for(0.91, 0.0, None) == "Low"          # the rule, if it were ranked at all
    case = make_case(tmp_path, P=0.0, W=None)
    assert brief_of(case)["leads"] == []
    page = case.path("summary.html").read_text()
    assert "1 had room photos that did not match (best P 0.00)" in page


def test_no_scan_is_not_a_lead_no_reference_photos(tmp_path):
    case = make_case(tmp_path, has_scan=False)
    assert brief_of(case)["leads"] == []
    assert "1 had no reference photos" in case.path("summary.html").read_text()


def test_missing_matches_caps_everything_at_low(tmp_path):
    case = make_case(tmp_path, with_matches=False)
    b = brief_of(case)
    assert b["status"] == "partial"
    assert any(s.startswith("locator (matches.json missing)") for s in b["failed_steps"])
    assert all(l["tier"] == "Low" for l in b["leads"])
    assert "matches.json missing" in case.path("summary.html").read_text()


def test_medium_without_window_check(tmp_path):
    lead = brief_of(make_case(tmp_path, W=None))["leads"][0]
    assert lead["tier"] == "Medium"
    assert lead["caps"] == ["capped at Medium: no window photo, window check skipped"]
    assert lead["score"] == round(100 * 0.91 * (0.15 * 0.74 + 0.10 * 0.8 + 0.45 * 0.78) / 0.70)


def test_ranked_by_tier_then_score(tmp_path):
    other = {"property_id": "CS-90001", "address": "9 Other Ave", "lat": 29.746, "lon": -95.376,
             "type": "office", "floors": 2, "fit": 0.9, "has_scan": True, "scan_id": "mp_9",
             "fit_reasons": []}
    weak = {"property_id": "CS-90001", "scan_id": "mp_9", "P": 0.45, "W": None, "window_checked": False}
    b = brief_of(make_case(tmp_path, extra=[other], extra_matches=[weak]))
    assert [(l["rank"], l["tier"]) for l in b["leads"]] == [(1, "High"), (2, "Low")]
    assert b["leads"][1]["display_name"] == "Building B (synthetic case)"


def test_page_shows_names_never_addresses_or_phones(tmp_path):
    case = make_case(tmp_path)
    b = brief_of(case)
    page = case.path("summary.html").read_text()
    assert "Building A (synthetic case)" in page and "123 Real Street" not in page
    assert "555-0142" not in page and "555-0142" not in json.dumps(b["leads"])
    assert "3 accounts, R 0.91" in page and "acct_233" in page        # ring card + recruiter
    assert "Z-A1" in page and "Midtown" in page                         # zone card
    assert 'href="log.jsonl"' in page
    assert "Public data only" in page                                 # Track 2 badge (no private layers)
    assert "Leads for human verification. Place clues give areas, not addresses." in page


def test_verify_next_is_records_never_entry(tmp_path):
    steps = brief_of(make_case(tmp_path))["leads"][0]["verify_next"]
    assert any("legal process" in s and "floors 3-5" in s for s in steps)
    assert any(s.startswith("Confirms:") for s in steps) and any(s.startswith("Rules out:") for s in steps)
    banned = ("entry", "enter ", "raid", "approach", "door", "access plan", "visit")
    assert not any(w in s.lower() for s in steps for w in banned)


def test_same_case_same_brief(tmp_path):
    case = make_case(tmp_path)
    assert briefer.run(case) == briefer.run(case)


def test_false_positive_count(tmp_path):
    key = {"A": {"members": ["acct_017", "acct_102"], "recruiters": [], "amplifiers": [],
                 "buildings": [{"label": "A", "property_id": "CS-OTHER", "scan_id": "x", "unit": "1"}]},
           "hard_negatives": {"spa_chain": ["acct_233"]}, "decoy_buildings": []}
    path = tmp_path / "key.json"
    path.write_text(json.dumps(key))
    case = make_case(tmp_path)
    fp = briefer.false_positives(brief_of(case), case.selected_ring().members, path)
    assert fp["wrong_at_high"] == 1 and fp["true_building_rank"] is None
    assert fp["hard_negative_accounts_in_ring"] == ["acct_233"]


@pytest.mark.parametrize("i,name", [(1, "A"), (26, "Z"), (27, "AA")])
def test_display_names(i, name):
    assert briefer.display_name(i) == f"Building {name} (synthetic case)"
