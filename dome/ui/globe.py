"""Globe flight, link chart and side panels for the demo UI. Everything here sits behind flags.

    DOME_GLOBE=1 python -m dome.ui.app --port 5001      # then open /globe
    DOME_STEPS=1   adds "Show the work" (/steps, see dome/ui/steps/)
    DOME_GRAPH=1   live runs through dome.graph_stream (falls back to replay when it is missing)

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
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, request, send_file, send_from_directory

from .. import config

bp = Blueprint("globe", __name__)

ROOT = Path(config.ROOT)
NIGHT = Path(config.ROOT) / "samples" / "night"           # shared fallbacks; marked "sample" on the page
STATIC = Path(__file__).resolve().parent / "static"
ASSET_ROOTS = ("data/demo_assets", "data/matches")          # the only folders /asset serves
ASSET_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

STREET_RE = re.compile(r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][A-Za-z0-9'.-]*\s+){1,4}"
                       r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Way|Pkwy|Parkway|Ct|Court|Pl|Place|Hwy|Fwy)\b\.?")
PHONE_RE = re.compile(r"(?:\(?\d{3}\)?[\s.-]?)?555[\s.-]?\d{4}")
WALLET_RE = re.compile(r"\b(?:bc1|0x|[13])[A-Za-z0-9]{20,}\b")


def enabled() -> bool:
    return os.getenv("DOME_GLOBE") == "1"


def steps_enabled() -> bool:
    return os.getenv("DOME_STEPS") == "1"


def live_enabled() -> bool:
    return os.getenv("DOME_GRAPH") == "1"


def _gate():
    if not enabled():
        abort(404)


def _asset_gate():
    if not (enabled() or steps_enabled()):
        abort(404)


def night(name: str):
    """A shared sample file from samples/night/ (fallback only; the page labels it as a sample)."""
    p = NIGHT / name
    if not p.exists():
        return None
    if name.endswith(".jsonl"):
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- masking
def mask_text(s: str) -> str:
    s = STREET_RE.sub("[address removed]", s)
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


MATTERPORT_REQUIRED = {"title": "0", "mls": "2", "brand": "0", "help": "0", "hr": "0", "dh": "0", "search": "0", "qs": "1"}


def matterport_url(embed: dict | None) -> str | None:
    """The showcase URL, always with the title and details hidden (the splash shows the street address)."""
    if not embed or not re.match(r"^[A-Za-z0-9]{6,20}$", str(embed.get("model_id", ""))):
        return None
    params = {}
    for part in str(embed.get("params", "")).split("&"):
        k, _, v = part.partition("=")
        if re.match(r"^[a-z]{1,12}$", k) and re.match(r"^[A-Za-z0-9._-]{0,20}$", v):
            params[k] = v
    params.update(MATTERPORT_REQUIRED)                   # never weaker than this, whatever the pack says
    ss = embed.get("ss")
    head = f"https://my.matterport.com/show/?m={embed['model_id']}"
    if isinstance(ss, int):
        head += f"&ss={ss}"
    return head + "&" + "&".join(f"{k}={v}" for k, v in params.items())


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
    out = {"globe": enabled()}
    if steps_enabled():
        from .steps import AGENTS
        out["steps"] = AGENTS
    if ask_enabled():
        out["ask"] = True
    if live_enabled():
        out["live"] = _graph_stream() is not None
        out["assistant"] = assistant_name()
    return jsonify(out)


@bp.get("/asset/<path:rel>")
def asset(rel):
    """Images under data/demo_assets/ and data/matches/ only. Resolved, then checked: no traversal."""
    _asset_gate()
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
            "matterport_url": matterport_url(pack.get("matterport_embed")),
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
KIND_TYPE = {"ring": "cell", "contact": "phone", "phone": "phone", "text": "script", "keyword": "script", "script": "script",
             "photo": "photo", "room": "room", "building": "building", "account": "account",
             "wallet": "wallet_cluster", "wallet_cluster": "wallet_cluster", "service": "service",
             "payment": "wallet_cluster"}
KIND_LAYER = {"dm": "network", "echo_event": "network", "heartbeat": "network", "wallet_note": "money",
              "money": "money", "wallet_flow": "money", "photo_in_room": "place", "merchant": "money",
              "shared_phone": "content", "payment_then_post": "money", "room_in_building": "place",
              "posting_burst": "network", "ring": "content", "contact": "content", "phone": "content", "text": "content", "keyword": "content",
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
    unscored = set(cx.get("unscored") or [])
    nodes, edges = {}, []
    ranks = cx.get("ranks") or {}
    for cell in ranks.get("0", []):
        cid = cell.get("id")
        kind = cell.get("kind", "account")
        nodes[cid] = {"id": cid, "type": KIND_TYPE.get(kind, "account"), "label": cell.get("masked_label") or cell.get("label") or cid,
                      "role": cell.get("role") or "member", "layer": KIND_LAYER.get(kind, "network"),
                      "score": None if cid in unscored else scores.get(cid),
                      "reason": cell.get("reason") or reasons.get(cid) or ("in the complex, not scored" if cid in unscored else None)}
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
            nodes[cid] = {"id": cid, "type": "cell" if r != "1" else KIND_TYPE.get(kind, "cell"),
                          "label": cell.get("masked_label") or cell.get("label") or f"{kind} ×{len(members)}",
                          "role": f"rank {r} cell", "layer": layer,
                          "score": scores.get(cid), "reason": reason}
            edges += [{"source": m, "target": cid, "type": kind, "layer": layer, "reason": reason} for m in members]
    return {"source": "complex.json", "nodes": list(nodes.values()), "edges": edges}


def _cid(wc: dict) -> str:
    return "w:" + str(wc.get("cluster_id") or wc.get("id"))


def add_money(money: dict, nodes: dict, node, edge) -> None:
    """Money block (contract: rings[i].money): wallet_clusters, flows, cash_out, payment_then_post."""
    for wc in money.get("wallet_clusters", []):
        wid = _cid(wc)
        reasons = wc.get("reasons") or ([wc["reason"]] if wc.get("reason") else [])
        node(wid, type="wallet_cluster", label=wc.get("masked_label") or wid[2:], layer="money",
             role=wc.get("role") or "wallet cluster", score=wc.get("confidence"),
             reason="; ".join(reasons) or None)
        for a in wc.get("members", []) + wc.get("accounts", []):
            if a in nodes:
                edge(a, wid, "pays_into", "money", "; ".join(reasons) or "account linked to this cluster")
    for pp in money.get("payment_then_post", []):
        wid, acct = "w:" + str(pp.get("wallet")), pp.get("account")
        if wid in nodes and acct in nodes:
            edge(wid, acct, "payment_then_post", "money",
                 f"paid {str(pp.get('paid_at', ''))[11:16]}, post {str(pp.get('post_at', ''))[11:16]}")
    for fl in money.get("flows", []):
        a, b = fl.get("from"), fl.get("to")
        a = a if a in nodes else "w:" + str(a)
        b = b if b in nodes else "w:" + str(b)
        if a in nodes and b in nodes:
            why = fl.get("reason") or (f"{fl.get('btc')} BTC in {fl.get('txs')} txs" if fl.get("btc") is not None else "funds moved")
            edge(a, b, fl.get("kind", "flow"), "money", why)
    for co in money.get("cash_out", []):
        sid = "s:" + str(co.get("service") or co.get("id"))
        node(sid, type="service", label=co.get("masked_label") or co.get("service") or sid, layer="money",
             role="cash-out", reason=co.get("reason") or (f"{co.get('times')} deposits" if co.get("times") else None))
        src = "w:" + str(co.get("cluster_id") or co.get("cluster") or co.get("from"))
        if src in nodes:
            edge(src, sid, "cash_out", "money", co.get("reason") or f"cash-out, {co.get('times', '?')} times")


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
        add_money(money, nodes, node, edge)
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
    """case graph.json, else complex.json, else rings.json (+ matches), else samples/night/graph.json."""
    d = _case_dir(case_id)
    g = _load(d, "graph.json")
    if g and g.get("nodes") is not None:
        g = {"source": "graph.json", **g}
    else:
        cx = _load(d, "complex.json")
        rings = _load(d, "rings.json")
        if cx and cx.get("ranks"):
            g = graph_from_complex(cx)
        elif rings is not None:
            g = graph_from_rings(rings, _load(d, "matches.json"), _load(d, "brief.json"))
        else:
            g = {"source": "samples/night/graph.json", "sample": True, **(night("graph.json") or {"nodes": [], "edges": []})}
    g["case"] = d.name
    return scrub(g)


# ---------------------------------------------------------------------- panels
@bp.get("/panels")
def panels():
    """Spotter queue, topology, money: the case file first, else samples/night/ marked `sample: true`.

    The page labels samples as "sample, not from this case" and hides them in presenter mode.
    """
    _gate()
    d = _case_dir(request.args.get("case", ""))
    return jsonify(scrub(panels_for(d)))


def _pick(d: Path, name: str):
    data = _load(d, name)
    if data is not None:
        return data, False
    return night(name), True


def panels_for(d: Path) -> dict:
    cx, cx_sample = _pick(d, "complex.json")
    scores = (cx or {}).get("scores") or {}

    spot, spot_sample = _pick(d, "spotter.json")
    spotter = None
    if spot is not None:
        queue = spot.get("queue", []) if isinstance(spot, dict) else spot      # older drafts: a bare list
        spotter = {"queue": [{**q, "model": scores.get(q.get("account"))} for q in queue],
                   "flag_rule": spot.get("flag_rule") if isinstance(spot, dict) else None,
                   "model_name": (cx or {}).get("model"), "sample": spot_sample}

    topology = None
    if cx and cx.get("ranks"):
        topology = {"ranks": {r: [{"id": c.get("id"), "kind": c.get("kind"), "size": len(c.get("members", [])),
                                   "label": c.get("masked_label") or c.get("label") or c.get("id"),
                                   "score": None if c.get("id") in set(cx.get("unscored") or []) else scores.get(c.get("id")),
                                   "reason": c.get("reason") or (cx.get("reasons") or {}).get(c.get("id"))}
                                  for c in cells] for r, cells in cx["ranks"].items()},
                    "features": cx.get("features"), "model": cx.get("model"), "sample": cx_sample,
                    "threshold": cx.get("threshold"), "unscored": cx.get("unscored") or [],
                    "disagreements": cx.get("disagreements") or [],
                    "fresh_test": (cx.get("eval_structural") or {}).get("fresh_test")}

    rings = _load(d, "rings.json") or {}
    money = next((r.get("money") for r in rings.get("rings", []) if r.get("money")), None) or rings.get("money")
    if money:
        money = {**money, "sample": False}
    elif night("money.json"):
        money = {**night("money.json"), "sample": True}
    return {"spotter": spotter, "topology": topology, "money": money, "actions": _actions(d.name),
            "live": live_enabled() and _graph_stream() is not None, "assistant": assistant_name()}


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


def _record(kind: str, extra: dict | None = None) -> dict:
    _gate()
    body = request.get_json(silent=True) or {}
    case_id = str(body.get("case", ""))
    d = _case_dir(case_id)
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": kind,
           "account": str(body.get("account", ""))[:64] or None,
           "property_id": str(body.get("property_id", ""))[:64] or None,
           "note": "recorded only; Dome contacts, dispatches and publishes nothing", **(extra or {})}
    with open(_actions_path(d.name), "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return {"recorded": True, **row}


# ---------------------------------------------------------------------- live runs (DOME_GRAPH=1)
_live: dict[str, dict] = {}


def assistant_name() -> str | None:
    """Which LangGraph assistant live runs use. dome.graph_stream reads the same variable; we only show it."""
    return os.getenv("DOME_GRAPH_ASSISTANT") or "dome_rules"      # graph_stream's default too; "dome" at merge


def _graph_stream():
    """Avishek's dome.graph_stream (stream_run, resume) when DOME_GRAPH=1 and it imports; else None."""
    if not live_enabled():
        return None
    try:
        from .. import graph_stream   # noqa: PLC0415  (optional module)
        if hasattr(graph_stream, "stream_run"):
            return graph_stream
    except Exception:
        pass
    return None


def _pump(state: dict, produce) -> None:
    """Run a graph_stream call in a thread and collect its contract E events."""
    def run():
        try:
            out = produce()
            if isinstance(out, dict):
                state["thread_id"] = out.get("thread_id") or state["thread_id"]
                out = out.get("events", [])
            for ev in out or []:
                if isinstance(ev, dict):
                    state["thread_id"] = ev.get("thread_id") or state["thread_id"]
                    state["events"].append(scrub(ev))
        except Exception as exc:     # a live failure falls back to replay on the page
            state["error"] = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            state["done"] = True
    state["done"] = False
    threading.Thread(target=run, daemon=True).start()


@bp.post("/spotter/choose")
def spotter_choose():
    """Start a case from an account: live via stream_run when DOME_GRAPH=1, else the page replays."""
    rec = _record("start_case_from_account")
    gs = _graph_stream()
    if gs is None:
        return jsonify({**rec, "live": False})
    key = uuid.uuid4().hex[:12]
    state = {"events": [], "done": False, "error": None, "thread_id": key}
    _live[key] = state
    account = rec["account"] or ""
    case_id = "live-" + re.sub(r"[^A-Za-z0-9_-]", "", account)[:40]
    _pump(state, lambda: gs.stream_run({"case_id": case_id, "dataset": "synth", "seed_account": account,
                                         "seed": account}))
    return jsonify({**rec, "live": True, "run": key, "case_id": case_id, "assistant": assistant_name()})


@bp.post("/approve")
def approve():
    """Approve for report: resume(thread_id, "approve") on a live run, else record the approval only."""
    body = request.get_json(silent=True) or {}
    state = _live.get(str(body.get("run", "")))
    gs = _graph_stream()
    rec = _record("approve_for_report", {"live": bool(state and gs)})
    if state and gs is not None and hasattr(gs, "resume"):
        _pump(state, lambda: gs.resume(state["thread_id"], "approve"))
    return jsonify(rec)


# ---------------------------------------------------------------------- events (contract E)
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
    return {"t": t, "agent": step or "supervisor", "phase": phase,
            "message": mask_text(msg), "refs": refs, "decision": row.get("decision")}


def case_events(d: Path, pace: float) -> tuple[list, str]:
    """case events.jsonl (contract E), else log.jsonl converted, else samples/night/events.jsonl."""
    p = d / "events.jsonl"
    if p.exists():
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()], "events.jsonl"
    p = d / "log.jsonl"
    if p.exists():
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        evs = [e for e in (to_event(r, 0) for r in rows) if e]
        for i, e in enumerate(evs):
            e["t"] = round(i * pace, 2)
        return evs, "log.jsonl"
    return night("events.jsonl") or [], "samples/night/events.jsonl"


@bp.get("/events")
def events():
    """Server-sent events in contract E: {t, agent, phase, message, refs}. Replays keep their `t` timing
    (scaled by `speed`); `?run=<id>` streams a live DOME_GRAPH run instead."""
    _gate()
    run = request.args.get("run")
    if run:
        state = _live.get(run) or abort(404)

        def live_stream():
            i, idle = 0, 0
            while idle < 600:
                while i < len(state["events"]):
                    yield f"data: {json.dumps(state['events'][i])}\n\n"
                    i += 1
                if state["done"]:
                    break
                time.sleep(0.2)
                idle += 1
            yield f"event: end\ndata: {json.dumps({'error': state['error']})}\n\n"
        return Response(live_stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})

    d = _case_dir(request.args.get("case", ""))
    pace = min(max(request.args.get("pace", default=1.2, type=float), 0.0), 10.0)
    speed = min(max(request.args.get("speed", default=1.0, type=float), 0.0), 20.0)
    evs, source = case_events(d, pace)
    evs = [scrub({**e, "source": source, "sample": source.startswith("samples/")}) for e in evs]

    def stream():
        last = 0.0
        for e in evs:
            wait = max(0.0, float(e.get("t") or 0) - last) / speed if speed else 0
            last = float(e.get("t") or 0)
            if wait:
                time.sleep(min(wait, 10))
            yield f"data: {json.dumps(e)}\n\n"
        yield "event: end\ndata: {}\n\n"

    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------------- ask about this case (DOME_ASK=1)
NOT_IN_CASE = "That isn't in this case's files."
_PATH_TOKEN = re.compile(r"([A-Za-z_][\w-]*)|\[(\d+)\]")


def ask_enabled() -> bool:
    return os.getenv("DOME_ASK") == "1"


def _ask_gate():
    if not ask_enabled():
        abort(404)


def _recorded_ask(d: Path):
    from . import app as ui
    p = Path(ui.RECORDED) / d.name / "ask.json"
    if p.exists():
        try:
            return {**json.loads(p.read_text(encoding="utf-8")), "recorded": True}
        except json.JSONDecodeError:
            return None
    return None


@bp.get("/ask")
def ask_recorded():
    """The recorded Q&A for a replayed case (samples/demo_cases/<case>/ask.json), if there is one."""
    _ask_gate()
    d = _case_dir(request.args.get("case", ""))
    return jsonify(scrub(_recorded_ask(d) or {"recorded": False}))


@bp.post("/ask")
def ask():
    """dome.ask.answer(case_id, question): answers only from the case files, with checked citations."""
    _ask_gate()
    body = request.get_json(silent=True) or {}
    d = _case_dir(str(body.get("case", "")))
    q = str(body.get("question", "")).strip()[:500]
    if not q:
        return jsonify({"answer": NOT_IN_CASE, "citations": [], "answerable": False})
    try:
        from .. import ask as ask_mod
        out = ask_mod.answer(d.name, q, root=d.parent)
    except Exception as exc:          # no model key, bad output, anything: say so plainly
        return jsonify({"answer": NOT_IN_CASE, "citations": [], "answerable": False,
                        "error": f"{type(exc).__name__}"[:80]})
    if not isinstance(out, dict) or not out.get("answerable"):
        return jsonify({"answer": NOT_IN_CASE, "citations": [], "answerable": False})
    cites = [{"file": str(c.get("file", "")), "path": str(c.get("path", ""))} for c in out.get("citations") or []]
    return jsonify(scrub({"answer": out.get("answer", ""), "citations": cites, "answerable": True}))


def resolve_path(data, path: str):
    """Walk a citation path like leads[0].reasons[1]. Raises KeyError/IndexError when it does not exist."""
    cur = data
    for name, idx in _PATH_TOKEN.findall(path):
        cur = cur[name] if name else cur[int(idx)]
    return cur


@bp.get("/ask/cite")
def ask_cite():
    """Open a cited field: only *.json files in this case folder, only existing paths."""
    _ask_gate()
    d = _case_dir(request.args.get("case", ""))
    name = Path(request.args.get("file", "")).name            # "case/real-a/brief.json" -> "brief.json"
    if not re.match(r"^[A-Za-z0-9_-]{1,64}\.json$", name) or not (d / name).is_file():
        abort(404)
    data = _load(d, name)
    path = request.args.get("path", "")[:200]
    if any(name == "address" for name, _ in _PATH_TOKEN.findall(path)):
        abort(404)                                             # addresses never leave the server
    try:
        value = resolve_path(data, path) if path else data
    except (KeyError, IndexError, TypeError):
        abort(404)
    text = json.dumps(scrub(value), indent=1, ensure_ascii=False)
    return jsonify({"file": name, "path": path, "value": scrub(value) if len(text) < 20000 else text[:20000] + " …"})
