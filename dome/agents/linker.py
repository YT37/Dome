"""Linker (Avishek): which flagged accounts are one ring, and why?  -> rings.json

Rules make the links; nothing here asks an LLM for a number.

  1. Keys per account      contact, photo, text, interaction, place, time (device: off)
  2. Down-weight           a key shared by many accounts counts for almost nothing
  3. Link                  two accounts link only if they share TWO DIFFERENT KINDS of key.
                           Place never counts toward the two: it gives an area, not identity.
                           One kind alone is a weak hint, kept for photo expansion.
  4. Ring                  a linked cluster where the content layer (contact/photo/text) and
                           the connectivity layer (interaction/time) agree
  5. Recruiters            bio offers modelling/jobs and interactions mostly run into the ring

Ring confidence R = 1 - prod(1 - w_k) over the key kinds the ring shares, capped at 0.95.

All data is synthetic. A ring is a lead for human review, not a finding about a person.

Runs alone:  python -m dome.agents.linker --case solo --data mini
With no dataset on the case, run() returns the stub scenario's rings instead.
"""
from __future__ import annotations

import copy
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Optional

from .. import config
from ..case import Case
from ..data_tools import _stub

CONTENT = ("contact", "photo", "text", "device")     # identity-bearing content keys
CONNECT = ("interaction", "time")                    # connectivity layer
KIND_ORDER = ("contact", "photo", "device", "text", "interaction", "place", "time")


# ============================================================ dataset
DATASET_ALIASES = {"synth": "data/synth"}   # Ishaan's generator output


def resolve_dataset(name_or_path: str) -> Path:
    p = Path(DATASET_ALIASES.get(name_or_path, name_or_path))
    for cand in (p, config.ROOT / p, config.SAMPLES / "data" / name_or_path):
        if (cand / "accounts.json").exists() or (cand / "dataset.json").exists():
            return cand
    raise FileNotFoundError(f"no dataset at '{name_or_path}' (need accounts.json, posts.json, "
                            "interactions.json)")


def load_dataset(name_or_path: str) -> dict:
    """{accounts: {handle: account}, posts: [...], interactions: [...]}. Never reads answer_key."""
    d = resolve_dataset(name_or_path)
    if (d / "dataset.json").exists():
        raw = json.loads((d / "dataset.json").read_text(encoding="utf-8"))
    else:
        raw = {n: json.loads((d / f"{n}.json").read_text(encoding="utf-8"))
               for n in ("accounts", "posts", "interactions")}
    # Ishaan's renders.json: photo_id -> {scan_id, view, path}. Only `view` and `path` are read;
    # scan_id is ground truth for the Locator's stubs and is never used to link accounts.
    renders = {}
    if (d / "renders.json").exists():
        renders = json.loads((d / "renders.json").read_text(encoding="utf-8"))
    posts = []
    for i, p in enumerate(raw["posts"]):
        p = dict(p)
        p.setdefault("post_id", f"post_{i:05d}")
        p["account"] = p.get("account") or p.get("account_id") or p.get("handle")
        items = p.get("photos") or p.get("photo_ids") or []
        p["photos"] = [_photo(x, renders) for x in items]
        p["stated_area"] = p.get("stated_area") or ""
        posts.append(p)
    interactions = [dict(it, post=it.get("post") or it.get("post_id"))
                    for it in raw.get("interactions") or []]
    return {"accounts": {a.get("account_id") or a["handle"]: a for a in raw["accounts"]},
            "posts": posts, "interactions": interactions}


def _photo(x: Any, renders: Optional[dict] = None) -> dict:
    """A photo is a dict {photo_id, path, phash, has_window}, a file path, or a bare photo id
    (Ishaan's data). With no image file to hash, the photo id stands in for the pHash."""
    renders = renders or {}
    if isinstance(x, str):
        if "/" in x or "\\" in x or x.endswith((".jpg", ".png")):
            x = {"path": x}
        else:
            r = renders.get(x) or {}
            x = {"photo_id": x, "path": r.get("path") or f"data/photos/{x}.jpg",
                 "has_window": r.get("view") == "window"}
    x = dict(x)
    x.setdefault("photo_id", Path(x["path"]).stem)
    if not x.get("phash"):
        x["phash"] = _file_phash(x["path"]) or hash_id(x["photo_id"])
    x.setdefault("has_window", False)
    return x


def hash_id(photo_id: str) -> str:
    """Stand-in 64-bit hash for a photo with no image file: equal ids give equal hashes."""
    import hashlib
    return hashlib.sha256(photo_id.encode()).hexdigest()[:16]


def _file_phash(path: str) -> Optional[str]:
    f = Path(path) if Path(path).is_absolute() else config.ROOT / path
    if not f.exists():
        return None
    try:
        import imagehash
        from PIL import Image
        return str(imagehash.phash(Image.open(f)))
    except Exception:
        return None


def _time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ============================================================ step 1: keys
_NUM = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_NUM_RE = re.compile("|".join(_NUM))
_PHONE_RE = re.compile(r"(?<!\d)(?:\d[\s\-.()]{0,3}){6,10}\d(?!\d)")


def undisguise(text: str) -> str:
    """'four1five five5five 0142' -> '415 555 0142'. Only tokens that become pure digits change,
    so ordinary words like 'phone' or 'someone' are left alone."""
    out = []
    for tok in re.split(r"(\s+)", text.lower()):
        core = tok.strip(".,;:!?()[]")
        swapped = _NUM_RE.sub(lambda m: _NUM[m.group()], core)
        out.append(tok.replace(core, swapped) if core and swapped.isdigit() else tok)
    return "".join(out)


def extract_contacts(text: str, phones: Iterable[str] = ()) -> set[str]:
    """Phones (plain or disguised, keyed by the last 7 digits), @handles and $payment tags."""
    keys = set()
    for chunk in [undisguise(text)] + [undisguise(p) for p in phones]:
        for m in _PHONE_RE.finditer(chunk):
            digits = re.sub(r"\D", "", m.group())
            if len(digits) in (7, 10, 11):
                keys.add(f"contact:{digits[-7:-4]}-{digits[-4:]}")
    low = text.lower()
    keys |= {f"contact:@{h}" for h in re.findall(r"(?<!\w)@([a-z0-9_.]{3,})", low)}
    keys |= {f"contact:${h}" for h in re.findall(r"\$([a-z][a-z0-9_]{2,})", low)}
    return keys


_AD_CTA = re.compile(config.AD_CALL_TO_ACTION, re.I)


def is_ad(post: dict) -> bool:
    text = post.get("text", "")
    return bool(post.get("phones") or extract_contacts(text) or _AD_CTA.search(text))


def template(text: str) -> str:
    """Ad text with numbers, contacts, names and punctuation stripped."""
    t = re.sub(r"https?://\S+|[@$]\w+", " ", undisguise(text))
    t = re.sub(r"\b(?:ask for|call me|i am|i'm|my name is)\s+[a-z]+", " ", t)
    t = re.sub(r"[^a-z\s]", " ", t)
    return " ".join(t.split())


def _shingles(tmpl: str, k: int = 3) -> set[str]:
    w = tmpl.split()
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


class _UF:
    def __init__(self):
        self.p: dict = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


_EMBEDDER: Any = None


def embed(texts: list[str]):
    """Sentence embeddings (all-MiniLM-L6-v2), unit length. Returns (matrix, backend name).
    Falls back to character n-gram vectors if sentence-transformers is not installed
    or the model can't be downloaded (offline, blocked network)."""
    import numpy as np
    global _EMBEDDER
    try:
        if _EMBEDDER == "unavailable":
            raise ImportError("embedding model unavailable")
        if _EMBEDDER is None:
            from sentence_transformers import SentenceTransformer
            try:
                _EMBEDDER = SentenceTransformer(config.EMBED_MODEL)
            except Exception as e:   # no network / no cached model: degrade, don't crash
                _EMBEDDER = "unavailable"
                raise ImportError(str(e)) from e
        return np.asarray(_EMBEDDER.encode(texts, normalize_embeddings=True,
                                           show_progress_bar=False)), config.EMBED_MODEL
    except ImportError:
        dim = 2048
        m = np.zeros((len(texts), dim))
        for i, t in enumerate(texts):
            for j in range(len(t) - 3):
                m[i, hash_stable(t[j:j + 4]) % dim] += 1.0
        m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
        return m, "char-4gram fallback"


def hash_stable(s: str) -> int:
    import hashlib
    return int.from_bytes(hashlib.md5(s.encode()).digest()[:4], "big")


def cluster_templates(templates: list[str]) -> tuple[dict, dict, list[dict], str]:
    """Two passes over the unique templates.
    copies      MinHash LSH on word shingles catches near-identical copies
    rewordings  sentence embeddings catch the same script in different words
    Returns (copy cluster per template, final cluster per template, embedding catches, backend).
    """
    uniq = sorted({t for t in templates if len(t.split()) >= config.TEXT_MIN_WORDS})
    sh = {t: _shingles(t) for t in uniq}
    copies = _UF()
    for t in uniq:
        copies.find(t)
    try:
        from datasketch import MinHash, MinHashLSH
        lsh, mh = MinHashLSH(threshold=config.MINHASH_THRESHOLD, num_perm=128), {}
        for t in uniq:
            m = MinHash(num_perm=128, seed=1)
            for s in sh[t]:
                m.update(s.encode())
            mh[t] = m
            lsh.insert(t, m)
        cand = {(a, b) for a in uniq for b in lsh.query(mh[a]) if a < b}
    except ImportError:
        cand = set(combinations(uniq, 2))

    def jac(a, b):
        return len(sh[a] & sh[b]) / max(1, len(sh[a] | sh[b]))

    for a, b in sorted(cand):
        if jac(a, b) >= config.MINHASH_THRESHOLD:   # confirm candidates with exact Jaccard
            copies.union(a, b)

    final, catches, backend = _UF(), [], "none"
    for t in uniq:
        final.union(t, copies.find(t))
    if len(uniq) > 1:
        vecs, backend = embed(uniq)
        sims = vecs @ vecs.T
        for i, j in combinations(range(len(uniq)), 2):
            a, b = uniq[i], uniq[j]
            if sims[i, j] >= config.EMBED_THRESHOLD and copies.find(a) != copies.find(b):
                final.union(a, b)
                catches.append({"a": a, "b": b, "cosine": round(float(sims[i, j]), 3),
                                "jaccard": round(jac(a, b), 3)})
    return ({t: copies.find(t) for t in uniq}, {t: final.find(t) for t in uniq}, catches, backend)


def rarity(n: int) -> float:
    """Inverse-frequency scale for a key shared by n accounts: 1.0 for a pair, about 0.8 at 12,
    0.15 at 50, 0.01 at 200. A downtown cell or a hub account counts for almost nothing."""
    return 1.0 / (1.0 + (max(0, n - 2) / config.RARE_KEY_SIZE) ** 2)


# ============================================================ steps 2-5
@dataclass
class Linked:
    rings_file: dict                                   # rings.json content (minus photo expansion)
    pair: dict = field(default_factory=dict)           # (a, b) -> {kind: {"w", "key", "why"}}
    strength: dict = field(default_factory=dict)       # (a, b) -> 0..1, every pair with any key
    embedding_catches: list = field(default_factory=list)
    embed_backend: str = "none"
    stats: dict = field(default_factory=dict)


def _strength(kinds: dict) -> float:
    return 1.0 - math.prod(1.0 - v["w"] for v in kinds.values())


def link_accounts(ds: dict) -> Linked:
    W = config.KEY_WEIGHTS
    accounts, posts = ds["accounts"], ds["posts"]
    by_acct = defaultdict(list)
    for p in posts:
        if p["account"] in accounts:
            by_acct[p["account"]].append(p)

    # ---- step 1: keys shared through an index (key -> accounts)
    index: dict[tuple[str, str], set] = defaultdict(set)     # (kind, key) -> accounts
    detail: dict[tuple[str, str], str] = {}

    # text key = AD template: only posts that carry a contact or a booking call-to-action.
    # Everyday chatter is often templated too, and must never become a "shared script".
    tmpl_of = {p["post_id"]: template(p.get("text", "")) if is_ad(p) else "" for p in posts}
    copy_c, final_c, catches, backend = cluster_templates(list(tmpl_of.values()))
    cluster_ids = {c: f"tmpl_{i + 1}" for i, c in enumerate(sorted(set(final_c.values())))}
    acct_copy_clusters = defaultdict(set)

    hashes = sorted({ph["phash"] for p in posts for ph in p["photos"] if ph.get("phash")})
    photo_uf = _UF()
    for h in hashes:
        photo_uf.find(h)
    if len(hashes) <= 4000:   # near-duplicate photos: small Hamming distance between pHashes
        ints = [int(h, 16) for h in hashes]
        for i, j in combinations(range(len(hashes)), 2):
            if (ints[i] ^ ints[j]).bit_count() <= config.PHASH_MAX_DISTANCE:
                photo_uf.union(hashes[i], hashes[j])

    for a, plist in by_acct.items():
        for p in plist:
            for k in extract_contacts(p.get("text", ""), p.get("phones") or []):
                if k != f"contact:@{a.lower()}":
                    index[("contact", k)].add(a)
            t = tmpl_of[p["post_id"]]
            if t in final_c:
                index[("text", "text:" + cluster_ids[final_c[t]])].add(a)
                acct_copy_clusters[a].add(copy_c[t])
            for ph in p["photos"]:
                if ph.get("phash"):
                    index[("photo", "photo:phash_" + photo_uf.find(ph["phash"])[:8])].add(a)
            if p.get("stated_area"):
                index[("place", "place:" + re.sub(r"\W+", "_", p["stated_area"].lower()))].add(a)
            for lm in p.get("landmarks") or []:
                index[("place", "place:lm_" + re.sub(r"\W+", "_", lm.lower()))].add(a)
            if p.get("area_code"):
                index[("place", f"place:ac_{p['area_code']}")].add(a)
    for a, acct in accounts.items():
        if acct.get("created"):
            index[("time", "time:created_" + str(acct["created"])[:10])].add(a)

    pair: dict[tuple[str, str], dict] = defaultdict(dict)

    def add(a: str, b: str, kind: str, w: float, key: str, why: str) -> None:
        if a == b or a not in accounts or b not in accounts:
            return
        k = (a, b) if a < b else (b, a)
        if w > pair[k].get(kind, {"w": -1})["w"]:
            pair[k][kind] = {"w": round(w, 4), "key": key, "why": why}

    # ---- step 2: inverse-frequency down-weighting of shared keys
    for (kind, key), accts in sorted(index.items()):
        n = len(accts)
        if n < 2 or n > config.MAX_KEY_FANOUT:
            continue
        w = W[kind] * rarity(n)
        why = {"contact": f"same contact {key.split(':', 1)[1]}",
               "photo": "same photo reposted", "text": "same ad script",
               "place": f"same stated area ({key.split(':', 1)[1]})",
               "time": f"accounts created the same day ({key[-10:]})"}[kind]
        if n > config.RARE_KEY_SIZE:
            why += f" (shared by {n} accounts, down-weighted)"
        for a, b in combinations(sorted(accts), 2):
            if kind == "text" and not (acct_copy_clusters[a] & acct_copy_clusters[b]):
                add(a, b, kind, w, key, "reworded copy of the same script (embeddings caught it, "
                                        "MinHash missed it)")
            else:
                add(a, b, kind, w, key, why)

    # ---- connectivity: repeated reposts/replies, and amplifying the same post within an hour
    direct, partners, amplified = Counter(), defaultdict(set), defaultdict(list)
    for it in ds["interactions"]:
        a, b = it.get("from"), it.get("to")
        if it.get("kind") not in ("repost", "reply") or a == b:
            continue
        direct[(min(a, b), max(a, b))] += 1
        partners[a].add(b)
        partners[b].add(a)
        if it["kind"] == "repost":
            amplified[it.get("post") or f"acct:{b}"].append((_time(it["time"]), a))
    for (a, b), n in sorted(direct.items()):
        if n >= config.MIN_REPEAT_INTERACTIONS:   # a hub everyone reposts is down-weighted
            scale = min(rarity(len(partners[a])), rarity(len(partners[b])))
            add(a, b, "interaction", W["interaction"] * scale, f"interaction:direct_x{n}",
                f"{n} reposts/replies between them")
    coamp: dict[tuple[str, str], list] = defaultdict(list)
    for target, events in amplified.items():
        events.sort()
        scale = rarity(len({a for _, a in events}))
        for i, (t1, a) in enumerate(events):
            for t2, b in events[i + 1:]:
                if (t2 - t1).total_seconds() > 3600:
                    break
                if a != b:
                    coamp[(min(a, b), max(a, b))].append(scale)
    for (a, b), scales in sorted(coamp.items()):
        if len(scales) < config.MIN_REPEAT_INTERACTIONS:   # once is chance; repeated is a pattern
            continue
        add(a, b, "interaction", W["interaction"] * max(scales), f"interaction:coamp_x{len(scales)}",
            f"both amplified the same post within an hour ({len(scales)} times)")

    # ---- lockstep posting: repeatedly posting within minutes of each other
    timeline = sorted((_time(p["time"]), p["account"]) for p in posts
                      if p.get("time") and p["account"] in accounts)
    lock = Counter()
    for i, (t1, a) in enumerate(timeline):
        near = set()
        for t2, b in timeline[i + 1:]:
            if (t2 - t1).total_seconds() > config.LOCKSTEP_SECONDS:
                break
            if a != b:
                near.add(b)
        if len(near) <= 15:
            for b in near:
                lock[(min(a, b), max(a, b))] += 1
    for (a, b), n in sorted(lock.items()):
        if n >= config.LOCKSTEP_MIN_TIMES:
            add(a, b, "time", W["time"], f"time:lockstep_x{n}",
                f"posted within {config.LOCKSTEP_SECONDS // 60} minutes of each other {n} times")

    # ---- step 3: two different kinds of key make a link; one kind is only a hint
    links, hints, strength = {}, {}, {}
    for k, kinds in pair.items():
        kinds = {kd: v for kd, v in kinds.items() if v["w"] >= config.MIN_KEY_WEIGHT}
        if not kinds:
            continue
        s = strength[k] = round(_strength(kinds), 3)
        counting = [kd for kd in kinds if kd != "place"]
        if len(counting) >= 2:
            links[k] = kinds
        elif s >= config.HINT_MIN_STRENGTH:
            hints[k] = kinds

    uf = _UF()
    for a, b in links:
        uf.union(a, b)
    groups = defaultdict(set)
    for a, b in links:
        groups[uf.find(a)] |= {a, b}
    clusters = [c for g in groups.values() for c in _leiden(g, links, strength)]

    # ---- step 4: a ring needs the content layer and the connectivity layer to agree
    rings, demoted = [], {}
    for members in clusters:
        inner = {k: v for k, v in links.items() if k[0] in members and k[1] in members}
        per_kind = defaultdict(list)
        for kinds in inner.values():
            for kd, v in kinds.items():
                per_kind[kd].append(v["w"])
        shared = {kd: statistics.mean(ws) for kd, ws in per_kind.items()
                  if len(ws) >= min(config.RING_KIND_MIN_LINKS, len(inner))}
        has_content = any(k in shared for k in CONTENT)
        has_connect = any(k in shared for k in CONNECT)
        if len(members) < 2 or not inner or (
                config.REQUIRE_LAYER_AGREEMENT and not (has_content and has_connect)):
            missing = "connectivity" if has_content else "content"
            for k, v in inner.items():
                demoted[k] = (v, f"; no {missing} layer in this group, so a hint and not a ring")
            continue
        conf = min(config.RING_CONFIDENCE_CAP, 1.0 - math.prod(1.0 - w for w in shared.values()))
        rings.append({"members": sorted(members), "confidence": round(conf, 2),
                      "key_kinds": [k for k in KIND_ORDER if k in shared], "_inner": inner})

    rings.sort(key=lambda r: (-r["confidence"], r["members"][0]))
    in_ring = {m: i for i, r in enumerate(rings) for m in r["members"]}
    out_degree = defaultdict(list)
    for it in ds["interactions"]:
        if it.get("kind") in ("repost", "reply"):
            out_degree[it["from"]].append(it["to"])

    def link_json(k, kinds, extra=""):
        ordered = [kd for kd in KIND_ORDER if kd in kinds]
        return {"a": k[0], "b": k[1], "keys": [kinds[kd]["key"] for kd in ordered], "kinds": ordered,
                "strength": round(_strength(kinds), 2),
                "reason": "; ".join(kinds[kd]["why"] for kd in ordered) + extra}

    out_rings = []
    for i, r in enumerate(rings):
        members = set(r["members"])
        photos, seen = [], set()
        for m in r["members"]:
            for p in by_acct[m]:
                for ph in p["photos"]:
                    if ph["photo_id"] not in seen:
                        seen.add(ph["photo_id"])
                        photos.append({"photo_id": ph["photo_id"], "path": ph["path"], "account": m,
                                       "has_window": bool(ph["has_window"])})
        # ---- step 5: recruiter flags
        recruiters = []
        for a in sorted(accounts):
            m = re.search(config.RECRUITER_BIO, accounts[a].get("bio") or "", re.I)
            outs = out_degree.get(a, [])
            into = sum(t in members for t in outs)
            if m and len(outs) >= 3 and into / len(outs) >= config.RECRUITER_MIN_SHARE:
                recruiters.append({"account": a, "reason": f"bio says '{m.group().lower()}'; "
                                   f"{into} of {len(outs)} reposts/replies go to ring accounts"})
        places = Counter(v["place"]["key"] for v in r["_inner"].values() if "place" in v)
        out_rings.append({
            "ring_id": f"R-{i + 1}", "members": r["members"], "confidence": r["confidence"],
            "key_kinds": r["key_kinds"],
            "links": [link_json(k, v) for k, v in sorted(r["_inner"].items(),
                                                         key=lambda kv: (-_strength(kv[1]), kv[0]))],
            "recruiters": recruiters, "place_keys": [k for k, _ in places.most_common(5)],
            "photos": sorted(photos, key=lambda p: p["photo_id"])})

    # weak hints: one kind only, or a group the layers did not agree on. Kept for the analyst,
    # ring-adjacent ones first, then the strongest of the rest.
    weak = [link_json(k, v, "; one key kind is a hint, not a link") for k, v in hints.items()]
    weak += [link_json(k, v, extra) for k, (v, extra) in demoted.items()]
    weak.sort(key=lambda h: (not (h["a"] in in_ring or h["b"] in in_ring), -h["strength"], h["a"], h["b"]))
    return Linked(
        rings_file={"rings": out_rings, "weak_hints": weak[:config.MAX_WEAK_HINTS]},
        pair=dict(pair), strength=strength, embedding_catches=catches, embed_backend=backend,
        stats={"accounts": len(accounts), "posts": len(posts), "pairs_with_any_key": len(strength),
               "links": len(links), "hints": len(hints), "rings": len(out_rings)})


def _leiden(group: set, links: dict, strength: dict) -> list[set]:
    """Leiden splits big linked groups; small groups are already one ring."""
    if len(group) < config.LEIDEN_MIN_SIZE:
        return [group]
    try:
        import igraph as ig
        import leidenalg
    except ImportError:
        return [group]
    nodes = sorted(group)
    idx = {n: i for i, n in enumerate(nodes)}
    edges = sorted(k for k in links if k[0] in group and k[1] in group)
    g = ig.Graph(n=len(nodes), edges=[(idx[a], idx[b]) for a, b in edges])
    part = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition,
                                    weights=[strength[e] for e in edges], seed=0)
    return [{nodes[i] for i in comm} for comm in part if len(comm) >= 2]


# ============================================================ agent entry point
def run(case: Case) -> dict:
    inp = case.input
    if not inp.dataset:
        return {"case_id": case.case_id, **copy.deepcopy(_stub.scenario()["rings"])}
    return {"case_id": case.case_id, **link_accounts(load_dataset(inp.dataset)).rings_file}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="dome.agents.linker")
    ap.add_argument("--case", required=True)
    ap.add_argument("--data", default=None, help="dataset folder or a name under samples/data/")
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--seed", default=None, help="investigate the ring containing this account")
    a = ap.parse_args()
    c = Case.open(a.case, scenario=a.scenario, dataset=a.data, seed_account=a.seed)
    obj = c.save("rings.json", run(c))
    c.log(actor="agent", event="tool_result", step="linker", output_file="rings.json",
          message="linker run alone from the CLI")
    for r in obj.rings:
        print(f"{r.ring_id}  R {r.confidence}  {len(r.members)} accounts  kinds {r.key_kinds}  "
              f"photos {len(r.photos)}  recruiters {[x.account for x in r.recruiters]}")
    print(f"{len(obj.weak_hints)} weak hints. Wrote {c.path('rings.json')}")
