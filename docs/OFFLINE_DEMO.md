# Dome offline demo

Dome's real run needed Matterport, Vexcel, the CoStar kit, Gemini and LangSmith. Those accesses were
for the hackathon and are being revoked. The offline demo keeps Dome demonstrable after that: one
command, no network, no keys, the same real results (Building A #1, High 59, P 0.68, pin moved 22.8 m,
floor 3, W 0.60) and every "Show the work" step.

## Run it

```bash
scripts/run_demo.sh                 # full demo
scripts/run_demo.sh --imageless     # same story, no CoStar/Matterport/Vexcel imagery
scripts/run_demo.sh --port 5010
```

It checks the bundle's manifest (sha256 of every file), links the bundle's photos and images into the
repository's git-ignored folders, starts the UI and opens `/?replay=real-a`. Set `DOME_BUNDLE` if the
bundle is not at `~/DomeDemoBundle`, and `PY` to choose the Python.

Tests (skip cleanly without a bundle, so the public repository stays green):

```bash
DOME_BUNDLE=~/DomeDemoBundle pytest -q tests/test_offline_demo.py
```

## What is recorded and what is live

| Part | Offline | Labelled |
|---|---|---|
| The whole pipeline (Spotter → Briefer) | **Recomputed** by the same code from the frozen inputs, scripted | the test checks it reproduces the real numbers |
| Room match over 125 scans, geo fix, window check | Replayed from the real run's saved results (scores, detections, Gemini answers) | "recorded from the real run on Nov 15, 2026" |
| "Re-run the room match live" (Locator step) | **Computed live**: DINOv2 retrieval, DISK + LightGlue + RANSAC on 6 bundled scans (A, D and 4 other shortlisted scans), about 50 s on CPU. A wins (P 0.42), D and the others score 0 | "computed live on 6 bundled scans" (smaller index than the full 125-scan search, so P differs) |
| Ask about this case | The question asked during the real run gets its recorded answer; any other question gets "This question wasn't recorded in the offline demo." | "Recorded answer from the real run" |
| LLM supervisor, LangSmith | Not run offline (scripted planner). The public trace link and a JSON export of it are kept | |
| Run Case button | Replays the recorded run, pausing at the report approval like the LangGraph interrupt | |
| Matterport 3D tour | Replaced by the 360° viewer on the bundled cube faces | |
| Base maps | Natural Earth land (public domain, in `dome/ui/static/vendor/`), plus the bundled Vexcel ortho | |

## How offline mode works

`DOME_OFFLINE=1` with `DOME_BUNDLE=<bundle>` (`dome/offline.py`, set up when the `dome` package is
imported):

- `.env` is never read, and every key variable is cleared;
- all cache reads go to `<bundle>/cache`; a request the bundle does not hold raises
  `OfflineMiss("not in offline bundle: ...")` and never falls back to the network;
- Gemini answers come only from the saved responses;
- Hugging Face and Transformers run offline on `<bundle>/models`;
- a socket guard refuses every connection except localhost and logs the call site;
- the UI loads only `dome/ui/static/vendor/` (MapLibre, Cytoscape and fcose, Chart.js, Pannellum,
  Leaflet, Geist fonts, Natural Earth), shows the badge "Offline demo: recorded from the real run on
  Nov 15, 2026", and draws no online tiles.

`DOME_IMAGELESS=1` (with offline mode) serves no CoStar, Matterport or Vexcel imagery and no images
rendered from it: the image routes return 404, the Globe keeps the footprints as vectors, the inside
view becomes the floor-plan outline drawn as lines with the matched sweep marked, and match images
become charts of matched points. Everything synthetic (accounts, posts, money, link chart, topology,
Spotter) is unchanged.

## The bundle, and why it is not in the repository

Built once by `scripts/freeze_demo.py`, outside the repository (default `~/DomeDemoBundle`, about
0.9 GB). It re-runs the real case under `strace` and copies exactly the files that run reads, then:

| Folder | What | Source |
|---|---|---|
| `case/real-a/` | the real run's outputs and its "Show the work" steps, scrubbed | derived |
| `cache/` | the Matterport and Vexcel responses and images the run used, room-match results, geo fit, window detections, saved Gemini answers | Matterport, Vexcel, derived, Gemini |
| `cache/costar_index_v1.sqlite` | the 173 CoStar properties around Ring A's dome: id, type, floors, units, year, lat/lon, scan links, unit number; **no addresses, owners or names** | CoStar |
| `data/` | the 32 rendered ad photos, match images, asset packs for buildings A and D | Matterport and Vexcel derived |
| `live_index/` | the 6-scan room-match index for the live re-run | Matterport derived |
| `derived/` | floor-plan outlines (geometry) for the imageless mode | Matterport derived |
| `models/` | DINOv2-small, all-MiniLM-L6-v2, DISK and LightGlue weights | open models |
| `langsmith/` | JSON export and link of the public Deep Agents trace | derived |

`MANIFEST.json` lists every file with its sha256, size, source, date and a `licensed` flag. Every text
file passes the same scrubbing as `scripts/record_demo_case.py` (address fields blanked, street
addresses removed, phone numbers and wallet strings masked), and the freeze fails if any remains.

**Data rights.** CoStar, Matterport and Vexcel data (imagery, panoramas, floor plans, property
records and images rendered from them) was licensed for the hackathon. The bundle is private: never
commit it, never upload it anywhere public. Keep it only if CoStar agrees; if not, delete
`data/`, `live_index/` and the image files under `cache/`, and use `--imageless` (confirm with CoStar
whether footprint geometry and floor-plan outlines may stay; if not, delete `derived/` as well).

## Rebuild the bundle (if access returns)

With the data keys in `.env` and the real case run once (`case/real-a`):

```bash
python scripts/freeze_demo.py --case real-a --out ~/DomeDemoBundle
python scripts/freeze_demo.py --verify-only --out ~/DomeDemoBundle
```

Then revoke the Matterport token and the Vexcel key again.
