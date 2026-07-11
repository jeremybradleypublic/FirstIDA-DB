# disasmgen — C++ synthetic (asm, source) pair generator

**Status:** approved design · **Date:** 2026-07-11

## Purpose

Grow the FirstIDA-DB dataset of `(asm, C/C++ source)` function pairs with a
*generative* track that complements the existing GitHub harvester
(`pipeline/harvest.py`). Where the harvester mines real repos, this generator
manufactures pairs from scratch, so the dataset can be grown "at large" without
depending on repo availability, and can cover regions of code-shape space that
real repos under-sample.

Generated pairs live in the **same** `dataset/pairs.db` but are explicitly
marked distinct from harvested pairs via a new `origin` column. The generator
runs as its own process, in **parallel** with the harvester, with its own
journal stream, its own live terminal dashboard, and a dbgraph refresh.

## Scope

Two generation routes (a third "solely-off-asm" route was considered and
**dropped** as unstable — reconstructing source from asm with no compiler or
authored source is unreliable):

1. **Direct** — synthesize C/C++ source, compile it through the existing
   container toolchain, disassemble with objdump. Compiler in the loop;
   correspondence guaranteed.
2. **Hybrid (asmjit/zydis)** — from a small internal function IR, render real C
   source *and* emit x86-64 machine code with asmjit, then decode it with
   zydis. Correspondence guaranteed by construction; no compiler.

Out of scope for this spec: a template config/DSL (templates live in C++ and
grow by editing), non-x86-64 architectures, and PE/Windows toolchains (a seam is
left for them but they are not built now).

## Architecture

```
generator/  (C++ · CMake · native binary)            pipeline/  (Python)
  disasmgen direct  ──►  JSONL {name, lang, signature, source}       │
  disasmgen hybrid  ──►  JSONL {name, lang, signature, source, asm,  │
                                obj_format, compiler, opt_level}     │
                                                                     ▼
                                          pipeline/generate.py  (ingest driver)
                                            • direct → compile each source through
                                              the EXISTING env→compile→disasm→pair
                                              pipeline → real objdump asm
                                            • hybrid → ingest full pairs as-is
                                            • store.insert_pair(origin=…), dedup
                                              by pair_hash
                                            • own /journal stream + dbgraph refresh
```

**Key boundary:** the C++ binary is a *pure generator* — it prints JSONL and
touches no database. Python owns every DB write, so hashing, dedup, journaling,
and dbgraph integration are reused, not reimplemented in C++.

### Component: `generator/` (C++)

- Top-level directory, sibling to `pipeline/`. One CLI binary `disasmgen` with
  subcommands `direct` and `hybrid` (plus `--count`, `--seed`, `--out` for JSONL
  path or stdout).
- Build: CMake. Dependencies **asmjit** (zlib license) and **zydis** (MIT)
  pulled via `FetchContent` at pinned tags. Builds natively on macOS, Linux, and
  Windows (no OS-specific code in the generator).
- Each unit is independently testable: the source synthesizer, the IR, the IR→C
  renderer, the IR→asmjit lowerer, and the zydis formatter.

#### Route 1 — Direct synthesizer

Emits diverse, self-contained functions from parameterized templates:
arithmetic/reduction loops, memcpy/dot-product, bitwise ops, branchy compares,
struct field access, bounded recursion, small string ops. Each template is swept
over element types (`int`, `unsigned`, `long`, `float`, `double`, …) and shape
knobs. Output is JSONL, one object per function:
`{func_name, lang: "c"|"cpp", signature, source_text}`.

Scale comes from: templates × type params × shapes, then multiplied downstream
by compilers (gcc/clang) × opt levels (O0, O1, O2, O3, Os).

#### Route 2 — Hybrid IR

A tiny typed function IR (typed locals, integer/float arithmetic, comparisons,
one bounded loop, a return) is:

- **(a)** pretty-printed to real C source — this is Y;
- **(b)** lowered to asmjit, which emits x86-64 machine bytes; those bytes are
  decoded by zydis into asm text — this is X (zydis-native formatting).

The correspondence between X and Y is guaranteed because both are derived from
the same IR. No compiler and no container are involved. Output JSONL is a
complete pair:
`{func_name, lang, signature, source_text, asm_text, obj_format: "rawx86_64",
compiler: "asmjit", opt_level: "none"}`.

### Component: `pipeline/generate.py` (Python ingest driver)

- `direct` mode: reads the synthesizer's JSONL, writes each function to a
  translation unit, and runs the **existing** pipeline path
  (`env.start_toolchain` → `compile.compile_tu` across gcc/clang × O0–O3,Os →
  `disasm.disassemble` → `pair.pair_functions`). Inserts resulting pairs with
  `origin='gen:direct'`.
- `hybrid` mode: reads the full-pair JSONL and inserts each directly with
  `origin='gen:hybrid'` (no compile step).
- Both modes: dedup via existing `pair_hash` UNIQUE constraint; stream progress
  to a journal; emit dashboard events.
- CLI mirrors `harvest.py`: `--count`, `--route {direct,hybrid,both}`, `--db`,
  `--no-dashboard`, `--seed`.

### Component: database changes (`pipeline/store.py`)

- `migrate()` adds `origin TEXT` to `pairs` (idempotent, guarded by
  `PRAGMA table_info`). Existing rows are backfilled to `'harvest'`.
- `insert_pair(..., origin='harvest')` gains an `origin` parameter defaulting to
  `'harvest'`, so all existing callers (the harvester) keep writing `'harvest'`
  unchanged. Generated callers pass `'gen:direct'` / `'gen:hybrid'`.
- `connect()` adds `PRAGMA busy_timeout=5000` so the generator and harvester can
  write the same `pairs.db` concurrently (WAL is already enabled; the timeout
  handles the single-writer serialization window with retry instead of an
  immediate "database is locked").
- New column values introduced: `obj_format='rawx86_64'`, `compiler='asmjit'`.
  `arch` remains `'x86_64'`.

### Component: journal, dashboard, dbgraph, scripts

- The generator uses its **own** journal file `dataset/journal-gen.jsonl` to
  avoid interleaved appends with the harvester's `dataset/journal.jsonl`.
  Viewable with `scripts/journal.sh --path dataset/journal-gen.jsonl -f`.
- Its own rich dashboard (reusing `pipeline/dashboard.py`'s renderer where
  possible) with the live command mini-box, launched in a spawned Terminal via a
  new `scripts/generate.sh` that mirrors `scripts/collect.sh`.
- After a run, dbgraph is refreshed (`scripts/build_graph.sh`); `origin` becomes
  a queryable dimension and is documented in `db-graph/`.

## Windows portability seam

- The Hybrid route is already host-agnostic: asmjit emits and zydis decodes
  x86-64 bytes on any host OS/arch, so it needs no changes to run on Windows.
- The Direct route's only OS-bound step is compilation, which stays behind the
  `env.py` toolchain abstraction. A future PE toolchain slots in via a new
  `obj_format='pe'` without touching `generator/`.
- The C++ build is CMake-based and carries no POSIX-only assumptions, so it
  compiles on Windows.

## Error handling

- Generator (C++): a template/IR that fails to lower or decode is skipped and
  logged to stderr as a structured line; it never aborts the batch. Exit code is
  non-zero only on unrecoverable setup failure (e.g., asmjit init).
- Ingest (Python): a malformed JSONL line is skipped with a journal warning. A
  Direct-mode compile failure is recorded via the existing `skipped` table
  (reused) and never aborts the run. Dedup collisions are silently ignored
  (existing `INSERT OR IGNORE` behavior).
- Concurrency: `busy_timeout` absorbs writer contention; if it is still
  exceeded, the affected insert is retried once then logged and skipped.

## Testing strategy

- **C++ (ctest):** synthesizer output for each template compiles cleanly;
  Hybrid IR → asmjit bytes decode via zydis to the expected mnemonic sequence
  for a couple of fixed seeds; emitted JSONL validates against the agreed schema.
- **Python (pytest):** `origin` migration adds the column and backfills existing
  rows to `'harvest'`; `insert_pair` default keeps harvester rows `'harvest'`;
  a parallel-writer smoke test (two connections writing under `busy_timeout`
  without error); `generate.py` ingest for both routes, including dedup of a
  repeated pair.

## Execution plan (implementation)

Implementation proceeds via the writing-plans skill and is structured for
**parallel opus subagents** working on disjoint files:

- Agent 1 — `generator/` (C++, CMake, both routes).
- Agent 2 — `pipeline/generate.py` + `pipeline/store.py` migration/origin/busy_timeout.
- Agent 3 — `scripts/generate.sh` + dashboard/journal wiring + dbgraph note.

The JSONL record schema is the shared contract between Agent 1 and Agent 2 and
is fixed before the agents start. Per user preference, a fable agent authors the
detailed plan.
