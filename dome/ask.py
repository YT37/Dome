"""Ask about a case (Ishaan, contract H): answers only from the case folder, with citations.

    from dome.ask import answer
    answer("real-a", "Why is Building A High?")
    -> {"answer": "...", "citations": [{"file": "case/real-a/brief.json", "path": "leads[0].reasons[0]"}],
        "answerable": true}

Rules (enforced in code, not just in the prompt):
- Loads only case/<id>/*.json. Never the answer key, never the dataset, never the web.
- The model must cite a file and field for every claim. Each citation is checked: the file must
  be in this case folder and the field path must exist in it; anything else is dropped.
- An answer left with no valid citation becomes "That isn't in this case's files."
- No tool can contact, dispatch or publish anything; this only reads and answers.
Model: LangChain init_chat_model(DOME_MODEL), e.g. google_genai:gemini-3.5-flash.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from . import config

NOT_IN_CASE = "That isn't in this case's files."
CASE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_CHARS_PER_FILE = 15000
PATH_TOKEN = re.compile(r"([A-Za-z_][\w-]*)|\[(\d+)\]")

SYSTEM = (
    "You answer questions about one investigation case. All data is synthetic. "
    "Use ONLY the JSON files given below. Every claim must cite the file and the field it comes from. "
    "If the files do not contain the answer, say so. Never guess, never use outside knowledge, "
    "never give an address. Reply with JSON only: "
    '{"answer": "...", "citations": [{"file": "case/<id>/<name>.json", "path": "field.sub[0].x"}], "answerable": true|false}'
)


def case_files(case_id: str, root: Optional[Path] = None) -> dict[str, Any]:
    """{'case/<id>/<name>.json': parsed JSON} for every JSON file in the case folder."""
    if not CASE_ID.match(case_id or ""):
        return {}
    folder = Path(root or config.CASE_ROOT) / case_id
    out = {}
    for p in sorted(folder.glob("*.json")):
        try:
            out[f"case/{case_id}/{p.name}"] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def resolve(data: Any, path: str) -> bool:
    """Does `path` (e.g. 'leads[0].reasons[0]') exist in data?"""
    cur = data
    for name, idx in PATH_TOKEN.findall(path or ""):
        try:
            cur = cur[int(idx)] if idx else cur[name]
        except (KeyError, IndexError, TypeError, ValueError):
            return False
    return bool(path)


def _model():
    from langchain.chat_models import init_chat_model
    return init_chat_model(os.getenv("DOME_MODEL", config.MODEL))


def _parse(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def answer(case_id: str, question: str, root: Optional[Path] = None, model=None) -> dict:
    files = case_files(case_id, root)
    refusal = {"answer": NOT_IN_CASE, "citations": [], "answerable": False}
    if not files or not (question or "").strip():
        return refusal
    blob = "\n\n".join(f"=== {name} ===\n{json.dumps(data)[:MAX_CHARS_PER_FILE]}" for name, data in files.items())
    llm = model or _model()
    msg = llm.invoke([("system", SYSTEM), ("user", f"Case files:\n{blob}\n\nQuestion: {question.strip()}")])
    parsed = _parse(getattr(msg, "content", msg) if not isinstance(msg, str) else msg)
    if not parsed or not parsed.get("answerable"):
        return refusal
    cites = [c for c in parsed.get("citations", []) if isinstance(c, dict)
             and c.get("file") in files and resolve(files[c["file"]], c.get("path", ""))]
    if not cites:
        return refusal
    return {"answer": str(parsed.get("answer", "")).strip(), "citations": cites, "answerable": True}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Ask a question about a case (answers only from its files)")
    ap.add_argument("--case", required=True)
    ap.add_argument("question")
    a = ap.parse_args()
    print(json.dumps(answer(a.case, a.question), indent=2))
