"""Which live services does this machine have access to right now? (online mode)

    python scripts/check_access.py

Reads the keys from `.env` (repo/.env -> ../private/.env) and makes one small read-only request per
service. Prints OK or FAIL per service; never prints a key. Exit code 0 when the data tools a real
run needs (CoStar kit, Matterport, Vexcel) all work.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if os.environ.get("DOME_OFFLINE") == "1":
    sys.exit("check_access is for online mode; unset DOME_OFFLINE")
os.environ["DOME_STUBS"] = "0"

from dome import config  # noqa: E402  (loads .env)

A_SCAN, A_LAT, A_LON = "LqCMcmmVH3d", 29.753766, -95.377337


def costar():
    from dome.data_tools import costar as cs
    kit = cs.kit_dir()
    if not (kit / "data").exists():
        raise RuntimeError(f"CoStar kit not found at {kit}")
    return f"kit at {kit.resolve()}"


def matterport():
    from dome.data_tools import matterport as mp
    body = mp.graphql('query($id: ID!){ model(id: $id){ id } }', {"id": A_SCAN})
    return "model query answered" if body["data"]["model"]["id"] == A_SCAN else "unexpected answer"


def vexcel():
    from dome.data_tools import _common, vexcel as vx
    r = _common.request_with_backoff("GET", f"{vx.API}/property/extract", headers=vx._headers(), timeout=60,
                                     params={"wkt": vx.square_wkt(A_LAT, A_LON, 15), "layers": "building_outline"})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return "footprint query answered"


def gemini():
    from langchain.chat_models import init_chat_model
    init_chat_model(os.getenv("DOME_MODEL", config.MODEL)).invoke("Reply with the word ok")
    return f"{os.getenv('DOME_MODEL', config.MODEL)} answered"


def langsmith():
    if not os.environ.get("LANGSMITH_API_KEY"):
        raise RuntimeError("no LANGSMITH_API_KEY")
    from langsmith import Client
    list(Client().list_runs(project_name=os.getenv("LANGSMITH_PROJECT", "dome"), limit=1))
    return "runs listed"


def main() -> int:
    needed = {"CoStar kit": costar, "Matterport": matterport, "Vexcel": vexcel}
    optional = {"Gemini": gemini, "LangSmith": langsmith}
    ok_needed = True
    for group, checks in (("needed for a real run", needed), ("optional", optional)):
        print(f"{group}:")
        for name, fn in checks.items():
            try:
                print(f"  OK    {name:11s} {fn()}")
            except Exception as exc:
                print(f"  FAIL  {name:11s} {type(exc).__name__}: {str(exc)[:120]}")
                ok_needed &= group == "optional"
    print("\nOnline mode is ready." if ok_needed else
          "\nOnline mode needs every 'needed' service. Without them, use scripts/run_demo.sh (offline).")
    return 0 if ok_needed else 1


if __name__ == "__main__":
    sys.exit(main())
