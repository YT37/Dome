"""Firebase Python function serving the Dome UI at dome.surf (public mode).

Public mode (DOME_PUBLIC=1): the page replays the recorded real run (addresses already blanked by
scripts/record_demo_case.py); "Run Case" replays instead of running the pipeline; the Ask box is live
(Gemini key from Secret Manager, never in code) and rate-limited. The function's own folder is
read-only, so case clicks and new Gemini answers go to /tmp.
"""
import os
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
for k, v in {"DOME_PUBLIC": "1", "DOME_GLOBE": "1", "DOME_STEPS": "1", "DOME_ASK": "1", "DOME_STUBS": "1",
             "DOME_MONEY": "1", "DOME_SPOTTER": "1", "DOME_GRAPH_ASSISTANT": "dome_rules",
             "DOME_MODEL": "google_genai:gemini-3.5-flash",
             "DOME_CASE_ROOT": "/tmp/dome/case", "DOME_VISION_CACHE": "/tmp/dome/gemini"}.items():
    os.environ.setdefault(k, v)
for src, dst in ((HERE / "case", Path(os.environ["DOME_CASE_ROOT"])),
                 (HERE / "cache" / "gemini", Path(os.environ["DOME_VISION_CACHE"]))):
    if src.exists() and not dst.exists():
        shutil.copytree(src, dst)

from firebase_functions import https_fn, options  # noqa: E402

from dome.ui.app import app as flask_app  # noqa: E402


@https_fn.on_request(region="us-central1", memory=options.MemoryOption.GB_1, timeout_sec=120,
                     max_instances=3, secrets=["GOOGLE_API_KEY"])
def dome(req: https_fn.Request) -> https_fn.Response:
    with flask_app.request_context(req.environ):
        return flask_app.full_dispatch_request()
