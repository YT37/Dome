"""Case complex (contract F) and the night UniGCN node scorer (Avishek, for Arlequin).

ELI5: every piece of evidence becomes part of one shape.

    rank 0  things          accounts, wallet clusters, rooms (scans), buildings
    rank 1  shared notes    a phone two accounts share, a wallet that paid right before an
                            account posted, a room scan the ring's photos match, the building
                            a scan belongs to ...
    rank 2  events          an ad, a message, a payment and a ride inside 90 minutes
    rank 3  rings           the Linker's rings (output only: never fed to the model)

    python -m dome.complex --case real-a            # writes case/real-a/complex.json
    python -m dome.complex --train                  # trains + evaluates, saves the model
    python -m dome.complex --eval                   # prints the eval block for the README

The model: UniGCN (TopoModelX) passes messages node -> cell -> node over ranks 1 and 2 and
outputs P(part of a ring) for every node, wallets and rooms included. It is trained ONLY on
account labels from the synthetic answer key (train split), so wallet and room scores are
the model's transductive outputs, not something it was taught. A second opinion: the rules
still make every link and write every reason. Where the model and the rules disagree, the
account is listed in `disagreements` for the analyst.

Honest evaluation (--train): fixed seed, labelled accounts split 60 / 20 / 20, the epoch is
picked on validation loss, and only TEST numbers are reported. Ablation retrains per layer
(content / network / money / all). The held-out dataset (data/synth_heldout, the unchanged
generator with seed 101) is never trained on. Everything is synthetic.
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

from . import config
from .case import Case
from .schemas import load_optional

MODEL_PATH = config.ROOT / "dome" / "models" / "complex_unigcn.pt"
EVAL_PATH = config.ROOT / "dome" / "models" / "complex_eval.json"
SUMMARY = config.ROOT / "data" / "matches" / "summary.json"     # Yug's room_match results
HELDOUT = "data/synth_heldout"

NODE_TYPES = ("account", "wallet_cluster", "room", "building")
EXTRA_KINDS = ("payment_then_post", "wallet_note", "wallet_flow", "photo_in_room", "room_in_building")
LAYER_OF = {
    **{k: "content" for k in ("contact", "photo", "text", "device", "room", "style", "keyword", "place")},
    **{k: "network" for k in ("interaction", "time", "dm", "heartbeat", "echo", "route", "echo_event")},
    **{k: "money" for k in ("money", "merchant", "payment_then_post", "wallet_note", "wallet_flow")},
    **{k: "place" for k in ("photo_in_room", "room_in_building")},
}
LAYER_SETS = {"content": {"content"}, "network": {"network"}, "money": {"money"},
              "all": {"content", "network", "money", "place"}}
EPOCHS, EVAL_EVERY, SEED = 300, 10, 0


def _kinds() -> tuple:
    from .agents import topo
    return tuple(topo.CELL_KINDS) + EXTRA_KINDS


# ---------------------------------------------------------------------- masking
_DIGITS = re.compile(r"\+?\d[\d\s\-.()]{5,}\d")


def mask(s: str) -> str:
    """Data minimisation: phone-like digit runs become 555-…42 in ids and reasons."""
    def one(m):
        d = re.sub(r"\D", "", m.group(0))
        return f"{d[:3]}-…{d[-2:]}" if len(d) >= 7 else m.group(0)
    return _DIGITS.sub(one, str(s))


def _mid(raw: str) -> str:
    """Masked but unique cell id."""
    import hashlib
    m = mask(raw)
    return m if m == raw else f"{m}#{hashlib.sha1(raw.encode()).hexdigest()[:4]}"


# ---------------------------------------------------------------------- building the complex
def _photo_owner(ds: Optional[dict], rings: Any) -> dict:
    own = {}
    for p in (ds or {}).get("posts", []):
        for ph in p.get("photos") or []:
            pid = ph.get("photo_id") if isinstance(ph, dict) else ph
            if pid:
                own.setdefault(pid, p["account"])
    for r in (rings.rings if rings else []):
        for ph in r.photos:
            own.setdefault(ph.photo_id, ph.account)
    return own


def _room_results(case: Optional[Case]) -> dict:
    """{scan_id: {"P", "property_id", "photos"}} from the Locator's matches.json, then
    data/matches/summary.json (Yug's real room_match) for scans the case did not cover."""
    out: dict = {}
    m = case.load("matches.json") if case else None
    for z in (m.zones if m else []):
        for x in z.matches:
            out[x.scan_id] = {"P": x.P, "property_id": x.property_id,
                              "photos": sorted({e.photo for e in x.evidence}), "source": "matches.json"}
    if SUMMARY.exists():
        try:
            summ = json.loads(SUMMARY.read_text(encoding="utf-8"))
        except Exception:
            summ = {}
        for scan, s in (summ.items() if isinstance(summ, dict) else []):
            if scan in out or not isinstance(s, dict):
                continue
            out[scan] = {"P": s.get("P"), "property_id": s.get("property_id"),
                         "photos": sorted({str(e.get("photo")) for e in s.get("evidence") or []
                                           if e.get("photo")}), "source": "data/matches/summary.json"}
    return out


def cells_from(linked_cells: list, rings: Any = None, wallet_notes: Any = None,
               rooms: Optional[dict] = None, photo_owner: Optional[dict] = None) -> list[dict]:
    """All cells of ranks 1 and 2 as dicts {rank, kind, id, members, reason}."""
    cells: list[dict] = []
    for rank, kind, key, accts in linked_cells:
        if len(set(accts)) >= 2:
            cells.append({"rank": rank, "kind": kind, "id": _mid(f"c_{key}"), "members": sorted(set(accts)),
                          "reason": mask(f"shared {kind} key {key.split('#')[0]}")})
    # money block (contract B) of every ring: wallet cluster nodes join accounts and each other
    for r in (rings.rings if rings else []):
        mb = r.money
        if mb is None:
            continue
        ptp = defaultdict(int)
        for x in mb.payment_then_post:
            ptp[(x.wallet, x.account)] += 1
        for (w, a), n in sorted(ptp.items()):
            cells.append({"rank": 1, "kind": "payment_then_post", "id": f"c_ptp_{w}_{a}",
                          "members": [w, a], "reason": f"{w} paid the ad platform before {a} posted ({n}x listed)"})
        for f in mb.flows:
            cells.append({"rank": 1, "kind": "wallet_flow", "id": f"c_flow_{f.from_}_{f.to}",
                          "members": [f.from_, f.to], "reason": f"{f.txs} transactions, {f.btc} BTC"})
    for n in (wallet_notes.notes if wallet_notes else []):
        cells.append({"rank": 1, "kind": "wallet_note", "id": f"c_note_{n.cluster_id}_{n.account}",
                      "members": [n.cluster_id, n.account], "reason": mask(n.reason)})
    owner = photo_owner or {}
    for scan, s in sorted((rooms or {}).items()):
        if s.get("P") is None:
            continue
        accts = sorted({owner[p] for p in s["photos"] if p in owner})
        room = f"room_{scan}"
        if accts:
            cells.append({"rank": 1, "kind": "photo_in_room", "id": f"c_room_{scan}",
                          "members": [room] + accts,
                          "reason": f"ring photos match scan {scan} (P {s['P']}, {s['source']})"})
        if s.get("property_id"):
            cells.append({"rank": 1, "kind": "room_in_building", "id": f"c_bld_{scan}",
                          "members": [room, f"bld_{s['property_id']}"],
                          "reason": f"CoStar links scan {scan} to {s['property_id']}"})
    return cells


def node_type(n: str, accounts: set) -> str:
    if n in accounts:
        return "account"
    if n.startswith("room_"):
        return "room"
    if n.startswith("bld_"):
        return "building"
    return "wallet_cluster"


# ---------------------------------------------------------------------- model features
def featurize(ds: dict, cells: list[dict], layers: set) -> tuple[list[str], list[list[float]], list[list[int]]]:
    """Nodes, features and cell membership, keeping only cells (and activity) in `layers`."""
    kinds = _kinds()
    accounts = set(ds["accounts"])
    use = [c for c in cells if LAYER_OF.get(c["kind"], "content") in layers]
    nodes = sorted(accounts | {m for c in use for m in c["members"]})
    idx = {n: i for i, n in enumerate(nodes)}
    count: dict = defaultdict(Counter)
    members = []
    for c in use:
        ids = sorted({idx[m] for m in c["members"] if m in idx})
        if len(ids) >= 2:
            members.append(ids)
            for i in ids:
                count[i][c["kind"]] += 1
    # a node in no cell gets a singleton cell, so UniGCN's mean over cells is defined (no NaN)
    covered = {i for ids in members for i in ids}
    members += [[i] for i in range(len(nodes)) if i not in covered]
    posts = Counter(p["account"] for p in ds["posts"]) if "content" in layers else Counter()
    sent = Counter(m["from"] for m in ds.get("messages") or []) if "network" in layers else Counter()
    paid = Counter(t["from"] for t in ds.get("transactions") or []) if "money" in layers else Counter()
    X = []
    for i, n in enumerate(nodes):
        row = [math.log1p(count[i][k]) for k in kinds]
        row += [math.log1p(posts[n]), math.log1p(sent[n]), math.log1p(paid[n]),
                float(len(count[i])), math.log1p(sum(count[i].values()))]
        t = node_type(n, accounts)
        row += [1.0 if t == x else 0.0 for x in NODE_TYPES]
        X.append(row)
    return nodes, X, members


def _dataset_cells(name: str, private: bool = True) -> tuple[dict, list[dict], dict]:
    from .agents.linker import link_accounts, load_dataset
    ds = load_dataset(name)
    linked = link_accounts(ds, private=private)
    return ds, cells_from(linked.cells), linked.rings_file


def _split(universe: list[str], pos: set, seed: int = SEED) -> tuple[set, set, set]:
    """Stratified 60 / 20 / 20 over labelled accounts, fixed seed."""
    rng = random.Random(seed)
    out = (set(), set(), set())
    for group in (sorted(a for a in universe if a in pos), sorted(a for a in universe if a not in pos)):
        g = list(group)
        rng.shuffle(g)
        n = len(g)
        a, b = int(round(0.6 * n)), int(round(0.8 * n))
        out[0].update(g[:a])
        out[1].update(g[a:b])
        out[2].update(g[b:])
    return out


def _fit(nodes, X, members, y_of: dict, train: set, val: set, select: bool = True):
    """Train UniGCN on `train`, keep the epoch with the best validation AUC."""
    import torch
    from .agents import topo
    torch.manual_seed(SEED)
    scale = [max(1e-6, max(col)) for col in zip(*X)]
    x, inc = topo._tensors(topo._scale(X, scale), members, len(nodes))
    net = topo._Net(len(X[0]))
    opt = torch.optim.Adam(net.params, lr=topo.LR, weight_decay=1e-4)
    ti = torch.tensor([i for i, n in enumerate(nodes) if n in train])
    y = torch.tensor([float(y_of.get(n, 0)) for n in nodes])
    w_pos = float((y[ti] == 0).sum() / max(1, (y[ti] == 1).sum()))
    vi = torch.tensor([i for i, n in enumerate(nodes) if n in val])
    best, best_state, best_auc = float("inf"), None, float("nan")
    for ep in range(1, EPOCHS + 1):
        opt.zero_grad()
        p = net(x, inc)[ti].clamp(1e-6, 1 - 1e-6)
        loss = -(w_pos * y[ti] * torch.log(p) + (1 - y[ti]) * torch.log(1 - p)).mean()
        loss.backward()
        opt.step()
        if ep % EVAL_EVERY == 0:   # model selection: lowest weighted BCE on the validation split
            with torch.no_grad():
                out = net(x, inc)
                pv = out[vi].clamp(1e-6, 1 - 1e-6)
                vloss = float(-(w_pos * y[vi] * torch.log(pv) + (1 - y[vi]) * torch.log(1 - pv)).mean())
            if vloss < best:
                prob = dict(zip(nodes, out.tolist()))
                best, best_auc = vloss, topo._auc(prob, {n for n in val if y_of.get(n)}, val)
                best_state = {k: {n: t.clone() for n, t in v.items()} for k, v in net.state().items()}
    if select and best_state is not None:
        net.load(best_state)
    return net, scale, best_auc


def _probs(net, scale, nodes, X, members) -> dict:
    import torch
    from .agents import topo
    x, inc = topo._tensors(topo._scale(X, scale), members, len(nodes))
    with torch.no_grad():
        return dict(zip(nodes, net(x, inc).tolist()))


def _metrics(prob: dict, pos: set, universe: set, ring: Optional[set] = None) -> dict:
    from .agents import topo
    out = {**topo._prf({a for a in universe if prob.get(a, 0) >= 0.5}, pos, universe),
           "auc": topo._auc(prob, pos, universe), "n": len(universe), "positives": len(pos & universe)}
    if ring:
        out["ring_found"] = f"{sum(prob.get(a, 0) >= 0.5 for a in ring)}/{len(ring)}"
    return out


def train(verbose: bool = True, dataset: str = "synth") -> dict:
    """Train on `dataset`'s train split, report test numbers, ablate by layer, score the
    held-out dataset, save the all-layer model."""
    import torch
    from .agents import topo
    ds, cells, _ = _dataset_cells(dataset)
    per, pos, ignore = topo._truth(dataset)
    universe = sorted(a for a in ds["accounts"] if a not in ignore)
    tr, va, te = _split(universe, pos)
    y_of = {a: int(a in pos) for a in universe}
    res: dict = {"dataset": dataset, "split": {"train": len(tr), "val": len(va), "test": len(te),
                                               "seed": SEED, "test_positives": len(pos & te)},
                 "ablation_test": {}}
    saved = None
    for name, layers in LAYER_SETS.items():
        nodes, X, members = featurize(ds, cells, layers)
        if not members:
            res["ablation_test"][name] = "no cells in this layer"
            continue
        net, scale, val_auc = _fit(nodes, X, members, y_of, tr, va)
        prob = _probs(net, scale, nodes, X, members)
        res["ablation_test"][name] = {**_metrics(prob, pos, te), "val_auc": round(val_auc, 3)}
        if name == "all":
            saved = (net, scale, nodes, X, members, prob)
    net, scale, nodes, X, members, prob = saved
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state": net.state(), "scale": scale, "kinds": list(_kinds()), "node_types": list(NODE_TYPES),
                "trained_on": f"{dataset}: train split (60% of labelled accounts, seed {SEED}); account labels only",
                "epochs_max": EPOCHS,
                "split": {"dataset": dataset, "train": sorted(tr), "val": sorted(va), "test": sorted(te)}},
               MODEL_PATH)
    res["rules_vs_model_test"] = _rules_vs_model(dataset, prob, pos, te)
    res["heldout"] = heldout(net, scale)
    # sensitivity: the same model trained a fixed 300 epochs (topo.py's protocol), no selection
    nodes, X, members = featurize(ds, cells, LAYER_SETS["all"])
    net300, scale300, _ = _fit(nodes, X, members, y_of, tr, va, select=False)
    p300 = _probs(net300, scale300, nodes, X, members)
    res["sensitivity_fixed_300_epochs"] = {"test": _metrics(p300, pos, te),
                                           "heldout": heldout(net300, scale300).get("model")}
    EVAL_PATH.write_text(json.dumps(res, indent=2), encoding="utf-8")
    if verbose:
        print(json.dumps(res, indent=2))
        print(eval_line(res))
    return res


def _rules_vs_model(dataset: str, prob: dict, pos: set, test: set) -> dict:
    from .agents import topo
    from .agents.linker import link_accounts, load_dataset
    rf = link_accounts(load_dataset(dataset)).rings_file
    rules = {m for r in rf["rings"] for m in r["members"]}
    return {"rules_test": topo._prf(rules, pos, test), "model_test": topo._prf(
        {a for a in test if prob.get(a, 0) >= 0.5}, pos, test)}


def heldout(net=None, scale=None) -> dict:
    """Score data/synth_heldout (never trained on). 'not run' if it is missing."""
    from .agents import topo
    from .agents.linker import resolve_dataset
    try:
        resolve_dataset(HELDOUT)
    except FileNotFoundError:
        return {"status": "held-out ring: not run (no data/synth_heldout)"}
    if net is None:
        net, scale = load_model()
        if net is None:
            return {"status": "held-out ring: not run (no model)"}
    ds, cells, rf = _dataset_cells(HELDOUT)
    per, pos, ignore = topo._truth(HELDOUT)
    nodes, X, members = featurize(ds, cells, LAYER_SETS["all"])
    prob = _probs(net, scale, nodes, X, members)
    universe = {a for a in ds["accounts"] if a not in ignore}
    ring = set().union(*per.values())
    rules = {m for r in rf["rings"] for m in r["members"]}
    return {"status": "run", "dataset": HELDOUT + " (generator unchanged, seed 101; never trained on)",
            "model": _metrics(prob, pos, universe, ring),
            "rules": topo._prf(rules, pos, universe)}


def _saved_split() -> Optional[dict]:
    try:
        import torch
        return torch.load(MODEL_PATH, map_location="cpu", weights_only=False).get("split")
    except Exception:
        return None


def load_model():
    if not MODEL_PATH.exists():
        return None, None
    try:
        import torch
        from .agents import topo
        st = torch.load(MODEL_PATH, map_location="cpu", weights_only=False)
        if st.get("kinds") != list(_kinds()):
            return None, None
        net = topo._Net(len(st["scale"]))
        net.load(st["state"])
        return net, st["scale"]
    except Exception:
        return None, None


def eval_line(res: Optional[dict] = None) -> str:
    """One line per row for Ishaan's README table."""
    res = res or (json.loads(EVAL_PATH.read_text()) if EVAL_PATH.exists() else None)
    if not res:
        return "complex eval: not run (python -m dome.complex --train)"
    rows = []
    for name, m in res["ablation_test"].items():
        if isinstance(m, dict):
            rows.append(f"{name}: P {m['precision']} R {m['recall']} AUC {m['auc']}")
        else:
            rows.append(f"{name}: {m}")
    h = res.get("heldout", {})
    hl = (f"held-out ring {h['model'].get('ring_found')} found, P {h['model']['precision']} "
          f"R {h['model']['recall']} AUC {h['model']['auc']} (rules P {h['rules']['precision']} "
          f"R {h['rules']['recall']})") if h.get("status") == "run" else h.get("status", "")
    s300 = res.get("sensitivity_fixed_300_epochs") or {}
    if s300.get("heldout"):
        hl += (f" | fixed 300 epochs: held-out {s300['heldout'].get('ring_found')} found, "
               f"AUC {s300['heldout']['auc']} (unstable across training length: no generalisation claim)")
    s = res["split"]
    return (f"UniGCN complex, {res['dataset']} test split ({s['test']} accounts, {s['test_positives']} ring): "
            + "; ".join(rows) + f" | {hl}")


# ---------------------------------------------------------------------- per case
def build(case: Case) -> dict:
    """Contract F for one case: the ring's neighbourhood of the complex, model scores for its
    nodes, and model-vs-rules disagreements. Writes case/<id>/complex.json."""
    from .agents.linker import link_accounts, load_dataset
    rings = case.load("rings.json")
    ring = case.selected_ring()
    notes = load_optional(case.dir, "wallet_notes.json")
    ds = load_dataset(case.input.dataset) if case.input.dataset else None
    linked = link_accounts(ds, layers=case.input.layers, private=case.input.private_layers) if ds else None
    rooms = _room_results(case)
    cells = cells_from(linked.cells if linked else [], rings, notes, rooms, _photo_owner(ds, rings))
    if not ds and rings:   # stub case: the Linker's links are the shared notes
        for r in rings.rings:
            for l in r.links:
                for k, kd in zip(l.keys, l.kinds):
                    cells.append({"rank": 1, "kind": kd, "id": _mid(f"c_{k}~{l.a}~{l.b}"),
                                  "members": sorted([l.a, l.b]), "reason": mask(l.reason)})
    accounts = set(ds["accounts"]) if ds else {m for r in (rings.rings if rings else []) for m in r.members}
    core = set(ring.members) | {x.account for x in ring.recruiters} if ring else set()
    near = [c for c in cells if set(c["members"]) & core]
    nodes0 = sorted(core | {m for c in near if c["kind"] in EXTRA_KINDS for m in c["members"]})
    keep = set(nodes0)
    ranks: dict = {"0": [{"id": n, "kind": node_type(n, accounts)} for n in nodes0], "1": [], "2": [], "3": []}
    seen = set()
    for c in near:
        mem = [m for m in c["members"] if m in keep]
        if len(mem) >= 2 and c["id"] not in seen:
            seen.add(c["id"])
            ranks[str(c["rank"])].append({"id": c["id"], "kind": c["kind"], "members": mem, "reason": c["reason"]})
    for r in (rings.rings if rings else []):
        wallets = sorted({x.wallet for x in r.money.payment_then_post} if r.money else set())
        ranks["3"].append({"id": r.ring_id, "kind": "ring", "members": sorted(r.members) + wallets,
                           "reason": f"rules: {', '.join(r.key_kinds)} agree (R {r.confidence})"})

    out: dict = {"ranks": ranks, "scores": {}, "model": "UniGCN (TopoModelX)"}
    net, scale = load_model()
    if net is None or ds is None:
        out["model"] += ": not run (" + ("stub case, no dataset" if ds is None else "no trained model") + ")"
    else:
        nodes, X, members = featurize(ds, cells, LAYER_SETS["all"])
        prob = _probs(net, scale, nodes, X, members)
        spot = load_optional(case.dir, "spotter.json")
        queue = [x.account for x in spot.queue] if spot else []
        out["scores"] = {n: round(prob[n], 3) for n in list(nodes0) + queue if n in prob}
        # which split each scored account was in when the model was trained (honesty:
        # train-split scores are in-sample)
        # (read from the model file, never from the answer key)
        sp = _saved_split()
        if sp and sp.get("dataset") == case.input.dataset:
            tr, va, te = (set(sp[k]) for k in ("train", "val", "test"))
            out["score_split"] = {n: ("train" if n in tr else "val" if n in va else "test" if n in te
                                      else "not in training data") for n in out["scores"] if n in accounts}
        rule_members = {m for r in rings.rings for m in r.members} if rings else set()
        dis = [{"id": a, "rules": a in rule_members, "model": round(p, 3),
                "note": "model says ring, rules found no link" if a not in rule_members else
                        "rules link it, model doubts it"}
               for a, p in prob.items() if a in accounts and ((p >= 0.5) != (a in rule_members))]
        out["disagreements"] = sorted(dis, key=lambda d: -abs(d["model"] - 0.5))[:20]
        out["trained_on"] = "account labels of the synth train split only; wallet/room scores are model outputs"
        if EVAL_PATH.exists():
            out["eval"] = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    out["sources"] = {"rooms": sorted({s["source"] for s in rooms.values()}),
                      "money": bool(rings and any(r.money for r in rings.rings)),
                      "wallet_notes": notes is not None}
    from .schemas import ComplexFile
    ComplexFile.model_validate(out)
    case.path("complex.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="dome.complex")
    ap.add_argument("--case", default=None, help="write case/<id>/complex.json")
    ap.add_argument("--train", action="store_true", help="train + evaluate, save the model")
    ap.add_argument("--eval", action="store_true", help="print the saved eval block")
    a = ap.parse_args(argv)
    if a.train:
        train()
    if a.eval:
        print(json.dumps(json.loads(EVAL_PATH.read_text()), indent=2) if EVAL_PATH.exists() else "{}")
        print(eval_line())
    if a.case:
        out = build(Case(a.case))
        print(f"complex.json: rank sizes { {k: len(v) for k, v in out['ranks'].items()} }, "
              f"{len(out['scores'])} scores, {len(out.get('disagreements', []))} disagreements; {out['model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
