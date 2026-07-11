#!/usr/bin/env bash
# Run BOTH data sources in parallel: the git scraper (harvester) and the
# synthetic generator, writing the same dataset/pairs.db concurrently (safe —
# WAL + busy_timeout). By DEFAULT they share ONE unified live dashboard split
# down the middle ([git scraper] | [generator]); pass --plain for interleaved
# prefixed log lines instead. Rows are tagged in the DB by source_system
# ('git-scraper' vs 'generator', via the pairs_labeled view). When both finish
# the source split is printed and the HTML gallery opens.
#
#   scripts/run_all.sh                          # unified dashboard, new window
#   scripts/run_all.sh --repos 30 --gen 500 --route hybrid
#   scripts/run_all.sh --here                   # unified dashboard, this terminal
#   scripts/run_all.sh --plain --here           # prefixed log lines instead
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"

REPOS=10; GEN=200; ROUTE=both; HERE=0; PLAIN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repos) REPOS="$2"; shift 2;;
    --gen)   GEN="$2";   shift 2;;
    --route) ROUTE="$2"; shift 2;;
    --here)  HERE=1;     shift;;
    --plain) PLAIN=1;    shift;;
    -h|--help) sed -n '2,16p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ -x "$PY" ] || { echo "error: $ROOT/.venv not found — pip install -r requirements.txt" >&2; exit 1; }

ensure_binary() {
  if [ ! -x "$ROOT/generator/build/disasmgen" ]; then
    echo ">> building disasmgen (first run fetches pinned asmjit/zydis)…"
    cmake -S "$ROOT/generator" -B "$ROOT/generator/build" -DCMAKE_BUILD_TYPE=Release
    cmake --build "$ROOT/generator/build" --target disasmgen -j
  fi
}

run_plain() {
  cd "$ROOT"
  echo ">> [scraper] harvest --limit $REPOS   +   [generator] --count $GEN --route $ROUTE"
  echo
  ( "$PY" -m pipeline.harvest --limit "$REPOS" --no-dashboard 2>&1 \
      | while IFS= read -r l; do printf '[scraper]   %s\n' "$l"; done ) &
  local hpid=$!
  ( "$PY" -m pipeline.generate --count "$GEN" --route "$ROUTE" --no-dashboard --no-gallery 2>&1 \
      | while IFS= read -r l; do printf '[generator] %s\n' "$l"; done ) &
  local gpid=$!
  wait "$hpid" || true
  wait "$gpid" || true
  echo
  echo ">> source split:"
  "$PY" -c "import pipeline.store as s; c=s.connect('$ROOT/dataset/pairs.db'); print('  ', dict(c.execute('SELECT source_system, COUNT(*) FROM pairs_labeled GROUP BY source_system').fetchall()))"
  "$PY" -m pipeline.gallery --out "$ROOT/dataset/gallery.html" >/dev/null
  open "$ROOT/dataset/gallery.html" 2>/dev/null || xdg-open "$ROOT/dataset/gallery.html" 2>/dev/null || true
}

if [ "$HERE" -eq 1 ]; then
  ensure_binary
  cd "$ROOT"
  if [ "$PLAIN" -eq 1 ]; then
    run_plain
  else
    exec "$PY" -m pipeline.run_both --repos "$REPOS" --gen "$GEN" --route "$ROUTE"
  fi
else
  P=""; [ "$PLAIN" -eq 1 ] && P="--plain"
  CMD="cd $(printf '%q' "$ROOT") && exec scripts/run_all.sh --here $P --repos $REPOS --gen $GEN --route $ROUTE"
  osascript \
    -e "tell application \"Terminal\" to do script \"${CMD//\"/\\\"}\"" \
    -e 'tell application "Terminal" to activate' >/dev/null
  echo "Launched scraper + generator (parallel) in a new Terminal window."
fi
