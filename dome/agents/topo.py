"""Topological ring scorer (Avishek, for Arlequin): a hypergraph neural network on the
Linker's combinatorial complex.

ELI5: a normal graph only draws lines between TWO accounts. Real coordination happens in
groups: five accounts share one phone; an ad, a message, a payment and a ride are one event.
So we build a shape out of the Linker's evidence:

    rank 0  accounts                       (the points)
    rank 1  each sticky note shared by 2+ accounts: one cell holding all of them
            (a phone, a wallet, a script, a DM thread, a heartbeat pair ...)
    rank 2  each echo event: one cell joining the accounts of an ad, a message, a payment
            and a ride inside 90 minutes

A UniGCN network (TopoModelX) passes messages account -> cell -> account twice and outputs,
for every account, the probability that it belongs to a ring. Per account the input is just
how many cells of each kind it sits in, so the network has to learn from the SHAPE.

Role in Dome: a second opinion next to the rules, never a replacement. The rules make every
link and write every reason (that is what an investigator needs); the topological score is
reported per ring as `topo_score` and in the comparison. Optional: without torch/TopoModelX
or the model file, the Linker runs exactly as before.

Honest evaluation (python -m dome.agents.topo --train):
  trained on mini Rings A and B (+ 70% of mini's other accounts),
  tested on mini Ring C (never seen) + the held-out 30%, and on the whole synth dataset
  (a different generator run, never seen). All synthetic.

    python -m dome.agents.topo --train          # trains, prints held-out scores, saves model
    python -m dome.agents.topo --eval synth     # scores a dataset with the saved model
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from .. import config

MODEL_PATH = config.ROOT / "dome" / "models" / "topo_unigcn.pt"            # Track 1: with messages + payments
MODEL_PATH_PUBLIC = config.ROOT / "dome" / "models" / "topo_unigcn_public.pt"  # Track 2: public data only


def model_path(private: bool = True) -> Path:
    return MODEL_PATH if private else MODEL_PATH_PUBLIC
CELL_KINDS = ("money", "contact", "dm", "room", "photo", "device", "text", "style", "route",
              "echo", "interaction", "heartbeat", "merchant", "place", "time", "echo_event")
HIDDEN, LAYERS, EPOCHS, LR, SEED = 32, 2, 300, 0.01, 0


def available() -> bool:
    try:
        import torch  # noqa: F401
        from topomodelx.nn.hypergraph.unigcn import UniGCN  # noqa: F401
        return True
    except Exception:
        return False


def features(ds: dict, cells: list) -> tuple[list[str], list[list[float]], list[list[int]]]:
    """Nodes, per-node features (log1p count of cells per kind, plus activity), cell members."""
    nodes = sorted(ds["accounts"])
    idx = {a: i for i, a in enumerate(nodes)}
    count = defaultdict(Counter)
    members = []
    for rank, kind, key, accts in cells:
        ids = [idx[a] for a in accts if a in idx]
        if len(ids) >= 2:
            members.append(ids)
            for i in ids:
                count[i][kind] += 1
    posts = Counter(p["account"] for p in ds["posts"])
    sent = Counter(m["from"] for m in ds.get("messages") or [])
    paid = Counter(t["from"] for t in ds.get("transactions") or [])
    X = []
    for i, a in enumerate(nodes):
        row = [math.log1p(count[i][k]) for k in CELL_KINDS]
        row += [math.log1p(posts[a]), math.log1p(sent[a]), math.log1p(paid[a]),
                # kind-agnostic shape: how many different kinds of cell, and how many cells
                float(len(count[i])), math.log1p(sum(count[i].values()))]
        X.append(row)
    return nodes, X, members


class _Net:
    """UniGCN (TopoModelX) + a linear head -> ring probability per account."""

    def __init__(self, n_in: int):
        import torch
        from topomodelx.nn.hypergraph.unigcn import UniGCN
        torch.manual_seed(SEED)
        # aggr_norm: average (not sum) over a cell's accounts, so one huge cell can't swamp
        self.base = UniGCN(in_channels=n_in, hidden_channels=HIDDEN, n_layers=LAYERS, aggr_norm=True)
        # the head sees the account's own counts and what the shape passed to it (residual)
        self.head = torch.nn.Linear(HIDDEN + n_in, 1)
        self.params = list(self.base.parameters()) + list(self.head.parameters())

    def __call__(self, x, inc):
        import torch
        h, _ = self.base(x, inc)
        return torch.sigmoid(self.head(torch.cat([torch.relu(h), x], dim=-1))).squeeze(-1)

    def state(self) -> dict:
        return {"base": self.base.state_dict(), "head": self.head.state_dict()}

    def load(self, st: dict) -> None:
        self.base.load_state_dict(st["base"])
        self.head.load_state_dict(st["head"])


def _scale(X, scale):
    return [[v / s for v, s in zip(row, scale)] for row in X]


def _tensors(X, members, n):
    import torch
    rows, cols = [], []
    for j, ids in enumerate(members):
        for i in ids:
            rows.append(i)
            cols.append(j)
    inc = torch.sparse_coo_tensor(torch.tensor([rows, cols]), torch.ones(len(rows)),
                                  (n, max(1, len(members)))).coalesce()
    return torch.tensor(X, dtype=torch.float32), inc


def predict(ds: dict, cells: list, private: bool = True) -> Optional[dict[str, float]]:
    """{account: P(in a ring)} with the saved model, or None if the model can't run.
    private=False uses the model trained on public data only (Track 2)."""
    path = model_path(private)
    if not available() or not path.exists():
        return None
    import torch
    if not private:   # Track 2: never read message or payment counts
        ds = {**ds, "messages": [], "transactions": []}
    nodes, X, members = features(ds, cells)
    if not members:
        return None
    st = torch.load(path, map_location="cpu", weights_only=False)
    net = _Net(len(X[0]))
    net.load(st["state"])
    X = _scale(X, st["scale"])
    x, inc = _tensors(X, members, len(nodes))
    with torch.no_grad():
        p = net(x, inc).tolist()
    return {a: round(v, 4) for a, v in zip(nodes, p)}


# ------------------------------------------------------------------ training + honest eval
def _truth(name: str) -> tuple[dict, set, set]:
    """Answer key (scoring only): ring name -> accounts, all positives, accounts to ignore."""
    from .linker import resolve_dataset
    d = resolve_dataset(name)
    kf = next(p for p in (d / "answer_key.json", d.parent / "answer_key" / "answer_key.json") if p.exists())
    key = json.loads(kf.read_text(encoding="utf-8"))
    rings = key.get("rings") or {k: v for k, v in key.items() if isinstance(v, dict) and "members" in v}
    per = {n: set(r["members"]) | set(r.get("recruiters", [])) for n, r in rings.items()}
    ignore = {a for r in rings.values() for a in r.get("amplifiers", [])}   # neither in nor out
    return per, set().union(*per.values()), ignore


def _prf(pred: set, pos: set, universe: set) -> dict:
    tp = len(pred & pos & universe)
    p = tp / max(1, len(pred & universe))
    r = tp / max(1, len(pos & universe))
    return {"precision": round(p, 3), "recall": round(r, 3)}


def _auc(prob: dict, pos: set, universe: set) -> float:
    """Chance a random ring account outranks a random non-ring account (1.0 = perfect order)."""
    p = [prob[a] for a in universe if a in pos]
    n = [prob[a] for a in universe if a not in pos]
    if not p or not n:
        return float("nan")
    return round(sum((x > y) + 0.5 * (x == y) for x in p for y in n) / (len(p) * len(n)), 3)


def train(verbose: bool = True, private: bool = True) -> dict:
    import torch
    from .linker import link_accounts, load_dataset
    random.seed(SEED)
    ds = load_dataset("mini")
    if not private:   # Track 2: the model never sees messages or payments
        ds = {**ds, "messages": [], "transactions": []}
    linked = link_accounts(ds, private=private)
    nodes, X, members = features(ds, linked.cells)
    per, pos, ignore = _truth("mini")
    held_ring = per.get("C", set())
    scale = [max(1e-6, max(col)) for col in zip(*X)]
    X = _scale(X, scale)
    rng = random.Random(SEED)
    negatives = [a for a in nodes if a not in pos and a not in ignore]
    rng.shuffle(negatives)
    test_neg = set(negatives[: int(0.3 * len(negatives))])
    train_set = [i for i, a in enumerate(nodes) if a not in held_ring and a not in test_neg and a not in ignore]
    y = torch.tensor([1.0 if a in pos else 0.0 for a in nodes])
    x, inc = _tensors(X, members, len(nodes))
    net = _Net(len(X[0]))
    opt = torch.optim.Adam(net.params, lr=LR, weight_decay=1e-4)
    ti = torch.tensor(train_set)
    w_pos = float((y[ti] == 0).sum() / max(1, (y[ti] == 1).sum()))
    for _ in range(EPOCHS):
        opt.zero_grad()
        p = net(x, inc)[ti].clamp(1e-6, 1 - 1e-6)
        loss = -(w_pos * y[ti] * torch.log(p) + (1 - y[ti]) * torch.log(1 - p)).mean()
        loss.backward()
        opt.step()
    model_path(private).parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state": net.state(), "scale": scale, "features": list(CELL_KINDS) + ["posts", "messages_sent", "payments_sent",
                                                          "distinct_kinds", "cells"],
                "trained_on": "mini rings A+B (+70% of other accounts); held out ring C and 30%",
                "private_layers": private,
                "hidden": HIDDEN, "layers": LAYERS, "epochs": EPOCHS}, model_path(private))
    with torch.no_grad():
        prob = dict(zip(nodes, net(x, inc).tolist()))
    test_u = held_ring | test_neg
    res = {"mini_heldout": {**_prf({a for a in test_u if prob[a] >= 0.5}, pos, test_u),
                            "auc": _auc(prob, pos, test_u)},
           "mini_ring_C_scores": {a: round(prob[a], 3) for a in sorted(held_ring)},
           "mini_ring_C_found": f"{sum(prob[a] >= 0.5 for a in held_ring)}/{len(held_ring)}",
           "synth": evaluate("synth", private=private)}
    if verbose:
        print(json.dumps(res, indent=2))
    return res


def evaluate(name: str, private: bool = True) -> dict:
    """Account-level 'is this account in a ring?' for the four approaches on one dataset."""
    from .linker import link_accounts, load_dataset
    ds = load_dataset(name)
    if not private:
        ds = {**ds, "messages": [], "transactions": []}
    per, pos, ignore = _truth(name)
    universe = set(ds["accounts"]) - ignore
    out = {}
    for layers in ("content", "network", "both"):
        rf = link_accounts(ds, layers=layers, private=private).rings_file
        out[layers] = _prf({m for r in rf["rings"] for m in r["members"]}, pos, universe)
    linked = link_accounts(ds, private=private)
    prob = predict(ds, linked.cells, private=private)
    if prob is not None:
        out["topological"] = {**_prf({a for a, p in prob.items() if p >= 0.5}, pos, universe),
                              "auc": _auc(prob, pos, universe)}
        out["topological"]["ring_scores"] = {r["ring_id"]: r.get("topo_score")
                                             for r in linked.rings_file["rings"]}
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="dome.agents.topo")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--eval", default=None, help="dataset name, e.g. synth")
    ap.add_argument("--no-private", action="store_true", help="Track 2: public data only")
    a = ap.parse_args()
    if a.train:
        train(private=not a.no_private)
    if a.eval:
        print(json.dumps(evaluate(a.eval, private=not a.no_private), indent=2))
