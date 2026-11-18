"""Shared helpers for the "Show the work" adapters.

Rules every adapter follows:
- Read only the case folder, data/synth/, data/matches/, data/demo_assets/. Never data/answer_key/.
- Every step shows what code produced, read from a real file, and names that file in `source`.
- If the in-between data is not there, the step shows the final result and says
  "in-between data not recorded". No invented numbers.
- No address ever: steps are scrubbed (address keys dropped, street text and phones masked).
"""
from __future__ import annotations

import json
from pathlib import Path

from ... import config
from .. import globe

ROOT = Path(config.ROOT)
ALLOWED = ("data/synth", "data/matches", "data/demo_assets")
NOT_RECORDED = "in-between data not recorded"


def live_index_dir() -> Path | None:
    """The offline bundle's 6-scan room-match index, when one is configured."""
    import os
    b = os.environ.get("DOME_BUNDLE")
    d = Path(b).expanduser() / "live_index" if b else None
    return d if d and d.is_dir() and any(d.glob("*.npz")) else None


class Ctx:
    """Read-only access to one case folder plus the allowed shared data folders."""

    def __init__(self, case_dir: Path, root: Path | None = None):
        self.case_dir = Path(case_dir)
        self.root = Path(root) if root else ROOT
        self.case = self.case_dir.name
        self._memo: dict = {}

    # files ---------------------------------------------------------------
    def load(self, name: str):
        """A JSON file in the case folder, or None."""
        key = ("case", name)
        if key not in self._memo:
            p = self.case_dir / name
            try:
                self._memo[key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
            except (OSError, json.JSONDecodeError):
                self._memo[key] = None
        return self._memo[key]

    def load_data(self, rel: str):
        """A JSON file under data/synth, data/matches or data/demo_assets, or None."""
        rel = rel.lstrip("/")
        if not any(rel.startswith(a + "/") for a in ALLOWED) or ".." in rel:
            raise ValueError(f"not an allowed data path: {rel}")
        key = ("data", rel)
        if key not in self._memo:
            p = self.root / rel
            try:
                self._memo[key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
            except (OSError, json.JSONDecodeError):
                self._memo[key] = None
        return self._memo[key]

    def src(self, name: str) -> str:
        """How a case file is named under each step ("read from")."""
        return f"case/{self.case}/{name}"

    # derived -------------------------------------------------------------
    def best_match(self) -> tuple[dict | None, dict | None]:
        """(match, zone) with the highest P in matches.json."""
        best, zone = None, None
        for z in (self.load("matches.json") or {}).get("zones", []):
            for m in z.get("matches", []):
                if best is None or (m.get("P") or 0) > (best.get("P") or 0):
                    best, zone = m, z
        return best, zone

    def pack(self) -> tuple[dict | None, str | None]:
        """The asset pack of the best-matching scan and its path."""
        best, _ = self.best_match()
        scan = (best or {}).get("scan_id")
        if not scan:
            return None, None
        rel = f"data/demo_assets/{scan}/assets.json"
        try:
            return self.load_data(rel), rel
        except ValueError:
            return None, None

    def room_match(self) -> tuple[dict | None, str | None]:
        """case room_match.json first, then data/matches/summary.json."""
        rm = self.load("room_match.json")
        if rm:
            return rm, self.src("room_match.json")
        rm = self.load_data("data/matches/summary.json")
        return (rm, "data/matches/summary.json") if rm else (None, None)

    def property_of_scan(self) -> dict:
        out = {}
        for z in (self.load("candidates.json") or {}).get("zones", []):
            for c in z.get("candidates", []):
                if c.get("scan_id"):
                    out[c["scan_id"]] = c
        return out


def asset(rel: str | None) -> str | None:
    if rel and globe.imageless() and str(rel).startswith(globe.LICENSED_IMAGE_ROOTS):
        return None                                   # imageless mode: the step falls back to text/charts
    """A page URL for an image under the served asset folders (data/demo_assets, data/matches, data/photos)."""
    if not rel or rel.startswith("/") or ".." in rel:
        return None
    if not any(rel.startswith(r + "/") for r in globe.ASSET_ROOTS):
        return None
    return "/asset/" + rel


def step(sid: str, title: str, kind: str, data: dict, caption: str, source: str | list) -> dict:
    assert kind in {"image", "chart", "table", "graph", "map", "text", "live"}
    if isinstance(source, list):
        source = ", ".join(s for s in source if s)
    return {"id": sid, "title": title, "kind": kind, "data": data, "caption": caption, "source": source}


def not_recorded(sid: str, title: str, final: str, source: str, bullets: list | None = None) -> dict:
    """The step's in-between data is missing: show the final result, say so."""
    return step(sid, title, "text", {"text": final, "bullets": bullets or [], "note": NOT_RECORDED},
                f"{final} ({NOT_RECORDED})", source)


def chart(labels, datasets, *, ctype="bar", threshold=None, x=None, y=None, horizontal=False,
          stacked=False, highlight=None) -> dict:
    return {"type": ctype, "labels": labels, "datasets": datasets, "threshold": threshold,
            "x": x, "y": y, "horizontal": horizontal, "stacked": stacked, "highlight": highlight or []}


def table(columns, rows, highlight=None) -> dict:
    return {"columns": columns, "rows": rows, "highlight": highlight or []}


def fmt(x, nd=2):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return x
