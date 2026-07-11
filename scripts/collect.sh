#!/usr/bin/env bash
# Launch the data-collection harvester in its OWN macOS Terminal window, so the
# live dashboard runs in a dedicated window while this shell stays free.
#
#   scripts/collect.sh                 # discover + harvest 50 repos (default)
#   scripts/collect.sh --limit 20      # smaller run
#   scripts/collect.sh --no-discover   # drain the existing queue only
#   scripts/collect.sh --here          # run in THIS terminal (no new window)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

HERE=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--here" ]; then HERE=1; else ARGS+=("$a"); fi
done
[ ${#ARGS[@]} -eq 0 ] && ARGS=(--limit 50)

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "error: $ROOT/.venv not found — create it and 'pip install -r requirements.txt'." >&2
  exit 1
fi

if [ "$HERE" -eq 1 ]; then
  exec "$ROOT/.venv/bin/python" -m pipeline.harvest "${ARGS[@]}"
fi

CMD="cd $(printf '%q' "$ROOT") && exec .venv/bin/python -m pipeline.harvest ${ARGS[*]}"
osascript \
  -e "tell application \"Terminal\" to do script \"${CMD//\"/\\\"}\"" \
  -e 'tell application "Terminal" to activate' >/dev/null

echo "Launched collection in a new Terminal window:  harvest ${ARGS[*]}"
echo "Watch the dashboard there; this shell is free."
