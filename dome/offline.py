"""Offline demo mode: DOME_OFFLINE=1 with DOME_BUNDLE=<private bundle folder>.

Everything the real run needs comes from the frozen bundle (scripts/freeze_demo.py): the API
responses and images the run read, a trimmed CoStar database without addresses, the saved Gemini
answers and the model weights. In this mode:
- `.env` is never read and no key is needed;
- every cache read goes to <bundle>/cache; a request that is not in the bundle raises
  OfflineMiss("not in offline bundle: ...") and never falls back to the network;
- Hugging Face and Transformers run offline on <bundle>/models;
- a socket guard refuses every connection except localhost and logs the call site.

Results shown come from the real run on Nov 15, 2026 (recorded) or are recomputed from the frozen
inputs; the UI labels which is which.
"""
from __future__ import annotations

import os
import socket
import sys
import traceback
from pathlib import Path

RECORDED_ON = "Nov 15, 2026"
_installed = False
BLOCKED: list[str] = []          # call sites of refused connections (for tests and the log)


class OfflineMiss(RuntimeError):
    """A request the offline bundle does not hold."""


def enabled() -> bool:
    return os.environ.get("DOME_OFFLINE") == "1"


def imageless() -> bool:
    return enabled() and os.environ.get("DOME_IMAGELESS") == "1"


def bundle() -> Path:
    b = os.environ.get("DOME_BUNDLE")
    if not b:
        raise OfflineMiss("DOME_OFFLINE=1 needs DOME_BUNDLE=<path to the offline bundle>")
    return Path(b).expanduser().resolve()


def miss(what: str) -> OfflineMiss:
    return OfflineMiss(f"not in offline bundle: {what}")


def _is_local(address) -> bool:
    if isinstance(address, (str, bytes)):          # unix socket path
        return True
    host = address[0] if isinstance(address, tuple) and address else ""
    return host in ("127.0.0.1", "::1", "localhost", "0.0.0.0", "") or str(host).startswith("127.")


def _guard_socket() -> None:
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex

    def _refuse(address):
        site = "".join(traceback.format_stack(limit=8)[:-2]).strip().splitlines()
        where = next((l.strip() for l in reversed(site) if l.strip().startswith("File") and "/dome/" in l), site[-1] if site else "?")
        BLOCKED.append(f"{address!r} from {where}")
        sys.stderr.write(f"[dome offline] blocked a network connection to {address!r} ({where})\n")
        raise OSError(f"offline demo: network access is disabled (tried {address!r})")

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address):
            _refuse(address)
        return orig_connect(self, address)

    def connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address):
            _refuse(address)
        return orig_connect_ex(self, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


def setup() -> None:
    """Called once at import of the `dome` package when DOME_OFFLINE=1."""
    global _installed
    if _installed or not enabled():
        return
    _installed = True
    b = bundle()
    if not (b / "MANIFEST.json").exists():
        raise OfflineMiss(f"no offline bundle at {b} (MANIFEST.json missing)")
    os.environ.update({
        "DOME_CACHE_DIR": str(b / "cache"),
        "DOME_VISION_CACHE": str(b / "cache" / "gemini"),
        "DOME_STUBS": "0",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
        "HF_HOME": str(b / "models" / "huggingface"),
        "HF_HUB_CACHE": str(b / "models" / "huggingface" / "hub"),
        "TORCH_HOME": str(b / "models" / "torch"),
        "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false",
        "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
    })
    for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "LANGSMITH_API_KEY",
              "MATTERPORT_TOKEN_ID", "MATTERPORT_TOKEN_SECRET", "VEXCEL_API_KEY"):
        os.environ.pop(k, None)                    # nothing in this mode may use a key
    _guard_socket()


# ---------------------------------------------------------------------- bundle files for a clone
LINKED = ("data/photos", "data/matches", "data/demo_assets")


def link_data(repo_root: Path) -> list[str]:
    """Make the bundle's git-ignored data (ad photos, match images, asset-pack images) visible at the
    paths the code reads, as symlinks. Never overwrites a file that is already there."""
    b, made = bundle(), []
    for sub in LINKED:
        src_root = b / sub
        if not src_root.exists():
            continue
        for src in src_root.rglob("*"):
            if not src.is_file():
                continue
            dst = repo_root / src.relative_to(b)
            if dst.exists() or dst.is_symlink():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src)
            made.append(str(dst.relative_to(repo_root)))
    return made


if __name__ == "__main__":       # python -m dome.offline link
    if sys.argv[1:] == ["link"]:
        root = Path(__file__).resolve().parents[1]
        os.environ.setdefault("DOME_OFFLINE", "1")
        print(f"linked {len(link_data(root))} bundle files into the repo's ignored data folders")
