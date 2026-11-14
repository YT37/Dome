# Dome

> A dome over the search area that shrinks to one building.

Dome is an investigation tool for trust and safety teams, anti-trafficking NGOs and police
trafficking units. Five agents under one LangChain **deepagents** supervisor turn a set of
already-flagged social accounts into a ranked, explained list of buildings where a ring's
photos were most likely taken. **Every output is a lead for human verification.**

**All data is synthetic.** No real accounts, people or phone numbers. Nothing is scraped.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

No API key needed (rule-based planner, same tools, same guards):

```bash
python -m dome.supervisor --case demo-a --scenario ring_a --scripted
python -m dome.supervisor --case demo-b --scenario ring_b --scripted
python -m dome.supervisor --case demo-c --scenario ring_c --scripted
python -m dome.supervisor --case demo-w --scenario weak_ring --scripted
```

With the **real Linker** on a synthetic dataset (accounts, posts, interactions) instead of the
stub rings. `--seed` picks the ring that contains that account:

```bash
python samples/data/make_mini.py
python -m dome.supervisor --case real-a --scenario ring_a --data mini --scripted
python -m dome.supervisor --case real-c --scenario ring_c --data mini --scripted
```

On Ishaan's full synthetic dataset (`data/synth/`, 784 accounts, 2005 posts):

```bash
python -m dome.supervisor --case synth-a --scenario ring_a --data synth --seed acct_103 --scripted
```

Linker alone, scored against the hidden answer key (the Arlequin solo demo):

```bash
python -m dome.eval --data synth
python -m dome.agents.linker --case solo --data synth --seed acct_103
```

| Dataset | Precision | Recall | recall@10 (A / B / C) | Hard negatives | Recruiters |
|---|---|---|---|---|---|
| `synth` (784 accounts) | 1.00 | 1.00 | 1.00 / 1.00 / 1.00 | 150 accounts, all unlinked | 3 of 3 |
| `mini` (132 accounts) | 1.00 | 1.00 | 0.96 / 1.00 / 1.00 | 23 accounts, all unlinked | 3 of 3 |

Each run also shows a reworded ad that MinHash missed (Jaccard 0.00) and sentence
embeddings caught (cosine 0.77 on `synth`, 0.88 on `mini`).

The answer key (`data/answer_key/`) is read only by `dome/eval.py`. No agent opens it.

With the LLM supervisor (copy `.env.example` to `.env`, set `ANTHROPIC_API_KEY`):

```bash
python -m dome.supervisor --case demo-c --scenario ring_c
```

Outputs land in `case/<case_id>/`: `rings.json`, `zones.json`, `candidates.json`,
`matches.json`, `brief.json`, `summary.html` and the audit trail `log.jsonl`.

Switch model in one line: `DOME_MODEL=openai:gpt-5.5` (or `--model`, or `dome/config.py`).

## Connect to LangChain

**LangSmith tracing.** Set these in `.env` and every supervisor step and tool call is traced:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=dome
```

**LangGraph Studio / server.** `langgraph.json` exposes the supervisor as graph `dome`:

```bash
pip install -e ".[studio]"
langgraph dev
```

Pick a case with configurable `{"case_id": "demo-c", "scenario": "ring_c"}`.

**In your own code.** The supervisor is a compiled LangGraph graph:

```python
from dome.case import Case
from dome.supervisor import build_agent

case = Case.open("demo-c", scenario="ring_c", reset=True)
agent = build_agent(case)                      # create_deep_agent(...) under the hood
for chunk in agent.stream({"messages": [{"role": "user", "content": "Run the pipeline."}]}):
    print(chunk)
```

## Architecture

| # | Agent | Writes | Answers |
|---|---|---|---|
| 1 | Linker | `rings.json` | Which accounts are one ring, and why? |
| 2 | Zoner | `zones.json` | Where is the ring active, as an area? |
| 3 | Lister | `candidates.json` | Which buildings are inside and fit the photos? |
| 4 | Locator | `matches.json` | Which building's room and window view match? |
| 5 | Briefer | `brief.json` + `summary.html` | How strong is each lead and why? |

`dome/supervisor.py` is a `create_deep_agent` supervisor (`deepagents==0.7.38`). Its tools:
`case_status`, `run_linker`, `run_zoner`, `run_lister`, `run_locator`, `run_briefer`,
`log_decision`, plus read-only file tools (`ls`, `read_file`, `glob`, `grep`) scoped to the
case folder. `execute`, file writes and the general-purpose subagent are removed.

The LLM picks the next step and writes reasons. **Numbers come from deterministic code**:
same case folder in, same scores out.

**The supervisor is the Briefer's voice.** `run_briefer` computes every tier, score and cap.
The supervisor then calls `write_brief_text` with each lead's plain-language reasons, what a
human should check next, and a case summary. That tool refuses any number not already in
the brief, any missing or unknown lead, and any phone number, and it never touches a tier
or score. `brief.json` records `text_source: "llm"` (or `"template"` in `--scripted` mode). Every `run_*` tool hashes its inputs, validates the
output against `dome/schemas.py`, retries once, then marks the step failed.

### Decisions that depend on the data

Enforced as guards in code, so they hold even if the LLM forgets. Each writes a `decision`
line to `log.jsonl` with its evidence.

| Condition | Action | Scenario |
|---|---|---|
| Ring confidence R < 0.4 | stop after the Zoner; brief says "weak ring, zone only" | `weak_ring` |
| Zone has `wide: true` | Lister keeps only buildings with a scan | `ring_c` |
| Two or more zones | Lister and Locator once per zone | `ring_b` |
| No scan with P >= 0.4 | pull weak-link photos, re-run Locator once | `ring_c` |
| No window in any photo | skip window check (W = null), cap at Medium | `ring_c` |

```json
{"ts": "2026-11-14T15:02:11Z", "case_id": "demo-c", "actor": "guard", "event": "decision",
 "step": "locator:Z-C1", "decision": "expand_weak_photos_and_retry",
 "evidence": {"zone_id": "Z-C1", "best_P": 0.31, "threshold": 0.4, "attempt": 1},
 "message": "No scan matched above threshold; asking Linker for weak-link photos and searching once more."}
```

## Guardrails

- Dome finds a building that matches the evidence. It does **not** prove anyone is inside.
- Place clues give an area (the dome), never an address.
- A building needs a photo match to beat Low. High needs room **and** window match.
- The supervisor has no tool that contacts, dispatches or publishes anything. It stops at the brief.
- Every query, weight and decision is logged with a timestamp.
- Login and device layers are optional and off in the demo.

## The Linker

1. **Keys per account:** contact (phones, including disguised ones like "five5five 0142",
   @handles, $payment tags), photo (pHash; the photo id until real images exist), text (ad
   templates only, meaning posts with a contact or booking call-to-action: MinHash for copies
   plus `all-MiniLM-L6-v2` embeddings for rewordings), interaction (repeated reposts/replies, or
   amplifying the same post within an hour), place (area, landmark, area code), time
   (same creation day, lockstep posting). The device layer is off.
2. **Inverse-frequency down-weighting:** a key shared by many accounts counts for almost nothing.
3. **Two kinds make a link:** two accounts link only if they share two different kinds of key
   (place never counts toward the two). One kind alone is a weak hint, used later for photo
   expansion.
4. **Layers must agree:** a cluster is a ring only if it has a content key and a connectivity
   key. Leiden splits linked groups of 20+.
5. **Recruiters:** a bio offering modelling or jobs, with most reposts/replies going into the ring.

Ring confidence R = 1 − Π(1 − w_k) over the kinds the ring shares, capped at 0.95.
Tuning lives in `dome/config.py`.

## Status

- **Real:** supervisor, schemas, Linker, Lister, Locator logic, scoring (`dome/eval.py`).
- **Stubs:** `zoner.py` and `briefer.py` (Ishaan; the Briefer stub already applies the real
  tier rules), and everything in `dome/data_tools/` (Yug), which return fixtures from
  `samples/scenarios/`.
- `data/synth/` is Ishaan's generator output (`python -m dome.synth.generate`);
  `samples/data/mini/` is a smaller hand-built set used by the tests.
  `samples/*.json` is the contract; `dome/schemas.py` wins if they differ.
