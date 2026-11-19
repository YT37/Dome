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
LIVE_OFF = "live questions are off now that the hackathon is over"
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


def _no_addresses(x: Any) -> Any:
    """Real cases carry CoStar street addresses internally; they never go to the model."""
    if isinstance(x, dict):
        return {k: ("" if k == "address" else _no_addresses(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [_no_addresses(v) for v in x]
    return x


def case_files(case_id: str, root: Optional[Path] = None) -> dict[str, Any]:
    """{'case/<id>/<name>.json': parsed JSON} for every JSON file in the case folder."""
    if not CASE_ID.match(case_id or ""):
        return {}
    folder = Path(root or config.CASE_ROOT) / case_id
    out = {}
    for p in sorted(folder.glob("*.json")):
        try:
            out[f"case/{case_id}/{p.name}"] = _no_addresses(json.loads(p.read_text(encoding="utf-8")))
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


def _recorded_answer(case_id: str, question: str, root: Optional[Path]) -> Optional[dict]:
    """Offline demo: the question asked during the real run (case/<id>/ask.json), answered with what
    the model said then, labelled as recorded. Any other question gets no answer offline."""
    norm = lambda q: re.sub(r"[^a-z0-9 ]", "", (q or "").lower()).split()   # noqa: E731
    p = Path(root or config.CASE_ROOT) / case_id / "ask.json"
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if norm(rec.get("question")) != norm(question):
        return None
    return {"answer": rec.get("answer", ""), "citations": rec.get("citations", []),
            "answerable": bool(rec.get("answerable")), "recorded": True,
            "note": "Recorded answer from the real run on Nov 15, 2026 (offline demo)"}


def _cached_invoke(user: str) -> str:
    """The model's raw reply, cached under cache/gemini/ask_<hash>.json keyed by model +
    system prompt + case files + question (free-tier quota: same question, no new call)."""
    import hashlib
    from .data_tools.gemini_vision import cache_dir, log_call
    model_name = os.getenv("DOME_MODEL", config.MODEL)
    key = hashlib.sha256("\x1f".join((model_name, SYSTEM, user)).encode()).hexdigest()[:20]
    path = cache_dir() / f"ask_{key}.json"
    if path.exists():
        try:
            text = json.loads(path.read_text(encoding="utf-8"))["text"]
            log_call("ask", cached=True)
            return text
        except (KeyError, ValueError):
            pass
    if os.getenv("DOME_OFFLINE") == "1":
        raise RuntimeError("not recorded in the offline demo")
    try:
        msg = _model().invoke([("system", SYSTEM), ("user", user)])
    except Exception as exc:
        from .data_tools.gemini_vision import is_quota_error
        log_call("ask", cached=False, ok=False, note="quota" if is_quota_error(exc) else type(exc).__name__)
        raise
    content = getattr(msg, "content", msg)
    if isinstance(content, list):               # some chat models return a list of parts
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    text = content if isinstance(content, str) else json.dumps(content)
    log_call("ask", cached=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model_name, "text": text}, indent=1), encoding="utf-8")
    return text


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
    if os.getenv("DOME_OFFLINE") == "1":
        rec = _recorded_answer(case_id, question, root)
        if rec is not None:
            return rec
    blob = "\n\n".join(f"=== {name} ===\n{json.dumps(data)[:MAX_CHARS_PER_FILE]}" for name, data in files.items())
    user = f"Case files:\n{blob}\n\nQuestion: {question.strip()}"
    if model is not None:                       # injected model (tests): no disk cache
        msg = model.invoke([("system", SYSTEM), ("user", user)])
        text = getattr(msg, "content", msg) if not isinstance(msg, str) else msg
    else:
        try:
            text = _cached_invoke(user)
        except Exception as exc:                # no cached answer and the call failed
            from .data_tools.gemini_vision import is_quota_error
            if os.getenv("DOME_PUBLIC") == "1":     # hosted site after the hackathon: no model key
                return {**refusal, "reason": LIVE_OFF}
            if os.getenv("DOME_OFFLINE") == "1":
                return {**refusal, "reason": "This question wasn't recorded in the offline demo"}
            note = "Gemini quota reached and no cached answer for this question" if is_quota_error(exc) \
                else f"model call failed ({type(exc).__name__})"
            return {**refusal, "reason": note}
    parsed = _parse(text if isinstance(text, str) else json.dumps(text))
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
