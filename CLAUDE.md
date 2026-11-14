# Dome: Avishek's handoff for Claude Code

Paste this whole file into Claude Code (or save it as `CLAUDE.md` at the repo root). It is self-contained: you do not need the plan doc to do this work. All times are Eastern.

---

## 1. Shared brief (what Dome is)

**Project:** Dome (HackPrinceton, team of 3: Avishek, Ishaan, Yug). **Submit by 8 AM Sunday Nov 15. Hard deadline.**

Dome is an investigation tool for trust and safety teams, anti-trafficking NGOs and police trafficking units. Five agents under one LangChain **deepagents** supervisor turn a set of already-flagged social accounts into a ranked, explained list of buildings where a trafficking ring's photos were most likely taken. Every output is a **lead for human verification**.

Hook: "A dome over the search area that shrinks to one building."

Tracks: Business & Enterprise (main), CoStar "AI for the Built World", LangChain deepagents, Amazon Best Practical AI, Arlequin (Track 1 vs 2 still open; Yug asks Saturday).

### Pipeline (each agent reads and writes JSON in `case/<case_id>/`)

| # | Agent | Owner | Reads | Writes | Answers |
|---|---|---|---|---|---|
| 1 | Linker | Avishek | flagged accounts, posts, interactions | `rings.json` | Which accounts are one ring, and why? |
| 2 | Zoner | Ishaan | `rings.json` + public place clues | `zones.json` | Where is the ring active, as an area? |
| 3 | Lister | Avishek | `zones.json` + ring photos | `candidates.json` | Which buildings are inside and fit the photos? |
| 4 | Locator | Avishek | `candidates.json` + ring photos | `matches.json` | Which building's room and window view match? |
| 5 | Briefer | Ishaan | all four files | `brief.json` + `summary.html` | How strong is each lead and why? |

Every step appends to `case/<case_id>/log.jsonl` (timestamp, tool, input hash, output file, decision, evidence).

### Repo layout

```
dome/schemas.py            (Avishek)  Pydantic models for every JSON file
dome/supervisor.py         (Avishek)  deepagents supervisor
dome/case.py               (Avishek)  case folder helpers: load/save validated JSON, log.jsonl
dome/config.py             (Avishek)  model name + thresholds (one-line model switch)
dome/agents/linker.py, lister.py, locator.py   (Avishek)
dome/agents/zoner.py, briefer.py               (Ishaan; stubs exist so the pipeline runs)
dome/data_tools/costar.py, matterport.py, vexcel.py, geo.py, vision.py  (Yug)
dome/synth/  generator + answer_key.json (Ishaan)      dome/ui/ (Ishaan)
samples/     one sample JSON per file: THE CONTRACT
tests/
```

### Rules (non-negotiable)

- All accounts, posts and people are **synthetic**. Never scrape, never use real people. Photos are rendered from Matterport scans; people are grey silhouettes; phones are 555 numbers.
- **Numbers come from deterministic code.** The LLM plans the next step, writes plain-language reasons and reads photo cues. Same case folder in = same scores out.
- **Supervisor decisions must depend on the data** and be logged with the evidence that triggered them.
- **The supervisor has no tool that contacts, dispatches or publishes anything.** The pipeline stops at the summary. Do not add email, HTTP POST, messaging or shell tools to it.
- Place clues give an **area, never an address**. A building needs a photo match to beat Low. High needs room match and window match.
- Validate every JSON file against `schemas.py` before the next agent starts. A failed validation retries once, then the step is marked failed and the Briefer reports it. **Schema changes go through Avishek.**
- The access plan (`detect_exits`) is stretch: only after the 4 PM Saturday gate.
- Repo must be public and created after 8 PM Fri Nov 13.

---

## 2. Schedule and gates

| When (Sat to Sun) | Avishek | Ishaan | Yug |
|---|---|---|---|
| Sat 3:30 to 6 AM | **`schemas.py` + `samples/`, push first** | data generator design | data_tools stubs returning `samples/` |
| Sat 6 AM to 12 PM | supervisor running all 5 agents on samples; start Linker | accounts, posts, interactions, answer key | CoStar table questions; real costar/matterport/vexcel, cached |
| Sat 12 to 4 PM | Linker done; Lister + Locator on Yug's tools; supervisor decisions | Zoner; Briefer | photo renders by 1 PM; `vision.room_match`; `geo.fix_scan_location` |
| **Sat 4 PM** | **GATE: Ring A end to end to a High lead** | | |
| Sat 4 to 9 PM | Rings B and C; Arlequin solo demo with recall@10 | case summary page, map | geo fix + window check; CoStar solo numbers |
| Sat 9 PM to Sun 2 AM | tune weights; README | UI polish, Devpost, slides | stretch access plan; **record backup run by 2 AM** |
| Sun 2 to 6 AM | fix bugs, rehearse | video, rehearse | fix bugs, rehearse |
| **Sun 7 AM** | **code freeze** | | |
| **Sun 7:30 / 8 AM** | **submit by 7:30, hard deadline 8 AM** | | |
| Sun 9:30 AM to 2:30 PM | judging (2-minute presentations) | | |

If behind at 4 PM, cut in this order: (1) access plan, (2) Zoner DBSCAN (fixed grid instead), (3) live window check and geo fix (show one hand-checked example). Never cut the photo-to-scan match, the Briefer's reasons or the false-positive count.

### What you depend on

| From | What | By |
|---|---|---|
| Yug | data_tools stubs matching `samples/` (signatures in section 5) | Sat 6 AM |
| Yug | CoStar table answers (panoramas downloadable? scans linked to CoStar IDs? polygon queries? Vexcel obliques/outlines/DSM? scan geometry?) | Sat 10 AM |
| Yug | Arlequin answer on entering both tracks | Sat 12 PM |
| Ishaan | synthetic data with the v2 fields (section 6) | Sat 12 PM |
| Yug, to Ishaan | ad-style photo renders + which scan each came from | Sat 1 PM |

Who waits on you: **Yug and Ishaan both need `schemas.py` and `samples/` by 6 AM Sat.**

---

## 3. Your tasks, in order (each with "done when")

### Task 1: `dome/schemas.py` + `samples/` (due Sat 6 AM, push first)

Pydantic v2 models, one top-level model per file, plus `LogEntry` for `log.jsonl`. Section 4 gives the shapes. Put one valid example per file in `samples/` (`rings.json`, `zones.json`, `candidates.json`, `matches.json`, `brief.json`, `log.jsonl`, plus `flagged_accounts.json` as an input example). Add `geo.fix_scan_location` to the data_tools contract (section 5; it is new and you own adding it).

**Done when:** `python -c "from dome.schemas import *"` works; a test loads every file in `samples/` and validates it; pushed and teammates told.

### Task 2: `dome/supervisor.py` (Sat 6 AM to 12 PM, decisions by 4 PM)

A deepagents supervisor (`create_deep_agent`, pinned `deepagents==0.7.38`) whose tools are the five agents plus status and logging tools. Mostly deterministic Python; the LLM picks the next step and writes reasons.

Tools the supervisor gets (and nothing that reaches the outside world):

- `case_status()`: which files exist, whether they validate, the key numbers (R, zones and their `wide` flag, best P per zone, window photo count) as facts.
- `run_linker(expand_weak_photos: bool = False)`, `run_zoner()`, `run_lister(zone_id, scanned_only)`, `run_locator(zone_id)`, `run_briefer(stop_reason=None)`.
- `log_decision(decision, evidence, reason)`: the LLM records why it chose a path.
- Built-in deepagents file tools scoped to the case folder, **read only** (`ls`, `read_file`, `glob`, `grep`). Exclude `execute`; deny writes with `FilesystemPermission`; disable the general-purpose subagent.

Each `run_*` tool: hash inputs, run the agent, validate output against the schema, **retry once** on failure, then mark the step failed; append `tool_call`, `tool_result` and any `step_failed` to `log.jsonl`; return a short JSON summary to the LLM.

**Data-driven decisions** (code enforces them as guards, so they hold even if the LLM forgets; each fires a `decision` log line with its evidence):

| Condition (from the data) | Action |
|---|---|
| Ring confidence R < 0.4 | stop after the Zoner; Briefer reports "weak ring, zone only" |
| Zone has `wide: true` | Lister keeps only buildings with a Matterport scan |
| Two or more zones | run Lister and Locator once per zone |
| Locator: no scan with P ≥ threshold (0.4) | `run_linker(expand_weak_photos=True)` to pull photos from weakly linked accounts, re-run Locator **once** |
| No window in any photo | skip window check (W = null), cap the lead at Medium |

Also: a `--scripted` mode that walks the same tools with a fixed rule-based planner and no LLM (offline demo fallback and tests).

Model: default `anthropic:claude-sonnet-5-5`, set in `dome/config.py` or env `DOME_MODEL` (e.g. `openai:gpt-5.5`). One-line change.

**Done when:** `python -m dome.supervisor --case demo-a --scenario ring_a` runs all five steps on stub data and writes all files; each of the five decisions above fires in at least one test scenario with its log line; one decision is shown live in the demo (Ring C asking for more photos is the LangChain 60-second demo).

### Task 3: Linker, `dome/agents/linker.py` (done by Sat 4 PM)

Connect flagged accounts into rings, with a reason for every link. A ring forms only when the content layer and the connectivity layer agree.

**Step 1: keys per account.**

| Key | Layer | Made from | Weight |
|---|---|---|---|
| contact | content | phone (incl. disguised like "four1five"), handle, payment ID | 0.9 |
| photo | content | perceptual hash (pHash) of each photo | 0.8 |
| device (optional) | lawful | device ID / IP; **off in the Track 2 demo** | 0.7 |
| text | content | ad template, numbers and names stripped: MinHash for copies **plus sentence embeddings for rewordings** | 0.6 |
| interaction | connectivity | repeated reposts/replies between two accounts, or both amplifying the same post within an hour | 0.5 |
| place | content | stated area, landmarks, area code, snapped to a ~1 km cell | 0.3 |
| time | connectivity | creation date and posting windows (batch-created, lockstep posting) | 0.2 |

**Step 2: graph + inverse-frequency down-weighting.** Accounts link to every key they have; interaction edges link accounts directly. A key shared by hundreds of accounts (downtown cell, big account everyone reposts) is scaled by inverse frequency and counts for almost nothing.

**Step 3: link and cluster.** Two accounts link **only if they share at least two different kinds of key**. One kind alone is a weak hint (kept in `weak_hints`, used later for photo expansion), never a link. Leiden (`leidenalg`) splits big linked groups; each cluster is a ring.

**Step 4: recruiter flags.** An account whose bio says "modelling agency" / "job offers" but whose interaction edges mostly run into the ring is flagged as a likely recruiter, with a reason.

**Ring confidence** R = 1 − Π(1 − w_k) over the distinct key kinds the ring shares (after down-weighting), capped at 0.95. Contact + photo + text: 1 − 0.1×0.2×0.4 = 0.99 → 0.95. Place + time alone: 0.44, weak.

**Tools:** regex + LLM for disguised numbers, `imagehash`, `datasketch` (MinHash LSH), `all-MiniLM-L6-v2` + FAISS, `networkx`, `leidenalg`. Rules make the links; the LLM only writes the reasons.

**`expand_weak_photos=True`:** add photos from weak-hint accounts to the ring (`photos[].link_strength = "weak"`), set `photo_expansion_used = true`. Used once by the supervisor's no-match loop.

**If it fails:** no group shares two kinds → return weak hints only; Briefer says "no ring found".

**Done when:** Rings A and B found; hard negatives (rental hosts reusing listing photos, the spa chain with one script, the delivery driver, friend groups) stay unlinked; precision/recall vs `answer_key.json` printed; recall@10 printed (seed one account, rank all others by link strength, share of its true ring in the top 10); one reworded script pair MinHash missed and embeddings caught.

### Task 4: Lister, `dome/agents/lister.py` (Sat 12 to 4 PM)

List CoStar buildings inside a zone and rate how well each fits the ring's photos.

1. `costar.properties_in_polygon(zone.polygon, types)` (Yug clips to polygon if CoStar only does radius/box).
2. A vision model reads the ring photos **once** and lists cues: residential or hotel, apartment or house, rough window-view height, visible building features (stored as `photo_cues`).
3. **fit** = 0.5 (property type matches) + 0.3 (floor count consistent with window height) + 0.2 (other cues).
4. Flag `has_scan` / `scan_id`.
5. If `scanned_only` (wide zone), drop unscanned buildings. Over 50 candidates: keep top 50, scanned first, then by fit.

If no scanned candidates: Briefer can only give Low and says so.

**Done when:** true building is in the list for Ring A; print its rank and how much the list shrank from every building in the zone.

### Task 5: Locator, `dome/agents/locator.py` (Sat 12 to 4 PM, Yug's tools do the heavy lifting)

For scanned candidates in one zone:

1. `vision.room_match(photo_paths, scan_ids)` → P per scan (share of the ring's room groups that match that scan; inlier threshold ~60, Yug tunes).
2. For each scan with P ≥ threshold (0.4 in `config.py`): `geo.fix_scan_location(scan_id, rough_lat, rough_lon)` → true lat/lon, heading, floor range, error estimate.
3. If any photo has a window: `vexcel.oblique_view(...)` via `vision.window_check(window_crop, lat, lon, heading_deg)` → W, checks, floor range. If no window photo: W = null, `window_checked = false`.
4. Write `matches.json` (one entry per zone, upserted), including `attempt` (1, or 2 after photo expansion), `best_P` and `above_threshold`.

**Done when:** Ring A's true building is top-1 with P ≥ 0.6 and W ≥ 0.6 → Briefer says High. This is the **4 PM gate**.

### Task 6: rings B and C (Sat 4 to 9 PM)

- Ring B: clues split over 2 areas, photos from 2 buildings → two zones, two leads (Lister + Locator per zone).
- Ring C: vague city-wide clues, no window photos → wide zone (scanned only), no match first time, expand photos, retry once, W skipped, capped at Medium. This is the live supervisor-decision demo.

### Task 7: Arlequin solo demo (Sat 4 to 9 PM)

Linker (+ Ishaan's Zoner) alone from the command line: ring precision/recall, recall@10, one reworded-script link, one recruiter flag, hard negatives unlinked. Each agent must also run alone from the CLI (`python -m dome.agents.linker --case ...`).

### Task 8: README (Sat 9 PM to Sun 2 AM)

Problem, target user (T&S teams, NGOs, police trafficking units), how to run, what's synthetic, guardrails, the deepagents architecture, decision log example, final tuned weights. Amazon judges read it as documentation.

---

## 4. JSON contract (match `dome/schemas.py`)

The plan's examples, extended so the supervisor can make its decisions. Field names are the contract.

**`rings.json`** (Linker): all rings found among the flagged accounts. A case investigates one ring (`ring_id` in `case/<id>/input.json`, default: highest confidence).

```json
{"case_id": "demo-a",
 "rings": [{"ring_id": "R-A", "members": ["acct_017", "acct_102"], "confidence": 0.91,
   "key_kinds": ["contact", "text", "photo"],
   "links": [{"a": "acct_017", "b": "acct_102", "keys": ["contact:555-0142", "text:tmpl_7"],
              "kinds": ["contact", "text"], "strength": 0.96,
              "reason": "same phone in 14 ads; reworded copy of the same script"}],
   "recruiters": [{"account": "acct_233", "reason": "bio says modelling agency; 31 of 33 reposts go to ring accounts"}],
   "place_keys": ["cell_29.76_-95.37"],
   "photos": [{"photo_id": "img_311", "path": "data/photos/img_311.jpg", "account": "acct_017",
               "link_strength": "core", "has_window": true}],
   "photo_expansion_used": false}],
 "weak_hints": [{"a": "acct_017", "b": "acct_404", "keys": ["place:cell_29.76_-95.37"], "kinds": ["place"],
                 "strength": 0.3, "reason": "same 1 km cell only; one key kind is a hint, not a link"}]}
```

**`zones.json`** (Zoner)

```json
{"case_id": "demo-a", "ring_id": "R-A",
 "zones": [{"zone_id": "Z-A1", "polygon": [[29.761, -95.372], [29.768, -95.361], [29.755, -95.358]],
   "area_km2": 2.4, "weight_share": 0.81, "confidence": 0.74, "wide": false,
   "reasons": ["34 ads name Midtown or a Midtown landmark", "area code 713 fits", "login layer off"]}]}
```

`wide = true` if most clues are city-wide/VPN or area > 25 km².

**`candidates.json`** (Lister): one block per zone.

```json
{"case_id": "demo-a", "ring_id": "R-A",
 "zones": [{"zone_id": "Z-A1", "scanned_only": false, "total_in_zone": 143,
   "photo_cues": {"setting": "apartment", "window_floor_est": [3, 5], "features": ["balcony", "street trees"]},
   "candidates": [{"property_id": "CS-88412", "address": "(from CoStar)", "lat": 29.7612, "lon": -95.3671,
     "type": "multifamily", "floors": 6, "fit": 0.8, "has_scan": true, "scan_id": "mp_4471",
     "fit_reasons": ["multifamily matches apartment photos", "6 floors fits a 3rd to 5th floor view"]}]}]}
```

**`matches.json`** (Locator): one block per zone.

```json
{"case_id": "demo-a", "ring_id": "R-A",
 "zones": [{"zone_id": "Z-A1", "attempt": 1, "threshold": 0.4, "best_P": 0.78, "above_threshold": true,
   "photos_used": 9, "window_photos": 3,
   "matches": [{"property_id": "CS-88412", "scan_id": "mp_4471", "P": 0.78, "W": 0.67,
     "window_checked": true, "floor_range": [3, 5],
     "geo": {"lat": 29.7612, "lon": -95.3671, "heading_deg": 212, "pin_moved_m": 140, "error_estimate_m": 12},
     "evidence": [{"photo": "img_311", "view": "mp_4471/sweep_12/az_135", "inliers": 212}],
     "window_checks": {"road_front": true, "parking_front": true, "building_across": false}}]}]}
```

**`brief.json`** (Briefer, Ishaan)

Tier rules first (the score never promotes past a rule):
- **High:** P ≥ 0.6 and W ≥ 0.6 and R ≥ 0.6
- **Medium:** P ≥ 0.6 with no window check, or 0.4 ≤ P < 0.6 with W ≥ 0.6
- **Low:** everything else; place clues alone are always Low

Score = 100 · R · (0.15 Z + 0.10 F + 0.45 P + 0.30 W); with no W, drop it and rescale the rest to sum to 1. Worked example: R .91, Z .74, F .8, P .78, W .67 → 68, High.

```json
{"case_id": "demo-a", "ring_id": "R-A", "status": "complete",
 "leads": [{"rank": 1, "property_id": "CS-88412", "address": "(from CoStar)", "zone_id": "Z-A1",
   "tier": "High", "score": 68,
   "factors": {"R": 0.91, "Z": 0.74, "F": 0.8, "P": 0.78, "W": 0.67},
   "reasons": ["R 0.91: same phone in 14 ads, reworded script", "P 0.78: 7 of 9 room photos match the unit scan, 212 matched points", "W 0.67: road and parking agree, building across not visible"],
   "caps": [], "verify_next": ["confirm unit layout with the building's current listing"]}],
 "failed_steps": [], "decisions": ["..."],
 "footer": "Leads for human verification. Place clues give areas, not addresses. Not evidence of anyone's presence. Generated from synthetic data."}
```

`status` is one of `complete`, `weak_ring_zone_only`, `no_ring`, `partial`. If any input file is missing, the Briefer still writes a summary, lists `failed_steps` and caps every lead at Low.

**`log.jsonl`**: one `LogEntry` per line:

```json
{"ts": "2026-11-14T15:02:11Z", "case_id": "demo-c", "actor": "guard", "event": "decision", "step": "locator",
 "decision": "expand_weak_photos_and_retry",
 "evidence": {"zone_id": "Z-C1", "best_P": 0.31, "threshold": 0.4, "attempt": 1},
 "message": "No scan matched above threshold; asking Linker for weak-link photos and searching once more."}
```

---

## 5. data_tools contract (Yug implements; keep signatures exact)

Stubs return `samples/` data until real versions land. Cache every API response to disk; save every image a function returns so the Briefer can show it.

```python
# costar.py
properties_in_polygon(polygon: list[tuple[float, float]], types: list[str]) -> list[dict]
    # keys: property_id, address, lat, lon, type, floors, units, year_built, has_scan, scan_id

# matterport.py
sweep_views(scan_id: str) -> list[dict]
    # keys: view_id, image_path, heading_deg (model frame), floor, sweep_id

# vexcel.py
oblique_view(lat: float, lon: float, heading_deg: float) -> str          # image path
building_outlines(lat: float, lon: float, radius_m: float) -> list[dict] # keys: outline, height_m

# geo.py  (NEW: Avishek adds this to the contract)
fix_scan_location(scan_id: str, rough_lat: float, rough_lon: float, radius_m: float = 300) -> dict
    # keys: lat, lon, heading_deg (model to true north), building_id, floor_range, error_estimate_m, evidence

# vision.py
room_match(photo_paths: list[str], scan_ids: list[str]) -> list[dict]
    # keys: scan_id, P (0-1), evidence: [{photo, view_id, inliers, match_img}]
window_check(window_crop: str, lat: float, lon: float, heading_deg: float) -> dict
    # keys: W (0-1), checks: {name: bool}, floor_range: [lo, hi]
detect_exits(scan_id: str) -> list[dict]   # STRETCH
    # keys: kind (exit|stair|door|elevator), x, y, floor, seen (bool)
```

---

## 6. Synthetic data you will receive (Ishaan, by Sat 12 PM)

~800 accounts: Ring A (12 accounts, 90 posts, 3 recruiters, 5 amplifiers; shared script, some reworded; photos from one real scanned building), Ring B (8 accounts, 50 posts, 2 areas, 2 buildings), Ring C (6 accounts, 30 posts, vague clues, no window photos), ~150 hard negatives, ~600 background.

- Account: `handle`, `display_name`, `bio`, `created`, `last_active`, `flags`, optional `logins: [{time, lat, lon, precision_km, vpn}]`
- Post: `text`, `photos`, `phones`, `time`, `stated_area` (may be empty), `area_code`, `landmarks: []`
- Dataset: `interactions: [{from, to, kind (follow|repost|reply), time}]`
- `answer_key.json` maps ring → building, scan, unit. **Hidden from agents; scoring only.**

Until then, code against `samples/` and the stub scenarios in `samples/scenarios/`.

---

## 7. Guardrails (say these in code comments, README and pitch)

- Dome finds a building that matches the evidence. It does **not** prove anyone is inside, and nothing it outputs is a target.
- Place clues → an area (the dome), never a pin from text or logins.
- A building needs a photo match to beat Low; High needs room **and** window match.
- Every lead says "lead for human verification" and what would confirm or rule it out.
- The agent takes no action: no tool to contact, dispatch or publish. Stops at the brief.
- Audit trail: every query, weight and decision logged with a timestamp.
- Data minimisation: people masked first; residents never looked up; CoStar records describe buildings, not tenants.
- Public first, lawful only: login/device layers are optional and off in the demo.
- Synthetic only: first slide and opening line.

---

## 8. Starter code

Claude (in the project thread) is building a runnable starter for Tasks 1 and 2: `dome/schemas.py`, `dome/case.py`, `dome/config.py`, `dome/supervisor.py`, stub agents and data_tools, `samples/` and `samples/scenarios/` (ring_a, ring_b, ring_c, weak_ring), and tests that fire every decision. When it lands, **use it as the base and keep this file's contract consistent with it**; if they differ, `dome/schemas.py` wins.
