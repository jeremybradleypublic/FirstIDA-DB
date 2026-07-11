#!/usr/bin/env bash
# Run BOTH data sources in parallel in ONE terminal: the git scraper (harvester)
# and the synthetic generator, writing the same dataset/pairs.db concurrently
# (safe — WAL + busy_timeout). Each stream's output is prefixed so you can tell
# them apart; when both finish, the source split is printed and the HTML gallery
# opens. Rows are tagged in the DB by source_system ('git-scraper' vs
# 'generator', via the pairs_labeled view).
#
#   scripts/run_all.sh                          # 10 repos + 200 generated funcs
#   scripts/run_all.sh --repos 30 --gen 500 --route hybrid
#   scripts/run_all.sh --here                   # run in THIS terminal
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"

REPOS=10; GEN=200; ROUTE=both; HERE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repos) REPOS="$2"; shift 2;;
    --gen)   GEN="$2";   shift 2;;
    --route) ROUTE="$2"; shift 2;;
    --here)  HERE=1;     shift;;
    -h|--help) sed -n '2,13p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ -x "$PY" ] || { echo "error: $ROOT/.venv not found — pip install -r requirements.txt" >&2; exit 1; }

run_both() {
  cd "$ROOT"
  # Build the generator binary first (fetches asmjit/zydis once).
  if [ ! -x "$ROOT/generator/build/disasmgen" ]; then
    echo ">> building disasmgen (first run fetches pinned asmjit/zydis)…"
    cmake -S "$ROOT/generator" -B "$ROOT/generator/build" -DCMAKE_BUILD_TYPE=Release
    cmake --build "$ROOT/generator/build" --target disasmgen -j
  fi

  echo ">> starting  [scraper] harvest --limit $REPOS   +   [generator] --count $GEN --route $ROUTE"
  echo ">> (both write dataset/pairs.db in parallel; follow journals with scripts/journal.sh)"
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
  echo ">> both finished — source split in dataset/pairs.db:"
  "$PY" -c "import pipeline.store as s; c=s.connect('$ROOT/dataset/pairs.db'); print('  ', dict(c.execute('SELECT source_system, COUNT(*) FROM pairs_labeled GROUP BY source_system').fetchall()))"
  echo ">> sources list: dataset/sources_used.tsv"
  echo ">> opening gallery…"
  "$PY" -m pipeline.gallery --out "$ROOT/dataset/gallery.html" >/dev/null
  open "$ROOT/dataset/gallery.html" 2>/dev/null \
    || xdg-open "$ROOT/dataset/gallery.html" 2>/dev/null \
    || echo "   open it: $ROOT/dataset/gallery.html"
}

if [ "$HERE" -eq 1 ]; then
  run_both
else
  CMD="cd $(printf '%q' "$ROOT") && exec scripts/run_all.sh --here --repos $REPOS --gen $GEN --route $ROUTE"
  osascript \
    -e "tell application \"Terminal\" to do script \"${CMD//\"/\\\"}\"" \
    -e 'tell application "Terminal" to activate' >/dev/null
  echo "Launched scraper + generator (parallel) in a new Terminal window."
fi
