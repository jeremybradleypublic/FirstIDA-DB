# disasmgen C++ Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native C++ generator (`generator/disasmgen`) that synthesizes (asm, C/C++ source) function pairs via two routes — Direct (templates → real compiler) and Hybrid (typed IR → asmjit bytes → zydis text) — and a Python driver (`pipeline/generate.py`) that ingests its JSONL into the existing `dataset/pairs.db` marked with a new `origin` column.

**Architecture:** The C++ binary is a pure generator: it prints JSONL and never touches the database. Python owns every DB write — Direct-route records are written into one scratch "repo" and pushed through the EXISTING `env → compile → disasm → pair` pipeline (real objdump asm, `origin='gen:direct'`), while Hybrid-route records are complete pairs inserted as-is (`origin='gen:hybrid'`). The generator runs in parallel with the harvester: own journal (`dataset/journal-gen.jsonl`), own Terminal dashboard (`scripts/generate.sh`), shared WAL DB serialized by `busy_timeout`, and a dbgraph refresh after each run.

**Tech Stack:** C++17, CMake, asmjit, zydis, Python 3.14, sqlite3, tree-sitter, rich.

## Global Constraints
- `store.insert_pair` gains `origin='harvest'` as a DEFAULT — every existing caller keeps writing `'harvest'` with zero changes.
- Any scratch repo dir the Direct route writes MUST be under `$HOME` (Colima only virtiofs-mounts the home dir; mirror `harvest.py`'s `SCRATCH_ROOT` pattern with a sibling `~/.cache/disasm_generate`).
- Do NOT change `pair_hash` hashing: it stays `_sha1(f"{func_name}\n{asm_text}\n{source_text}")` — `origin` is NOT part of the hash.
- The C++ binary prints JSONL only; it never opens, reads, or writes any database.
- C++ dependencies come via CMake `FetchContent` at PINNED refs: asmjit commit `7596c6d035c27c9e5faad445f3214f2c971b2f2b` (v1.18, 2025-09-06, snake_case API — verified) and zydis tag `v4.1.1`; network is needed at FIRST configure only.
- New column values introduced by Hybrid: `obj_format='rawx86_64'`, `compiler='asmjit'`, `opt_level='none'`; `arch` stays `'x86_64'`.
- Parallel-safe with the harvester: `store.connect` adds `PRAGMA busy_timeout=5000` (WAL is already on) so two writers to `pairs.db` retry instead of raising "database is locked".

---

## Shared Contract (FROZEN — fixed before any stream starts)

Every line the C++ binary prints on its JSONL output is one JSON object.

**Common fields (both routes):**
- `route` — `"direct"` | `"hybrid"`
- `func_name` — str
- `lang` — `"c"` | `"cpp"`
- `signature` — str
- `source_text` — str
- `seed` — int

**Hybrid-only additional fields:**
- `asm_text` — str
- `obj_format` — `"rawx86_64"`
- `compiler` — `"asmjit"`
- `opt_level` — `"none"`

Direct records carry NO asm — Python compiles the source through the real toolchain. This schema appears identically in `generator/src/main.cpp` (producer), `pipeline/generate.py` (`REQUIRED_COMMON` / `REQUIRED_HYBRID` validators), and every test that touches records. It is the only coupling between Stream A and Stream B.

**Stream dependency note for the dispatcher:**
- **Stream A** (C++, Tasks 3–7) and **Stream B** (Python, Tasks 1–2, 8–10) are fully disjoint — parallelize freely. Stream B's Direct-ingest tests use stubs/small sources and never need the C++ binary.
- **Stream C** Tasks 11–12 only touch `scripts/` and docs and can run any time; Task 13 (end-to-end) REQUIRES Streams A and B complete.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `generator/CMakeLists.txt` | Create | CMake build: pinned FetchContent deps, `disasmgen_core` lib, `disasmgen` binary, ctest registration. |
| `generator/src/jsonl.hpp` / `generator/src/jsonl.cpp` | Create | Hand-rolled JSON string escaping + one-line JSON object emitter (no JSON lib dependency). |
| `generator/src/direct.hpp` / `generator/src/direct.cpp` | Create | Direct-route source synthesizer: parameterized C/C++ function templates swept over types/shapes. |
| `generator/src/ir.hpp` | Create | The tiny typed Hybrid IR (`IRFunc`): typed locals, int/float add/sub/mul, one comparison, one bounded loop, a return. |
| `generator/src/render_c.hpp` / `generator/src/render_c.cpp` | Create | IR → real C source pretty-printer (`render_c`, `signature_of`, `ty_cname`). |
| `generator/src/lower_asmjit.hpp` / `generator/src/lower_asmjit.cpp` | Create | IR → asmjit → raw x86-64 machine bytes (SysV registers). |
| `generator/src/format_zydis.hpp` / `generator/src/format_zydis.cpp` | Create | Raw bytes → zydis-decoded Intel-syntax asm text, one instruction per line. |
| `generator/src/hybrid.hpp` / `generator/src/hybrid.cpp` | Create | Seeded random IR synthesizer (`synthesize_ir`). |
| `generator/src/main.cpp` | Create | CLI: `disasmgen <direct\|hybrid> [--count N] [--seed S] [--out PATH]`; prints JSONL; skips-and-logs per-record failures to stderr. |
| `generator/tests/test_jsonl.cpp` | Create | ctest: JSON escaping of quote/newline/backslash; exact emitted object. |
| `generator/tests/test_direct.cpp` | Create | ctest: every template's source is non-empty, contains its `func_name`, deterministic per seed. |
| `generator/tests/test_render_c.cpp` | Create | ctest: IR renders to the expected C constructs. |
| `generator/tests/test_hybrid.cpp` | Create | ctest: fixed IR lowers to bytes that zydis decodes to a known mnemonic sequence; whole seeded batch lowers cleanly. |
| `pipeline/store.py` | Modify (lines 5–13, 28–32, 40–54, 71–79) | Add `origin TEXT` to schema + idempotent migrate/backfill; `insert_pair(..., origin='harvest')`; `PRAGMA busy_timeout=5000` in `connect`. |
| `pipeline/run_pipeline.py` | Modify (lines 32–34, 77–82) | Thread a new `origin="harvest"` param into the `store.insert_pair` call. |
| `pipeline/generate.py` | Create | Ingest driver: run binary via `journal.run`, validate JSONL, hybrid insert / direct compile-through-pipeline, CLI + dashboard + dbgraph refresh. |
| `tests/test_store.py` | Modify (append) | busy_timeout, migration/backfill, origin default+custom, parallel-writer smoke. |
| `tests/test_run_pipeline_origin.py` | Create | Hermetic (no Docker) proof that `run(..., origin=...)` reaches `insert_pair`. |
| `tests/test_generate.py` | Create | Record validation, hybrid ingest + dedup, direct scratch-repo writer, origin threading, fake-binary `run_generator`, `generate()` orchestration. |
| `scripts/generate.sh` | Create | Mirror of `collect.sh`: build `generator/build/disasmgen` if missing, spawn macOS Terminal running `.venv/bin/python -m pipeline.generate`, `--here` for inline. |
| `db-graph/README.md` | Modify (append) | One-line note: `origin` is now a queryable dimension of the graph. |
| `README.md` | Modify (append) | Document the generator track and `scripts/generate.sh`. |

---

## Task 1 [Stream B]: `store.py` — `origin` column, migration/backfill, `busy_timeout`

**Files:**
- Modify: `/Users/jbradley/Desktop/create_disasm_dataset/pipeline/store.py` (lines 5–13 `_SCHEMA`, 28–32 `connect`, 40–54 `insert_pair`, 71–79 `migrate`)
- Test: `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_store.py` (append)

**Interfaces:**
- Consumes: existing `connect(db_path) -> sqlite3.Connection`, `init_schema(conn)`, `migrate(conn)`, `insert_pair(conn, *, repo, file_path, func_name, signature, lang, arch, opt_level, obj_format, compiler, source_text, asm_text) -> bool`.
- Produces: `connect` additionally sets `PRAGMA busy_timeout=5000`; `migrate(conn)` additionally adds `origin TEXT` to `pairs` (PRAGMA-guarded) and backfills `UPDATE pairs SET origin='harvest' WHERE origin IS NULL`; `insert_pair(..., origin='harvest') -> bool` stores `origin`. `pair_hash` computation is untouched.

- [ ] **Step 1: Write the failing tests.** Append to `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_store.py`:

```python
import sqlite3
import threading


def test_connect_sets_busy_timeout(tmp_path):
    conn = store.connect(str(tmp_path / "t.db"))
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


_LEGACY_SCHEMA = """
CREATE TABLE pairs (
    id          INTEGER PRIMARY KEY,
    repo        TEXT, file_path TEXT, func_name TEXT, signature TEXT, lang TEXT,
    arch        TEXT, opt_level TEXT, obj_format TEXT, compiler TEXT,
    source_text TEXT, asm_text TEXT,
    source_hash TEXT, asm_hash TEXT,
    pair_hash   TEXT UNIQUE
);
CREATE TABLE skipped (
    id INTEGER PRIMARY KEY, repo TEXT, file_path TEXT, opt_level TEXT, reason TEXT
);
CREATE TABLE repos (
    id INTEGER PRIMARY KEY, url TEXT, commit_sha TEXT, license TEXT,
    status TEXT, n_pairs INTEGER, processed_at TEXT
);
"""


def test_migrate_adds_origin_and_backfills(tmp_path):
    # Build a pre-origin legacy DB by hand, with one existing harvested row.
    db = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(db)
    raw.executescript(_LEGACY_SCHEMA)
    raw.execute("INSERT INTO pairs (func_name, pair_hash) VALUES ('old_fn', 'h1')")
    raw.commit()
    raw.close()

    conn = store.connect(db)
    store.migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(pairs)")}
    assert "origin" in cols
    row = conn.execute("SELECT origin FROM pairs WHERE func_name='old_fn'").fetchone()
    assert row[0] == "harvest"
    store.migrate(conn)          # idempotent: second run is a no-op
    assert store.count_pairs(conn) == 1


def test_insert_pair_origin_default_and_custom(tmp_path):
    conn = _mk(tmp_path)
    store.migrate(conn)
    assert store.insert_pair(conn, **_args()) is True
    assert conn.execute(
        "SELECT origin FROM pairs WHERE func_name='foo'").fetchone()[0] == "harvest"
    assert store.insert_pair(conn, origin="gen:hybrid",
                             **_args(func_name="hyb")) is True
    assert conn.execute(
        "SELECT origin FROM pairs WHERE func_name='hyb'").fetchone()[0] == "gen:hybrid"


def test_parallel_writers_smoke(tmp_path):
    # Two connections (one per thread, sqlite3 objects are thread-bound)
    # writing the same WAL DB under busy_timeout, without error.
    db = str(tmp_path / "p.db")
    boot = store.connect(db)
    store.init_schema(boot)
    store.migrate(boot)
    boot.close()
    errs = []

    def writer(tag):
        conn = store.connect(db)
        try:
            for i in range(25):
                store.insert_pair(conn, **_args(
                    func_name=f"{tag}_{i}", asm_text=f"<{tag}_{i}>:\n ret"))
        except Exception as e:      # noqa: BLE001 — the test records any failure
            errs.append(e)
        finally:
            conn.close()

    t1 = threading.Thread(target=writer, args=("a",))
    t2 = threading.Thread(target=writer, args=("b",))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert errs == []
    conn = store.connect(db)
    assert store.count_pairs(conn) == 50
```

- [ ] **Step 2: Run the tests, see them fail.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest tests/test_store.py -q`. Expected: `test_connect_sets_busy_timeout` fails with `assert 0 == 5000`; `test_migrate_adds_origin_and_backfills` fails with `AssertionError: assert 'origin' in {...}`; `test_insert_pair_origin_default_and_custom` fails with `TypeError: insert_pair() got an unexpected keyword argument 'origin'` (and/or `sqlite3.OperationalError: no such column: origin`).

- [ ] **Step 3: Implement in `pipeline/store.py`.** Three edits.

  (a) In `_SCHEMA`, extend the `pairs` create so FRESH databases get the column without needing `migrate`:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS pairs (
    id          INTEGER PRIMARY KEY,
    repo        TEXT, file_path TEXT, func_name TEXT, signature TEXT, lang TEXT,
    arch        TEXT, opt_level TEXT, obj_format TEXT, compiler TEXT,
    source_text TEXT, asm_text TEXT,
    source_hash TEXT, asm_hash TEXT,
    pair_hash   TEXT UNIQUE,
    origin      TEXT
);
CREATE TABLE IF NOT EXISTS skipped (
    id INTEGER PRIMARY KEY, repo TEXT, file_path TEXT, opt_level TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY, url TEXT, commit_sha TEXT, license TEXT,
    status TEXT, n_pairs INTEGER, processed_at TEXT
);
"""
```

  (b) Replace `connect`:

```python
def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # The harvester and the generator write the same DB in parallel; WAL
    # allows one writer at a time, and busy_timeout retries instead of
    # raising an immediate "database is locked".
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
```

  (c) Replace `insert_pair` (NOTE: `pair_hash` line is byte-identical to today's — `origin` is not hashed):

```python
def insert_pair(conn, *, repo, file_path, func_name, signature, lang, arch,
                opt_level, obj_format, compiler, source_text, asm_text,
                origin='harvest') -> bool:
    source_hash = _sha1(source_text)
    asm_hash = _sha1(asm_text)
    pair_hash = _sha1(f"{func_name}\n{asm_text}\n{source_text}")
    cur = conn.execute(
        """INSERT OR IGNORE INTO pairs
           (repo,file_path,func_name,signature,lang,arch,opt_level,obj_format,
            compiler,source_text,asm_text,source_hash,asm_hash,pair_hash,origin)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (repo, file_path, func_name, signature, lang, arch, opt_level, obj_format,
         compiler, source_text, asm_text, source_hash, asm_hash, pair_hash, origin),
    )
    conn.commit()
    return cur.rowcount == 1
```

  (d) Replace `migrate` (keep the existing repos logic; add the pairs block):

```python
def migrate(conn) -> None:
    """Idempotent PRAGMA-guarded migrations: repos harvest columns, and the
    pairs.origin provenance column (existing rows backfilled to 'harvest')."""
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_repos_url ON repos(url)")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(repos)")}
    if "reason" not in cols:
        conn.execute("ALTER TABLE repos ADD COLUMN reason TEXT")
    if "stars" not in cols:
        conn.execute("ALTER TABLE repos ADD COLUMN stars INTEGER")
    pair_cols = {r[1] for r in conn.execute("PRAGMA table_info(pairs)")}
    if "origin" not in pair_cols:
        conn.execute("ALTER TABLE pairs ADD COLUMN origin TEXT")
    conn.execute("UPDATE pairs SET origin='harvest' WHERE origin IS NULL")
    conn.commit()
```

- [ ] **Step 4: Run the tests, see them pass.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest tests/test_store.py -q`. Expected: all tests in the file pass, including the three pre-existing ones (default origin keeps them green).

- [ ] **Step 5: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add pipeline/store.py tests/test_store.py
git commit -m "$(cat <<'EOF'
feat(store): origin column + backfill migration + busy_timeout

pairs.origin distinguishes 'harvest' rows from the new generator's
'gen:direct'/'gen:hybrid'; insert_pair defaults origin='harvest' so all
existing callers are unchanged; busy_timeout=5000 lets the generator and
harvester write pairs.db concurrently. pair_hash is untouched.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 2 [Stream B]: `run_pipeline.run` — thread `origin` to `insert_pair`

**Files:**
- Modify: `/Users/jbradley/Desktop/create_disasm_dataset/pipeline/run_pipeline.py` (lines 32–34 signature, 77–82 insert call)
- Test: `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_run_pipeline_origin.py` (create)

**Interfaces:**
- Consumes: `store.insert_pair(..., origin='harvest')` from Task 1.
- Produces: `run(repo_dir, repo=None, db_path="dataset/pairs.db", compilers=("gcc","clang"), opt_levels=("O0","O1","O2","O3","Os"), progress=None, journal=None, origin="harvest") -> {"pairs":int,"skipped":int,"files":int}`. This is how Direct-mode reuses the whole compile→disasm→pair path with `origin="gen:direct"`.

- [ ] **Step 1: Write the failing hermetic test.** Create `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_run_pipeline_origin.py` (no Docker: every toolchain-facing seam is monkeypatched; NOT marked integration):

```python
"""Hermetic (no Docker) proof that run_pipeline.run threads `origin` into
store.insert_pair. All container-facing seams are monkeypatched."""
import types

import pipeline.run_pipeline as rp


class _FakeTC:
    def stop(self):
        pass


def _stub_pipeline(monkeypatch, calls):
    monkeypatch.setattr(rp.env, "start_toolchain",
                        lambda repo_dir, journal=None: _FakeTC())
    monkeypatch.setattr(rp.extract, "extract_functions", lambda path: ["rec"])
    monkeypatch.setattr(rp.compile_mod, "compiler_label",
                        lambda tc, compiler, lang: f"{compiler}-0.0-fake")
    monkeypatch.setattr(
        rp.compile_mod, "compile_tu",
        lambda tc, rel, compiler, opt, lang, incs:
        types.SimpleNamespace(ok=True, obj_path="/out/a.o", reason=None))
    monkeypatch.setattr(rp.disasm, "disassemble", lambda tc, obj: ["asm-stub"])
    monkeypatch.setattr(
        rp.pair, "pair_functions",
        lambda records, asm: [types.SimpleNamespace(
            func_name="f", signature="int f(void)", lang="c",
            source_text="int f(void){return 0;}", asm_text="<f>:\n ret")])

    def fake_insert(conn, **kw):
        calls.append(kw)
        return True
    monkeypatch.setattr(rp.store, "insert_pair", fake_insert)


def _mk_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.c").write_text("int f(void){return 0;}\n")
    return str(repo)


def test_default_origin_is_harvest(tmp_path, monkeypatch):
    calls = []
    _stub_pipeline(monkeypatch, calls)
    rp.run(_mk_repo(tmp_path), repo="stub", db_path=str(tmp_path / "d.db"),
           compilers=("gcc",), opt_levels=("O0",))
    assert calls
    assert all(c["origin"] == "harvest" for c in calls)


def test_origin_param_is_threaded(tmp_path, monkeypatch):
    calls = []
    _stub_pipeline(monkeypatch, calls)
    stats = rp.run(_mk_repo(tmp_path), repo="stub", db_path=str(tmp_path / "d.db"),
                   compilers=("gcc",), opt_levels=("O0",), origin="gen:direct")
    assert stats["pairs"] == 1
    assert calls
    assert all(c["origin"] == "gen:direct" for c in calls)
```

- [ ] **Step 2: Run it, see it fail.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest tests/test_run_pipeline_origin.py -q`. Expected: `test_default_origin_is_harvest` fails with `KeyError: 'origin'` (insert_pair is never called with origin); `test_origin_param_is_threaded` fails with `TypeError: run() got an unexpected keyword argument 'origin'`.

- [ ] **Step 3: Implement in `pipeline/run_pipeline.py`.** Change the `run` signature (lines 32–34):

```python
def run(repo_dir, repo=None, db_path="dataset/pairs.db",
        compilers=("gcc", "clang"), opt_levels=("O0", "O1", "O2", "O3", "Os"),
        progress=None, journal=None, origin="harvest"):
```

  and thread it into the insert call (lines 77–82):

```python
                    for p in pair.pair_functions(records, asm):
                        if store.insert_pair(conn, repo=repo, file_path=rel,
                                             func_name=p.func_name, signature=p.signature,
                                             lang=p.lang, arch="x86_64", opt_level=opt,
                                             obj_format="elf", compiler=label,
                                             source_text=p.source_text, asm_text=p.asm_text,
                                             origin=origin):
                            stats["pairs"] += 1
```

- [ ] **Step 4: Run tests, see them pass.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest tests/test_run_pipeline_origin.py tests/test_store.py -q`. Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add pipeline/run_pipeline.py tests/test_run_pipeline_origin.py
git commit -m "$(cat <<'EOF'
feat(run_pipeline): origin param threaded into insert_pair

run(..., origin='harvest') lets the generator's Direct route reuse the
entire env->compile->disasm->pair path while tagging rows 'gen:direct'.
Harvester behavior is unchanged (default 'harvest').

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 3 [Stream A]: CMake skeleton + JSONL emitter

**Files:**
- Create: `/Users/jbradley/Desktop/create_disasm_dataset/generator/CMakeLists.txt`, `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/jsonl.hpp`, `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/jsonl.cpp`
- Test: `/Users/jbradley/Desktop/create_disasm_dataset/generator/tests/test_jsonl.cpp`

**Interfaces:**
- Produces: `std::string disasmgen::json_escape(const std::string& s)`; `class disasmgen::JsonObj { void add(const std::string& key, const std::string& value); void add_int(const std::string& key, long long value); std::string str() const; }` emitting a single-line `{...}` object. No third-party JSON library — output is hand-rolled with escaping for quotes, backslashes, and control characters.

- [ ] **Step 1: Write the failing test.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/tests/test_jsonl.cpp` (minimal assert-based harness — every C++ test in this plan returns non-zero on failure and is registered with `add_test`):

```cpp
#include "../src/jsonl.hpp"
#include <cstdio>
#include <string>

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
      return 1;                                                              \
    }                                                                        \
  } while (0)

int main() {
  using disasmgen::json_escape;
  CHECK(json_escape("plain") == "plain");
  CHECK(json_escape("a\"b") == "a\\\"b");
  CHECK(json_escape("line1\nline2") == "line1\\nline2");
  CHECK(json_escape("back\\slash") == "back\\\\slash");
  CHECK(json_escape("tab\there") == "tab\\there");
  CHECK(json_escape(std::string("nul\x01byte")) == "nul\\u0001byte");

  disasmgen::JsonObj o;
  o.add("func_name", "f\"1");
  o.add("source_text", "int f(void) {\n  return 1;\n}");
  o.add_int("seed", 42);
  CHECK(o.str() ==
        "{\"func_name\":\"f\\\"1\","
        "\"source_text\":\"int f(void) {\\n  return 1;\\n}\","
        "\"seed\":42}");
  std::puts("ok test_jsonl");
  return 0;
}
```

- [ ] **Step 2: Write the initial CMakeLists.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.24)
project(disasmgen LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(disasmgen_core STATIC
  src/jsonl.cpp)
target_include_directories(disasmgen_core PUBLIC src)

enable_testing()
add_executable(test_jsonl tests/test_jsonl.cpp)
target_link_libraries(test_jsonl PRIVATE disasmgen_core)
add_test(NAME jsonl COMMAND test_jsonl)
```

- [ ] **Step 3: Run the build, see it fail.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build && cmake --build /Users/jbradley/Desktop/create_disasm_dataset/generator/build`. Expected failure: `Cannot find source file: src/jsonl.cpp` at configure time (the implementation does not exist yet).

- [ ] **Step 4: Implement.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/jsonl.hpp`:

```cpp
#pragma once
#include <string>
#include <vector>

namespace disasmgen {

// Escape a string for embedding inside a JSON string literal:
// quotes, backslashes, \n \r \t, and all other control chars as \u00XX.
std::string json_escape(const std::string& s);

// Builds one single-line JSON object: {"k":"v","n":42}. Insertion order is
// preserved. This is the ONLY JSON emitter in the generator — no JSON lib.
class JsonObj {
 public:
  void add(const std::string& key, const std::string& value);
  void add_int(const std::string& key, long long value);
  std::string str() const;

 private:
  std::vector<std::string> parts_;
};

}  // namespace disasmgen
```

  and `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/jsonl.cpp`:

```cpp
#include "jsonl.hpp"

#include <cstdio>

namespace disasmgen {

std::string json_escape(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 8);
  for (unsigned char c : s) {
    switch (c) {
      case '"':  out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if (c < 0x20) {
          char buf[8];
          std::snprintf(buf, sizeof buf, "\\u%04x", c);
          out += buf;
        } else {
          out += static_cast<char>(c);
        }
    }
  }
  return out;
}

void JsonObj::add(const std::string& key, const std::string& value) {
  parts_.push_back("\"" + json_escape(key) + "\":\"" + json_escape(value) + "\"");
}

void JsonObj::add_int(const std::string& key, long long value) {
  parts_.push_back("\"" + json_escape(key) + "\":" + std::to_string(value));
}

std::string JsonObj::str() const {
  std::string out = "{";
  for (size_t i = 0; i < parts_.size(); ++i) {
    if (i) out += ",";
    out += parts_[i];
  }
  out += "}";
  return out;
}

}  // namespace disasmgen
```

- [ ] **Step 5: Build and run the test, see it pass.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build && cmake --build /Users/jbradley/Desktop/create_disasm_dataset/generator/build && ctest --test-dir /Users/jbradley/Desktop/create_disasm_dataset/generator/build --output-on-failure`. Expected: `1/1 Test #1: jsonl ... Passed`.

- [ ] **Step 6: Add `generator/build/` to gitignore and commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
echo "generator/build/" >> .gitignore
git add generator/CMakeLists.txt generator/src/jsonl.hpp generator/src/jsonl.cpp generator/tests/test_jsonl.cpp .gitignore
git commit -m "$(cat <<'EOF'
feat(generator): CMake skeleton + hand-rolled JSONL emitter with ctest

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 4 [Stream A]: Direct-route source synthesizer

**Files:**
- Create: `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/direct.hpp`, `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/direct.cpp`
- Modify: `/Users/jbradley/Desktop/create_disasm_dataset/generator/CMakeLists.txt`
- Test: `/Users/jbradley/Desktop/create_disasm_dataset/generator/tests/test_direct.cpp`

**Interfaces:**
- Produces: `struct disasmgen::DirectFunc { std::string func_name, lang, signature, source_text; }`; `std::vector<DirectFunc> disasmgen::synthesize_direct(int count, uint64_t seed)`. Six template families (reduction loop, dot product, bitwise mix, branchy compare, char count, C++ reference accumulate) swept over element types (`int`, `unsigned int`, `long`, `float`, `double`) and seed-drawn shape knobs. Deterministic for a given seed; every `func_name` is unique within a batch.

- [ ] **Step 1: Write the failing test.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/tests/test_direct.cpp`:

```cpp
#include "../src/direct.hpp"
#include <cstdio>
#include <set>
#include <string>

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
      return 1;                                                              \
    }                                                                        \
  } while (0)

int main() {
  auto funcs = disasmgen::synthesize_direct(60, 42);
  CHECK(funcs.size() == 60);
  std::set<std::string> names;
  bool saw_c = false, saw_cpp = false;
  for (const auto& f : funcs) {
    CHECK(!f.source_text.empty());
    CHECK(f.source_text.find(f.func_name) != std::string::npos);
    CHECK(!f.signature.empty());
    CHECK(f.signature.find(f.func_name) != std::string::npos);
    CHECK(f.lang == "c" || f.lang == "cpp");
    saw_c = saw_c || f.lang == "c";
    saw_cpp = saw_cpp || f.lang == "cpp";
    CHECK(names.insert(f.func_name).second);  // unique in batch
  }
  CHECK(saw_c);
  CHECK(saw_cpp);
  // deterministic per seed
  auto again = disasmgen::synthesize_direct(60, 42);
  CHECK(again[7].source_text == funcs[7].source_text);
  // a different seed changes at least one shape knob somewhere
  auto other = disasmgen::synthesize_direct(60, 43);
  bool differs = false;
  for (size_t i = 0; i < 60; ++i) {
    if (other[i].source_text != funcs[i].source_text) { differs = true; break; }
  }
  CHECK(differs);
  std::puts("ok test_direct");
  return 0;
}
```

- [ ] **Step 2: Register in CMake.** In `/Users/jbradley/Desktop/create_disasm_dataset/generator/CMakeLists.txt`, change the library sources and add the test:

```cmake
add_library(disasmgen_core STATIC
  src/jsonl.cpp
  src/direct.cpp)
```

  and after the existing `add_test(NAME jsonl ...)` line:

```cmake
add_executable(test_direct tests/test_direct.cpp)
target_link_libraries(test_direct PRIVATE disasmgen_core)
add_test(NAME direct COMMAND test_direct)
```

- [ ] **Step 3: Run the build, see it fail.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build && cmake --build /Users/jbradley/Desktop/create_disasm_dataset/generator/build`. Expected failure: `Cannot find source file: src/direct.cpp`.

- [ ] **Step 4: Implement.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/direct.hpp`:

```cpp
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace disasmgen {

struct DirectFunc {
  std::string func_name;
  std::string lang;         // "c" | "cpp"
  std::string signature;
  std::string source_text;  // one complete, self-contained function definition
};

// Deterministically synthesize `count` diverse self-contained functions from
// parameterized templates swept over element types and shape knobs.
std::vector<DirectFunc> synthesize_direct(int count, uint64_t seed);

}  // namespace disasmgen
```

  Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/direct.cpp`:

```cpp
#include "direct.hpp"

#include <random>
#include <string>

namespace disasmgen {
namespace {

struct TypeInfo {
  const char* cname;
  const char* abbr;
  bool is_float;
};

constexpr TypeInfo kTypes[] = {
    {"int", "i", false},          {"unsigned int", "u", false},
    {"long", "l", false},         {"float", "f", true},
    {"double", "d", true},
};
constexpr int kNumTypes = 5;
constexpr int kNumFamilies = 6;

using Rng = std::mt19937_64;

int ri(Rng& r, int lo, int hi) {  // uniform int in [lo, hi]
  return static_cast<int>(lo + r() % static_cast<uint64_t>(hi - lo + 1));
}

std::string num(int v) { return std::to_string(v); }

// Family 0: reduction loop over an array.
DirectFunc reduce_loop(Rng& r, const TypeInfo& t, const std::string& name) {
  int k = ri(r, 1, 9), m = ri(r, 2, 7);
  std::string T = t.cname;
  std::string sig = T + " " + name + "(const " + T + " *xs, int n)";
  std::string src = sig + " {\n" +
      "    " + T + " acc = " + num(k) + ";\n" +
      "    for (int i = 0; i < n; ++i) {\n" +
      "        acc += xs[i] * " + num(m) + ";\n" +
      "    }\n" +
      "    return acc;\n}\n";
  return {name, "c", sig, src};
}

// Family 1: dot product of two arrays.
DirectFunc dot_product(Rng& r, const TypeInfo& t, const std::string& name) {
  int stride = ri(r, 1, 3);
  std::string T = t.cname;
  std::string sig = T + " " + name + "(const " + T + " *a, const " + T +
                    " *b, int n)";
  std::string src = sig + " {\n" +
      "    " + T + " s = 0;\n" +
      "    for (int i = 0; i < n; i += " + num(stride) + ") {\n" +
      "        s += a[i] * b[i];\n" +
      "    }\n" +
      "    return s;\n}\n";
  return {name, "c", sig, src};
}

// Family 2: bitwise mixer (always unsigned, regardless of the swept type).
DirectFunc bitmix(Rng& r, const TypeInfo&, const std::string& name) {
  int s1 = ri(r, 1, 15), s2 = ri(r, 1, 15);
  unsigned mask = 0x0f0f0f0fu << ri(r, 0, 3);
  std::string sig = "unsigned int " + name + "(unsigned int a, unsigned int b)";
  std::string src = sig + " {\n" +
      "    unsigned int x = a ^ (b << " + num(s1) + ");\n" +
      "    x |= (a >> " + num(s2) + ");\n" +
      "    return x & " + std::to_string(mask) + "u;\n}\n";
  return {name, "c", sig, src};
}

// Family 3: branchy compare chain returning small codes.
DirectFunc branchy(Rng& r, const TypeInfo& t, const std::string& name) {
  int t1 = ri(r, 1, 40), t2 = t1 + ri(r, 1, 40);
  std::string T = t.cname;
  std::string sig = "int " + name + "(" + T + " x, " + T + " y)";
  std::string src = sig + " {\n" +
      "    if (x < " + num(t1) + ") {\n" +
      "        return y > x ? 1 : 2;\n" +
      "    }\n" +
      "    if (x < " + num(t2) + ") {\n" +
      "        return y == x ? 3 : 4;\n" +
      "    }\n" +
      "    return 5;\n}\n";
  return {name, "c", sig, src};
}

// Family 4: small string op — count occurrences of one character.
DirectFunc count_char(Rng& r, const TypeInfo&, const std::string& name) {
  char ch = static_cast<char>('a' + ri(r, 0, 25));
  std::string sig = "int " + name + "(const char *s)";
  std::string src = sig + " {\n" +
      "    int c = 0;\n" +
      "    while (*s) {\n" +
      "        if (*s == '" + std::string(1, ch) + "') {\n" +
      "            ++c;\n" +
      "        }\n" +
      "        ++s;\n" +
      "    }\n" +
      "    return c;\n}\n";
  return {name, "c", sig, src};
}

// Family 5: C++ reference-parameter saturating accumulate.
DirectFunc ref_accumulate(Rng& r, const TypeInfo& t, const std::string& name) {
  int cap = ri(r, 50, 500);
  std::string T = t.cname;
  std::string sig = T + " " + name + "(" + T + " &acc, " + T + " v)";
  std::string src = sig + " {\n" +
      "    acc += v;\n" +
      "    if (acc > " + num(cap) + ") {\n" +
      "        acc = " + num(cap) + ";\n" +
      "    }\n" +
      "    return acc;\n}\n";
  return {name, "cpp", sig, src};
}

const char* kFamilyTag[kNumFamilies] = {"red", "dot", "bit", "brc", "cnt", "acc"};

}  // namespace

std::vector<DirectFunc> synthesize_direct(int count, uint64_t seed) {
  Rng r(seed ^ 0x9e3779b97f4a7c15ull);
  std::vector<DirectFunc> out;
  out.reserve(count);
  for (int idx = 0; idx < count; ++idx) {
    const TypeInfo& t = kTypes[r() % kNumTypes];
    int fam = static_cast<int>(r() % kNumFamilies);
    std::string name = std::string("g_") + kFamilyTag[fam] + "_" + t.abbr +
                       "_" + std::to_string(idx);
    switch (fam) {
      case 0: out.push_back(reduce_loop(r, t, name)); break;
      case 1: out.push_back(dot_product(r, t, name)); break;
      case 2: out.push_back(bitmix(r, t, name)); break;
      case 3: out.push_back(branchy(r, t, name)); break;
      case 4: out.push_back(count_char(r, t, name)); break;
      default: out.push_back(ref_accumulate(r, t, name)); break;
    }
  }
  return out;
}

}  // namespace disasmgen
```

- [ ] **Step 5: Build and run, see it pass.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build && cmake --build /Users/jbradley/Desktop/create_disasm_dataset/generator/build && ctest --test-dir /Users/jbradley/Desktop/create_disasm_dataset/generator/build --output-on-failure`. Expected: `2/2 tests passed` (jsonl, direct).

- [ ] **Step 6: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add generator/src/direct.hpp generator/src/direct.cpp generator/tests/test_direct.cpp generator/CMakeLists.txt
git commit -m "$(cat <<'EOF'
feat(generator): direct-route source synthesizer — 6 template families x 5 types

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 5 [Stream A]: Hybrid IR types + IR→C renderer

**Files:**
- Create: `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/ir.hpp`, `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/render_c.hpp`, `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/render_c.cpp`
- Modify: `/Users/jbradley/Desktop/create_disasm_dataset/generator/CMakeLists.txt`
- Test: `/Users/jbradley/Desktop/create_disasm_dataset/generator/tests/test_render_c.cpp`

**Interfaces:**
- Produces: `enum class disasmgen::Ty { I32, I64, F64 }`, `enum class BinOp { Add, Sub, Mul }`, `enum class CmpOp { Lt, Gt, Eq }`, `struct IRFunc { std::string name; Ty ty; BinOp loop_op, post_op; CmpOp cmp; int trip_count; long long init_const; }`; `const char* ty_cname(Ty)`; `std::string signature_of(const IRFunc&)`; `std::string render_c(const IRFunc&)`. The IR is deliberately SMALL: typed locals, int/float add/sub/mul, ONE comparison, ONE bounded loop, a return — no calls, no pointers. Both the renderer (this task) and the lowerer (Task 6) implement the same fixed semantics, which is what guarantees X/Y correspondence.

- [ ] **Step 1: Write the failing test.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/tests/test_render_c.cpp`:

```cpp
#include "../src/ir.hpp"
#include "../src/render_c.hpp"
#include <cstdio>
#include <string>

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
      return 1;                                                              \
    }                                                                        \
  } while (0)

static bool has(const std::string& hay, const char* needle) {
  return hay.find(needle) != std::string::npos;
}

int main() {
  using namespace disasmgen;
  IRFunc f;
  f.name = "fixture";
  f.ty = Ty::I32;
  f.loop_op = BinOp::Add;
  f.post_op = BinOp::Sub;
  f.cmp = CmpOp::Lt;
  f.trip_count = 4;
  f.init_const = 1;

  CHECK(std::string(ty_cname(Ty::I32)) == "int");
  CHECK(std::string(ty_cname(Ty::I64)) == "long long");
  CHECK(std::string(ty_cname(Ty::F64)) == "double");
  CHECK(signature_of(f) == "int fixture(int a, int b)");

  std::string src = render_c(f);
  CHECK(has(src, "int fixture(int a, int b) {"));
  CHECK(has(src, "int acc = 1;"));
  CHECK(has(src, "for (int i = 0; i < 4; ++i) {"));
  CHECK(has(src, "acc = acc + a;"));
  CHECK(has(src, "if (acc < b) {"));
  CHECK(has(src, "acc = acc - b;"));
  CHECK(has(src, "return acc;"));

  f.ty = Ty::F64;
  f.loop_op = BinOp::Mul;
  f.cmp = CmpOp::Gt;
  std::string fsrc = render_c(f);
  CHECK(has(fsrc, "double fixture(double a, double b) {"));
  CHECK(has(fsrc, "double acc = 1.0;"));
  CHECK(has(fsrc, "acc = acc * a;"));
  CHECK(has(fsrc, "if (acc > b) {"));
  std::puts("ok test_render_c");
  return 0;
}
```

- [ ] **Step 2: Register in CMake.** In `generator/CMakeLists.txt` add `src/render_c.cpp` to the `disasmgen_core` sources, and append:

```cmake
add_executable(test_render_c tests/test_render_c.cpp)
target_link_libraries(test_render_c PRIVATE disasmgen_core)
add_test(NAME render_c COMMAND test_render_c)
```

- [ ] **Step 3: Run the build, see it fail.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build && cmake --build /Users/jbradley/Desktop/create_disasm_dataset/generator/build`. Expected failure: `Cannot find source file: src/render_c.cpp`.

- [ ] **Step 4: Implement.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/ir.hpp`:

```cpp
#pragma once
#include <string>

namespace disasmgen {

enum class Ty { I32, I64, F64 };
enum class BinOp { Add, Sub, Mul };
enum class CmpOp { Lt, Gt, Eq };  // Eq is only ever GENERATED for integer types

// One tiny typed function shape — the single source of truth for BOTH the C
// renderer (render_c.cpp) and the asmjit lowerer (lower_asmjit.cpp), which is
// what guarantees the (asm, source) correspondence by construction:
//
//   T f(T a, T b) {
//       T acc = (T)init_const;                       // typed local
//       for (int i = 0; i < trip_count; ++i) {       // ONE bounded loop
//           acc = acc <loop_op> a;                   // add/sub/mul
//       }
//       if (acc <cmp> b) {                           // ONE comparison
//           acc = acc <post_op> b;
//       }
//       return acc;                                  // a return
//   }
//
// No calls, no pointers, no memory.
struct IRFunc {
  std::string name;
  Ty ty = Ty::I32;
  BinOp loop_op = BinOp::Add;
  BinOp post_op = BinOp::Sub;
  CmpOp cmp = CmpOp::Lt;
  int trip_count = 4;       // 1..16
  long long init_const = 1; // small non-negative constant
};

const char* ty_cname(Ty ty);  // "int" | "long long" | "double"

}  // namespace disasmgen
```

  Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/render_c.hpp`:

```cpp
#pragma once
#include "ir.hpp"
#include <string>

namespace disasmgen {

// "int f(int a, int b)"
std::string signature_of(const IRFunc& f);

// The complete C function definition implementing the IR semantics.
std::string render_c(const IRFunc& f);

}  // namespace disasmgen
```

  Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/render_c.cpp`:

```cpp
#include "render_c.hpp"

namespace disasmgen {
namespace {

const char* op_c(BinOp op) {
  switch (op) {
    case BinOp::Add: return "+";
    case BinOp::Sub: return "-";
    default:         return "*";
  }
}

const char* cmp_c(CmpOp c) {
  switch (c) {
    case CmpOp::Lt: return "<";
    case CmpOp::Gt: return ">";
    default:        return "==";
  }
}

}  // namespace

const char* ty_cname(Ty ty) {
  switch (ty) {
    case Ty::I32: return "int";
    case Ty::I64: return "long long";
    default:      return "double";
  }
}

std::string signature_of(const IRFunc& f) {
  std::string t = ty_cname(f.ty);
  return t + " " + f.name + "(" + t + " a, " + t + " b)";
}

std::string render_c(const IRFunc& f) {
  std::string t = ty_cname(f.ty);
  std::string s = signature_of(f) + " {\n";
  s += "    " + t + " acc = " + std::to_string(f.init_const);
  if (f.ty == Ty::F64) s += ".0";
  s += ";\n";
  s += "    for (int i = 0; i < " + std::to_string(f.trip_count) + "; ++i) {\n";
  s += std::string("        acc = acc ") + op_c(f.loop_op) + " a;\n";
  s += "    }\n";
  s += std::string("    if (acc ") + cmp_c(f.cmp) + " b) {\n";
  s += std::string("        acc = acc ") + op_c(f.post_op) + " b;\n";
  s += "    }\n";
  s += "    return acc;\n}\n";
  return s;
}

}  // namespace disasmgen
```

- [ ] **Step 5: Build and run, see it pass.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build && cmake --build /Users/jbradley/Desktop/create_disasm_dataset/generator/build && ctest --test-dir /Users/jbradley/Desktop/create_disasm_dataset/generator/build --output-on-failure`. Expected: 3/3 pass.

- [ ] **Step 6: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add generator/src/ir.hpp generator/src/render_c.hpp generator/src/render_c.cpp generator/tests/test_render_c.cpp generator/CMakeLists.txt
git commit -m "$(cat <<'EOF'
feat(generator): tiny typed hybrid IR + IR->C renderer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 6 [Stream A]: asmjit lowerer + zydis formatter + IR synthesizer (pinned FetchContent deps)

**Files:**
- Create: `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/lower_asmjit.hpp`, `.../src/lower_asmjit.cpp`, `.../src/format_zydis.hpp`, `.../src/format_zydis.cpp`, `.../src/hybrid.hpp`, `.../src/hybrid.cpp`
- Modify: `/Users/jbradley/Desktop/create_disasm_dataset/generator/CMakeLists.txt`
- Test: `/Users/jbradley/Desktop/create_disasm_dataset/generator/tests/test_hybrid.cpp`

**Interfaces:**
- Consumes: `IRFunc` (Task 5); asmjit v1.18 snake_case API (`Environment::set_arch`, `CodeHolder::init/flatten/has_unresolved_fixups/text_section`, `x86::Assembler`, `new_label`); Zydis v4 API (`ZydisDecoderDecodeFull`, `ZydisFormatterFormatInstruction`).
- Produces: `std::vector<uint8_t> disasmgen::lower_x64(const IRFunc& f, std::string* err)` — raw x86-64 machine bytes, SysV convention (`a`=edi/rdi/xmm0, `b`=esi/rsi/xmm1, return eax/rax/xmm0), empty on failure with `*err` set; `std::string disasmgen::format_asm(const std::vector<uint8_t>& bytes, std::string* err)` — Intel-syntax text, one `"<offset>: <insn>"` line per instruction; `std::vector<IRFunc> disasmgen::synthesize_ir(int count, uint64_t seed)` — seeded random IRs (F64 never draws `CmpOp::Eq`).

- [ ] **Step 1: Write the failing test.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/tests/test_hybrid.cpp`. The fixed-seed fixture `{I32, Add, Sub, Lt, trip=4, init=1}` must lower to exactly this instruction stream — `mov eax,1; mov ecx,4; L1: add eax,edi; dec ecx; jnz L1; cmp eax,esi; jge L2; sub eax,esi; L2: ret` — and zydis must decode those bytes back to that known mnemonic sequence:

```cpp
#include "../src/format_zydis.hpp"
#include "../src/hybrid.hpp"
#include "../src/ir.hpp"
#include "../src/lower_asmjit.hpp"

#include <cstdio>
#include <sstream>
#include <string>
#include <vector>

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
      return 1;                                                              \
    }                                                                        \
  } while (0)

// Pull the mnemonic (first token after "<offset>: ") out of each asm line.
static std::vector<std::string> mnemonics(const std::string& asm_text) {
  std::vector<std::string> out;
  std::istringstream ss(asm_text);
  std::string line;
  while (std::getline(ss, line)) {
    size_t colon = line.find(": ");
    if (colon == std::string::npos) continue;
    std::string rest = line.substr(colon + 2);
    size_t sp = rest.find(' ');
    out.push_back(sp == std::string::npos ? rest : rest.substr(0, sp));
  }
  return out;
}

int main() {
  using namespace disasmgen;

  // (1) Fixed IR -> bytes -> zydis -> known mnemonic sequence.
  IRFunc f;
  f.name = "fixture";
  f.ty = Ty::I32;
  f.loop_op = BinOp::Add;
  f.post_op = BinOp::Sub;
  f.cmp = CmpOp::Lt;
  f.trip_count = 4;
  f.init_const = 1;

  std::string err;
  std::vector<uint8_t> bytes = lower_x64(f, &err);
  CHECK(!bytes.empty());
  std::string text = format_asm(bytes, &err);
  CHECK(!text.empty());
  std::vector<std::string> m = mnemonics(text);
  const char* want[] = {"mov", "mov", "add", "dec", "jnz",
                        "cmp", "jge", "sub", "ret"};
  CHECK(m.size() == 9);
  for (int i = 0; i < 9; ++i) CHECK(m[i] == want[i]);

  // (2) F64 path returns via xmm0 and compares with ucomisd.
  f.ty = Ty::F64;
  f.loop_op = BinOp::Mul;
  f.cmp = CmpOp::Gt;
  bytes = lower_x64(f, &err);
  CHECK(!bytes.empty());
  text = format_asm(bytes, &err);
  CHECK(text.find("ucomisd") != std::string::npos);
  CHECK(text.find("mulsd") != std::string::npos);

  // (3) Eq on F64 is a structured skip, not a crash.
  f.cmp = CmpOp::Eq;
  err.clear();
  CHECK(lower_x64(f, &err).empty());
  CHECK(!err.empty());

  // (4) Every IR in a seeded batch lowers and decodes cleanly, and the
  //     synthesizer never draws Eq for F64.
  for (const auto& ir : synthesize_ir(25, 7)) {
    if (ir.ty == Ty::F64) CHECK(ir.cmp != CmpOp::Eq);
    CHECK(ir.trip_count >= 1 && ir.trip_count <= 16);
    std::string e;
    std::vector<uint8_t> b = lower_x64(ir, &e);
    CHECK(!b.empty());
    CHECK(!format_asm(b, &e).empty());
  }
  // determinism
  CHECK(synthesize_ir(25, 7)[3].name == synthesize_ir(25, 7)[3].name);
  CHECK(synthesize_ir(25, 7)[3].trip_count == synthesize_ir(25, 7)[3].trip_count);
  std::puts("ok test_hybrid");
  return 0;
}
```

- [ ] **Step 2: Add pinned FetchContent deps and register everything in CMake.** In `generator/CMakeLists.txt`, insert after the `set(CMAKE_CXX_STANDARD_REQUIRED ON)` line (network is required the FIRST time this configure runs; both refs are PINNED — asmjit is commit-based so we pin the v1.18 release commit, zydis by release tag; FetchContent's git clone also pulls zydis's vendored zycore submodule by default):

```cmake
include(FetchContent)

# --- pinned native deps (network needed at first configure only) -----------
set(ASMJIT_STATIC TRUE CACHE BOOL "" FORCE)
set(ASMJIT_TEST OFF CACHE BOOL "" FORCE)
FetchContent_Declare(asmjit
  GIT_REPOSITORY https://github.com/asmjit/asmjit.git
  GIT_TAG 7596c6d035c27c9e5faad445f3214f2c971b2f2b)  # v1.18 (2025-09-06), zlib license

set(ZYDIS_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(ZYDIS_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(ZYDIS_BUILD_DOXYGEN OFF CACHE BOOL "" FORCE)
FetchContent_Declare(zydis
  GIT_REPOSITORY https://github.com/zyantific/zydis.git
  GIT_TAG v4.1.1)                                    # MIT license

FetchContent_MakeAvailable(asmjit zydis)
```

  Update the core library block to:

```cmake
add_library(disasmgen_core STATIC
  src/jsonl.cpp
  src/direct.cpp
  src/render_c.cpp
  src/lower_asmjit.cpp
  src/format_zydis.cpp
  src/hybrid.cpp)
target_include_directories(disasmgen_core PUBLIC src)
target_link_libraries(disasmgen_core PUBLIC asmjit Zydis)
```

  and append the test:

```cmake
add_executable(test_hybrid tests/test_hybrid.cpp)
target_link_libraries(test_hybrid PRIVATE disasmgen_core)
add_test(NAME hybrid COMMAND test_hybrid)
```

- [ ] **Step 3: Run the configure, see it fail.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build`. Expected: the dependency fetch succeeds (first time takes a couple of minutes) and then configure fails with `Cannot find source file: src/lower_asmjit.cpp`.

- [ ] **Step 4: Implement the lowerer.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/lower_asmjit.hpp`:

```cpp
#pragma once
#include "ir.hpp"
#include <cstdint>
#include <string>
#include <vector>

namespace disasmgen {

// Lower `f` to raw x86-64 machine code (SysV: a = edi/rdi/xmm0,
// b = esi/rsi/xmm1; return in eax/rax/xmm0). Returns the flat byte buffer,
// or an empty vector with *err set on failure (a failed IR is SKIPPED by the
// caller, never fatal to the batch).
std::vector<uint8_t> lower_x64(const IRFunc& f, std::string* err);

}  // namespace disasmgen
```

  Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/lower_asmjit.cpp`:

```cpp
#include "lower_asmjit.hpp"

#include <asmjit/x86.h>

namespace disasmgen {
namespace {

using namespace asmjit;

void emit_int_op(x86::Assembler& a, BinOp op, const x86::Gp& dst,
                 const x86::Gp& src) {
  switch (op) {
    case BinOp::Add: a.add(dst, src); break;
    case BinOp::Sub: a.sub(dst, src); break;
    case BinOp::Mul: a.imul(dst, src); break;
  }
}

void emit_f64_op(x86::Assembler& a, BinOp op, const x86::Xmm& dst,
                 const x86::Xmm& src) {
  switch (op) {
    case BinOp::Add: a.addsd(dst, src); break;
    case BinOp::Sub: a.subsd(dst, src); break;
    case BinOp::Mul: a.mulsd(dst, src); break;
  }
}

}  // namespace

std::vector<uint8_t> lower_x64(const IRFunc& f, std::string* err) {
  Environment env;
  env.set_arch(Arch::kX64);
  CodeHolder code;
  if (code.init(env) != Error::kOk) {
    if (err) *err = "asmjit CodeHolder init failed";
    return {};
  }
  x86::Assembler a(&code);

  Label loop = a.new_label();
  Label skip = a.new_label();

  if (f.ty == Ty::F64) {
    // acc = xmm2; a = xmm0, b = xmm1 (SysV float args); return in xmm0.
    if (f.cmp == CmpOp::Eq) {  // never generated for F64; guard anyway
      if (err) *err = "Eq comparison unsupported for F64";
      return {};
    }
    a.mov(x86::eax, static_cast<int>(f.init_const));
    a.cvtsi2sd(x86::xmm2, x86::eax);        // acc = (double)init_const
    a.mov(x86::ecx, f.trip_count);
    a.bind(loop);
    emit_f64_op(a, f.loop_op, x86::xmm2, x86::xmm0);
    a.dec(x86::ecx);
    a.jnz(loop);
    a.ucomisd(x86::xmm2, x86::xmm1);
    if (f.cmp == CmpOp::Lt) a.jae(skip);    // !(acc < b)
    else                    a.jbe(skip);    // !(acc > b)
    emit_f64_op(a, f.post_op, x86::xmm2, x86::xmm1);
    a.bind(skip);
    a.movapd(x86::xmm0, x86::xmm2);
    a.ret();
  } else {
    // acc = eax/rax; a = edi/rdi, b = esi/rsi; return in eax/rax.
    auto emit_int_body = [&](const x86::Gp& acc, const x86::Gp& pa,
                             const x86::Gp& pb) {
      a.mov(acc, f.init_const);
      a.mov(x86::ecx, f.trip_count);
      a.bind(loop);
      emit_int_op(a, f.loop_op, acc, pa);
      a.dec(x86::ecx);
      a.jnz(loop);
      a.cmp(acc, pb);
      if (f.cmp == CmpOp::Lt)      a.jge(skip);  // signed !(acc < b)
      else if (f.cmp == CmpOp::Gt) a.jle(skip);  // signed !(acc > b)
      else                         a.jne(skip);  // !(acc == b)
      emit_int_op(a, f.post_op, acc, pb);
      a.bind(skip);
      a.ret();
    };
    if (f.ty == Ty::I64) emit_int_body(x86::rax, x86::rdi, x86::rsi);
    else                 emit_int_body(x86::eax, x86::edi, x86::esi);
  }

  if (code.flatten() != Error::kOk || code.has_unresolved_fixups()) {
    if (err) *err = "asmjit produced unresolved code";
    return {};
  }
  const CodeBuffer& buf = code.text_section()->buffer();
  return std::vector<uint8_t>(buf.data(), buf.data() + buf.size());
}

}  // namespace disasmgen
```

- [ ] **Step 5: Implement the zydis formatter.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/format_zydis.hpp`:

```cpp
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace disasmgen {

// Decode raw x86-64 bytes into Intel-syntax text, one instruction per line,
// formatted "<hex offset>: <instruction>". Returns "" with *err set if any
// byte fails to decode (caller SKIPS the record; never fatal to the batch).
std::string format_asm(const std::vector<uint8_t>& bytes, std::string* err);

}  // namespace disasmgen
```

  Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/format_zydis.cpp`:

```cpp
#include "format_zydis.hpp"

#include <Zydis/Zydis.h>

#include <cstdio>

namespace disasmgen {

std::string format_asm(const std::vector<uint8_t>& bytes, std::string* err) {
  ZydisDecoder decoder;
  if (!ZYAN_SUCCESS(ZydisDecoderInit(&decoder, ZYDIS_MACHINE_MODE_LONG_64,
                                     ZYDIS_STACK_WIDTH_64))) {
    if (err) *err = "zydis decoder init failed";
    return "";
  }
  ZydisFormatter formatter;
  if (!ZYAN_SUCCESS(ZydisFormatterInit(&formatter, ZYDIS_FORMATTER_STYLE_INTEL))) {
    if (err) *err = "zydis formatter init failed";
    return "";
  }

  std::string out;
  ZyanUSize offset = 0;
  ZydisDecodedInstruction insn;
  ZydisDecodedOperand operands[ZYDIS_MAX_OPERAND_COUNT];
  while (offset < bytes.size()) {
    if (!ZYAN_SUCCESS(ZydisDecoderDecodeFull(&decoder, bytes.data() + offset,
                                             bytes.size() - offset, &insn,
                                             operands))) {
      if (err) *err = "undecodable byte at offset " + std::to_string(offset);
      return "";
    }
    char text[256];
    if (!ZYAN_SUCCESS(ZydisFormatterFormatInstruction(
            &formatter, &insn, operands, insn.operand_count_visible, text,
            sizeof text, offset, ZYAN_NULL))) {
      if (err) *err = "format failed at offset " + std::to_string(offset);
      return "";
    }
    char line[300];
    std::snprintf(line, sizeof line, "%4llx: %s\n",
                  static_cast<unsigned long long>(offset), text);
    out += line;
    offset += insn.length;
  }
  return out;
}

}  // namespace disasmgen
```

- [ ] **Step 6: Implement the IR synthesizer.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/hybrid.hpp`:

```cpp
#pragma once
#include "ir.hpp"
#include <cstdint>
#include <vector>

namespace disasmgen {

// Deterministically draw `count` random IRFuncs. F64 never draws CmpOp::Eq
// (float equality is not lowered); trip_count in [1,16]; init_const in [0,99].
std::vector<IRFunc> synthesize_ir(int count, uint64_t seed);

}  // namespace disasmgen
```

  Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/hybrid.cpp`:

```cpp
#include "hybrid.hpp"

#include <random>

namespace disasmgen {

std::vector<IRFunc> synthesize_ir(int count, uint64_t seed) {
  std::mt19937_64 r(seed ^ 0xda3e39cb94b95bdbull);
  std::vector<IRFunc> out;
  out.reserve(count);
  for (int i = 0; i < count; ++i) {
    IRFunc f;
    f.ty = static_cast<Ty>(r() % 3);
    f.loop_op = static_cast<BinOp>(r() % 3);
    f.post_op = static_cast<BinOp>(r() % 3);
    f.cmp = (f.ty == Ty::F64) ? static_cast<CmpOp>(r() % 2)   // Lt | Gt only
                              : static_cast<CmpOp>(r() % 3);  // Lt | Gt | Eq
    f.trip_count = static_cast<int>(1 + r() % 16);
    f.init_const = static_cast<long long>(r() % 100);
    const char* ts = (f.ty == Ty::I32) ? "i32"
                     : (f.ty == Ty::I64) ? "i64" : "f64";
    f.name = std::string("h_") + ts + "_" + std::to_string(i);
    out.push_back(f);
  }
  return out;
}

}  // namespace disasmgen
```

- [ ] **Step 7: Build and run, see it pass.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build && cmake --build /Users/jbradley/Desktop/create_disasm_dataset/generator/build && ctest --test-dir /Users/jbradley/Desktop/create_disasm_dataset/generator/build --output-on-failure`. Expected: 4/4 pass (jsonl, direct, render_c, hybrid).

- [ ] **Step 8: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add generator/src/lower_asmjit.hpp generator/src/lower_asmjit.cpp \
        generator/src/format_zydis.hpp generator/src/format_zydis.cpp \
        generator/src/hybrid.hpp generator/src/hybrid.cpp \
        generator/tests/test_hybrid.cpp generator/CMakeLists.txt
git commit -m "$(cat <<'EOF'
feat(generator): hybrid route — IR->asmjit x86-64 bytes -> zydis asm text

asmjit pinned at v1.18 commit 7596c6d0, zydis at v4.1.1, both via
FetchContent. Fixed-seed IR decodes to the expected mnemonic sequence.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 7 [Stream A]: `disasmgen` CLI main

**Files:**
- Create: `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/main.cpp`
- Modify: `/Users/jbradley/Desktop/create_disasm_dataset/generator/CMakeLists.txt`
- Test: ctest smoke entries (binary exit codes) + manual JSONL validation step

**Interfaces:**
- Consumes: `synthesize_direct`, `synthesize_ir`, `render_c`, `signature_of`, `lower_x64`, `format_asm`, `JsonObj`.
- Produces: binary `disasmgen` with subcommand as `argv[1]` (`direct`|`hybrid`) and flags `--count N` (default 100), `--seed S` (default 0), `--out PATH` (default stdout). Prints one JSON object per line matching the FROZEN schema exactly. Per-record failures are skipped and logged to stderr as one structured JSON line; exit code is non-zero only on unrecoverable setup failure (bad args, unopenable `--out`).

- [ ] **Step 1: Register the binary and smoke tests in CMake (failing first).** Append to `generator/CMakeLists.txt`:

```cmake
add_executable(disasmgen src/main.cpp)
target_link_libraries(disasmgen PRIVATE disasmgen_core)

add_test(NAME cli_direct COMMAND disasmgen direct --count 3 --seed 1)
add_test(NAME cli_hybrid COMMAND disasmgen hybrid --count 3 --seed 1)
add_test(NAME cli_bad_route COMMAND disasmgen bogus)
set_tests_properties(cli_bad_route PROPERTIES WILL_FAIL TRUE)
```

- [ ] **Step 2: Run configure, see it fail.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build`. Expected failure: `Cannot find source file: src/main.cpp`.

- [ ] **Step 3: Implement.** Create `/Users/jbradley/Desktop/create_disasm_dataset/generator/src/main.cpp` (the JSON keys below are the FROZEN schema — do not rename any):

```cpp
#include "direct.hpp"
#include "format_zydis.hpp"
#include "hybrid.hpp"
#include "jsonl.hpp"
#include "lower_asmjit.hpp"
#include "render_c.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

void usage() {
  std::fprintf(stderr,
               "usage: disasmgen <direct|hybrid> [--count N] [--seed S] "
               "[--out PATH]\n");
}

struct Args {
  std::string route;
  int count = 100;
  unsigned long long seed = 0;
  std::string out_path;  // empty -> stdout
};

bool parse_args(int argc, char** argv, Args* a) {
  if (argc < 2) return false;
  a->route = argv[1];
  if (a->route != "direct" && a->route != "hybrid") return false;
  for (int i = 2; i < argc; ++i) {
    std::string flag = argv[i];
    if (i + 1 >= argc) return false;
    const char* val = argv[++i];
    if (flag == "--count")     a->count = std::atoi(val);
    else if (flag == "--seed") a->seed = std::strtoull(val, nullptr, 10);
    else if (flag == "--out")  a->out_path = val;
    else return false;
  }
  return a->count > 0;
}

}  // namespace

int main(int argc, char** argv) {
  Args args;
  if (!parse_args(argc, argv, &args)) {
    usage();
    return 2;
  }

  std::FILE* out = stdout;
  if (!args.out_path.empty()) {
    out = std::fopen(args.out_path.c_str(), "w");
    if (!out) {  // unrecoverable setup failure -> non-zero exit
      std::fprintf(stderr, "{\"error\":\"cannot open out path %s\"}\n",
                   disasmgen::json_escape(args.out_path).c_str());
      return 1;
    }
  }

  int emitted = 0, skipped = 0;
  if (args.route == "direct") {
    for (const auto& f : disasmgen::synthesize_direct(
             args.count, static_cast<uint64_t>(args.seed))) {
      disasmgen::JsonObj o;
      o.add("route", "direct");
      o.add("func_name", f.func_name);
      o.add("lang", f.lang);
      o.add("signature", f.signature);
      o.add("source_text", f.source_text);
      o.add_int("seed", static_cast<long long>(args.seed));
      std::fprintf(out, "%s\n", o.str().c_str());
      ++emitted;
    }
  } else {
    for (const auto& ir : disasmgen::synthesize_ir(
             args.count, static_cast<uint64_t>(args.seed))) {
      std::string err;
      std::vector<uint8_t> bytes = disasmgen::lower_x64(ir, &err);
      std::string asm_text =
          bytes.empty() ? std::string() : disasmgen::format_asm(bytes, &err);
      if (asm_text.empty()) {  // structured skip on stderr; never abort batch
        std::fprintf(stderr, "{\"skip\":\"%s\",\"reason\":\"%s\"}\n",
                     disasmgen::json_escape(ir.name).c_str(),
                     disasmgen::json_escape(err).c_str());
        ++skipped;
        continue;
      }
      disasmgen::JsonObj o;
      o.add("route", "hybrid");
      o.add("func_name", ir.name);
      o.add("lang", "c");
      o.add("signature", disasmgen::signature_of(ir));
      o.add("source_text", disasmgen::render_c(ir));
      o.add_int("seed", static_cast<long long>(args.seed));
      o.add("asm_text", asm_text);
      o.add("obj_format", "rawx86_64");
      o.add("compiler", "asmjit");
      o.add("opt_level", "none");
      std::fprintf(out, "%s\n", o.str().c_str());
      ++emitted;
    }
  }
  if (out != stdout) std::fclose(out);
  std::fprintf(stderr,
               "{\"done\":true,\"route\":\"%s\",\"emitted\":%d,\"skipped\":%d}\n",
               args.route.c_str(), emitted, skipped);
  return 0;
}
```

- [ ] **Step 4: Build, run ctest, see it pass.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build && cmake --build /Users/jbradley/Desktop/create_disasm_dataset/generator/build && ctest --test-dir /Users/jbradley/Desktop/create_disasm_dataset/generator/build --output-on-failure`. Expected: 7/7 pass.

- [ ] **Step 5: Validate JSONL output by hand.** Command: `/Users/jbradley/Desktop/create_disasm_dataset/generator/build/disasmgen hybrid --count 2 --seed 7 2>/dev/null | while IFS= read -r line; do printf '%s' "$line" | /Users/jbradley/Desktop/create_disasm_dataset/.venv/bin/python -m json.tool > /dev/null && echo "valid JSON"; done`. Expected output: `valid JSON` twice. Also run `/Users/jbradley/Desktop/create_disasm_dataset/generator/build/disasmgen direct --count 2 --seed 7 2>/dev/null | head -1` and confirm the line contains `"route":"direct"` and NO `"asm_text"` key.

- [ ] **Step 6: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add generator/src/main.cpp generator/CMakeLists.txt
git commit -m "$(cat <<'EOF'
feat(generator): disasmgen CLI — direct/hybrid subcommands printing JSONL

Pure generator: prints the frozen JSONL schema to --out/stdout, logs
per-record skips as structured stderr lines, never touches any DB.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 8 [Stream B]: `pipeline/generate.py` — record validation + Hybrid ingest

**Files:**
- Create: `/Users/jbradley/Desktop/create_disasm_dataset/pipeline/generate.py`
- Test: `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_generate.py` (create)

**Interfaces:**
- Consumes: `store.connect/init_schema/migrate/insert_pair(..., origin=...)` (Task 1); `Journal` (`pipeline/journal.py`).
- Produces: module constants `HOME`, `SCRATCH_ROOT` (under `$HOME`), `JOURNAL_PATH = "dataset/journal-gen.jsonl"`, `BIN`, `REQUIRED_COMMON`, `REQUIRED_HYBRID`; `parse_records(jsonl_text, journal=None) -> list[dict]` (malformed/incomplete lines skipped with a journal warning, never fatal); `ingest_hybrid(conn, records, journal=None) -> {"pairs": int, "dedup": int}` inserting exactly `store.insert_pair(conn, repo="gen:hybrid", file_path=f"gen/hybrid/{rec['func_name']}.c", func_name=..., signature=..., lang=..., arch="x86_64", opt_level="none", obj_format="rawx86_64", compiler="asmjit", source_text=..., asm_text=..., origin="gen:hybrid")`.

- [ ] **Step 1: Write the failing tests.** Create `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_generate.py`:

```python
import json
import os

import pipeline.generate as gen
import pipeline.store as store


def _hybrid_rec(name="h_i32_0", **over):
    rec = {"route": "hybrid", "func_name": name, "lang": "c",
           "signature": f"int {name}(int a, int b)",
           "source_text": f"int {name}(int a, int b) {{\n    return a + b;\n}}\n",
           "seed": 7,
           "asm_text": "   0: add edi, esi\n   2: mov eax, edi\n   4: ret\n",
           "obj_format": "rawx86_64", "compiler": "asmjit", "opt_level": "none"}
    rec.update(over)
    return rec


def _direct_rec(name="d0", **over):
    rec = {"route": "direct", "func_name": name, "lang": "c",
           "signature": f"int {name}(void)",
           "source_text": f"int {name}(void) {{\n    return 0;\n}}\n",
           "seed": 7}
    rec.update(over)
    return rec


def test_parse_records_accepts_valid_and_skips_bad():
    text = "\n".join([
        json.dumps(_hybrid_rec()),
        "{this is not json",                                   # malformed
        json.dumps({"route": "hybrid", "func_name": "x"}),     # missing fields
        json.dumps({"route": "bogus", "func_name": "y"}),      # bad route
        json.dumps({"skip": "h_f64_3", "reason": "err"}),      # stderr noise
        "",                                                    # blank line
        json.dumps(_direct_rec()),
    ])
    recs = gen.parse_records(text)
    assert [r["func_name"] for r in recs] == ["h_i32_0", "d0"]


def test_parse_records_direct_does_not_require_asm():
    recs = gen.parse_records(json.dumps(_direct_rec()))
    assert len(recs) == 1
    assert "asm_text" not in recs[0]


def test_schema_constants_match_frozen_contract():
    assert gen.REQUIRED_COMMON == ("route", "func_name", "lang", "signature",
                                   "source_text", "seed")
    assert gen.REQUIRED_HYBRID == ("asm_text", "obj_format", "compiler",
                                   "opt_level")
    assert gen.JOURNAL_PATH == "dataset/journal-gen.jsonl"
    assert gen.SCRATCH_ROOT.startswith(gen.HOME + os.sep)


def test_ingest_hybrid_origin_values_and_dedup(tmp_path):
    conn = store.connect(str(tmp_path / "g.db"))
    store.init_schema(conn)
    store.migrate(conn)
    stats = gen.ingest_hybrid(conn, [_hybrid_rec(), _hybrid_rec()])  # duplicate
    assert stats == {"pairs": 1, "dedup": 1}
    row = conn.execute(
        "SELECT origin, repo, file_path, arch, opt_level, obj_format, compiler "
        "FROM pairs").fetchone()
    assert row["origin"] == "gen:hybrid"
    assert row["repo"] == "gen:hybrid"
    assert row["file_path"] == "gen/hybrid/h_i32_0.c"
    assert row["arch"] == "x86_64"
    assert row["opt_level"] == "none"
    assert row["obj_format"] == "rawx86_64"
    assert row["compiler"] == "asmjit"
```

- [ ] **Step 2: Run tests, see them fail.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest tests/test_generate.py -q`. Expected: `ModuleNotFoundError: No module named 'pipeline.generate'`.

- [ ] **Step 3: Implement.** Create `/Users/jbradley/Desktop/create_disasm_dataset/pipeline/generate.py`:

```python
"""Generator ingest driver: runs the native `disasmgen` binary, validates its
JSONL against the frozen record schema, and ingests pairs into the SAME
dataset/pairs.db as the harvester — tagged origin='gen:direct'/'gen:hybrid'.

Runs in PARALLEL with the harvester: its own journal file
(dataset/journal-gen.jsonl, viewable with
`scripts/journal.sh --path dataset/journal-gen.jsonl -f`), its own dashboard
window (scripts/generate.sh), and a shared WAL DB serialized by busy_timeout.

Frozen JSONL record schema (the contract with generator/):
  common:  route ("direct"|"hybrid"), func_name, lang ("c"|"cpp"),
           signature, source_text, seed (int)
  hybrid adds: asm_text, obj_format ("rawx86_64"), compiler ("asmjit"),
           opt_level ("none")
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import pipeline.store as store
import pipeline.run_pipeline as run_pipeline
from pipeline.journal import Journal

HOME = os.path.expanduser("~")
# MUST be under $HOME — Colima only virtiofs-mounts the home dir, so a scratch
# repo anywhere else mounts as an empty /src inside the toolchain container
# (same constraint as harvest.SCRATCH_ROOT).
SCRATCH_ROOT = os.path.join(HOME, ".cache", "disasm_generate")
JOURNAL_PATH = "dataset/journal-gen.jsonl"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "generator", "build", "disasmgen")
GRAPH_SH = os.path.join(ROOT, "scripts", "build_graph.sh")

REQUIRED_COMMON = ("route", "func_name", "lang", "signature", "source_text", "seed")
REQUIRED_HYBRID = ("asm_text", "obj_format", "compiler", "opt_level")


def parse_records(jsonl_text, journal=None):
    """Validate JSONL against the frozen record schema. A malformed or
    incomplete line is skipped with a journal warning — never fatal."""
    records = []
    for i, line in enumerate(jsonl_text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            if journal:
                journal.event(f"malformed JSONL line {i}: not JSON — skipped",
                              level="warn")
            continue
        if not isinstance(rec, dict) or rec.get("route") not in ("direct", "hybrid"):
            if journal:
                journal.event(f"invalid record line {i}: bad route — skipped",
                              level="warn")
            continue
        required = REQUIRED_COMMON + (
            REQUIRED_HYBRID if rec["route"] == "hybrid" else ())
        missing = [k for k in required if k not in rec]
        if missing:
            if journal:
                journal.event(f"invalid record line {i}: missing {missing} — skipped",
                              level="warn")
            continue
        records.append(rec)
    return records


def ingest_hybrid(conn, records, journal=None):
    """Insert full hybrid pairs as-is (no compile step). Dedup collisions are
    counted, not errors (existing INSERT OR IGNORE via pair_hash)."""
    stats = {"pairs": 0, "dedup": 0}
    for rec in records:
        ok = store.insert_pair(
            conn, repo="gen:hybrid",
            file_path=f"gen/hybrid/{rec['func_name']}.c",
            func_name=rec["func_name"], signature=rec["signature"],
            lang=rec["lang"], arch="x86_64", opt_level="none",
            obj_format="rawx86_64", compiler="asmjit",
            source_text=rec["source_text"], asm_text=rec["asm_text"],
            origin="gen:hybrid")
        stats["pairs" if ok else "dedup"] += 1
    if journal:
        journal.event(f"hybrid ingest: {stats['pairs']} pairs, "
                      f"{stats['dedup']} dedup")
    return stats
```

- [ ] **Step 4: Run tests, see them pass.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest tests/test_generate.py -q`. Expected: all 4 pass. (`shutil`, `subprocess`, `sys`, `argparse`, `run_pipeline`, `Journal`, `GRAPH_SH` are imported now and used by Tasks 9–10.)

- [ ] **Step 5: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add pipeline/generate.py tests/test_generate.py
git commit -m "$(cat <<'EOF'
feat(generate): JSONL schema validation + hybrid ingest (origin=gen:hybrid)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 9 [Stream B]: `generate.py` — Direct ingest through the existing pipeline

**Files:**
- Modify: `/Users/jbradley/Desktop/create_disasm_dataset/pipeline/generate.py` (append functions)
- Test: `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_generate.py` (append)

**Interfaces:**
- Consumes: `run_pipeline.run(repo_dir, repo=None, db_path=..., compilers=..., opt_levels=..., progress=None, journal=None, origin="harvest")` (Task 2).
- Produces: `write_direct_repo(records, scratch_root=SCRATCH_ROOT) -> str` — writes ALL synthesized sources into ONE scratch "repo" dir under `$HOME`, one TU per record (`<func_name>.c` / `.cpp`); `ingest_direct(records, db_path, emit=..., journal=None) -> {"pairs","skipped","files"}` — calls `run_pipeline.run(scratch_dir, repo="gen:direct", db_path=db_path, progress=..., journal=journal, origin="gen:direct")`, then removes the scratch dir. tree-sitter re-extracts the function names inside `run`, so pairing round-trips; compile failures land in the existing `skipped` table and never abort the run. This test uses stubs — it does NOT need the C++ binary or Docker.

- [ ] **Step 1: Write the failing tests.** Append to `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_generate.py`:

```python
def test_write_direct_repo_one_tu_per_record_under_home(tmp_path):
    scratch = os.path.join(gen.HOME, ".cache", "disasm_generate_test")
    recs = [_direct_rec("d0"), _direct_rec("d1", lang="cpp")]
    try:
        dest = gen.write_direct_repo(recs, scratch_root=scratch)
        assert dest.startswith(gen.HOME + os.sep)   # Colima mount constraint
        with open(os.path.join(dest, "d0.c"), encoding="utf-8") as fh:
            assert fh.read() == recs[0]["source_text"]
        assert os.path.exists(os.path.join(dest, "d1.cpp"))
        # a second batch replaces, not accumulates
        dest2 = gen.write_direct_repo([_direct_rec("d2")], scratch_root=scratch)
        assert not os.path.exists(os.path.join(dest2, "d0.c"))
        assert os.path.exists(os.path.join(dest2, "d2.c"))
    finally:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)


def test_ingest_direct_threads_origin_and_cleans_up(tmp_path, monkeypatch):
    calls = {}

    def fake_run(repo_dir, repo=None, db_path="dataset/pairs.db",
                 compilers=("gcc", "clang"),
                 opt_levels=("O0", "O1", "O2", "O3", "Os"),
                 progress=None, journal=None, origin="harvest"):
        calls.update(repo_dir=repo_dir, repo=repo, db_path=db_path,
                     origin=origin, existed=os.path.isdir(repo_dir))
        if progress:
            progress({"type": "file", "file": "d0.c", "i": 1, "n": 1})
        return {"pairs": 3, "skipped": 1, "files": 1}

    monkeypatch.setattr(gen.run_pipeline, "run", fake_run)
    monkeypatch.setattr(gen, "SCRATCH_ROOT",
                        os.path.join(gen.HOME, ".cache", "disasm_generate_test"))
    events = []
    stats = gen.ingest_direct([_direct_rec("d0")], str(tmp_path / "g.db"),
                              emit=events.append)
    assert stats == {"pairs": 3, "skipped": 1, "files": 1}
    assert calls["repo"] == "gen:direct"
    assert calls["origin"] == "gen:direct"
    assert calls["repo_dir"].startswith(gen.HOME + os.sep)
    assert calls["existed"] is True                 # repo existed during run
    assert not os.path.exists(calls["repo_dir"])    # ...and is cleaned after
    assert any(e.get("type") == "file" and e.get("repo") == "gen:direct"
               for e in events)


def test_ingest_direct_empty_batch_is_noop(tmp_path):
    stats = gen.ingest_direct([], str(tmp_path / "g.db"))
    assert stats == {"pairs": 0, "skipped": 0, "files": 0}
```

- [ ] **Step 2: Run tests, see them fail.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest tests/test_generate.py -q`. Expected: the three new tests fail with `AttributeError: module 'pipeline.generate' has no attribute 'write_direct_repo'` / `'ingest_direct'`.

- [ ] **Step 3: Implement.** Append to `/Users/jbradley/Desktop/create_disasm_dataset/pipeline/generate.py`:

```python
def write_direct_repo(records, scratch_root=SCRATCH_ROOT):
    """Write every synthesized function as its own translation unit inside ONE
    scratch 'repo' dir under $HOME (Colima mount constraint), replacing any
    previous batch. Returns the repo dir path."""
    assert scratch_root.startswith(HOME + os.sep), "scratch root must be under $HOME"
    dest = os.path.join(scratch_root, "batch")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    for rec in records:
        ext = ".c" if rec["lang"] == "c" else ".cpp"
        path = os.path.join(dest, rec["func_name"] + ext)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(rec["source_text"])
    return dest


def ingest_direct(records, db_path, emit=lambda e: None, journal=None):
    """Compile synthesized sources through the EXISTING pipeline path
    (env -> compile -> disasm -> pair). tree-sitter re-extracts the function
    names from the written TUs, so pairing round-trips. Rows land with
    origin='gen:direct'; compile failures go to the existing `skipped` table
    and never abort the run."""
    if not records:
        return {"pairs": 0, "skipped": 0, "files": 0}
    dest = write_direct_repo(records)
    try:
        return run_pipeline.run(
            dest, repo="gen:direct", db_path=db_path,
            progress=lambda e: emit({**e, "repo": "gen:direct"}),
            journal=journal, origin="gen:direct")
    finally:
        shutil.rmtree(dest, ignore_errors=True)
```

- [ ] **Step 4: Run tests, see them pass.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest tests/test_generate.py -q`. Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add pipeline/generate.py tests/test_generate.py
git commit -m "$(cat <<'EOF'
feat(generate): direct ingest — scratch repo under $HOME through run_pipeline

One scratch 'repo' per batch; run_pipeline.run(..., origin='gen:direct')
reuses the whole env->compile->disasm->pair path with real objdump asm.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 10 [Stream B]: `generate.py` — binary runner, orchestration, CLI, dashboard, dbgraph hook

**Files:**
- Modify: `/Users/jbradley/Desktop/create_disasm_dataset/pipeline/generate.py` (append)
- Test: `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_generate.py` (append)

**Interfaces:**
- Consumes: `Journal(path="dataset/journal-gen.jsonl", emit=...)` with `.run(argv, *, cwd, env, timeout) -> (rc, out)`; `dashboard.run_with_dashboard(work, limit=None)`; `parse_records`/`ingest_hybrid`/`ingest_direct` (Tasks 8–9).
- Produces: `run_generator(route, count, seed, journal) -> list[dict]` — runs `[BIN, route, "--count", N, "--seed", S, "--out", tmpfile]` via `journal.run` (so the binary's stderr progress/skip lines stream into the dashboard mini-box while the JSONL lands clean in the `--out` file), then parses the file; `generate(count=100, route="both", db_path="dataset/pairs.db", seed=0, emit=...) -> {"pairs","skipped","dedup"}`; `refresh_graph(journal=None)` calling `scripts/build_graph.sh --structural-only`; `_plain(e)`; `main()` with CLI `--count N`, `--route {direct,hybrid,both}` (default both), `--db dataset/pairs.db`, `--seed S`, `--no-dashboard` — mirroring `harvest.main()`.

- [ ] **Step 1: Write the failing tests.** Append to `/Users/jbradley/Desktop/create_disasm_dataset/tests/test_generate.py`:

```python
def test_run_generator_reads_out_file_and_journals(tmp_path, monkeypatch):
    # A fake disasmgen: writes one frozen-schema record to --out, chatter to
    # stderr (which journal.run streams into the mini-box).
    rec_json = json.dumps(_hybrid_rec())
    fake = tmp_path / "disasmgen"
    fake.write_text(
        "#!/bin/sh\n"
        "out=''\n"
        'while [ $# -gt 0 ]; do\n'
        '  if [ "$1" = "--out" ]; then out="$2"; shift; fi\n'
        "  shift\n"
        "done\n"
        'printf %s\\\\n "$REC" > "$out"\n'
        'echo "{\\"done\\":true}" >&2\n')
    fake.chmod(0o755)
    monkeypatch.setenv("REC", rec_json)
    monkeypatch.setattr(gen, "BIN", str(fake))
    monkeypatch.setattr(gen, "SCRATCH_ROOT", str(tmp_path / "scratch"))
    from pipeline.journal import Journal
    j = Journal(path=str(tmp_path / "j.jsonl"))
    try:
        recs = gen.run_generator("hybrid", 1, 7, j)
    finally:
        j.close()
    assert len(recs) == 1
    assert recs[0]["func_name"] == "h_i32_0"
    journal_text = (tmp_path / "j.jsonl").read_text()
    assert "disasmgen" in journal_text          # journal.cmd recorded the argv


def test_run_generator_missing_binary_raises(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(gen, "BIN", str(tmp_path / "nope" / "disasmgen"))
    from pipeline.journal import Journal
    j = Journal(path=str(tmp_path / "j.jsonl"))
    try:
        with pytest.raises(RuntimeError, match="generate.sh"):
            gen.run_generator("hybrid", 1, 0, j)
    finally:
        j.close()


def test_generate_orchestrates_both_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "JOURNAL_PATH", str(tmp_path / "journal-gen.jsonl"))
    monkeypatch.setattr(
        gen, "run_generator",
        lambda route, count, seed, journal:
        [_hybrid_rec()] if route == "hybrid" else [_direct_rec()])
    monkeypatch.setattr(
        gen, "ingest_direct",
        lambda records, db_path, emit=None, journal=None:
        {"pairs": 2, "skipped": 1, "files": 1})
    events = []
    db = str(tmp_path / "g.db")
    totals = gen.generate(count=1, route="both", db_path=db, seed=7,
                          emit=events.append)
    assert totals == {"pairs": 3, "skipped": 1, "dedup": 0}
    assert os.path.exists(tmp_path / "journal-gen.jsonl")   # own journal file
    assert any(e.get("type") == "repo_done" and e.get("repo") == "gen:hybrid"
               for e in events)
    assert any(e.get("type") == "repo_done" and e.get("repo") == "gen:direct"
               for e in events)
    conn = store.connect(db)
    assert conn.execute(
        "SELECT origin FROM pairs").fetchone()[0] == "gen:hybrid"


def test_generate_single_route_hybrid_only(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "JOURNAL_PATH", str(tmp_path / "journal-gen.jsonl"))
    seen = []
    monkeypatch.setattr(
        gen, "run_generator",
        lambda route, count, seed, journal: seen.append(route) or [_hybrid_rec()])
    totals = gen.generate(count=1, route="hybrid",
                          db_path=str(tmp_path / "g.db"), seed=0)
    assert seen == ["hybrid"]
    assert totals["pairs"] == 1
```

- [ ] **Step 2: Run tests, see them fail.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest tests/test_generate.py -q`. Expected: the four new tests fail with `AttributeError: module 'pipeline.generate' has no attribute 'run_generator'` / `'generate'`.

- [ ] **Step 3: Implement.** Append to `/Users/jbradley/Desktop/create_disasm_dataset/pipeline/generate.py`:

```python
def run_generator(route, count, seed, journal):
    """Run the native generator via journal.run so its stderr progress/skip
    lines stream into the dashboard mini-box, while the JSONL itself lands
    clean in a --out temp file (journal.run merges stderr into stdout, so
    capturing JSONL from stdout would interleave)."""
    if not (os.path.isfile(BIN) and os.access(BIN, os.X_OK)):
        raise RuntimeError(
            f"{BIN} not found — build it with: cmake -S generator -B "
            f"generator/build && cmake --build generator/build "
            f"(scripts/generate.sh does this automatically)")
    os.makedirs(SCRATCH_ROOT, exist_ok=True)
    out_path = os.path.join(SCRATCH_ROOT, f"{route}.jsonl")
    rc, _ = journal.run([BIN, route, "--count", str(count),
                         "--seed", str(seed), "--out", out_path])
    if rc != 0:
        raise RuntimeError(f"disasmgen {route} failed (rc={rc})")
    with open(out_path, encoding="utf-8") as fh:
        text = fh.read()
    os.remove(out_path)
    return parse_records(text, journal=journal)


def generate(count=100, route="both", db_path="dataset/pairs.db", seed=0,
             emit=lambda e: None):
    """Run the selected route(s) and ingest into db_path. Returns totals."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = store.connect(db_path)
    store.init_schema(conn)
    store.migrate(conn)
    journal = Journal(path=JOURNAL_PATH, emit=emit)
    totals = {"pairs": 0, "skipped": 0, "dedup": 0}
    try:
        journal.event(f"generate start (route={route}, count={count}, seed={seed})")
        routes = ("direct", "hybrid") if route == "both" else (route,)
        for i, r in enumerate(routes):
            emit({"type": "stage", "repo": f"gen:{r}", "stage": "generating"})
            records = run_generator(r, count, seed, journal)
            journal.event(f"{r}: {len(records)} record(s) from generator")
            if r == "hybrid":
                st = ingest_hybrid(conn, records, journal=journal)
                totals["pairs"] += st["pairs"]
                totals["dedup"] += st["dedup"]
                emit({"type": "repo_done", "repo": "gen:hybrid", "status": "done",
                      "pairs": st["pairs"], "skipped": st["dedup"]})
            else:
                emit({"type": "stage", "repo": "gen:direct", "stage": "compiling"})
                st = ingest_direct(records, db_path, emit=emit, journal=journal)
                totals["pairs"] += st["pairs"]
                totals["skipped"] += st["skipped"]
                emit({"type": "repo_done", "repo": "gen:direct", "status": "done",
                      "pairs": st["pairs"], "skipped": st["skipped"]})
            emit({"type": "progress", "processed": i + 1})
        journal.event(f"generate finished: {totals['pairs']} pairs, "
                      f"{totals['skipped']} skipped, {totals['dedup']} dedup")
        return totals
    finally:
        conn.close()
        journal.close()


def refresh_graph():
    """Refresh the dbgraph knowledge graph after a run. `origin` is now a
    queryable dimension of the dataset graph (see db-graph/README.md)."""
    if not os.path.exists(GRAPH_SH):
        return
    subprocess.run(["bash", GRAPH_SH, "--structural-only"], check=False)


def _plain(e):
    t = e.get("type")
    if t == "repo_done":
        print(f"[{e.get('status')}] {e.get('repo')}  pairs={e.get('pairs', 0)} "
              f"skipped={e.get('skipped', 0)}")
    elif t == "stage" and e.get("repo"):
        print(f"  {e['stage']}: {e['repo']}")
    elif t == "log":
        print(f"  ({e.get('level')}) {e.get('msg')}")


def main():
    ap = argparse.ArgumentParser(
        description="Generate synthetic (asm, source) pairs via disasmgen.")
    ap.add_argument("--count", type=int, default=100, help="functions per route")
    ap.add_argument("--route", choices=("direct", "hybrid", "both"),
                    default="both")
    ap.add_argument("--db", default="dataset/pairs.db")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-dashboard", action="store_true",
                    help="plain line logging (CI/tests)")
    args = ap.parse_args()

    def work(emit):
        return generate(count=args.count, route=args.route, db_path=args.db,
                        seed=args.seed, emit=emit)

    if args.no_dashboard:
        totals = work(_plain)
    else:
        try:
            import pipeline.dashboard as dashboard
        except ImportError:
            print("rich not installed; falling back to plain logging "
                  "(pip install rich)", file=sys.stderr)
            totals = work(_plain)
        else:
            totals = dashboard.run_with_dashboard(work, limit=args.count)
    print(f"pairs={totals['pairs']} skipped={totals['skipped']} "
          f"dedup={totals['dedup']}")
    refresh_graph()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the full Python suite, see it pass.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest -q`. Expected: all non-integration tests pass (integration tests skip without Docker).

- [ ] **Step 5: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add pipeline/generate.py tests/test_generate.py
git commit -m "$(cat <<'EOF'
feat(generate): CLI + dashboard + own journal + dbgraph refresh

journal-gen.jsonl keeps the generator's stream separate from the
harvester's; dashboard reuses run_with_dashboard; refresh_graph() calls
scripts/build_graph.sh --structural-only after a run.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 11 [Stream C]: `scripts/generate.sh` — Terminal launcher + build-if-missing

**Files:**
- Create: `/Users/jbradley/Desktop/create_disasm_dataset/scripts/generate.sh`
- Test: `bash -n` syntax check + no-venv/no-binary error paths (full end-to-end is Task 13)

**Interfaces:**
- Consumes: `generator/CMakeLists.txt` (Stream A), `pipeline/generate.py` CLI (Stream B) — but this script can be WRITTEN and syntax-checked before either lands.
- Produces: `scripts/generate.sh [--count N] [--route direct|hybrid|both] [--seed S] [--here]` — mirrors `scripts/collect.sh`: builds `generator/build/disasmgen` via cmake if missing, then spawns a macOS Terminal running `.venv/bin/python -m pipeline.generate <args>` (or execs inline with `--here`).

- [ ] **Step 1: See the missing-script failure.** Command: `bash -n /Users/jbradley/Desktop/create_disasm_dataset/scripts/generate.sh`. Expected: `bash: /Users/jbradley/Desktop/create_disasm_dataset/scripts/generate.sh: No such file or directory`.

- [ ] **Step 2: Write the script.** Create `/Users/jbradley/Desktop/create_disasm_dataset/scripts/generate.sh`:

```bash
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
```

- [ ] **Step 3: Syntax-check and make executable.** Commands: `bash -n /Users/jbradley/Desktop/create_disasm_dataset/scripts/generate.sh && chmod +x /Users/jbradley/Desktop/create_disasm_dataset/scripts/generate.sh && echo OK`. Expected: `OK`.

- [ ] **Step 4: Verify the guard rails fire.** Command: `cd /tmp && ROOTLESS_DIR=$(mktemp -d) && cp -r /Users/jbradley/Desktop/create_disasm_dataset/scripts "$ROOTLESS_DIR/" && bash "$ROOTLESS_DIR/scripts/generate.sh" --here; echo "exit=$?"`. Expected: `error: ... .venv not found ...` and `exit=1` (no venv next to the copied script).

- [ ] **Step 5: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add scripts/generate.sh
git commit -m "$(cat <<'EOF'
feat(scripts): generate.sh — Terminal launcher, builds disasmgen if missing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 12 [Stream C]: docs — dbgraph `origin` note + README generator section

**Files:**
- Modify: `/Users/jbradley/Desktop/create_disasm_dataset/db-graph/README.md` (append), `/Users/jbradley/Desktop/create_disasm_dataset/README.md` (append)

**Interfaces:**
- Consumes: nothing at runtime — documentation of the `origin` column and the new track.
- Produces: user-facing docs; the dbgraph refresh itself is wired in Task 10 (`refresh_graph`) and re-verified end-to-end in Task 13.

- [ ] **Step 1: Append the dbgraph note.** Append to `/Users/jbradley/Desktop/create_disasm_dataset/db-graph/README.md`:

````markdown

## Provenance: the `origin` dimension

`pairs.origin` is now a queryable dimension of the graph: `'harvest'` rows come
from the GitHub harvester, `'gen:direct'` rows from compiler-in-the-loop
synthetic templates, and `'gen:hybrid'` rows from the asmjit/zydis IR generator
(`obj_format='rawx86_64'`, `compiler='asmjit'`). The graph is refreshed
automatically after each generator run (`scripts/build_graph.sh
--structural-only`), so per-origin slices show up in `DB_MAP.md` after a
rebuild:

```sql
SELECT origin, COUNT(*) FROM pairs GROUP BY origin;
```
````

- [ ] **Step 2: Append the README section.** Append to `/Users/jbradley/Desktop/create_disasm_dataset/README.md`:

````markdown

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
````

- [ ] **Step 3: Commit.**

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git add db-graph/README.md README.md
git commit -m "$(cat <<'EOF'
docs: origin provenance dimension in db-graph; generator track in README

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL
EOF
)"
```

---

## Task 13 [Stream C — REQUIRES Streams A and B complete]: end-to-end verification

**Files:**
- No new files — verification only (`generator/build/` artifacts, `dataset/pairs.db`, `dataset/journal-gen.jsonl`, `db-graph/` refresh).

**Interfaces:**
- Consumes: everything above, assembled: `scripts/generate.sh --here` → cmake build → `disasmgen` → `pipeline.generate` → `pairs.db` → `scripts/build_graph.sh --structural-only`.

- [ ] **Step 1: Full C++ test suite.** Command: `cmake -S /Users/jbradley/Desktop/create_disasm_dataset/generator -B /Users/jbradley/Desktop/create_disasm_dataset/generator/build && cmake --build /Users/jbradley/Desktop/create_disasm_dataset/generator/build && ctest --test-dir /Users/jbradley/Desktop/create_disasm_dataset/generator/build --output-on-failure`. Expected: 7/7 pass.

- [ ] **Step 2: Full Python test suite.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -m pytest -q`. Expected: all pass (integration tests skip if Docker/Colima is down).

- [ ] **Step 3: Hybrid end-to-end (no Docker needed).** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && scripts/generate.sh --here --route hybrid --count 25 --seed 1 --no-dashboard`. Expected output ends with `pairs=25 skipped=0 dedup=0` (or `dedup>0` on a re-run — re-running the same seed must dedup to 0 new pairs), followed by the dbgraph refresh output (`>> scan`, `>> build`, `done.`).

- [ ] **Step 4: Verify DB provenance split.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && .venv/bin/python -c "import pipeline.store as store; conn = store.connect('dataset/pairs.db'); print(dict(conn.execute('SELECT origin, COUNT(*) FROM pairs GROUP BY origin').fetchall()))"`. Expected: `{'harvest': <existing count>, 'gen:hybrid': 25}` — existing rows were backfilled to `'harvest'`, generated rows are tagged.

- [ ] **Step 5: Verify the generator's own journal.** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && scripts/journal.sh --path dataset/journal-gen.jsonl` (or `.venv/bin/python -m pipeline.journal --path dataset/journal-gen.jsonl --tail 20`). Expected: `$ .../disasmgen hybrid --count 25 ...` cmd line plus `generate start` / `generate finished` events; `dataset/journal.jsonl` (the harvester's) is untouched by this run.

- [ ] **Step 6: Direct end-to-end (needs Docker/Colima up; skip if unavailable, noting it).** Command: `cd /Users/jbradley/Desktop/create_disasm_dataset && scripts/generate.sh --here --route direct --count 10 --seed 1 --no-dashboard`. Expected: pairs > 0 (each function × gcc/clang × O0–Os yields up to 100 pairs from 10 sources; some templates may skip at some opt levels — that is the existing `skipped`-table path, not an error). Then re-run Step 4 and confirm a `'gen:direct'` bucket appeared.

- [ ] **Step 7: Parallel smoke (optional but recommended).** Start `scripts/collect.sh --limit 1` and, while it runs, `scripts/generate.sh --here --route hybrid --count 50 --seed 2 --no-dashboard`. Expected: both complete without `database is locked` (WAL + busy_timeout=5000).

- [ ] **Step 8: Commit any verification fixes and finish.** If Steps 1–7 exposed fixes, commit them with the same trailer format, then run the superpowers:finishing-a-development-branch skill to integrate.

```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
git status   # confirm clean tree; every task was committed as it landed
```

---

## Self-review checklist (verified during authoring)

- Spec coverage: Direct route (Tasks 4, 2, 9), Hybrid route (Tasks 5–7, 8), `origin` column + backfill + `busy_timeout` (Task 1), pure-generator boundary (Task 7 — JSONL only), own journal `dataset/journal-gen.jsonl` (Task 10), own dashboard + Terminal launcher (Tasks 10–11), dbgraph refresh + docs (Tasks 10, 12), error handling (skip-and-log in `main.cpp`, `parse_records`, `skipped` table via `run_pipeline`), Windows seam (no OS-specific code in `generator/`; PE lands later via a new `obj_format` without touching it).
- The frozen JSONL schema is identical in the contract section, `main.cpp`, `REQUIRED_COMMON`/`REQUIRED_HYBRID`, and every test fixture (`_hybrid_rec`, `_direct_rec`).
- All signatures used across tasks match the exact existing interfaces: `run(..., progress=None, journal=None, origin="harvest")`, `insert_pair(..., origin='harvest')`, `Journal(path=..., emit=...)`, `run_with_dashboard(work, limit=None)`, `compile_tu(tc, rel_src, compiler, opt, lang, include_dirs)`.
- `pair_hash` untouched; scratch dirs under `$HOME`; pinned deps verified to exist (asmjit `7596c6d0…` = v1.18 with snake_case API confirmed against its headers; zydis `v4.1.1` tag confirmed).
