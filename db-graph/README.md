# db-graph — knowledge graph of `dataset/pairs.db`

Generated with [`dbgraph`](https://github.com/) — turns the project's SQLite database
into a small knowledge graph a local model (or a human) can navigate.

## What's here

| File | What it is |
|---|---|
| `DB_MAP.md` | Human-readable map: themes, per-table gists, and how to navigate. Inject into a model's context. |
| `dbgraph.html` | Self-contained interactive graph — open directly in a browser. |
| `graph.json` | The graph (nodes + edges) in JSON. |
| `labels.json` | Theme name/summary (hand-written). |
| `units.json` | Per-table units the scan produced. |
| `semantic_edges.json` | LLM-inferred relationships between tables (with confidence). |
| `structural_edges.json` | Structural relationships derived from the schema. |
| `semantic_cache.json` | Cached semantic enrichment (gists, keywords, edges). |

## The graph

**3 units** (the DB's three tables), **3 edges**, **1 theme** — *Disassembly Pair Corpus*:

- **`pairs`** — 642 matched (C/C++ source, x86-64 disassembly) function pairs from zlib.
- **`skipped`** — 50 translation units that failed to compile, with the compiler error.
- **`repos`** — empty provenance ledger for the future large-scale GitHub crawl.

Edges are `INFERRED`/`AMBIGUOUS` (e.g. *pairs* and *skipped* are complementary outcomes of
the same compile sweep; *repos* is the planned provenance source for both), so the
"Connections that matter" section of `DB_MAP.md` is intentionally empty — no high-confidence
foreign-key joins exist in this schema.

## Reproduce

The graph is derived from `dataset/pairs.db` (which is gitignored — regenerate it with the
pipeline first). Then:

```bash
# dbgraph must be installed: pip install -e <path-to-dbgraph>
dbgraph scan  dataset/pairs.db
# (LLM writes dataset/dbgraph-out/semantic_chunk_00.json per the batch contract)
dbgraph build dataset/pairs.db          # writes dataset/dbgraph-out/ + _dbgraph_* tables into the db
# write dataset/dbgraph-out/labels.json, then:
dbgraph build dataset/pairs.db
```

`dbgraph build` also writes `_dbgraph_units`, `_dbgraph_edges`, and `_dbgraph_themes` tables
back into `pairs.db` itself (not committed, since the db is gitignored).
