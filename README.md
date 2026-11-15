# Dome

> A dome over the search area that shrinks to one building.

Dome is an investigation tool for trust and safety teams, anti-trafficking NGOs and police
trafficking units. Five agents under one LangChain **deepagents** supervisor take a set of
already-flagged social accounts, find the ring behind them, and narrow its photos down to the
building where they were most likely taken. **Every output is a lead for human verification.**

**All data is synthetic.** No real accounts, people or phone numbers. Nothing is scraped.

The demo follows **one ring (Ring A)**: 12 posting accounts with a shared phone, a reworded
ad script, reposted room photos and three recruiters. Dome links them, draws the area, lists
the buildings inside, matches the photos to one building's scan, and explains a **High** lead.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

**With the AI supervisor.** Copy `.env.example` to `.env` and add a key. The default uses
**Google Gemini** (`GOOGLE_API_KEY` from aistudio.google.com/apikey; the free tier works,
paced to its rate limit):

```bash
python -m dome.supervisor --case demo-a
```

**Without an API key** (rule-based planner, same tools, same guards):

```bash
python -m dome.supervisor --case demo-a --scripted
```

**With the real Linker** on Ishaan's synthetic dataset (`data/synth/`, 784 accounts, 2005
posts) instead of the stub ring. Dome follows the ring that contains Ring A's seed account:

```bash
python -m dome.supervisor --case synth-a --data synth
```

Outputs land in `case/<case_id>/`: `rings.json`, `zones.json`, `candidates.json`,
`matches.json`, `brief.json`, `summary.html` and the audit trail `log.jsonl`.

Switch model in one line in `.env`: `DOME_MODEL=google_genai:gemini-3.5-flash` (default),
`anthropic:claude-sonnet-5-5` or `openai:gpt-5.5` (or pass `--model`).

## Linker on its own (Arlequin solo demo)

Scored against the hidden answer key:

```bash
python -m dome.eval --data synth
python -m dome.agents.linker --case solo --data synth --seed acct_103
```

| Dataset | Precision | Recall | recall@10 | Hard negatives | Recruiters |
|---|---|---|---|---|---|
| `synth` (784 accounts) | 1.00 | 1.00 | 1.00 | 150 accounts, all unlinked | 3 of 3 |
| `mini` (132 accounts, used by tests) | 1.00 | 1.00 | 0.96–1.00 | 23 accounts, all unlinked | 3 of 3 |

The dataset contains more than one ring, and the Linker must keep them apart, so the scores
cover every ring in it; the demo then follows Ring A. Each run also shows a reworded ad that
MinHash missed (Jaccard 0.00) and sentence embeddings caught (cosine 0.77 on `synth`).

The answer key (`data/answer_key/`) is read only by `dome/eval.py`. No agent opens it.

### Shared keyword (public, Track 2)

The same hashtag, emoji or code word (`#tapin`, the rose emoji for "roses" = money) used
again and again in captions and public comments (`comments.json`) is a sticky note (`keyword`,
weight 0.5, content layer). An account must use it at least twice, and a tag used by more than
40 accounts (`#love`, `#houston`) counts for nothing; a single use ("what does #tapin mean")
counts for nothing either. `python -m dome.synth.public_comments --data data/synth --key
data/answer_key/answer_key.json` plants the code words and the decoys. On synth, Track 2: Ring A
plus its 3 recruiters form one ring, the friend group (heavy users of common tags) and the
one-off users stay unlinked, and content-only recall rises to 1.00.

### v2: messages and payments (Arlequin Track 1)

Two more synthetic files, `messages.json` and `transactions.json`, sit next to the accounts
(`python -m dome.synth.private_layers --data data/synth --key data/answer_key/answer_key.json`
plants the patterns; `answer_key_private.json` scores them).

```bash
python -m dome.eval --data synth --three-way              # all layers on (the demo setting)
```

On `synth`, every planted pattern is found: shared wallet and DM links in Ring A, the relay
race (a burned phone moves from one account to the next, then that account's wallet moves on),
the three heartbeat accounts that take turns, 4 of 4 money-shape roles (collector, handler,
hub, recruiter) and echo events that join an ad, the buyer's message, the payment and the ride
inside 90 minutes. Hard negatives (friend group, rental hosts, busy motel, delivery driver)
stay unlinked.

| Layers | Precision | Recall | Hard negatives linked |
|---|---|---|---|
| content only | 1.00 | 1.00 | 0 |
| network only | 0.93 | 1.00 | 7 |
| both (Dome) | 1.00 | 1.00 | 0 |

Network-only with public data alone drops to recall 0.38: the messages and payments are what
make the connectivity layer strong, and the content layer is what keeps it honest.

### Topological ring scorer (Arlequin)

`dome/agents/topo.py` turns the Linker's evidence into a combinatorial complex: accounts are
points, every sticky note shared by 2+ accounts is one cell holding all of them (a phone, a
wallet, a DM thread, a heartbeat pair), and every echo event is a higher-order cell joining the
accounts of an ad, a message, a payment and a ride. A UniGCN hypergraph network (TopoModelX)
passes messages account → cell → account and outputs P(in a ring) per account. Each ring gets
`topo_score` (mean over members) as a second opinion next to the rule-based `confidence`; the
rules still make every link and write every reason.

```bash
pip install -r requirements-topo.txt            # optional; without it topo_score is null
python -m dome.agents.topo --train              # ~10 s on CPU, saves dome/models/topo_unigcn.pt
python -m dome.eval --data synth --three-way    # adds the four-way table
```

Trained only on `mini` Rings A and B (plus 70% of its other accounts). Honest results:

| Test (never seen in training) | Precision | Recall | AUC |
|---|---|---|---|
| mini Ring C + 30% held-out accounts | 1.00 | 0.33 (2 of 6 above 0.5) | 1.00 |
| synth, whole dataset (account level) | 1.00 | 1.00 | 0.90 |

On synth the rule layers find 0.80 (content), 0.80 (network) and 0.93 (both) of ring accounts
at the account level; the topological model also catches the third recruiter. On mini Ring C,
whose evidence looks different from A and B (no shared phone or script), every Ring C account
still ranks above every non-ring account (AUC 1.00), but only 2 of 6 clear 0.5: with this little
training data the model learns the shape of the rings it saw. `DOME_TOPO=0` turns it off.

**Public-only model (kept, not used in the demo):** Arlequin allows any synthetic data, so every
demo runs with messages and payments on. A second model, `dome/models/topo_unigcn_public.pt`, was
trained without messages or payments for the public-only setting; on synth it still finds every
ring account (precision 1.00, recall 1.00, AUC 0.90); on mini Ring C every account still ranks
above every non-ring account (AUC 1.00) but none clears 0.5.

## Connect to LangChain

**LangSmith tracing.** Set these in `.env` and every supervisor step and tool call is traced
(tracing switches itself off when no key is set):

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=dome
```

**LangGraph Studio / server.** `langgraph.json` exposes the supervisor as graph `dome`
(module `dome.supervisor:make_graph`, so the package must be installed):

```bash
pip install -e ".[studio]"
langgraph dev
```

Then open **https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024** (free
LangSmith login), pick the `dome` graph, and send a message such as "Run the pipeline to the
brief." Choose the case in the assistant's configurable settings, e.g.
`{"case_id": "studio-a"}` or `{"case_id": "synth-a", "dataset": "synth", "seed_account": "acct_103"}`.
Outputs land in `case/<case_id>/` as usual.

**In your own code.** The supervisor is a compiled LangGraph graph:

```python
from dome.case import Case
from dome.supervisor import build_agent

case = Case.open("demo-a", scenario="ring_a", reset=True)
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
| 5 | Briefer | `brief.json` + `summary.html` | How strong is the lead and why? |

`dome/supervisor.py` is a `create_deep_agent` supervisor (`deepagents==0.7.38`). Its tools:
`case_status`, `run_linker`, `run_zoner`, `run_lister`, `run_locator`, `run_briefer`,
`write_brief_text`, `log_decision`, plus read-only file tools (`ls`, `read_file`, `glob`,
`grep`) scoped to the case folder. `execute`, `write_file`, `edit_file`, `delete` and the
general-purpose subagent are not registered at all, writes are also denied by permission,
and a harness profile hides them.

The AI picks the next step, logs why, and writes the brief's words. **Numbers come from
deterministic code**: same case folder in, same scores out. Every `run_*` tool hashes its
inputs, validates the output against `dome/schemas.py`, retries once, then marks the step
failed.

**The supervisor is the Briefer's voice.** `run_briefer` computes the tier, score and caps.
The supervisor then calls `write_brief_text` with the plain-language reasons, what a human
should check next, and a case summary. That tool refuses any number not already in the
brief, a missing lead, a street address and any phone number, and never touches a tier or
score. `brief.json` records `text_source: "llm"` (or `"template"` with `--scripted`).

### Safety rules

Enforced in code, so they hold even if the AI forgets. Each writes a `decision` line to
`log.jsonl` with its evidence.

| Condition | Action |
|---|---|
| Ring confidence R < 0.4 | stop after the Zoner; the brief reports the area only |
| Zone is `wide` (city-wide clues) | the Lister keeps only buildings with a scan |
| No scan matches with P ≥ 0.4 | no building lead; the brief says so |
| No window in any photo | skip the window check (W = null), cap the lead at Medium |

Tiers: **High** needs P, W and R all ≥ 0.6. A strong room match (P ≥ 0.6) that falls short
anywhere else is **Medium**, with a cap line saying why. Everything else is **Low**.

## Guardrails

- Dome finds a building that matches the evidence. It does **not** prove anyone is inside.
- Place clues give an area (the dome), never an address. The brief shows a display name.
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
   (place never counts toward the two). One kind alone is a weak hint, never a link.
4. **Layers must agree:** a cluster is a ring only if it has a content key and a connectivity
   key. Leiden splits linked groups of 20+.
5. **Recruiters:** a bio offering modelling or jobs, with most reposts/replies going into the ring.

6. **v2 sticky notes and patterns** (`dome/agents/patterns.py`): shared wallet (0.9), direct
   messages (0.85), same room from the Locator's room groups (0.8), same merchant (0.4, an
   area only, never counts toward the two), heartbeat (0.4: same daily rhythm, never active in
   the same 10 minutes), echo (0.7: two accounts in 2+ events). Relay race and money-shape
   roles are reported, not counted. `--layers content|network|both` and `--no-private`.

Ring confidence R = 1 − Π(1 − w_k) over the kinds the ring shares, capped at 0.95.

**v2 supervisor decisions:** a ring with roles but no place in its messages or payments makes
the Zoner fall back to login data and caps every lead at Medium; room groups holding photos
from accounts outside the ring re-run the Linker once with same-room links (logged with which
members and roles changed). The Lister adds up to +0.15 fit for buildings within 500 m of a
motel or echo place the ring paid; that reorders the list but never lifts a lead past Low.
Tuning lives in `dome/config.py`.

## Status

- **Real:** supervisor, schemas, Linker, Lister, Locator logic, scoring (`dome/eval.py`).
- **Stubs:** `zoner.py` and `briefer.py` (Ishaan; the Briefer stub already applies the tier
  rules), and everything in `dome/data_tools/` (Yug), which answer from Ring A's fixture in
  `samples/scenarios/ring_a/`.
- `data/synth/` is Ishaan's generator output (`python -m dome.synth.generate`);
  `samples/data/mini/` is a smaller hand-built set used by the tests.
  `samples/*.json` is the contract; `dome/schemas.py` wins if they differ.
