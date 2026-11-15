# Ishaan → Yug: status of my parts, and what to check

Branch: `ishaan` (built on `avishek-topo`, i.e. PR 3 on top of `main`). Everything below is pushed.
Scope is **Ring A + decoy D, Track 2 (public data only)**. All data is synthetic.

## 1. Check it in 5 minutes

```bash
git fetch && git checkout ishaan
pip install -r requirements.txt          # adds flask for the UI
pytest -q                                # expect 98 passed, 7 skipped
python -m dome.ui.app                    # http://127.0.0.1:5000 (on macOS, port 5000 is often AirPlay: use --port 5001)
```

In the page:

1. **Run Case** with "Scripted (no LLM)" ticked → the step strip runs Linker → Briefer, Ring A lights up in
   the graph, the dome is drawn, then one pin: **Building A (synthetic case), High 66**. The first run on a
   fresh machine takes ~1–2 min (the Linker loads its model); later runs are fast.
2. Preset **Ring C** → **Medium 58** and two highlighted decisions: `scanned_buildings_only_wide_zone`
   and `skip_window_check_cap_medium`.
3. Replay without running anything: `http://127.0.0.1:5000/?replay=demo-a` (or `demo-c`), or the
   **Replay…** dropdown. These play from `samples/demo_cases/` if there is no live case folder.
4. Left rail: **Overview, Network, Topology, Map, Evidence, Decisions, Guide** (the guide explains how to
   read every number and colour; each panel's `?` jumps to its section).

What to look for: no street address, no phone number, nothing about private layers anywhere on screen.
`tests/test_ui.py` checks the file whitelist (`/case/<id>/file/../../.env` is refused) and that addresses
never leave the server.

## 2. What I built

| Area | Files | State |
| --- | --- | --- |
| Synthetic data (Ring A + decoy D, 150 hard negatives, 600 background) | `dome/synth/`, `data/synth/`, `data/answer_key/` | done; checker passes; 32 render jobs |
| Zoner (place clues → 1 km grid → 80% cells → zones) | `dome/agents/zoner.py` | done; Ring A's building and D inside the dome on synth and mini |
| Briefer (tiers, score, caps, reasons, verify-next, summary page, false-positive scoring) | `dome/agents/briefer.py`, `dome/ui/templates/summary.html.j2` | done; Track 2 check passes (High 66, no private wording) |
| **Demo UI** (Flask + Leaflet + Cytoscape, dark) | `dome/ui/app.py`, `dome/ui/static/` | new; works live, scripted and in replay |
| Replay backups | `samples/demo_cases/demo-a`, `demo-c` | recorded from scripted Track 2 runs |
| Tests | `tests/test_synth.py`, `test_zoner.py`, `test_briefer.py`, `test_ui.py` | all green |

UI endpoints (all read-only except `/run`, which only starts the supervisor; no contact/dispatch tools, no chat):
`POST /run`, `GET /status`, `/case/<id>/log?since=n`, `/case/<id>/file/<whitelisted>.json`,
`/case/<id>/summary`, `/graph?data=`, `/complex?data=` (the topological view), `/cases`.

## 3. What changed from the plan (and why)

- **Scope cut to Ring A + decoy D** (team decision). Placeholders for A and D are the stub scenario's own
  buildings (`CS-88412` / `mp_4471`, `CS-88107` / `mp_2210`) so the pipeline runs end to end on stubs.
- **Ring A's ads name Downtown** (Downtown, Main Street Square, Market Square Park, Central station), not
  Midtown: the stub's Building A is in Downtown, ~2 km from real Midtown. The mini dataset was changed the
  same way (PR merged), which fixed `test_ring_a_pipeline_on_the_real_linker[mini]`.
- **Unmatched buildings are not leads.** Following `write_brief_text`'s contract, only buildings with a photo
  match are leads; the page shows the rest as per-zone counts ("6 other buildings checked, none is a lead").
- **Map tiles:** CARTO's dark tiles now need an API key, so the map uses Esri's *World Dark Gray Base*
  (no labels), capped at zoom 14 and slightly blurred so no place names are readable.
- **Topology view:** `topo_score` needs `torch` + TopoModelX (`requirements-topo.txt`), not installed on my
  machine. The view still shows the combinatorial complex from the Linker (accounts = rank 0, shared keys =
  rank 1 cells, per-account cell counts heatmap) and shows the model's P / `topo_score` automatically when
  the packages are installed. Keys are never sent to the page, only their kinds.
- **"Public data only" badge** on the summary page and the UI, read from `rings.json` → `private_layers: false`.

## 4. What I'm waiting on

| From | What | Why it matters |
| --- | --- | --- |
| **Yug** | Real rows for **A** and **D** in `dome/synth/buildings.json` (`label, role, unit, property_id, scan_id, lat, lon`); D under 1 km from A; tell me where A is | I regenerate (`python -m dome.synth.generate --out data/synth --seed 37`), move Ring A's place names to A's area if needed, and the answer key updates itself. Photo ids don't change. |
| **Yug** | 32 renders in `data/photos/<photo_id>.jpg` (A: 15 interior + 5 window, D: 12 interior), zipped, not committed | real `room_match`; the job list: see the command in section 6 |
| **Yug** | Real `room_match` + `geo`: A ≥ 0.6, D < 0.4, tight `floor_range` | High on real data; "verify next" uses the floor range |
| **Avishek** | Real `window_check` (needs `vexcel.oblique_view` to return a real image) | without it W is null and A caps at Medium |
| **Avishek** | Merge PR 3 (`avishek-topo`) into `main`, then `ishaan` into `main` | the UI and my changes are on top of PR 3 |
| Whoever runs the demo machine | `pip install -r requirements-topo.txt` if you want the topo model's P in the Topology view | optional |

Still open from earlier (Avishek): the mini dataset's ad text still says "sweet and discreet" / "ask for
Mia/Kay/Lena" (breaks the bland-wording rule), and his Linker finds a 2-account ring `R-2` on synth.

## 5. What's left on my side

1. Swap in your A and D rows, regenerate, re-run the gate and the scoring (≈30 min after I get them).
2. Re-run the UI and the Track 2 check on real `room_match` / `geo` / `window_check` once they land.
3. Record fresh `samples/demo_cases/` from the final data + a screen recording (stage backup).
4. Devpost text and slides (numbers only from the README), then rehearse.

## 6. Commands

```bash
# render jobs (photo id, building, scan, view)
python -c "import json; b={x['scan_id']:x['label'] for x in json.load(open('dome/synth/buildings.json'))}; r=json.load(open('data/synth/renders.json')); [print(k, b[v['scan_id']], v['scan_id'], v['view']) for k,v in r.items() if v['scan_id']]"

# the 4 PM gate and the false-positive count (scoring only reads the answer key)
python -m dome.supervisor --case synth-a --data synth --no-private --scripted
python -m dome.agents.briefer --case synth-a --score data/answer_key/answer_key.json
```

Rules I kept: synthetic only; 555 numbers; no street address or real building name on screen; areas, not
addresses; only a photo match makes a lead; no agent reads `data/answer_key/`; the UI never computes a
tier or score.
