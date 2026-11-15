"""Night eval (Ishaan): money and Spotter against the answer keys.  SCORING ONLY.

    python -m dome.eval_night [--data data/synth] [--key data/answer_key]

The only code (besides dome/eval.py) that reads data/answer_key/. Prints:
  money    wallet precision / recall (addresses in the ring's clusters), role accuracy,
           and which ring accounts the payment-then-post notes tie (precision / recall)
  spotter  precision@10, recall, and how many negatives were flagged
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agents import money, spotter


def money_eval(data: Path, key: Path) -> dict:
    ring = set(json.loads((key / "answer_key.json").read_text())["A"]["members"])
    ck = json.loads((key / "chain_key.json").read_text())
    chain = money.load_chain(data)
    if chain is None:
        return {"status": "no ledger"}
    out = money.analyse(*chain, json.loads((data / "posts.json").read_text()), ring)
    truth = {a: r for r, addrs in ck["clusters"].items() for a in addrs}
    found = {a: c["role"] for c in out["money"]["wallet_clusters"] for a in out["addresses"][c["cluster_id"]]}
    tp = len(set(found) & set(truth))
    roles_right = sum(1 for a, r in found.items() if truth.get(a) == r)
    noted = {n["account"] for n in out["wallet_notes"]["notes"]}
    paid_accts = {p["account"] for p in ck["payment_then_post"]}
    return {
        "wallet_precision": round(tp / len(found), 2) if found else 0.0,
        "wallet_recall": round(tp / len(truth), 2),
        "role_accuracy": round(roles_right / len(found), 2) if found else 0.0,
        "clusters": [f"{c['cluster_id']} {c['role']} ({c['addresses']} addr, conf {c['confidence']})" for c in out["money"]["wallet_clusters"]],
        "notes_precision": round(len(noted & ring) / len(noted), 2) if noted else 0.0,
        "notes_recall": round(len(noted & paid_accts) / len(paid_accts), 2) if paid_accts else 0.0,
        "decoy_addresses_in_clusters": len(set(found) & set(ck["decoys"])),
    }


def spotter_eval(data: Path, key: Path) -> dict:
    sk = json.loads((key / "spotter_key.json").read_text())
    pos = set(sk["positives"])
    neg = {a for ids in sk["negatives"].values() for a in ids}
    q = spotter.from_dataset(data)["queue"]
    flagged = [r["account"] for r in q]
    top = flagged[:10]
    return {
        "flagged": len(flagged),
        "precision_at_10": round(sum(a in pos for a in top) / len(top), 2) if top else 0.0,
        "recall": round(len(pos & set(flagged)) / len(pos), 2),
        "negatives_flagged": len(neg & set(flagged)),
        "negatives_total": len(neg),
    }


def _load(folder: Path, name: str):
    p = folder / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def results(case_dir: Path, data: Path, key: Path) -> list[tuple[str, str, str]]:
    """README rows (area, measure, value) from one real case folder + the evals. Missing -> 'not run'."""
    from .agents.zoner import point_in_zone
    from .synth.common import load_buildings
    ak = json.loads((key / "answer_key.json").read_text())
    truth = ak["A"]
    rows = []
    brief, rings, zones = _load(case_dir, "brief.json"), _load(case_dir, "rings.json"), _load(case_dir, "zones.json")
    ring = None
    if rings and brief:
        ring = next((r for r in rings["rings"] if r["ring_id"] == brief.get("ring_id")), None)
    if ring:
        members, all_ring = set(ring["members"]), set(truth["members"]) | set(truth["recruiters"]) | set(truth["amplifiers"])
        hard = {a for ids in ak["hard_negatives"].values() for a in ids}
        linked = {a for r in rings["rings"] for a in r["members"]}
        recs = {x["account"] for x in ring.get("recruiters", [])} | {x["account"] for x in ring.get("roles", []) if x.get("role") == "recruiter"}
        rows += [("Linker", "ring found (members)", f"{len(members)} accounts, R {ring['confidence']:.2f}"),
                 ("Linker", "precision (ring accounts that are Ring A)", f"{len(members & all_ring) / len(members):.2f}"),
                 ("Linker", "recall (Ring A's 12 posting accounts)", f"{len(members & set(truth['members'])) / len(truth['members']):.2f}"),
                 ("Linker", "recruiters found", f"{len((members | recs) & set(truth['recruiters']))} of {len(truth['recruiters'])}"),
                 ("Linker", "hard negatives linked into any ring", f"{len(linked & hard)} of {len(hard)}"),
                 ("Linker", "data layers", "public + private (messages, payments)" if rings.get("private_layers") else "public only")]
        if ring.get("topo_score") is not None:
            rows.append(("Topological model", "ring topo_score (second opinion)", f"{ring['topo_score']:.2f}"))
    if zones and zones.get("zones"):
        b = {x["label"]: x for x in load_buildings()}
        z = zones["zones"][0]
        inside = [lab for lab in ("A", "D") if lab in b and point_in_zone(z, b[lab]["lat"], b[lab]["lon"])]
        rows.append(("Zoner", "dome", f"{z['area_km2']} km², contains {' and '.join(inside) or 'neither A nor D'}"))
    rm = _load(case_dir, "room_match.json")
    if rm and rm.get("P"):
        scans = {x["label"]: x["scan_id"] for x in load_buildings()}
        order = sorted(rm["P"].items(), key=lambda kv: -kv[1])
        rank = next((i for i, (s, _) in enumerate(order, 1) if s == scans.get("A")), None)
        pa, pd = rm["P"].get(scans.get("A")), rm["P"].get(scans.get("D"))
        rows += [("Locator", "room match P(A)", f"{pa:.2f}" if pa is not None else "not run"),
                 ("Locator", "room match P(D) (decoy)", f"{pd:.2f}" if pd is not None else "not run"),
                 ("Locator", "Building A's rank among scans", f"#{rank} of {len(order)}" if rank else "not ranked"),
                 ("Locator", "coarse shortlist (DINOv2) for full matching", f"{len(rm.get('shortlist', []))} scans")]
    wc = _load(case_dir, "window_check.json")
    if wc:
        scans = {x["label"]: x["scan_id"] for x in load_buildings()}
        w = (wc.get(scans.get("A")) or {}).get("W")
        rows.append(("Locator", "window check W(A)", f"{w:.2f}" if w is not None else "skipped"))
    if brief and brief.get("leads"):
        top = brief["leads"][0]
        f = top["factors"]
        rows.append(("Briefer", "top lead", f"{top['display_name']}: {top['tier']}, score {top['score']}"))
        rows.append(("Briefer", "factors R / Z / F / P / W",
                     " / ".join("–" if f.get(k) is None else f"{f[k]:.2f}" for k in "RZFPW")))
        d_id = next((x["property_id"] for x in load_buildings() if x["label"] == "D"), None)
        d_lead = next((l for l in brief["leads"] if l["property_id"] == d_id), None)
        rows.append(("Briefer", "decoy D", f"{d_lead['tier']} lead" if d_lead else "not a lead"))
    m = money_eval(data, key)
    if "wallet_precision" in m:
        rows += [("Money", "wallet precision / recall (address level)", f"{m['wallet_precision']:.2f} / {m['wallet_recall']:.2f}"),
                 ("Money", "role accuracy (advertiser, collector, aggregator, cash-out)", f"{m['role_accuracy']:.2f}"),
                 ("Money", "decoy addresses in clusters", str(m["decoy_addresses_in_clusters"]))]
    s = spotter_eval(data, key)
    rows += [("Spotter", "precision@10", f"{s['precision_at_10']:.2f}"),
             ("Spotter", "recall / negatives flagged", f"{s['recall']:.2f} / {s['negatives_flagged']} of {s['negatives_total']}")]
    return rows


START, END = "<!-- results:start -->", "<!-- results:end -->"


def table(rows, case_dir: Path) -> str:
    lines = [f"Generated by `python -m dome.eval_night --results <case folder>` from the files of run `{case_dir.name}` and the "
             "evals; nothing typed by hand. All data synthetic.", "",
             "| Step | Measure | Result |", "| --- | --- | --- |"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    return "\n".join(lines)


def write_readme(md: str, readme: Path = Path("README.md")) -> bool:
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        return False
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    readme.write_text(f"{head}{START}\n{md}\n{END}{tail}", encoding="utf-8")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="data/synth")
    ap.add_argument("--key", default="data/answer_key")
    ap.add_argument("--results", metavar="CASE_DIR", help="print the README results table from a real case folder")
    ap.add_argument("--write-readme", action="store_true", help="with --results: fill the table between the README markers")
    a = ap.parse_args()
    data, key = Path(a.data), Path(a.key)
    if a.results:
        md = table(results(Path(a.results), data, key), Path(a.results))
        print(md)
        if a.write_readme:
            print("\nREADME updated" if write_readme(md) else "\nREADME markers not found")
        return
    m, s = money_eval(data, key), spotter_eval(data, key)
    print("money   ", json.dumps({k: v for k, v in m.items() if k != "clusters"}))
    for c in m.get("clusters", []):
        print("         ", c)
    print("spotter ", json.dumps(s))


if __name__ == "__main__":
    main()
