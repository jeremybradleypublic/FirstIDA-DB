# create_disasm_dataset

Builds a dataset of `(assembly, C/C++ source)` **function pairs**: `X` = x86-64
`objdump` disassembly of one function, `Y` = the original source function.
See `docs/DESIGN.md` for the full design and `docs/superpowers/plans/` for the plans.

## Prerequisites

- macOS with [Homebrew](https://brew.sh).
- Everything else is installed/provisioned automatically:
  - `brew install colima docker` (one-time; the pipeline starts Colima and builds
    the toolchain image on first run).
- Python env:
  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  ```

> Note: repositories to process must live under your home directory (`$HOME`).
> Colima only virtiofs-mounts `$HOME` by default, so a repo outside it (e.g. under
> the OS temp dir) would mount empty inside the toolchain container.

## Reproduce the zlib dataset (end-to-end)

```bash
git clone https://github.com/madler/zlib first_example/zlib   # sample repo (gitignored)
.venv/bin/python -m pipeline.run_pipeline first_example/zlib --repo zlib
```

This auto-starts the Linux x86-64 toolchain container (GCC + Clang + binutils),
compiles every translation unit at `-O0/-O1/-O2/-O3/-Os` with both compilers,
disassembles with `objdump`, pairs each symbol back to its source function, and
writes unique pairs into `dataset/pairs.db`.

Reference run (zlib): **642 pairs**, 69 distinct functions, all five opt levels,
both `gcc-12.2.0` and `clang-14.0.6`; 50 translation units that don't compile in
isolation (mostly `contrib/` needing platform headers) are logged to `skipped`.

## Point it at any other repo

```bash
.venv/bin/python -m pipeline.run_pipeline /path/to/any/c_or_cpp/repo --repo myrepo
```

Files that don't compile in isolation are logged to the `skipped` table and never
abort the run. Re-running is idempotent (dedup via `pairs.pair_hash`).

## Database

SQLite at `dataset/pairs.db` (gitignored — reproducible via the pipeline).

- `pairs(repo,file_path,func_name,signature,lang,arch,opt_level,obj_format,compiler,source_text,asm_text,...,pair_hash UNIQUE)`
- `skipped(repo,file_path,opt_level,reason)`
- `repos(url,commit_sha,license,status,n_pairs,processed_at)` — used by the Phase-2 scraper.

Example query:
```bash
sqlite3 dataset/pairs.db \
  "SELECT func_name,opt_level,compiler FROM pairs WHERE repo='zlib' LIMIT 10;"
```

## Knowledge graph (dbgraph)

Once the database is populated, turn it into a navigable knowledge graph with the
integrated wrapper. It scans the DB, (optionally) enriches per-table gists, builds the
graph, and refreshes the committed `db-graph/` folder.

```bash
# one-time: install the dbgraph tool into the venv
# (auto-reinstalled by the dbgraph repo's post-commit hook on every tool update)
.venv/bin/pip install /path/to/dbgraph

scripts/build_graph.sh                 # structural graph, reuses any cached gists
scripts/build_graph.sh --enrich        # add per-table gists via a headless `claude` run
scripts/build_graph.sh --serve         # build, then open the interactive graph locally
scripts/build_graph.sh --structural-only   # fastest; no LLM step
```

Outputs land in `dataset/dbgraph-out/` (gitignored working dir) and the curated copies are
mirrored into **`db-graph/`** (`DB_MAP.md`, self-contained `dbgraph.html`, `graph.json`, …).
`dbgraph build` also writes `_dbgraph_units` / `_dbgraph_edges` / `_dbgraph_themes` tables
back into `pairs.db`. For the richest gists inside Claude Code, run the `/dbgraph` skill,
then `scripts/build_graph.sh` to mirror the result. `db-graph/` auto-updates: the dbgraph
source repo's post-commit hook reinstalls the tool here, reruns the wrapper, and commits +
pushes when the graph changes. Architecture diagrams and the full artifact reference:
`db-graph/README.md`.

## Testing

```bash
.venv/bin/pytest -v            # unit tests always run; integration tests need Docker
```
Integration tests auto-skip when Docker/Colima is unavailable; start it with
`colima start` (or `colima start --vm-type=vz --vz-rosetta` for faster x86-64 emulation).

## Troubleshooting

- **Colima won't start:** `colima delete && colima start`.
- **Rebuild the toolchain image:** `docker rmi disasm-toolchain:latest` then re-run.
- **x86-64 emulation:** builds run under `--platform linux/amd64` (Rosetta); we only
  compile/disassemble, never execute, so this only affects compile latency.

## Synthetic generator (`generator/` + `pipeline/generate.py`)

Alongside the GitHub harvester there is a generative track: a native C++ tool
`generator/disasmgen` (CMake; asmjit + zydis pinned via FetchContent) that
prints JSONL and never touches the DB. Two routes:

- **direct** — parameterized C/C++ templates; Python compiles them through the
  existing container toolchain (gcc/clang x O0–Os) so the asm is real objdump
  output. Rows get `origin='gen:direct'`.
- **hybrid** — a tiny typed IR is pretty-printed to C *and* lowered by asmjit
  to x86-64 bytes decoded by zydis. Correspondence by construction, no
  compiler. Rows get `origin='gen:hybrid'` (`obj_format='rawx86_64'`,
  `compiler='asmjit'`, `opt_level='none'`).

Run it in its own Terminal window (safe in parallel with `scripts/collect.sh`;
same `dataset/pairs.db`, own journal `dataset/journal-gen.jsonl`):

```bash
scripts/generate.sh --count 200 --route both
scripts/journal.sh --path dataset/journal-gen.jsonl -f   # follow its journal
```

Harvested rows are backfilled with `origin='harvest'` by `store.migrate()`.

### Seeing what was generated

Each synthesized function streams into the run's journal/dashboard as it is
created (name + signature), so you watch them appear live. After a run,
`generate.py` also builds an interactive, self-contained **HTML console**
(`dataset/gallery.html`) covering BOTH data sources, with four tabs:

- **Pairs** — every `(source, asm)` pair from the scraper *and* the generator,
  filterable by source system, route, **session**, language, and full-text
  search. Hybrid asm carries a `<symbol>:` header so it reads like the
  objdump-derived scraper/direct asm.
- **Journal** — the live activity logs of both the scraper and the generator.
- **Sources** — the git repos the scraper used (sortable; stars/license/pairs).
- **Graph** — the dbgraph knowledge graph, embedded.

```bash
scripts/gallery.sh                      # build + open the console
python -m pipeline.gallery --route hybrid --limit 200
```

Each generator/scraper run tags its rows with a `session` id, so the console
lets you browse different runs. The console is written to `dataset/gallery.html`
(gitignored; rebuild anytime).

### Running both sources at once

`scripts/run_all.sh` runs the git scraper and the generator **in parallel**, both
writing the same `dataset/pairs.db` (safe — WAL + `busy_timeout`). By default they
share **one unified live dashboard** split down the middle — `[git scraper]` on the
left, `[generator]` on the right, each with its own progress, totals, and live
activity box. When both finish it prints the source split and opens the gallery.

```bash
scripts/run_all.sh                       # unified split dashboard, new window
scripts/run_all.sh --repos 30 --gen 500 --route hybrid
scripts/run_all.sh --here                # unified dashboard in this terminal
scripts/run_all.sh --plain --here        # interleaved [scraper]/[generator] log lines instead
```

### Telling the two data sources apart

`pairs.db` self-documents provenance. Every row has an `origin`
(`harvest` | `gen:direct` | `gen:hybrid`), and the **`pairs_labeled`** view adds a
coarse `source_system` column so it's obvious at a glance:

```sql
SELECT source_system, COUNT(*) FROM pairs_labeled GROUP BY source_system;
--  git-scraper | 84974      (repos mined by the scraper)
--  generator   |   298      (synthesized by disasmgen)
```

The scraper also writes **`dataset/sources_used.tsv`** — the list of every git
repo it used (url, status, stars, license, commit, n_pairs) — after each run, or
on demand with `python -m pipeline.harvest --export-sources`.
