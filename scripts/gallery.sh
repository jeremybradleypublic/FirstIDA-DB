#!/usr/bin/env bash
# Build the HTML gallery of generated (source, asm) pairs and open it in the
# default browser. Passes flags through to `python -m pipeline.gallery`.
#
#   scripts/gallery.sh                       # newest 300 generated pairs
#   scripts/gallery.sh --route hybrid --limit 100
#   scripts/gallery.sh --all                 # include harvested rows too
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dataset/gallery.html"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "error: $ROOT/.venv not found — create it and 'pip install -r requirements.txt'." >&2
  exit 1
fi

"$ROOT/.venv/bin/python" -m pipeline.gallery --out "$OUT" "$@"
open "$OUT" 2>/dev/null || echo "open it: $OUT"
