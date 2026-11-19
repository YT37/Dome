#!/usr/bin/env bash
# Dome online mode: the real data tools (CoStar kit, Matterport, Vexcel, Gemini), when access returns.
#
#   scripts/run_online.sh            # check access, then start the UI on the live tools
#   scripts/run_online.sh --run      # also run the real case first (case/real-a), then start the UI
#   scripts/run_online.sh --port 5003
#
# Keys live in ../private/.env (repo/.env is a link to it). With no access, use scripts/run_demo.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=5003
RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --run) RUN=1 ;;
    --port) PORT="${2:?--port needs a number}"; shift ;;
    *) echo "unknown option: $1 (use --run, --port N)" >&2; exit 2 ;;
  esac
  shift
done
if [ -z "${PY:-}" ]; then
  WS="$(cd "$ROOT/.." && pwd)"
  if [ -x "$WS/.venv/bin/python" ]; then PY="$WS/.venv/bin/python"; else PY="$(command -v python3)"; fi
fi
unset DOME_OFFLINE DOME_IMAGELESS DOME_BUNDLE
cd "$ROOT"

"$PY" scripts/check_access.py || echo "Some services are missing: cached requests still work, uncached ones will fail."

export DOME_STUBS=0 DOME_GLOBE=1 DOME_STEPS=1 DOME_ASK=1 DOME_MONEY=1 DOME_SPOTTER=1 DOME_GRAPH_ASSISTANT=dome_rules
if [ "$RUN" = 1 ]; then
  echo "Running the real case (scripted planner)…"
  "$PY" -m dome.supervisor --case real-a --data synth --scripted
  "$PY" -m dome.agents.briefer --case real-a --score data/answer_key/answer_key.json
fi

echo "Online UI on http://127.0.0.1:$PORT/"
exec "$PY" -m dome.ui.app --port "$PORT"
