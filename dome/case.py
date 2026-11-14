"""Case folder helpers: load/save validated JSON and append to log.jsonl."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from . import config
from .schemas import FILE_MODELS, CaseInput, LogEntry, Ring

OUTPUTS = ["rings.json", "zones.json", "candidates.json", "matches.json",
           "brief.json", "summary.html", "log.jsonl"]


class Case:
    def __init__(self, case_id: str, root: Optional[Path] = None):
        self.case_id = case_id
        self.dir = Path(root or config.CASE_ROOT) / case_id
        if self.path("input.json").exists() and self.input.scenario:
            # stub data_tools read their fixture from this scenario
            os.environ["DOME_SCENARIO"] = self.input.scenario

    @classmethod
    def open(cls, case_id: str, scenario: Optional[str] = None, ring_id: Optional[str] = None,
             root: Optional[Path] = None, reset: bool = False) -> "Case":
        """Create (or reuse) the case folder. reset=True clears earlier outputs."""
        case = cls(case_id, root)
        case.dir.mkdir(parents=True, exist_ok=True)
        if reset:
            for name in OUTPUTS:
                case.path(name).unlink(missing_ok=True)
        if scenario or not case.path("input.json").exists():
            inp = CaseInput(case_id=case_id, scenario=scenario, ring_id=ring_id)
            case.path("input.json").write_text(inp.model_dump_json(indent=2), encoding="utf-8")
        return cls(case_id, root)

    # ---- files ----
    def path(self, name: str) -> Path:
        return self.dir / name

    @property
    def input(self) -> CaseInput:
        return CaseInput.model_validate_json(self.path("input.json").read_text(encoding="utf-8"))

    def check(self, name: str) -> str:
        """'missing', 'valid' or 'invalid' (against dome/schemas.py)."""
        if not self.path(name).exists():
            return "missing"
        try:
            FILE_MODELS[name].model_validate_json(self.path(name).read_text(encoding="utf-8"))
            return "valid"
        except Exception:
            return "invalid"

    def load(self, name: str) -> Any:
        """The validated model, or None if the file is missing or invalid."""
        if self.check(name) != "valid":
            return None
        return FILE_MODELS[name].model_validate_json(self.path(name).read_text(encoding="utf-8"))

    def save(self, name: str, data: Any) -> BaseModel:
        """Validate against the schema, then write. Raises on invalid data; nothing is written."""
        model = FILE_MODELS[name]
        obj = data if isinstance(data, model) else model.model_validate(
            data.model_dump() if isinstance(data, BaseModel) else data)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path(name).write_text(obj.model_dump_json(indent=2), encoding="utf-8")
        return obj

    def selected_ring(self) -> Optional[Ring]:
        """The ring this case investigates: input.ring_id, else the highest confidence."""
        rings = self.load("rings.json")
        if not rings or not rings.rings:
            return None
        want = self.input.ring_id
        for r in rings.rings:
            if r.ring_id == want:
                return r
        return max(rings.rings, key=lambda r: (r.confidence, r.ring_id))

    def hash_inputs(self, names: list[str], args: Optional[dict] = None) -> str:
        h = hashlib.sha256()
        for n in names:
            p = self.path(n)
            h.update(n.encode())
            h.update(p.read_bytes() if p.exists() else b"<missing>")
        h.update(json.dumps(args or {}, sort_keys=True, default=str).encode())
        return h.hexdigest()[:12]

    # ---- log ----
    def log(self, **fields: Any) -> LogEntry:
        entry = LogEntry(ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         case_id=self.case_id, **fields)
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.path("log.jsonl").open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")
        return entry

    def read_log(self) -> list[LogEntry]:
        p = self.path("log.jsonl")
        if not p.exists():
            return []
        return [LogEntry.model_validate_json(line)
                for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    def failed_steps(self) -> list[str]:
        out: list[str] = []
        for e in self.read_log():
            if e.event == "step_failed" and e.step and e.step not in out:
                out.append(e.step)
        return out

    def decisions(self) -> list[LogEntry]:
        return [e for e in self.read_log() if e.event == "decision"]
