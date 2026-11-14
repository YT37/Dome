"""Shared plumbing for data_tools: env, stub flag, disk cache, HTTP backoff.

Nothing here prints or logs secret values.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]

_env_loaded = False


def load_env() -> None:
    """Load REPO_ROOT/.env once if python-dotenv is installed. Real env vars win."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / ".env", override=False)


REAL_KEYS = ("VEXCEL_API_KEY", "MATTERPORT_TOKEN_ID", "MATTERPORT_TOKEN_SECRET")


def use_stubs() -> bool:
    """DOME_STUBS=1 -> Avishek's scenario stubs (samples/scenarios/<DOME_SCENARIO>).
    DOME_STUBS=0 -> real CoStar / Matterport / Vexcel code.
    Unset -> real only when all data keys are present, so a teammate without keys still runs."""
    load_env()
    v = os.environ.get("DOME_STUBS", "").strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return not all(os.environ.get(k, "").strip() for k in REAL_KEYS)


def require_env(name: str) -> str:
    load_env()
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set. Put it in .env (see .env.example) or set DOME_STUBS=1."
        )
    return value


def cache_dir() -> Path:
    load_env()
    d = Path(os.environ.get("DOME_CACHE_DIR", REPO_ROOT / "cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:24]


def cache_path(namespace: str, key: str, ext: str) -> Path:
    d = cache_dir() / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.{ext.lstrip('.')}"


def cached_json(namespace: str, key_parts: Any, fetch: Callable[[], Any]) -> Any:
    """Return cached JSON for key_parts, calling fetch() and saving on a miss."""
    p = cache_path(namespace, cache_key(key_parts), "json")
    if p.exists():
        return json.loads(p.read_text())
    data = fetch()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(p)
    return data


def cached_file(namespace: str, key_parts: Any, ext: str, fetch: Callable[[], bytes]) -> Path:
    """Return path of a cached binary file, calling fetch() -> bytes on a miss."""
    p = cache_path(namespace, cache_key(key_parts), ext)
    if p.exists() and p.stat().st_size > 0:
        return p
    data = fetch()
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    return p


BACKOFF_S = (1, 2, 4, 8, 16)
RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_backoff(method: str, url: str, session=None, **kwargs):
    """requests call that retries 429/5xx with 1,2,4,8,16 s (+ jitter) backoff."""
    import requests

    sess = session or requests
    kwargs.setdefault("timeout", 120)
    for attempt in range(len(BACKOFF_S) + 1):
        r = sess.request(method, url, **kwargs)
        if r.status_code not in RETRY_STATUS or attempt == len(BACKOFF_S):
            return r
        time.sleep(BACKOFF_S[attempt] + random.uniform(0, 0.5))
    return r  # unreachable
