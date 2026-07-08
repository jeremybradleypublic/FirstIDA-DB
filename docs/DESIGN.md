# Disassembly ↔ Source Dataset — Unified Design & Pipeline

**Status:** design approved, pre-implementation
**Date:** 2026-07-08
**Companion spec:** `docs/superpowers/specs/2026-07-08-disasm-dataset-pipeline-design.md`

---

## 1. Objective

Build, at scale, a dataset of **`(assembly, source)` function pairs**. Each data point is a
single function:

- **X** — a snippet of x86-64 disassembly (`objdump -d` style).
- **Y** — the original C/C++ source that compiled to that assembly.

The pipeline must ingest an **arbitrary C/C++ repository**, sweep its source, drive a
compiler, isolate per-function assembly, pair it back to source, and write unique pairs
into a database.

**zlib is only an end-to-end smoke test** — one pre-downloaded repo to prove the path works.
The production goal is to **scrape thousands of C/C++ repos from GitHub** and stream each
through the same per-repo pipeline (`scrape.py` + `harvest.py`, §6b), deleting sources after
extraction so the corpus scales on bounded disk. Everything below is designed so the
single-repo path and the thousands-of-repos path are the *same* code, differing only in the
driver on top.

This document is the authoritative unified plan: the architecture, every design decision
and the alternatives we weighed, and — importantly — **how the choice of architecture,
compiler, and operating system changes the data you collect**.

---

## 2. The central difficulty

You cannot compile a function in isolation — it needs its headers, types, and macros. And
after compilation, the mapping from source to machine code is **lossy and many-to-one**:

- Functions get **inlined** and vanish as standalone symbols.
- Unused code is **eliminated** (dead-code elimination).
- Compilers emit **specialized clones** of one source function (GCC's `.constprop`,
  `.isra`, `.part` suffixes).
- Optimization **reorders, merges, vectorizes, and unrolls**, so X stops resembling Y.

So the pipeline **compiles whole translation units**, extracts source functions
**separately**, and **joins them by name**. Anything that doesn't survive as its own
symbol simply produces no pair. This is a deliberate accuracy-over-recall stance: we would
rather emit fewer, correct pairs than guess.

---

## 3. Pipeline architecture

Seven small, independently testable Python modules under `pipeline/`:

```
repo/ ─walk─> [*.c,*.cc,*.cpp] ─extract─> source funcs ─┐
                   │                                     ├─pair─> store ─> dataset/pairs.db
                   └─compile(opt)─> *.o ─disasm─> asm funcs ─┘
```

| Module | Responsibility | Key dependency |
|---|---|---|
| `env.py` | **Auto-provision the toolchain.** Ensure Colima installed + VM up, build the Docker image, start one persistent container. Idempotent. | Colima, docker CLI |
| `extract.py` | Parse a source file → function records `{name, signature, source_text, start_line, is_static, lang}`. | tree-sitter (C, C++) |
| `compile.py` | Compile one TU at one opt level in-container via `docker exec`; log failures, don't crash. | gcc/g++ in container |
| `disasm.py` | `objdump -d` + `c++filt` in-container → `{symbol: asm_text}`. | binutils in container |
| `pair.py` | Join disassembled symbols ↔ source functions by (demangled) name. | — |
| `store.py` | SQLite schema, dedup, idempotent insert. | sqlite3 |
| `run_pipeline.py` | Orchestrate **one repo**: bootstrap env, walk repo, sweep files × opt levels, populate DB. | all of the above |
| `scrape.py` | **Discover + download** C/C++ repos from GitHub (search or curated list) → local repo dir. | GitHub API, git |
| `harvest.py` | **Corpus driver**: for each discovered repo, download → `run_pipeline` → record provenance → **delete the repo**. Bounded disk, resumable. | scrape + run_pipeline |

### Execution model

One long-lived container (`--platform linux/amd64`, Rosetta-accelerated) per run. All
`gcc`/`g++`/`objdump`/`c++filt` calls go through `docker exec` — no per-file container
startup cost. Repo mounted read-only; scratch dir read-write. We only *compile* and
*disassemble*, never *run* the emitted binaries, so emulation cost is confined to compile
time.

### Storage schema (`dataset/pairs.db`)

```
pairs(id, repo, file_path, func_name, signature, lang,
      arch, opt_level, obj_format, compiler,
      source_text, asm_text, source_hash, asm_hash,
      pair_hash UNIQUE)          -- hash(func_name+asm_text+source_text)
skipped(id, repo, file_path, opt_level, reason)
repos(id, url, commit_sha, license, status,       -- provenance + resume ledger
      n_pairs, processed_at)                       -- status: pending|done|failed
```

`pair_hash` makes the whole run **idempotent and resumable**: re-running on the same or a
new repo only adds new pairs. `skipped` gives visibility into compile failures.

---

## 4. Design decision points

Each subsection states **what we chose**, **the alternatives**, and **why**.

### 4.1 Assembly representation (X)

**Chosen:** `objdump -d` disassembly of a compiled object.

- **Alternative — compiler `-S` textual assembly.** Cleaner and trivially split by label,
  but it is *pre-assembler* output full of directives (`.cfi_*`, `.p2align`) and
  pseudo-ops. It is not what a reverse engineer ever sees.
- **Why objdump:** it is the real artifact of binary analysis — addresses, opcode bytes,
  resolved mnemonics, call targets. It matches the downstream use case (understanding
  compiled binaries).

**Nuances still open as future dimensions:**

- **Syntax:** AT&T (objdump default) vs Intel (`-M intel`). Same semantics, different
  surface form; a model trained on one won't natively read the other.
- **Symbols present vs stripped.** Our pairing *needs* symbols, so we compile unstripped.
  But real-world binaries are frequently **stripped** — no `<func>` labels, only addresses.
  A realistic "input" distribution may want a stripped-style rendering of X (bytes +
  instructions, no symbol names) even though we use symbols internally to build the pair.
- **Relocations / PLT / GOT.** Calls to external functions appear as relocations or
  `call <printf@plt>`; position-independent code adds `%rip`-relative addressing. These are
  real and worth keeping, but they mean X carries link-time artifacts, not just codegen.

### 4.2 Target architecture

**Chosen:** x86-64.

Architecture is the single most fundamental axis — it changes X's entire vocabulary while
Y is unchanged. How different targets change the data:

| Arch | Character | Effect on the dataset |
|---|---|---|
| **x86-64** | CISC, variable-length (1–15 byte) instructions, rich addressing modes, few registers historically (16 GPRs) | Dense, complex instructions; heavy stack/`%rip` use; the de-facto standard for public disasm datasets |
| **arm64 / AArch64** | RISC, fixed 4-byte instructions, 31 GPRs, load/store architecture | More instructions per operation but more regular; less memory traffic; native on Apple Silicon |
| **arm32 / Thumb** | RISC + mixed 2/4-byte Thumb encoding, conditional execution | Encoding-mode ambiguity; conditional-execution idioms have no x86 analogue |
| **RISC-V** | Clean RISC, modular ISA extensions | Very regular; behavior depends heavily on enabled extensions (M/A/F/C…) |
| **x86-32** | CISC, 8 GPRs, stack-based argument passing (cdecl) | Args on the stack instead of registers → very different prologues |

**Calling conventions differ per arch** and reshape prologues/epilogues and how arguments
appear: System V AMD64 passes the first 6 integer args in `rdi,rsi,rdx,rcx,r8,r9`; AArch64
uses `x0–x7`; 32-bit x86 cdecl pushes args on the stack. **Endianness, register count, and
RISC-vs-CISC verbosity** all mean a model must essentially relearn X per architecture.
Multi-arch data improves generalization but multiplies volume and toolchain surface.

### 4.3 Compiler

**Chosen (v1):** GCC (`gcc`/`g++`) in the container. Clang is the obvious second dimension.

Different compilers lower the *same* source to *different* idioms:

- **GCC vs Clang/LLVM:** differ in switch lowering (jump table vs branch tree thresholds),
  `memcpy`/`memset` inlining, vectorization heuristics, stack-protector insertion, and the
  **specialized-clone suffixes** GCC emits (`.constprop.0`, `.isra.0`, `.part.0`) that Clang
  does not. These suffixes directly complicate name-based pairing (see §5).
- **MSVC:** Windows-only, emits PE/COFF, uses the Microsoft x64 ABI and name decoration —
  a genuinely different distribution, not just a different backend.
- **ICC/ICX (Intel):** aggressive auto-vectorization; distinct SIMD idioms.
- **Compiler version matters:** `gcc-9` and `gcc-13` produce materially different code.
  Pinning the version (we pin it via the Docker image) is essential for reproducibility;
  varying it deliberately is a diversity axis.

Compiler diversity is one of the cheapest ways to make the dataset robust, because it
teaches the model that many X map to one Y.

### 4.4 Operating system / object format / ABI

**Chosen:** Linux / ELF, via Docker. (Native macOS would give **Mach-O**; we rejected it as
less standard for this domain — see §7.)

The OS chiefly enters through the **object format and ABI**:

| OS | Format | ABI highlights that change X |
|---|---|---|
| **Linux** | ELF | System V AMD64: args in `rdi/rsi/...`, red zone, PLT/GOT for dynamic calls |
| **macOS** | Mach-O | System V-like, but **leading underscore** on symbols; different sections (`__TEXT,__text`) |
| **Windows** | PE/COFF | MS x64 ABI: args in `rcx/rdx/r8/r9`, **32-byte shadow space**, SEH unwind, decorated names |

So the same `foo(int,int,int,int)` receives its arguments in *different registers* on Linux
vs Windows, and its symbol is spelled differently on macOS vs Linux. Object format also
dictates how we split per-function assembly and how relocations/imports render. OS choice is
therefore not cosmetic — it changes both X's content and how the pipeline must parse it.

### 4.5 Optimization level

**Chosen:** all of `O0, O1, O2, O3, Os` — each a **distinct sample** for the same function.

Optimization is arguably the biggest driver of X↔Y *difficulty*:

- **O0** — verbose, stack-heavy, near one-to-one with source; every local spilled to the
  stack. Easiest to learn, least realistic.
- **O1/O2** — register allocation, common-subexpression elimination, inlining; X begins to
  diverge structurally from Y.
- **O3** — aggressive inlining, **loop unrolling**, **auto-vectorization** (SIMD); X can be
  unrecognizable relative to Y.
- **Os/Oz** — optimize for size; different tradeoffs again.

Two flags to be aware of as future knobs:

- **`-flto` (link-time optimization)** enables cross-TU inlining and **breaks per-TU
  pairing** — a function's code may migrate across object boundaries. We keep LTO off in v1.
- **`-march=native` / `-mavx2`** unlock wider SIMD, changing X substantially; left off for
  portability.

### 4.6 Source extraction

**Chosen:** tree-sitter (C and C++ grammars).

- **Alternative — libclang:** semantically exact (resolves macros, types, overloads) but
  heavy and needs correct compile flags per file.
- **Alternative — regex/ctags:** brittle; fails on nested braces, function pointers,
  attributes.
- **Why tree-sitter:** fast, error-tolerant (parses incomplete/odd code), gives exact byte
  ranges for function definitions, and needs no build. Precise enough for boundary
  extraction, which is all we need — semantics come from the compiler.

**Preprocessor nuance:** macros expand *before* codegen, so X reflects the **expanded** code
while Y is the **written** macro. There is an inherent small semantic gap between "the source
as written" and "the source the compiler actually saw." We capture source as written
(what a human would want to predict), and accept the gap.

### 4.7 Debug info & the pairing signal

**Chosen (v1):** compile with `-g`, pair by **symbol name**.

- `-g` gives us the symbol table (and, notably, does **not** change codegen), so X stays
  representative.
- **Alternative — DWARF line tables:** map instruction *ranges* to source *lines*, which is
  more precise and can even attribute *inlined* code back to its origin. Powerful but adds
  DWARF-parsing complexity. Flagged as a future upgrade to raise recall.

---

## 5. Pairing nuances (where the correctness lives)

Name-based joining must handle:

- **Inlining / DCE** — no symbol → no pair. Expected; drop silently.
- **C++ name mangling** — demangle with `c++filt`; but **overloads share a demangled
  name**, so keep the signature to disambiguate.
- **Static/local functions** — appear as local symbols; may collide across files (two
  different `static void init(void)`), so scope by file.
- **GCC IPA clones** — `foo.constprop.0`, `foo.isra.0`, `foo.part.0` are specialized
  variants of `foo`. Strip the suffix to recover the source name; optionally record the
  clone kind as metadata.
- **Leading underscore** — Mach-O/legacy decorate symbols with `_`; strip per format.
- **Hot/cold splitting** — compilers may emit `foo` and `foo.cold` in separate sections;
  decide whether to stitch or keep the hot body only.
- **Weak symbols / aliases / COMDAT folding** — multiple names for one body; dedup via
  `pair_hash`.

These are exactly the cases the TDD fixtures target (a mangled C++ symbol, a `static` C
function, a broken TU that must land in `skipped`).

---

## 6. Scaling to arbitrary repositories

- Clone any repo → `python run_pipeline.py <repo_dir>`.
- Best-effort include-flag discovery (`-I<repo>` + header dirs); files that don't compile
  in isolation are logged to `skipped`, never fatal.
- **Escape hatch:** if the repo ships (or can generate) a `compile_commands.json`, the
  pipeline uses those exact flags — the robust path for real build systems.
- Idempotent by `pair_hash`, so a corpus can be swept incrementally across many repos.

**Dataset hygiene (called out, partly future work):**

- **Licensing/provenance** — collected source carries its original license; record repo +
  path so provenance is auditable for downstream ML use.
- **Train/test split by repo** (not by function) to avoid leakage between near-identical
  functions.
- **Near-duplicate handling** — trivial getters/wrappers recur; `pair_hash` collapses exact
  dups, but semantic near-dups may warrant later filtering.

---

## 6b. GitHub scraping & large-scale corpus building

To build a *large* database we automate ingestion of many repos. The design keeps disk
usage **bounded** by processing each repo ephemerally: download → extract pairs → delete.

### Flow

```
discover repos ─> for each repo: ─┬─ download (shallow) ─> run_pipeline ─> append pairs
                                   ├─ record provenance in `repos`
                                   └─ delete repo dir   (disk stays flat)
```

`harvest.py` is the corpus driver; `scrape.py` handles discovery + download. The persistent
toolchain container is started once and reused across all repos.

### Discovery & repo-selection strategy (`scrape.py`)

**Auth:** the scraper shells out to the already-authenticated **`gh` CLI** (`gh search
repos`, `gh api`, `gh repo clone`), which reads its token from the OS keyring. No token
touches our code, the DB, or git. Fallback: `GITHUB_TOKEN=$(gh auth token)` at runtime for
any library that wants the raw token.

**Selection policy (locked):**

- **License:** permissive only — MIT, BSD-2/3, Apache-2.0, zlib, ISC — for clean training
  provenance.
- **Quality floor:** `stars >= 10`, `fork:false`, `archived:false`, `pushed:>2021`
  (maintained), plus a repo-size band (skip trivially tiny and multi-GB monorepos).
- **Diversity:** separate `language:C` and `language:C++` sweeps, crossed with **domain
  topics** (compression, cryptography, parsers, databases, networking, embedded, graphics/
  image, math, OS/kernel, CLI) so the function distribution is broad, not a monoculture.

**Breaking the 1,000-results-per-query cap** — the key mechanic for reaching *thousands* of
repos. GitHub Search returns at most 1,000 hits per query, so `scrape.py` **partitions** the
space into **star buckets** (`10..50`, `50..200`, `200..1000`, `>1000`) crossed with
language and topic, keeps each slice under the cap, and unions the results.

**De-duplication before download:** skip URLs already in the `repos` ledger; cap repos
per owner so one org can't dominate; optionally skip names matching heavily-vendored libs
(zlib/sqlite/stb) that inflate duplicate functions (`pair_hash` still collapses exact dups).

**Curated URL list** — a plain text file of repo URLs is also supported, for reproducible
named corpora. All paths converge on a stream of `{url, default_branch, license}` records.

**Yield feedback (future):** track pairs-per-repo and deprioritize classes that return
near-empty (e.g., header-only), so the sweep grows more efficient over time.

### Download strategy

- **`git clone --depth 1`** (shallow) or a **tarball** from `codeload.github.com`. Both
  avoid full history; tarball is lightest when we don't need git metadata.
- **Repo-level, not file-level.** Individual files rarely compile (they need the repo's
  headers), and our compile-whole-TU strategy needs the surrounding sources. So we fetch
  repos (or self-contained subtrees), not lone files.

### Ephemeral processing & bounded disk

After `run_pipeline` finishes a repo, `harvest.py` records the outcome and **deletes the
checkout**. Only `dataset/pairs.db` grows; raw sources never accumulate. This is what makes
sweeping thousands of repos feasible on a laptop.

### Idempotency, resume, and provenance

- The `repos` ledger stores `url`, `commit_sha`, `license`, `status`, `n_pairs`,
  `processed_at`. Re-running **skips repos already `done`** and can resume after
  interruption; a repo is only marked `done` after its pairs are committed.
- Recording `commit_sha` makes each contribution to the dataset reproducible to an exact
  source revision.

### Robustness & etiquette

- **Rate limits:** authenticating via `gh` gives the ~5000 requests/hour tier (vs ~60
  unauthenticated); cloning public repos over HTTPS doesn't count against the API limit.
  `scrape.py` backs off on `403`/secondary-limit responses.
- **Failure isolation:** a repo that fails to download or compile is marked `failed` with a
  reason; the sweep continues. No single bad repo aborts the corpus build.
- **Concurrency (future):** v1 processes repos sequentially for simplicity; the container
  supports parallel `docker exec`, so a bounded worker pool is a natural later speedup.

---

## 7. Why Docker/ELF over native macOS/Mach-O

A native build on this Apple Silicon Mac produces **arm64 Mach-O** by default, and even
`-target x86_64-apple-macos` produces **x86-64 Mach-O**, not ELF. Public disassembly
datasets and real reverse-engineering targets are overwhelmingly **Linux x86-64 ELF from
real GCC**. Running compilation in a `--platform linux/amd64` container gives us exactly
that, at the cost of a one-time Colima setup and running builds in a VM. Because we only
compile (never execute) the binaries, x86-64 emulation only affects compile latency. The
`obj_format` and `compiler` columns keep the door open to regenerate for other
format/toolchain combinations later.

---

## 8. Reproducibility

`README.md` (root) documents the full path: prerequisites (macOS + Homebrew — everything
else auto-installed by `env.py`), the single command to reproduce the zlib dataset, how to
point the pipeline at a new repo, the DB schema with example queries, and troubleshooting.
Because `env.py` provisions the toolchain, "reproduce" is effectively one command after
clone. The compiler is version-pinned via the Docker image so regenerated data is stable.

---

## 9. Out of scope (YAGNI for v1)

- Architectures other than x86-64; syntax other than AT&T.
- Compilers other than GCC (Clang is the first planned extension).
- LTO, `-march=native`, and stripped-style X rendering (all noted as future dimensions).
- DWARF-line-table pairing (future recall upgrade).
- Cross-repo semantic dedup and automated train/test splitting.
- Executing compiled binaries.

---

## 10. Testing strategy

TDD per module against tiny fixtures:

- `extract` finds known function names and exact source spans.
- `compile` produces an object; a deliberately broken file lands in `skipped`.
- `disasm` splits a known object into the expected symbols.
- `pair` matches names — including a C++ mangled symbol and a `static` C function.
- A full mini-run populates the DB with the expected row count and is idempotent on a
  second run.
