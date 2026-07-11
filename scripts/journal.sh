#!/usr/bin/env bash
# View the collection journal (persistent activity log written by the harvester).
#
#   scripts/journal.sh            # last 40 entries
#   scripts/journal.sh -f         # follow live (tail -f style)
#   scripts/journal.sh --tail 200
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/.venv/bin/python" -m pipeline.journal "$@"
