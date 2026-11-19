#!/usr/bin/env bash
# Dome offline demo: one command, no network, no keys.
#
#   scripts/run_demo.sh                 # full demo from the private bundle
#   scripts/run_demo.sh --imageless     # same story without CoStar/Matterport/Vexcel imagery
#   scripts/run_demo.sh --port 5010
#
# Needs the private bundle made by scripts/freeze_demo.py: DOME_BUNDLE, else ../private/DomeDemoBundle next to
# the repo, else ~/DomeDemoBundle. Python: PY=/path/to/python, else ../.venv next to the repo, else python3.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -n "${DOME_BUNDLE:-}" ]; then BUNDLE="$DOME_BUNDLE"
elif [ -d "$ROOT/../private/DomeDemoBundle" ]; then BUNDLE="$(cd "$ROOT/../private/DomeDemoBundle" && pwd)"
else BUNDLE="$HOME/DomeDemoBundle"; fi
PORT=5001
IMAGELESS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --imageless) IMAGELESS=1 ;;
    --port) PORT="${2:?--port needs a number}"; shift ;;
    *) echo "unknown option: $1 (use --imageless, --port N)" >&2; exit 2 ;;
  esac
  shift
done

if [ -z "${PY:-}" ]; then
  WS="$(cd "$ROOT/.." && pwd)"
  if [ -x "$WS/.venv/bin/python" ]; then PY="$WS/.venv/bin/python"; else PY="$(command -v python3)"; fi
fi

if [ ! -f "$BUNDLE/MANIFEST.json" ]; then
  echo "No offline bundle at $BUNDLE (set DOME_BUNDLE, or build one with scripts/freeze_demo.py)." >&2
  exit 1
fi

echo "Checking the bundle manifest (sha256 of every file)…"
"$PY" "$ROOT/scripts/freeze_demo.py" --verify-only --out "$BUNDLE"

export DOME_OFFLINE=1 DOME_BUNDLE="$BUNDLE" DOME_CASE_ROOT="$BUNDLE/case"
export DOME_GLOBE=1 DOME_STEPS=1 DOME_ASK=1 DOME_MONEY=1 DOME_SPOTTER=1
if [ "$IMAGELESS" = 1 ]; then export DOME_IMAGELESS=1; fi

cd "$ROOT"
"$PY" -m dome.offline link           # the bundle's ad photos and images, as symlinks in git-ignored folders

URL="http://127.0.0.1:$PORT/?replay=real-a"
echo "Offline demo on $URL  (recorded from the real run on Nov 15, 2026)"
( sleep 3; command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 || open "$URL" >/dev/null 2>&1 || true ) &
exec "$PY" -m dome.ui.app --port "$PORT"
