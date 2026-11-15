"""Globe flight, link chart and side panels for the demo UI. Everything here sits behind DOME_GLOBE=1.

    DOME_GLOBE=1 python -m dome.ui.app --port 5001      # then open /globe

Read only, like the rest of the UI: it reads files the agents wrote and the committed asset packs.
It computes no tier and no score. "Start case" and "Approve for report" only append a line to
case/<id>/ui_actions.jsonl; nothing is contacted, dispatched or published. Addresses never leave
the server; phone numbers and wallet strings are masked (555-…42, bc1q…7f3a). Synthetic case:
real buildings are demo locations only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, request, send_file, send_from_directory

from .. import config

bp = Blueprint("globe", __name__)

ROOT = Path(config.ROOT)
STATIC = Path(__file__).resolve().parent / "static"
ASSET_ROOTS = ("data/demo_assets", "data/matches")          # the only folders /asset serves
ASSET_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

PHONE_RE = re.compile(r"(?:\(?\d{3}\)?[\s.-]?)?555[\s.-]?\d{4}")
WALLET_RE = re.compile(r"\b(?:bc1|0x|[13])[A-Za-z0-9]{20,}\b")


def enabled() -> bool:
    return os.environ.get("DOME_GLOBE", "") == "1"


def _gate():
    if not enabled():
        abort(404)


# ---------------------------------------------------------------------- masking
def mask_text(s: str) -> str:
    s = PHONE_RE.sub(lambda m: "555-…" + re.sub(r"\D", "", m.group())[-2:], s)
    return WALLET_RE.sub(lambda m: m.group()[:4] + "…" + m.group()[-4:], s)


def scrub(obj):
    """Drop every `address` key and mask phones/wallets in every string, recursively."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k != "address"}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        return mask_text(obj)
    return obj


def _ui():
    from . import app as ui      # late import: app.py imports this module
    return ui


def _case_dir(case_id: str) -> Path:
    return _ui().case_dir(case_id)


def _load(d: Path, name: str):
    p = d / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def asset_url(rel: str | None) -> str | None:
    return f"/asset/{rel}" if rel else None


def load_pack(scan_id: str | None) -> dict | None:
    if not scan_id or not re.match(r"^[A-Za-z0-9_-]{1,64}$", scan_id):
        return None
    p = ROOT / "data" / "demo_assets" / scan_id / "assets.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- pages + assets
@bp.get("/globe")
def globe_page():
    _gate()
    return send_from_directory(STATIC, "globe.html")


@bp.get("/ui-flags")
def ui_flags():
    return jsonify({"globe": enabled()})


@bp.get("/asset/<path:rel>")
def asset(rel):
    """Images under data/demo_assets/ and data/matches/ only. Resolved, then checked: no traversal."""
    _gate()
    if "\x00" in rel or "\\" in rel:
        abort(404)
    target = (ROOT / rel).resolve()
    ok = any(target.is_relative_to((ROOT / r).resolve()) for r in ASSET_ROOTS)
    if not ok or target.suffix.lower() not in ASSET_TYPES or not target.is_file():
        abort(404)
    return send_file(target, mimetype=ASSET_TYPES[target.suffix.lower()], max_age=3600)


# ---------------------------------------------------------------------- flight
@bp.get("/flight")
def flight():
    """Everything the globe flight needs for one case, in one scrubbed payload."""
    _gate()
    d = _case_dir(request.args.get("case", ""))
    zones = _load(d, "zones.json") or {}
    cands = _load(d, "candidates.json") or {}
    matches = _load(d, "matches.json") or {}
    brief = _load(d, "brief.json") or {}
    rings = _load(d, "rings.json") or {}

    best, best_zone = None, None
    for z in matches.get("zones", []):
        for m in z.get("matches", []):
            if best is None or (m.get("P") or 0) > (best.get("P") or 0):
                best, best_zone = m, z
    lead = next((l for l in brief.get("leads", []) if best and l.get("property_id") == best.get("property_id")),
                (brief.get("leads") or [None])[0])

    pins = []
    for z in cands.get("zones", []):
        for c in z.get("candidates", [])[:150]:
            pins.append({"property_id": c.get("property_id"), "zone_id": z.get("zone_id"),
                         "lat": c.get("lat"), "lon": c.get("lon"), "type": c.get("type"),
                         "floors": c.get("floors"), "fit": c.get("fit"), "has_scan": c.get("has_scan"),
                         "top": bool(best and c.get("property_id") == best.get("property_id"))})

    pack = load_pack(best.get("scan_id") if best else None)
    inside = None
    if pack:
        ms = pack.get("matched_sweep") or {}
        faces = ms.get("faces") or []
        inside = {
            "display_name": pack.get("display_name"),
            "costar": pack.get("costar"), "floor": pack.get("floor"), "floor_source": pack.get("floor_source"),
            "footprint": pack.get("footprint_geojson"),
            "rough_pin": pack.get("rough_pin"), "fixed_pin": pack.get("fixed_pin"),
            "ortho": {"img": asset_url((pack.get("ortho") or {}).get("img")),
                      "bounds": (pack.get("ortho") or {}).get("bounds")} if pack.get("ortho") else None,
            "obliques": [{"img": asset_url(o.get("img")), "direction": (o.get("camera") or {}).get("direction"),
                          "capture_date": (o.get("camera") or {}).get("capture_date"),
                          "floor_band": o.get("floor_band")} for o in pack.get("obliques") or []],
            "sweep": {"sweep_id": ms.get("sweep_id"), "heading_deg": ms.get("heading_deg"),
                      "faces": [asset_url(f) for f in faces],          # up, side 1-4, down
                      "floorplan_img": asset_url(ms.get("floorplan_img")), "xy": ms.get("xy")},
            "matches": [{"photo": m.get("photo"), "match_img": asset_url(m.get("match_img")),
                         "inliers": m.get("inliers")} for m in pack.get("matches") or []],
        }
    ring = (rings.get("rings") or [None])[0] or {}
    out = {
        "case": d.name,
        "zones": zones.get("zones", []),
        "candidates": pins,
        "total_in_zone": sum(z.get("total_in_zone") or 0 for z in cands.get("zones", [])),
        "best": best, "best_zone": {k: v for k, v in (best_zone or {}).items() if k != "matches"} or None,
        "lead": lead,
        "ring": {"ring_id": ring.get("ring_id"), "members": len(ring.get("members", [])),
                 "confidence": ring.get("confidence"), "key_kinds": ring.get("key_kinds", [])} if ring else None,
        "inside": inside,
        "footer": brief.get("footer"),
    }
    return jsonify(scrub(out))


# ---------------------------------------------------------------------- link chart
KIND_TYPE = {"contact": "phone", "phone": "phone", "text": "script", "keyword": "script", "script": "script",
             "photo": "photo", "room": "room", "building": "building", "account": "account",
             "wallet": "wallet_cluster", "wallet_cluster": "wallet_cluster", "service": "service",
             "payment": "wallet_cluster"}
KIND_LAYER = {"contact": "content", "phone": "content", "text": "content", "keyword": "content",
              "script": "content", "photo": "content", "interaction": "network", "time": "network",
              "account": "network", "place": "place", "room": "place", "building": "place",
              "wallet": "money", "wallet_cluster": "money", "service": "money", "payment": "money"}


def _short(key: str) -> str:
    kind, _, val = key.partition(":")
    if kind == "contact":
        return mask_text(val) if PHONE_RE.search(val) else val[:3] + "…" + val[-2:]
    if kind == "photo":
        return "photo " + val.replace("phash_", "")[:6]
    if kind == "text":
        return "script " + val.replace("tmpl_", "#")
    return mask_text(val)[:24]


def graph_from_complex(cx: dict) -> dict:
    """Contract F: ranks {"0": [cells], ...}; rank 0 cells are nodes, higher cells join their members."""
    scores, reasons = cx.get("scores") or {}, cx.get("reasons") or {}
    nodes, edges = {}, []
    ranks = cx.get("ranks") or {}
    for cell in ranks.get("0", []):
        cid = cell.get("id")
        kind = cell.get("kind", "account")
        nodes[cid] = {"id": cid, "type": KIND_TYPE.get(kind, "account"), "label": cell.get("masked_label") or cid,
                      "role": cell.get("role") or "member", "layer": KIND_LAYER.get(kind, "network"),
                      "score": scores.get(cid), "reason": cell.get("reason") or reasons.get(cid)}
    for r in sorted(k for k in ranks if k != "0"):
        for cell in ranks[r]:
            kind = cell.get("kind", "")
            layer = KIND_LAYER.get(kind, "content")
            members = [m for m in cell.get("members", []) if m in nodes]
            reason = cell.get("reason") or reasons.get(cell.get("id"), "")
            if len(members) == 2 and r == "1":
                edges.append({"source": members[0], "target": members[1], "type": kind, "layer": layer,
                              "reason": reason})
                continue
            cid = cell.get("id")
            nodes[cid] = {"id": cid, "type": KIND_TYPE.get(kind, "script"),
                          "label": cell.get("masked_label") or kind, "role": f"rank {r} cell", "layer": layer,
                          "score": scores.get(cid), "reason": reason}
            edges += [{"source": m, "target": cid, "type": kind, "layer": layer, "reason": reason} for m in members]
    return {"source": "complex.json", "nodes": list(nodes.values()), "edges": edges}


def graph_from_rings(rings: dict, matches: dict | None, brief: dict | None) -> dict:
    nodes, edges, seen = {}, [], set()

    def node(nid, **kw):
        nodes.setdefault(nid, {"id": nid, "role": None, "score": None, "reason": None, **kw})

    def edge(a, b, typ, layer, reason):
        k = (a, b, typ)
        if k not in seen:
            seen.add(k)
            edges.append({"source": a, "target": b, "type": typ, "layer": layer, "reason": reason})

    for ring in rings.get("rings", []):
        roles = {r["account"]: r for r in ring.get("roles", []) + ring.get("recruiters", [])}
        for a in ring.get("members", []):
            role = roles.get(a, {}).get("role") or ("recruiter" if a in roles else "member")
            node(a, type="account", label=a, layer="network", role=role,
                 reason=roles.get(a, {}).get("reason") or f"member of {ring.get('ring_id')}")
        for link in ring.get("links", []):
            for key in link.get("keys", []):
                kind = key.partition(":")[0]
                if kind in ("contact", "text", "keyword", "photo"):
                    kid = "k:" + hashlib.sha1(key.encode()).hexdigest()[:10] if kind == "contact" else "k:" + key
                    node(kid, type=KIND_TYPE[kind], label=_short(key), layer="content", role="shared key",
                         reason=f"{kind} key shared inside {ring.get('ring_id')}")
                    for acct in (link["a"], link["b"]):
                        edge(acct, kid, kind, "content", f"{acct} uses this {kind} key")
                elif kind == "interaction":
                    edge(link["a"], link["b"], "interaction", "network", mask_text(link.get("reason", "")))
                elif kind == "place":
                    pid = "k:" + key
                    node(pid, type="place", label=_short(key), layer="place", role="area clue",
                         reason="stated area; gives an area, never an address")
                    for acct in (link["a"], link["b"]):
                        edge(acct, pid, "place", "place", "same stated area (down-weighted if common)")
        photo_owner = {p["photo_id"]: p.get("account") for p in ring.get("photos", [])}
        money = ring.get("money") or rings.get("money") or {}
        for wc in money.get("wallet_clusters", []):
            wid = "w:" + str(wc.get("id") or wc.get("cluster_id"))
            node(wid, type="wallet_cluster", label=wc.get("masked_label") or wid, layer="money",
                 role=wc.get("role") or "wallet cluster", reason=wc.get("reason"))
            for a in wc.get("members", []) + wc.get("accounts", []):
                if a in nodes:
                    edge(a, wid, "pays_into", "money", wc.get("reason") or "account linked to this cluster")
        for fl in money.get("flows", []):
            a, b = fl.get("from"), fl.get("to")
            a = a if a in nodes else "w:" + str(a)
            b = b if b in nodes else "w:" + str(b)
            if a in nodes and b in nodes:
                edge(a, b, fl.get("kind", "flow"), "money", fl.get("reason") or "funds moved")
        for co in money.get("cash_out", []):
            sid = "s:" + str(co.get("service") or co.get("id"))
            node(sid, type="service", label=co.get("masked_label") or co.get("service") or sid, layer="money",
                 role="cash-out", reason=co.get("reason"))
            src = "w:" + str(co.get("cluster") or co.get("from"))
            if src in nodes:
                edge(src, sid, "cash_out", "money", co.get("reason") or "cash-out")
        # photo -> room -> building, from the Locator
        for z in (matches or {}).get("zones", []):
            ranked = sorted(z.get("matches", []), key=lambda m: -(m.get("P") or 0))
            thr = z.get("threshold") or 0.4
            for m in [m for i, m in enumerate(ranked) if i < 3 or (m.get("P") or 0) >= thr][:6]:
                bid = "b:" + str(m.get("property_id"))
                name = next((l.get("display_name") for l in (brief or {}).get("leads", [])
                             if l.get("property_id") == m.get("property_id")), None)
                node(bid, type="building", label=name or m.get("property_id"), layer="place", role="lead",
                     score=m.get("P"), reason=f"P {m.get('P')}: ring photos match this building's scan")
                for ev in m.get("evidence", []):
                    pid, view = ev.get("photo"), ev.get("view", "")
                    room = "r:" + "/".join(view.split("/")[:2])
                    node(room, type="room", label="room " + view.split("/")[1][:6] if "/" in view else room,
                         layer="place", role="scan room", reason="a Matterport sweep in the matched scan")
                    node("p:" + pid, type="photo", label=pid, layer="content", role="ad photo",
                         reason=f"{ev.get('inliers')} matched points to {view}")
                    edge("p:" + pid, room, "room_match", "place", f"{ev.get('inliers')} inliers")
                    edge(room, bid, "inside", "place", "sweep belongs to this scan")
                    owner = photo_owner.get(pid)
                    if owner in nodes:
                        edge(owner, "p:" + pid, "posted", "content", f"{owner} posted {pid}")
    linked = {e["source"] for e in edges} | {e["target"] for e in edges}
    keep = [n for n in nodes.values() if n["type"] == "account" or n["id"] in linked]
    return {"source": "rings.json", "nodes": keep, "edges": edges}


def build_graph(case_id: str) -> dict:
    d = _case_dir(case_id)
    cx = _load(d, "complex.json")
    if cx and cx.get("ranks"):
        g = graph_from_complex(cx)
    else:
        rings = _load(d, "rings.json")
        if rings is None:
            abort(404)
        g = graph_from_rings(rings, _load(d, "matches.json"), _load(d, "brief.json"))
    g["case"] = d.name
    return scrub(g)


# ---------------------------------------------------------------------- panels
@bp.get("/panels")
def panels():
    """Spotter queue, topology, money. Each is null when its file is missing; the page hides it."""
    _gate()
    d = _case_dir(request.args.get("case", ""))
    spotter = _load(d, "spotter.json")
    if isinstance(spotter, dict):
        spotter = spotter.get("queue") or spotter.get("accounts")
    cx = _load(d, "complex.json")
    topology = None
    if cx and cx.get("ranks"):
        topology = {"ranks": {r: [{"id": c.get("id"), "kind": c.get("kind"), "size": len(c.get("members", [])),
                                   "label": c.get("masked_label") or c.get("id"),
                                   "score": (cx.get("scores") or {}).get(c.get("id")),
                                   "reason": c.get("reason") or (cx.get("reasons") or {}).get(c.get("id"))}
                                  for c in cells] for r, cells in cx["ranks"].items()},
                    "features": cx.get("features")}
    rings = _load(d, "rings.json") or {}
    money = rings.get("money")
    if not money:
        money = next((r.get("money") for r in rings.get("rings", []) if r.get("money")), None)
    approvals = _actions(d.name)
    return jsonify(scrub({"spotter": spotter, "topology": topology, "money": money, "actions": approvals}))


def _actions_path(case_id: str) -> Path:
    from . import app as ui
    p = Path(ui.CASES) / case_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "ui_actions.jsonl"


def _actions(case_id: str) -> list:
    from . import app as ui
    p = Path(ui.CASES) / case_id / "ui_actions.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _record(kind: str):
    _gate()
    body = request.get_json(silent=True) or {}
    case_id = str(body.get("case", ""))
    d = _case_dir(case_id)
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": kind,
           "account": str(body.get("account", ""))[:64] or None,
           "property_id": str(body.get("property_id", ""))[:64] or None,
           "note": "recorded only; Dome takes no action"}
    with open(_actions_path(d.name), "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return jsonify({"recorded": True, **row})


@bp.post("/spotter/choose")
def spotter_choose():
    return _record("start_case_from_account")


@bp.post("/approve")
def approve():
    return _record("approve_for_report")


# ---------------------------------------------------------------------- events (contract E)
AGENT = {"linker": "Linker", "zoner": "Zoner", "lister": "Lister", "locator": "Locator", "briefer": "Briefer"}


def to_event(row: dict, t: float) -> dict | None:
    ev = row.get("event")
    step = (row.get("step") or "").split(":")[0]
    phase = {"tool_call": "start", "tool_result": "result", "decision": "decision",
             "step_failed": "result", "interrupt": "interrupt"}.get(ev)
    if phase is None:
        return None
    refs = [row["output_file"]] if row.get("output_file") else []
    zone = (row.get("evidence") or {}).get("zone_id")
    if zone:
        refs.append(zone)
    msg = row.get("message") or row.get("decision") or ev
    return {"t": t, "agent": AGENT.get(step, step or "supervisor"), "phase": phase,
            "message": mask_text(msg), "refs": refs, "decision": row.get("decision")}


@bp.get("/events")
def events():
    """Server-sent events: log.jsonl replayed as contract E events at a fixed pace."""
    _gate()
    d = _case_dir(request.args.get("case", ""))
    pace = min(max(request.args.get("pace", default=1.2, type=float), 0.0), 10.0)
    p = d / "log.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
    evs = [e for i, r in enumerate(rows) if (e := to_event(r, round(i * pace, 2)))]

    def stream():
        for e in evs:
            yield f"data: {json.dumps(e)}\n\n"
            if pace:
                time.sleep(pace)
        yield "event: end\ndata: {}\n\n"

    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})
