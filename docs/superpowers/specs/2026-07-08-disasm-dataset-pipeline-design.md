# Disassembly Dataset Pipeline — Design Spec

**Date:** 2026-07-08
**Goal:** Build a large-scale dataset of `(assembly, C/C++ source)` function pairs. Each sample is one function: `X` = a snippet of x86-64 disassembly, `Y` = the original source that compiled to it. Bootstrap on zlib; generalize to arbitrary scraped C/C++ repos.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Assembly format (X) | `objdump -d` disassembly, split per function symbol |
| Target architecture | x86-64 |
| Object format | ELF (Linux), via Docker |
| Optimization levels | O0, O1, O2, O3, Os — each a distinct sample |
| Languages | C and C++ |
| Toolchain | Real Linux `gcc`/`g++` in a `--platform linux/amd64` container |
| Source parsing | tree-sitter (C + C++ grammars) |
| Storage | SQLite at `dataset/pairs.db` |
| Environment | Colima + docker CLI, auto-provisioned by the pipeline |

## Core strategy

Compile **whole translation units**, not isolated functions (a lone function rarely
compiles — it needs its headers/types/macros). Extract each function's source text
**separately** with tree-sitter, then **join on the function name** to the disassembled
symbols. Functions that get inlined, dead-code-eliminated, or renamed simply produce no
pair — expected and acceptable.

For each source file, for each optimization level:

1. **extract** — tree-sitter parses the file into function definitions
   (`name, signature, source_text, start_line, is_static, lang`).
2. **compile** — compile the whole TU to an ELF object with `-g` at the opt level.
3. **disasm** — `objdump -d` the object, split into per-symbol assembly blocks;
   demangle C++ symbols with `c++filt`.
4. **pair** — match each disassembled symbol to its extracted source function by
   (demangled) name.
5. **store** — insert one `(asm, source)` row per surviving (function × opt-level).

## Components

Small, independently testable Python modules under `pipeline/`:

- `env.py` — **automatic environment bootstrap.** Idempotent. Ensures Colima is
  installed (via Homebrew) and its VM is running, builds the toolchain Docker image
  from `docker/Dockerfile`, and starts one persistent container. Returns a handle used
  by later stages. Safe to call on every run.
- `extract.py` — tree-sitter C/C++ → list of function records with exact source byte
  ranges. No compilation required.
- `compile.py` — compile one TU at one opt level inside the container via `docker exec`.
  Best-effort include flags (`-I<repo>` and each dir containing headers); consumes
  `compile_commands.json` when present for exact flags. Records failures instead of
  crashing.
- `disasm.py` — run `objdump -d` (and `c++filt`) in the container → `{symbol: asm_text}`.
- `pair.py` — join disassembled symbols to extracted source functions by name
  (strip Mach-O/ELF leading underscore as needed; demangle C++).
- `store.py` — SQLite schema, dedup, idempotent insert.
- `run_pipeline.py` — orchestrator: bootstrap env, walk a repo dir, sweep all files ×
  opt levels, populate `dataset/pairs.db`. Accepts a repo path argument so it works on
  any cloned repo, defaulting to the bundled zlib.

## Execution model

One long-lived container (`--platform linux/amd64`, Rosetta-accelerated) is started once
per run. All `gcc`/`g++`/`objdump`/`c++filt` invocations go through `docker exec` — no
per-file container startup cost. The repo is mounted read-only; a scratch directory is
mounted read-write for object files. We only *compile* and *disassemble*, never *run*
the emitted binaries, so x86-64 emulation cost is limited to compile time.

## Data flow

```
repo/ ──walk──> [*.c,*.cc,*.cpp] ──extract──> source funcs ─┐
                     │                                       ├──pair──> store ──> dataset/pairs.db
                     └──compile(opt)──> *.o ──disasm──> asm funcs ─┘
```

## SQLite schema (`dataset/pairs.db`)

One row per unique pair:

```
pairs(
  id            INTEGER PRIMARY KEY,
  repo          TEXT,      -- e.g. "zlib"
  file_path     TEXT,      -- source file, repo-relative
  func_name     TEXT,      -- demangled function name
  signature     TEXT,      -- source signature
  lang          TEXT,      -- "c" | "cpp"
  arch          TEXT,      -- "x86_64"
  opt_level     TEXT,      -- "O0".."Os"
  obj_format    TEXT,      -- "elf"
  compiler      TEXT,      -- e.g. "gcc-13"
  source_text   TEXT,      -- Y
  asm_text      TEXT,      -- X
  source_hash   TEXT,
  asm_hash      TEXT,
  pair_hash     TEXT UNIQUE  -- hash(func_name + asm_text + source_text)
)

skipped(
  id INTEGER PRIMARY KEY, repo TEXT, file_path TEXT,
  opt_level TEXT, reason TEXT
)
```

Dedup on `pair_hash` makes runs idempotent and collapses identical trivial functions
across opt levels. `skipped` records compile failures for visibility.

## Error handling & scale

- Per-file compile failures → logged to `skipped`, sweep continues.
- Functions with no matching symbol (inlined / DCE'd) → silently dropped.
- Idempotent & resumable via `pair_hash` uniqueness — safe to re-run on the same or new
  repos; a re-run only adds new pairs.
- Scaling to arbitrary repos: clone repo → `python run_pipeline.py <repo_dir>`. Optionally
  supply `compile_commands.json` for exact build flags. Files that don't compile in
  isolation are skipped, not fatal.

## Reproducibility

`README.md` at project root documents:

- Prerequisites (macOS + Homebrew; everything else auto-installed).
- Single command to reproduce the zlib dataset end-to-end.
- How to point the pipeline at a new repo.
- The DB schema and how to query samples.
- Troubleshooting (Colima not starting, image rebuild, emulation notes).

The pipeline itself performs environment setup, so "reproduce" is one command after
cloning.

## Testing (TDD per module)

Tiny fixture `.c`/`.cpp` files with known functions:

- `extract` finds the expected function names and source spans.
- `compile` produces an object; a deliberately broken file lands in `skipped`.
- `disasm` splits a known object into the expected symbols.
- `pair` matches names, including a C++ mangled symbol and a `static` C function.
- A full mini-run populates the DB with the expected number of rows and is idempotent
  on a second run.

## Out of scope (YAGNI for v1)

- Architectures other than x86-64.
- Cross-repo function deduplication beyond `pair_hash`.
- Building via the repo's own build system (we compile TUs directly; `compile_commands.json`
  is the escape hatch).
- Running/executing compiled binaries.
