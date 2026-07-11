#!/usr/bin/env bash
# Build the dbgraph knowledge graph for the dataset and refresh db-graph/.
# Run this AFTER the pipeline has populated the database.
#
#   scripts/build_graph.sh [--db PATH] [--enrich] [--serve] [--structural-only]
#
#   --db PATH          database to graph        (default: dataset/pairs.db)
#   --enrich           run a headless `claude` session to add per-table gists
#   --structural-only  skip semantic enrichment entirely (fastest)
#   --serve            open the interactive graph locally when done
#
# By default the graph is structural, reusing any semantic enrichment already
# cached in dbgraph-out/. Rich per-table gists come from either:
#   * running the /dbgraph skill in Claude Code (writes semantic_chunk_*.json), or
#   * passing --enrich (headless claude), or
#   * an existing dbgraph-out/semantic_cache.json from a previous run.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DB="$REPO/dataset/pairs.db"
OUT_COPY="$REPO/db-graph"
ENRICH=0; SERVE=0; STRUCT_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB="$2"; shift 2;;
    --enrich) ENRICH=1; shift;;
    --serve) SERVE=1; shift;;
    --structural-only) STRUCT_ONLY=1; shift;;
    -h|--help) sed -n '2,14p' "$0"; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

# Resolve a working dbgraph command; prefer the project venv so nested tools resolve it too.
if [ -x "$REPO/.venv/bin/dbgraph" ]; then
  DBG="$REPO/.venv/bin/dbgraph"
  export PATH="$REPO/.venv/bin:$PATH"
elif command -v dbgraph >/dev/null 2>&1; then
  DBG="dbgraph"
else
  echo "error: dbgraph is not installed." >&2
  echo "  install it:  $REPO/.venv/bin/pip install <path-to-dbgraph>" >&2
  exit 1
fi

if [ ! -f "$DB" ]; then
  echo "error: database not found: $DB" >&2
  echo "  build it first:  $REPO/.venv/bin/python -m pipeline.run_pipeline <repo_dir> --repo NAME" >&2
  exit 1
fi

OUTDIR="$(dirname "$DB")/dbgraph-out"

echo ">> scan  ($DB)"
"$DBG" scan "$DB"

if [ "$STRUCT_ONLY" -eq 1 ]; then
  echo ">> semantic: skipped (--structural-only)"
elif [ -f "$OUTDIR/semantic_cache.json" ] || ls "$OUTDIR"/semantic_chunk_*.json >/dev/null 2>&1; then
  echo ">> semantic: reusing existing enrichment in $OUTDIR"
elif [ "$ENRICH" -eq 1 ] && command -v claude >/dev/null 2>&1; then
  echo ">> semantic: enriching via headless claude (best-effort)"
  claude -p "Run /dbgraph resume on $DB: read pending_semantic.json in the dbgraph-out \
directory next to that database; for each batch dispatch one general-purpose subagent \
(all in one message) to write dbgraph-out/semantic_chunk_NN.json per the embedded \
instructions; then run 'dbgraph build $DB'; then write dbgraph-out/labels.json naming \
each theme in pending_labels.json and run 'dbgraph build $DB' once more." \
    --allowedTools "Bash,Read,Write,Agent" \
    || echo ">> semantic: claude enrichment failed; continuing structural-only" >&2
else
  echo ">> semantic: none available; building structural-only"
  echo "   (run the /dbgraph skill in Claude Code, or pass --enrich, for per-table gists)"
fi

echo ">> build"
"$DBG" build "$DB"

echo ">> refreshing $OUT_COPY/"
mkdir -p "$OUT_COPY"
for f in DB_MAP.md dbgraph.html graph.json labels.json units.json \
         semantic_edges.json structural_edges.json semantic_cache.json; do
  if [ -f "$OUTDIR/$f" ]; then cp "$OUTDIR/$f" "$OUT_COPY/"; fi
done

echo ""
echo "done."
echo "  map:   $OUT_COPY/DB_MAP.md"
echo "  graph: $OUT_COPY/dbgraph.html   (open in a browser)"

if [ "$SERVE" -eq 1 ]; then
  echo ">> serving (Ctrl-C to stop)"
  "$DBG" serve "$DB"
fi
