#!/usr/bin/env bash
# Launch the synthetic-pair generator in its OWN macOS Terminal window, so the
# live dashboard runs in a dedicated window while this shell stays free. Safe
# to run WHILE scripts/collect.sh is harvesting: the generator has its own
# journal (dataset/journal-gen.jsonl) and the shared DB is WAL + busy_timeout.
#
#   scripts/generate.sh                          # both routes, 100 funcs each
#   scripts/generate.sh --count 500 --route hybrid
#   scripts/generate.sh --route direct --seed 7
#   scripts/generate.sh --here ...               # run in THIS terminal
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

HERE=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--here" ]; then HERE=1; else ARGS+=("$a"); fi
done
[ ${#ARGS[@]} -eq 0 ] && ARGS=(--count 100)

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "error: $ROOT/.venv not found — create it and 'pip install -r requirements.txt'." >&2
  exit 1
fi

# Build the native generator if missing (first configure fetches the pinned
# asmjit/zydis sources, so it needs the network once).
BIN="$ROOT/generator/build/disasmgen"
if [ ! -x "$BIN" ]; then
  if ! command -v cmake >/dev/null 2>&1; then
    echo "error: cmake is required to build generator/disasmgen." >&2
    exit 1
  fi
  echo ">> building disasmgen (first run fetches pinned asmjit/zydis)"
  cmake -S "$ROOT/generator" -B "$ROOT/generator/build" -DCMAKE_BUILD_TYPE=Release
  cmake --build "$ROOT/generator/build" --target disasmgen -j
fi

if [ "$HERE" -eq 1 ]; then
  exec "$ROOT/.venv/bin/python" -m pipeline.generate "${ARGS[@]}"
fi

CMD="cd $(printf '%q' "$ROOT") && exec .venv/bin/python -m pipeline.generate ${ARGS[*]}"
osascript \
  -e "tell application \"Terminal\" to do script \"${CMD//\"/\\\"}\"" \
  -e 'tell application "Terminal" to activate' >/dev/null

echo "Launched generator in a new Terminal window:  generate ${ARGS[*]}"
echo "Watch the dashboard there; this shell is free."
echo "Journal: scripts/journal.sh --path dataset/journal-gen.jsonl -f"
