# Dome: handoff to Yug, checking Avishek's work (Sat night, Nov 14)

Paste this file into Claude Code in your clone of `YT37/Dome`, or just read it. It lists what Avishek's side built, what changed from the plan, what is waiting on you, and the exact commands to check it all. All times are Eastern. **Code freeze 7 AM, submit by 7:30 AM, hard deadline 8 AM Sun.**

**Decision: Arlequin Track 2 (public data only).** The demo runs the Linker with `--no-private`, so no messages and no payments.

---

## 1. Where the code is

| Where | What | State |
|---|---|---|
| `main` | Your `yug` branch (real CoStar, Matterport, Vexcel, geo behind `DOME_STUBS`), Avishek's Gemini vision, Ishaan's mini fix, all of Avishek's v2 work (PR #2) | Merged |
| PR #3, `avishek-topo` | Topological ring scorer, plus the Track 2 fix (see 3.4) | Open, mergeable, **waiting on Avishek's go to merge** |
| PR #4, `claude/project-thread-s8f39o` | Remotion video (only touches `video/`) | Open, mergeable, waiting on the same go |

Until #3 merges, check out `avishek-topo`: it is `main` plus #3. Your `yug` branch has had no new commits since 9:54 AM, and all of it is in `main`.

---

## 2. What Avishek's side built (please check each)

| # | Item | Files | How to check |
|---|---|---|---|
| 1 | Schemas and samples: the contract for every case file. v2 adds `Role`, `Handoff`, `Event`, `LocationHint`, `RoomGroup`, `Message`, `Transaction` and `topo_score`; every new field defaults to empty, so v1 files still validate | `dome/schemas.py`, `samples/` | `pytest tests/test_dome.py -k sample` |
| 2 | Supervisor (deepagents) with guards and a `--scripted` mode. No tool can contact, publish or write | `dome/supervisor.py` | the demo commands in section 5 |
| 3 | Linker: 10 sticky notes, the two-kinds rule (place and merchant never count toward it), down-weighting, layer agreement, Leiden, recruiter flags. With private data on, it also finds wallets, DMs, relay race, heartbeat, echo events and money-shape roles. Switches: `--layers content\|network\|both` and `--no-private` | `dome/agents/linker.py`, `dome/agents/patterns.py` | `python -m dome.eval --data synth --no-private --three-way` |
| 4 | Lister: CoStar types mapped (`COSTAR_TYPE_MAP`), fit score, scanned-only for wide zones. Also a small "near the ring's motel" boost, which only applies with private data | `dome/agents/lister.py` | `case/<id>/candidates.json` |
| 5 | Locator: P from `vision.room_match`, `geo.fix_scan_location` for each match, W from the Gemini window check (W stays empty with a reason if it can't run honestly). Also writes `room_groups` via `vision.photo_groups` | `dome/agents/locator.py` | `case/<id>/matches.json` |
| 6 | Two new supervisor decisions. (a) Private data on but no place in it: Zoner uses logins and leads cap at Medium. (b) Room groups holding photos from accounts outside the ring: the Linker re-runs once with "same room" links | `dome/supervisor.py` | `pytest tests/test_v2.py -k "hints or room"` |
| 7 | Topological ring scorer (for Arlequin): a UniGCN network from TopoModelX. Accounts are nodes, each shared key is a cell holding all its accounts, and echo events are bigger cells. It gives each ring a `topo_score` as a second opinion; the rules still make every link. There are two models, with private data and public-only. It's optional: if TopoX isn't installed, `topo_score` is just empty | `dome/agents/topo.py`, `dome/models/*.pt`, `requirements-topo.txt` | `python -m dome.agents.topo --eval synth --no-private` |
| 8 | Synthetic messages and payments with the patterns planted. Not used in the Track 2 demo | `dome/synth/private_layers.py`, `data/synth/messages.json`, `transactions.json`, `answer_key_private.json` | `pytest tests/test_v2.py` |
| 8b | **Shared keyword** sticky note (public, so it works in Track 2): repeated hashtags, emoji and code words in captions and public comments (`comments.json`, planted by `dome/synth/public_comments.py`). Tags used by 40+ accounts and one-off uses count for nothing | `dome/agents/linker.py` (`keywords`), `dome/config.py` (`CODE_WORDS`, `KEYWORD_*`) | `pytest tests/test_v2.py -k keyword` |
| 9 | The Linker falls back to n-gram text vectors when the MiniLM model can't download (venue Wi-Fi) | `dome/agents/linker.py` | none needed |

**Numbers on synth, Track 2 (public only), with the shared keyword:** Ring A found 12/12 with precision 1.00, and its 3 recruiters now join the ring through shared code words. All 150 hard negatives stay unlinked. At the account level the rules find 1.00 / 0.80 / 1.00 of ring accounts (content / network / both), and the topological model also finds 1.00 (AUC 0.90). On mini Ring C (no code words, never seen in training) the topological model scores every account below 0.5. Say that honestly if asked: it learned the shape of rings that use code words.

---

## 3. Changes from the original plan

1. **One ring, not three.** Avishek focused the demo on Ring A on Saturday morning. Rings B and C and the "expand weak photos and retry" loop were cut from the supervisor. The mini dataset still has B and C for tests.
2. **v2 private layers were built and then parked.** Messages, payments, wallets, DMs, relay race, heartbeat, echo and roles all work, and they are in the code and tests. But Track 2 allows public data only, so the demo leaves them off (`--no-private`).
3. **Topological network added** after Arlequin's founder said he'd like to see their approach. It's a second opinion only: rules make the links, the network adds a score.
4. **Track 2 bug fixed (PR #3):** with `--no-private`, the "no location hints" rule used to cap Ring A at Medium just because the ring had recruiters. Now it only fires when private data is on. A Track 2 run gives **High, 66**.
5. **Ownership:** Avishek owns `vision.photo_cues` and `vision.window_check` (Gemini). You keep CoStar, Matterport, Vexcel, geo, `room_match` and `photo_groups`.
6. **Not built:** the `style` and `route` notes (they're in the schema, but nothing extracts them yet), and the access plan (`detect_exits`, a stretch goal).

---

## 4. Waiting on you (Yug), in priority order

1. **Real `vision.room_match`** (`dome/data_tools/vision.py`). It is still a stub that answers from `samples/scenarios/ring_a/scenario.json`. This is the photo-to-scan match the whole pitch rests on. Keep the signature: `room_match(photo_paths, scan_ids) -> [{scan_id, P, evidence: [{photo, view_id, inliers, match_img}]}]`. If it can't be real by 6 AM, show one hand-checked example live and say the rest is stubbed.
2. **Real-mode end-to-end run** with your keys: `DOME_STUBS=0 python -m dome.supervisor --case real-a --data synth --no-private --scripted`. Check:
   - `costar.properties_in_polygon` returns raw CoStar type words.
   - `geo.fix_scan_location` returns at least the contract keys.
   - `vexcel.oblique_view` returns a real image path, so W can be computed. Without one, the lead caps at Medium and the reason says why.
3. **`vision.photo_groups(photo_paths)`** (photo to photo, same matcher as `room_match`). It's a stub now that groups by `renders.json`. It is optional for Track 2, since it only feeds the room re-run decision.
4. **Ask Arlequin:** is synthetic data OK for a Track 2 entry? Track 2 says public data only. Our accounts and posts are synthetic, styled as public posts; nothing private is used.
5. **Record the backup run** if not done yet (stub mode is fine): the Track 2 command below.

---

## 5. Commands to check everything

```bash
git fetch origin && git switch avishek-topo   # or main once PR #3 is merged
pip install -r requirements.txt
pip install -r requirements-topo.txt          # optional: topological scorer (PyTorch Geometric)

pytest -q                                     # expect 91 passed, 6 skipped

# Track 2 demo (public data only), stub data tools: Ring A's building #1, High, 66
DOME_STUBS=1 python -m dome.supervisor --case t2-a --data synth --no-private --scripted

# Same with the LLM supervisor (needs ANTHROPIC_API_KEY or DOME_MODEL + key in .env)
DOME_STUBS=1 python -m dome.supervisor --case t2-llm --data synth --no-private

# Real data tools (your keys)
DOME_STUBS=0 python -m dome.supervisor --case real-a --data synth --no-private --scripted

# Arlequin numbers (Track 2): precision/recall, hard negatives, recruiters, four-way table
python -m dome.eval --data synth --no-private --three-way

# Topological model on its own
python -m dome.agents.topo --eval synth --no-private

# Decision demo: wide zone + no window photo -> capped at Medium (mini Ring C)
DOME_STUBS=1 python -m dome.supervisor --case t2-c --data mini --seed acct_701 --no-private --scripted
```

Every run writes `case/<id>/`: `rings.json`, `zones.json`, `candidates.json`, `matches.json`, `brief.json`, `summary.html` and `log.jsonl`, where every decision is logged with its evidence.

**Rules still apply:** no keys in git, no street addresses in anything shown, no data tool reads `data/answer_key/`, and numbers come from deterministic code.
