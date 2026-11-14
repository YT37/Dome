# Dome: handoff to Yug (from Avishek)

Paste this whole file into Claude Code, or read it on GitHub. It covers what Avishek built
and changed so far, and exactly what your `data_tools` must do. All times are Eastern.

**Branch:** `avishek` on `YT37/Dome`. **PR:** https://github.com/YT37/Dome/pull/1
(`avishek` into `ishaan`; Ishaan's generator and data are merged in, unchanged).

---

## 0. Status report (Saturday morning)

### Work done (Avishek)

| # | Item | State |
|---|---|---|
| 1 | `dome/schemas.py` + `samples/`: Pydantic contract for every case file and `log.jsonl`, one valid sample each | Done, tested |
| 2 | `dome/case.py`: case folder, validated load/save, `log.jsonl`, input hashing, `dataset_dir()` | Done |
| 3 | `dome/supervisor.py`: deepagents `create_deep_agent` supervisor (`deepagents==0.7.38`) with `case_status`, `run_linker/zoner/lister/locator/briefer`, `write_brief_text`, `log_decision` + read-only file tools | Done, tested |
| 4 | Lock-down: `execute`, `write_file`, `edit_file`, `delete` and the general-purpose subagent are **not registered at all**; writes also denied by permission | Done, tested for Gemini and Claude |
| 5 | Every `run_*` step: input hash, schema validation, retry once, then marked failed and reported | Done, tested |
| 6 | Safety rules as code guards with logged evidence: weak ring stops after Zoner, wide zone keeps scanned buildings only, no window caps Medium, no scan match gives no lead | Done, tested on Ring A variants |
| 7 | `--scripted` mode (no AI) using the same tools and guards; also finishes the run if the AI stops early or the API fails | Done, tested |
| 8 | **Real Linker** (`dome/agents/linker.py`): contact/photo/text/interaction/place/time keys, disguised phones, MinHash + sentence embeddings for reworded ads, inverse-frequency down-weighting, two-kinds rule, layer agreement, Leiden, recruiter flags | Done: on `data/synth` precision 1.00, recall 1.00, recall@10 1.00, all 150 hard negatives unlinked, 3/3 recruiters |
| 9 | `dome/eval.py`: Linker scoring vs the answer key (Arlequin solo demo) | Done |
| 10 | Lister (fit = type + floors + cues) and Locator (threshold, geo fix, window check) logic | Done on stubs; waiting on your real tools |
| 11 | Supervisor writes the brief's words via `write_brief_text`; refuses invented numbers, missing leads, phone numbers, street addresses | Done, tested |
| 12 | Briefer stub: tier rules (agreed with Ishaan), cap lines, `display_name`, summary page with ring card | Done (Ishaan replaces it) |
| 13 | Gemini as the default model (free tier works), rate pacing, retries, clear missing-key error, LangSmith auto-off without a key | Done; **one full Gemini run verified** (before the one-ring cut) |
| 14 | `langgraph.json` (graph `dome`), `.env.example`, README, `samples/data/mini` test dataset | Done; LangGraph Studio not yet tried |
| 15 | Tests | **44 passing** |

### Changes from the original plan

1. **Scope cut to one ring (Ring A).** Rings B and C and the weak-ring scenario removed.
2. **Photo-expansion retry loop removed** (it only served Ring C). With no match, the brief
   just says there's no lead. The LangChain demo now shows the AI running each step, logging
   why, and writing the brief, instead of a live "fetch more photos" decision.
3. **Tier rule changed** (agreed with Ishaan): a strong room match (P ≥ 0.6) is Medium,
   not Low, when W < 0.6 or R < 0.6.
4. **The supervisor writes the Briefer's words**; code still computes every tier and score.
5. **Model: Google Gemini** (`gemini-3.5-flash`) instead of Claude, for cost (free tier, $300
   Google credits) and the MLH "Best Use of Gemini API" prize.
6. **Contract additions:** `vision.photo_cues`, `Lead.display_name`, `Brief.summary`,
   `Brief.text_source`, `Brief.zones`, `CaseInput.dataset`, `CaseInput.seed_account`.
   **Removals:** `Ring.photo_expansion_used`, `RingPhoto.link_strength`, `MatchZone.attempt`.
7. **Linker detail:** text keys only come from posts that look like ads (contact or booking
   call-to-action), because Ishaan's templated background chatter otherwise linked
   unrelated accounts. Co-amplifying must happen at least twice.
8. **Repo:** the work lives on branch `avishek`, PR #1 into `ishaan`. There's no `main` yet;
   the team should pick the default branch when merging.

### Waiting on others

| From | What | Needed for |
|---|---|---|
| **Yug** | Real `costar`, `vision.room_match`, `geo.fix_scan_location`, `vision.window_check` (sections 4 and 6) | **4 PM gate** |
| **Yug** | Ad-style photo renders at `data/photos/<photo_id>.jpg` (or `path` in `renders.json`) | Real room match and photo cues |
| **Yug** | `vision.photo_cues`, ideally with Gemini vision | Lister fit, Gemini prize |
| **Yug** | Arlequin track answer; add the Gemini prize to the submission | Submission |
| **Ishaan** | Real Zoner (`run(case)` returning `ZonesFile`, uses `case.dataset_dir()`) | Linker + Zoner solo demo |
| **Ishaan** | Real Briefer with `display_name`, the agreed tier rules, `render_html(brief, case)` | Final brief and summary page |
| **Ishaan / Yug** | Update the answer key's placeholder ids for Ring A's building once real ids exist | Scoring |
| **Team** | Review and merge PR #1; choose the default branch | Everyone building on one base |

### Left on Avishek's end

1. Re-run Ring A with Gemini after the one-ring cut, and attach the $300 Google billing so
   the live demo isn't rate-limited.
2. Add a LangSmith key and check traces; try `langgraph dev` (LangGraph Studio).
3. Wire in Yug's real tools as they land; fix any contract mismatches; re-run the 4 PM gate.
4. Tune weights once real P and W values come in.
5. Finish the README (final weights, a real decision-log example) and help with the pitch.
6. Demo rehearsal; code freeze Sunday 7 AM, submit by 7:30.

---

## 1. What changed since the original plan (details for your tools)

| Change | What it means for you |
|---|---|
| **One ring only: Ring A.** Rings B and C and the weak-ring case are out of scope. | Make your tools work for Ring A's one building. No second building, no city-wide zone. |
| **Photo-expansion retry loop removed.** | `room_match` is called **once per zone**. No "expanded photos" second call. |
| **New tool: `vision.photo_cues(photo_paths)`.** | You own it (it's in `vision.py`). The Lister calls it once. See section 4. |
| **Supervisor runs on Google Gemini** (`gemini-3.5-flash`, set in `.env`). | You need a `GOOGLE_API_KEY` in `.env` to run the AI supervisor. `--scripted` needs no key. |
| **Supervisor writes the brief's words; code keeps every number.** | Your P and W go straight into the score. The AI can't change them. |
| **Tier rule:** a strong room match (P ≥ 0.6) is Medium if W < 0.6, W missing, or R < 0.6. High needs P, W, R all ≥ 0.6. | Your **4 PM gate** is Ring A's building with **P ≥ 0.6 and W ≥ 0.6**. |
| **Schema fields removed:** `Ring.photo_expansion_used`, `RingPhoto.link_strength`, `MatchZone.attempt`. | Don't set or read them; the schema rejects unknown fields. |
| **Schema fields added:** `Lead.display_name`, `Brief.summary`, `Brief.text_source`, `CaseInput.dataset`, `CaseInput.seed_account`. | Mostly Ishaan's side. Never put a street address in anything shown to people. |

`dome/schemas.py` is the contract. If this file and the code disagree, the code wins.

---

## 2. Run it

```powershell
cd D:\Dome                         # or wherever you cloned it
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q          # expect 44 passed
```

```powershell
# no API key: rule-based planner, same tools, same guards
.\.venv\Scripts\python.exe -m dome.supervisor --case demo-a --scripted

# AI supervisor (Gemini): copy .env.example to .env and set GOOGLE_API_KEY first
.\.venv\Scripts\python.exe -m dome.supervisor --case demo-a

# real Linker on Ishaan's dataset instead of the stub ring
.\.venv\Scripts\python.exe -m dome.supervisor --case synth-a --data synth --scripted
```

Expected today (on your stubs): **CS-88412, High, score 68** (stub ring) or **High 71**
(real Linker on `data/synth`). Output lands in `case/<case_id>/` (`summary.html` is the
page to look at, `log.jsonl` is the audit trail). Never commit `.env` (it's git-ignored).

The Gemini free tier allows 5 requests/minute and a small daily cap, so Dome paces itself
(an AI run takes about 4 to 5 minutes). Set `DOME_MAX_RPM=0` in `.env` once billing is on.

---

## 3. How your tools are reached

```
supervisor (Gemini, deepagents)
  -> run_linker  -> rings.json       (real Linker; no data_tools)
  -> run_zoner   -> zones.json       (Ishaan)
  -> run_lister  -> costar.properties_in_polygon, vision.photo_cues  -> candidates.json
  -> run_locator -> vision.room_match, geo.fix_scan_location, vision.window_check -> matches.json
  -> run_briefer -> brief.json + summary.html   (Ishaan; supervisor writes the words)
```

- Stubs live in `dome/data_tools/`. They answer from **Ring A's fixture**,
  `samples/scenarios/ring_a/scenario.json` (generated by `samples/scenarios/make_scenarios.py`),
  through `dome/data_tools/_stub.py`.
- **Replace the stub bodies, keep the signatures and return keys exactly.** The agents index
  these keys directly; a missing key is a crash, and the step is marked failed.
- Every tool output is validated against `dome/schemas.py` before the next agent runs.
  A failed step is retried once, then reported in the brief, and every lead is capped at Low.
- From the handoff: **cache every API response to disk** and **save every image a function
  returns** (match images, obliques), so the brief can show them. `data/photos/`,
  `data/matches/` and `data/vexcel/` are git-ignored for that.

---

## 4. The contract, exactly as the code uses it

### `costar.py`
```python
properties_in_polygon(polygon: list[tuple[float, float]], types: list[str]) -> list[dict]
```
- `polygon` is `[lat, lon]` pairs (lat first). Clip to the polygon yourself if CoStar only
  does radius/box. The stub uses ray casting (`_inside` in `costar.py`), so reuse it.
- `types=[]` means **all types**. The Lister always passes `[]` and uses the full count as
  "buildings in the zone".
- **Keys read:** `property_id`, `address`, `lat`, `lon`, `type`, `floors`, `has_scan`,
  `scan_id`. Also return `units`, `year_built` (contract). Optional `features: list[str]`
  boosts fit when they match the photo cues (e.g. `"balcony"`).
- **`type` must use these words** or fit loses half its score: `multifamily` (apartments),
  `hospitality` (hotels), `single_family` (houses). Anything else (`office`, `retail`) is fine
  as is.
- `has_scan: true` requires a `scan_id` (the schema enforces it).

### `vision.py`
```python
photo_cues(photo_paths: list[str]) -> dict                         # NEW
```
- Read the ring's photos **once**. Return `setting` (`"apartment"`, `"hotel"` or `"house"`),
  `window_floor_est` (`[lo, hi]` floor numbers, or `None` if no window is visible) and
  `features` (short strings, e.g. `["balcony", "street trees"]`).
- **Gemini prize opportunity:** this is the natural place to use Gemini's vision. Same key,
  `google-genai` / `langchain-google-genai` are already installed. Keep the stub as the
  fallback when there's no key or no image file.

```python
room_match(photo_paths: list[str], scan_ids: list[str]) -> list[dict]
```
- One dict per scan id: `scan_id`, `P` (0 to 1: share of the ring's room photos that match
  that scan), `evidence: [{photo, view_id, inliers, match_img}]`.
- **Keys read:** `scan_id`, `P`, and for each evidence item `photo`, `view_id`, `inliers`,
  `match_img` (may be `None`). `photo` is the photo id (e.g. `img_311`); `view_id` like
  `mp_4471/sweep_12/az_135`.
- Threshold is 0.4 (`config.MATCH_THRESHOLD`); geo fix and window check only run on scans at
  or above it. The inlier threshold (~60) is yours to tune.

```python
window_check(window_crop: str, lat: float, lon: float, heading_deg: float) -> dict
```
- **Note:** the Locator currently passes the **whole first window photo's path**, not a crop.
  Crop inside your function, or tell Avishek to change the call.
- Return `W` (0 to 1), `checks: {name: bool}` (e.g. `road_front`, `parking_front`,
  `building_across`) and `floor_range: [lo, hi]` (or `None`).
- **Keys read:** `W`, `checks`, `floor_range`. Call `vexcel.oblique_view(...)` inside it.

```python
detect_exits(scan_id: str) -> list[dict]       # STRETCH, not called by anything; skip it
```

### `geo.py` (added to the contract by Avishek)
```python
fix_scan_location(scan_id: str, rough_lat: float, rough_lon: float, radius_m: float = 300) -> dict
```
- Return `lat`, `lon`, `heading_deg` (model frame to true north), `building_id`,
  `floor_range`, `error_estimate_m`, `evidence`.
- **Keys read:** `lat`, `lon`, `heading_deg`, `error_estimate_m`, `floor_range`.
  The Locator computes how far the pin moved from CoStar's point.
- The stub's `window_check` finds its scan by exact `lat`/`lon` from this function, so if
  you replace one, replace both.

### `vexcel.py`, `matterport.py`
- `oblique_view(lat, lon, heading_deg) -> str` (image path),
  `building_outlines(lat, lon, radius_m) -> list[dict]` (`outline`, `height_m`),
  `sweep_views(scan_id) -> list[dict]` (`view_id`, `image_path`, `heading_deg`, `floor`,
  `sweep_id`).
- No agent calls these directly. Use them inside `room_match`, `window_check` and
  `fix_scan_location`.

---

## 5. Ishaan's data and your renders

- `data/synth/` (784 accounts, 2005 posts) is Ishaan's synthetic dataset. Ring A's posting
  accounts start with `acct_103`; the real Linker finds all 12 of them.
- His posts list **photo ids only** (`photo_ids`). The Linker turns each into the path
  `data/photos/<photo_id>.jpg`, unless `data/synth/renders.json` gives a `path` for it.
  **So put your ad-style renders at `data/photos/<photo_id>.jpg`, or fill in `path` in
  `renders.json`.** That's how `room_match` and `photo_cues` will receive real files.
- `renders.json` also maps photo id to `scan_id` and `view` (`interior` / `window` /
  `other`). `view == "window"` sets `has_window` on the photo, which decides whether the
  window check runs.
- The answer key (`data/answer_key/answer_key.json`) uses placeholder ids for Ring A's
  building (`CS-PLACEHOLDER-A`, `mp_placeholder_a`, unit `4B`). When your real CoStar and
  Matterport ids exist, agree with Ishaan on updating it. **No agent may read the answer key**;
  only `dome/eval.py` does.
- On `--data synth`, the Lister and Locator still answer from the Ring A stub fixture until
  your real CoStar/vision tools land; that's why the synth run still shows CS-88412.

---

## 6. Your checklist

1. **Real `costar.properties_in_polygon`** (cached), returning Ring A's real building inside
   Ring A's zone, with `has_scan` / `scan_id` linked to its Matterport scan.
2. **Real `vision.room_match`** on Ring A's photos against the scanned candidates. Ring A's
   building should come out top with **P ≥ 0.6**.
3. **Real `geo.fix_scan_location`** for that scan.
4. **Real `vision.window_check`** using `vexcel.oblique_view`, with **W ≥ 0.6** for Ring A.
5. **`vision.photo_cues`** (ideally with Gemini vision; see the prize note above).
6. Renders at `data/photos/<photo_id>.jpg` (or `path` in `renders.json`) by 1 PM.
7. **4 PM gate:** `python -m dome.supervisor --case synth-a --data synth --scripted` shows
   Ring A's building ranked #1, **High** (P ≥ 0.6, W ≥ 0.6, R ≥ 0.6). Then run it once
   without `--scripted` (Gemini).
8. **Record the backup demo run by 2 AM** (your item in the original schedule).
9. Run `pytest -q` before you push. The tests use the stub fixture, so keep
   `samples/scenarios/ring_a/scenario.json` working (or update it and the tests together).

If behind at 4 PM, the original cut order still applies minus what's already cut: drop the
live window check and geo fix (show one hand-checked example). **Never cut the photo-to-scan
match.**

---

## 7. Rules (unchanged, non-negotiable)

- Synthetic only. No real people, no scraping, 555 numbers, grey silhouettes.
- Numbers come from deterministic code. Same case folder in, same scores out.
- The supervisor has no tool that contacts, dispatches or publishes anything. Don't add
  HTTP-posting, email, messaging or shell tools to it. (Your tools may call the CoStar,
  Matterport, Vexcel and Gemini APIs to *read* data; that's fine.)
- Place clues give an area, never an address. No street address in the UI or summary;
  leads show a `display_name`.
- A building needs a photo match to beat Low. High needs room **and** window match.
- Schema changes go through Avishek.

---

## 8. What's where

| Path | What | Owner |
|---|---|---|
| `dome/schemas.py` | The JSON contract | Avishek |
| `dome/supervisor.py` | deepagents supervisor, guards, `--scripted`, Gemini wiring | Avishek |
| `dome/agents/linker.py` | Real Linker | Avishek |
| `dome/agents/lister.py`, `locator.py` | Call your tools; compute fit and thresholds | Avishek |
| `dome/agents/zoner.py`, `briefer.py` | Stubs for now (Briefer applies the tier rules) | Ishaan |
| `dome/data_tools/*.py` | **Stubs; yours to make real** | **Yug** |
| `dome/eval.py` | Linker scoring vs the answer key | Avishek |
| `dome/config.py` | Model, thresholds, weights, rate pacing | Avishek |
| `samples/scenarios/ring_a/` | Stub fixture for Ring A | shared |
| `data/synth/`, `dome/synth/` | Synthetic dataset and generator | Ishaan |
| `tests/` | 44 tests | shared |
