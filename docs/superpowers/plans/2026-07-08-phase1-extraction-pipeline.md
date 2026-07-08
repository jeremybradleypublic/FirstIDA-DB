# Phase 1: Per-Repo Extraction Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the per-repo pipeline that extracts `(x86-64 disassembly, C/C++ source)` function pairs from a local repository and populates `dataset/pairs.db`, proven end-to-end on the bundled zlib checkout.

**Architecture:** Pure-Python host stages (parse, pair, store) plus a Dockerized Linux toolchain (GCC + Clang + binutils) driven over `docker exec`. Source functions are extracted with tree-sitter; whole translation units are compiled at five opt levels by two compilers; `objdump` output is split per symbol and joined back to source functions **by name**. Unmatched functions (inlined / DCE'd) are dropped; failures are logged, never fatal. Dedup + idempotency come from a `pair_hash` UNIQUE constraint.

**Tech Stack:** Python 3.11+, tree-sitter (C + C++ grammars), SQLite (stdlib `sqlite3`), Colima + Docker CLI, a `debian:bookworm-slim` toolchain image (gcc, g++, clang, clang++, binutils), pytest.

## Global Constraints

- Python **3.11+**.
- Target: **x86-64**, **ELF** object format, produced inside a `--platform linux/amd64` container.
- Compilers: **gcc and clang** (both `.c` via gcc/clang, `.cc/.cpp/...` via g++/clang++).
- Optimization levels, each a distinct sample: **O0, O1, O2, O3, Os**.
- Assembly (X) = **`objdump -d`** output split per function symbol (AT&T, with raw bytes).
- Pairing joins by **(demangled) function base identifier**; **accuracy over recall** — no match ⇒ no pair.
- Every write is **idempotent** via `pairs.pair_hash` UNIQUE = `sha1(func_name + "\n" + asm_text + "\n" + source_text)`.
- DB path default: **`dataset/pairs.db`**. Never commit the DB (it is gitignored).
- Commit message trailer on every commit:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL`.

---

## File Structure

```
pipeline/
  __init__.py
  store.py          # SQLite schema, insert, dedup, skip log        (Task 1, pure)
  extract.py        # tree-sitter -> FunctionRecord list            (Task 2, pure)
  disasm.py         # parse_objdump (pure) + disassemble (docker)   (Task 3+6)
  pair.py           # join FunctionRecord <-> AsmFunc               (Task 4, pure)
  env.py            # Colima/Docker toolchain provisioning + exec   (Task 5, docker)
  compile.py        # compile one TU in-container                   (Task 6, docker)
  run_pipeline.py   # per-repo orchestrator + CLI                   (Task 7, docker)
docker/
  Dockerfile        # gcc/g++/clang/clang++/binutils toolchain image (Task 0)
tests/
  conftest.py       # docker-gated `toolchain` fixture              (Task 5)
  fixtures/
    simple.c
    overload.cpp
    broken.c
    objdump_sample.txt
    minirepo/add.c
    minirepo/add.h
  test_store.py     test_extract.py  test_disasm.py
  test_pair.py      test_env.py      test_compile.py  test_run_pipeline.py
requirements.txt
pytest.ini
README.md
```

**Interfaces shared across tasks (defined where noted, referenced elsewhere):**

- `extract.FunctionRecord` — `@dataclass(frozen=True)` fields: `name:str, signature:str, source_text:str, start_line:int, is_static:bool, lang:str`.
- `disasm.AsmFunc` — `@dataclass(frozen=True)` fields: `symbol:str, demangled:str, asm_text:str`.
- `pair.Pair` — `@dataclass(frozen=True)` fields: `func_name:str, signature:str, source_text:str, asm_text:str, lang:str`.
- `env.Toolchain` — object with `.container:str`, `.scratch:str`, `.exec(argv:list[str], input:str|None=None) -> subprocess.CompletedProcess`, `.stop() -> None`.
- `compile.CompileResult` — `@dataclass(frozen=True)` fields: `ok:bool, obj_path:str|None, reason:str|None` (`obj_path` is a container path like `/out/ab12.o`).

---

## Task 0: Scaffold, dependencies, and toolchain image

**Files:**
- Create: `pipeline/__init__.py` (empty)
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `docker/Dockerfile`
- Create: `tests/__init__.py` (empty)

**Interfaces:**
- Consumes: nothing.
- Produces: a working venv with tree-sitter + pytest importable; a buildable `docker/Dockerfile`.

- [ ] **Step 1: Write `requirements.txt`**

```
tree-sitter>=0.23,<0.24
tree-sitter-c>=0.23,<0.24
tree-sitter-cpp>=0.23,<0.24
pytest>=8,<9
```

- [ ] **Step 2: Write `pytest.ini`**

```ini
[pytest]
markers =
    integration: requires Docker/Colima toolchain (skipped when unavailable)
testpaths = tests
```

- [ ] **Step 3: Write `docker/Dockerfile`**

```dockerfile
# x86-64 ELF toolchain: GCC, Clang, and binutils (objdump, c++filt).
FROM --platform=linux/amd64 debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gcc g++ clang binutils libc6-dev \
 && rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
```

- [ ] **Step 4: Create venv and install deps**

Run:
```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
Expected: installs succeed; no errors.

- [ ] **Step 5: Verify the tree-sitter API we rely on**

Run:
```bash
.venv/bin/python -c "from tree_sitter import Language, Parser; import tree_sitter_c, tree_sitter_cpp; Language(tree_sitter_c.language()); Language(tree_sitter_cpp.language()); print('ok')"
```
Expected: prints `ok`. (If it errors, the grammar API changed — adjust `extract.py` in Task 2 accordingly before proceeding.)

- [ ] **Step 6: Create empty package files**

```bash
touch pipeline/__init__.py tests/__init__.py
```

- [ ] **Step 7: Commit**

```bash
git add pipeline/__init__.py tests/__init__.py requirements.txt pytest.ini docker/Dockerfile
git commit -m "chore: scaffold pipeline package, deps, and toolchain Dockerfile

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL"
```

---

## Task 1: `store.py` — SQLite schema, insert, dedup, skip log

**Files:**
- Create: `pipeline/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `connect(db_path:str) -> sqlite3.Connection`
  - `init_schema(conn) -> None`
  - `insert_pair(conn, *, repo, file_path, func_name, signature, lang, arch, opt_level, obj_format, compiler, source_text, asm_text) -> bool` (True if inserted, False if duplicate)
  - `record_skip(conn, *, repo, file_path, opt_level, reason) -> None`
  - `count_pairs(conn) -> int`

- [ ] **Step 1: Write the failing test** — `tests/test_store.py`

```python
import pipeline.store as store


def _mk(tmp_path):
    conn = store.connect(str(tmp_path / "t.db"))
    store.init_schema(conn)
    return conn


def _args(**over):
    base = dict(repo="zlib", file_path="a.c", func_name="foo", signature="int foo(void)",
                lang="c", arch="x86_64", opt_level="O0", obj_format="elf",
                compiler="gcc-12.2.0", source_text="int foo(void){return 1;}",
                asm_text="<foo>:\n ret")
    base.update(over)
    return base


def test_insert_then_dedup(tmp_path):
    conn = _mk(tmp_path)
    assert store.insert_pair(conn, **_args()) is True
    assert store.insert_pair(conn, **_args()) is False   # identical -> dedup
    assert store.count_pairs(conn) == 1


def test_distinct_asm_is_new_row(tmp_path):
    conn = _mk(tmp_path)
    assert store.insert_pair(conn, **_args(asm_text="<foo>:\n nop\n ret")) is True
    assert store.insert_pair(conn, **_args(asm_text="<foo>:\n ret")) is True
    assert store.count_pairs(conn) == 2


def test_record_skip(tmp_path):
    conn = _mk(tmp_path)
    store.record_skip(conn, repo="zlib", file_path="b.c", opt_level="O2", reason="compile failed")
    n = conn.execute("SELECT COUNT(*) FROM skipped").fetchone()[0]
    assert n == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError` (module not written yet).

- [ ] **Step 3: Write minimal implementation** — `pipeline/store.py`

```python
import hashlib
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pairs (
    id          INTEGER PRIMARY KEY,
    repo        TEXT, file_path TEXT, func_name TEXT, signature TEXT, lang TEXT,
    arch        TEXT, opt_level TEXT, obj_format TEXT, compiler TEXT,
    source_text TEXT, asm_text TEXT,
    source_hash TEXT, asm_hash TEXT,
    pair_hash   TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS skipped (
    id INTEGER PRIMARY KEY, repo TEXT, file_path TEXT, opt_level TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY, url TEXT, commit_sha TEXT, license TEXT,
    status TEXT, n_pairs INTEGER, processed_at TEXT
);
"""


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "surrogatepass")).hexdigest()


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def insert_pair(conn, *, repo, file_path, func_name, signature, lang, arch,
                opt_level, obj_format, compiler, source_text, asm_text) -> bool:
    source_hash = _sha1(source_text)
    asm_hash = _sha1(asm_text)
    pair_hash = _sha1(f"{func_name}\n{asm_text}\n{source_text}")
    cur = conn.execute(
        """INSERT OR IGNORE INTO pairs
           (repo,file_path,func_name,signature,lang,arch,opt_level,obj_format,
            compiler,source_text,asm_text,source_hash,asm_hash,pair_hash)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (repo, file_path, func_name, signature, lang, arch, opt_level, obj_format,
         compiler, source_text, asm_text, source_hash, asm_hash, pair_hash),
    )
    conn.commit()
    return cur.rowcount == 1


def record_skip(conn, *, repo, file_path, opt_level, reason) -> None:
    conn.execute(
        "INSERT INTO skipped (repo,file_path,opt_level,reason) VALUES (?,?,?,?)",
        (repo, file_path, opt_level, reason),
    )
    conn.commit()


def count_pairs(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM pairs").fetchone()[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/store.py tests/test_store.py
git commit -m "feat: sqlite store with pair dedup and skip log

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL"
```

---

## Task 2: `extract.py` — tree-sitter function extraction

**Files:**
- Create: `pipeline/extract.py`
- Test: `tests/test_extract.py`
- Test fixtures: `tests/fixtures/simple.c`, `tests/fixtures/overload.cpp`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `FunctionRecord` dataclass (fields listed in shared interfaces above).
  - `lang_for(path:str) -> str | None` (`"c"`, `"cpp"`, or `None` if not a TU).
  - `extract_functions(path:str) -> list[FunctionRecord]`.

- [ ] **Step 1: Write fixtures**

`tests/fixtures/simple.c`:
```c
#include <stdint.h>

static uint32_t helper(uint32_t a, uint32_t b) {
    return a + b;
}

int addtwo(int x, int y) {
    return x + y;
}
```

`tests/fixtures/overload.cpp`:
```cpp
int add(int a, int b) { return a + b; }
double add(double a, double b) { return a + b; }
```

- [ ] **Step 2: Write the failing test** — `tests/test_extract.py`

```python
import os
import pipeline.extract as extract

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_lang_for():
    assert extract.lang_for("a.c") == "c"
    assert extract.lang_for("a.cpp") == "cpp"
    assert extract.lang_for("a.cc") == "cpp"
    assert extract.lang_for("a.txt") is None


def test_extract_c_functions():
    recs = extract.extract_functions(os.path.join(FIX, "simple.c"))
    by_name = {r.name: r for r in recs}
    assert set(by_name) == {"helper", "addtwo"}
    assert by_name["helper"].is_static is True
    assert by_name["addtwo"].is_static is False
    assert by_name["addtwo"].lang == "c"
    assert "return x + y;" in by_name["addtwo"].source_text
    assert by_name["addtwo"].signature.startswith("int addtwo(int x, int y)")


def test_extract_cpp_overloads():
    recs = extract.extract_functions(os.path.join(FIX, "overload.cpp"))
    assert [r.name for r in recs] == ["add", "add"]
    assert all(r.lang == "cpp" for r in recs)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_extract.py -v`
Expected: FAIL — module not written.

- [ ] **Step 4: Write minimal implementation** — `pipeline/extract.py`

```python
from dataclasses import dataclass

from tree_sitter import Language, Parser
import tree_sitter_c
import tree_sitter_cpp

_C = Language(tree_sitter_c.language())
_CPP = Language(tree_sitter_cpp.language())

_C_EXT = {".c"}
_CPP_EXT = {".cc", ".cpp", ".cxx", ".c++", ".C"}
_NAME_TYPES = {"identifier", "field_identifier", "qualified_identifier",
               "destructor_name", "operator_name"}


@dataclass(frozen=True)
class FunctionRecord:
    name: str
    signature: str
    source_text: str
    start_line: int
    is_static: bool
    lang: str


def lang_for(path: str):
    for ext in _C_EXT:
        if path.endswith(ext):
            return "c"
    for ext in _CPP_EXT:
        if path.endswith(ext):
            return "cpp"
    return None


def _descend_declarator(node, target_types):
    """Follow `declarator` fields until reaching a node of a target type."""
    cur = node
    while cur is not None and cur.type not in target_types:
        cur = cur.child_by_field_name("declarator")
    return cur


def _function_name(fn_node, src: bytes):
    decl = _descend_declarator(fn_node.child_by_field_name("declarator"),
                               {"function_declarator"})
    if decl is None:
        return None
    name_node = _descend_declarator(decl.child_by_field_name("declarator"), _NAME_TYPES)
    if name_node is None:
        return None
    text = src[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace")
    return text.split("::")[-1].strip()


def _is_static(fn_node, src: bytes) -> bool:
    for child in fn_node.children:
        if child.type == "storage_class_specifier":
            if src[child.start_byte:child.end_byte] == b"static":
                return True
    return False


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "function_definition":
            yield n
        stack.extend(n.children)


def extract_functions(path: str):
    lang = lang_for(path)
    if lang is None:
        return []
    with open(path, "rb") as fh:
        src = fh.read()
    parser = Parser(_C if lang == "c" else _CPP)
    tree = parser.parse(src)
    out = []
    for fn in _walk(tree.root_node):
        name = _function_name(fn, src)
        if not name:
            continue
        body = fn.child_by_field_name("body")
        end_sig = body.start_byte if body is not None else fn.end_byte
        signature = src[fn.start_byte:end_sig].decode("utf-8", "replace").strip()
        source_text = src[fn.start_byte:fn.end_byte].decode("utf-8", "replace")
        out.append(FunctionRecord(
            name=name, signature=signature, source_text=source_text,
            start_line=fn.start_point[0] + 1, is_static=_is_static(fn, src), lang=lang,
        ))
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_extract.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add pipeline/extract.py tests/test_extract.py tests/fixtures/simple.c tests/fixtures/overload.cpp
git commit -m "feat: tree-sitter C/C++ function extraction

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL"
```

---

## Task 3: `disasm.py` — pure objdump parser

**Files:**
- Create: `pipeline/disasm.py`
- Test: `tests/test_disasm.py`
- Test fixture: `tests/fixtures/objdump_sample.txt`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `AsmFunc` dataclass (fields in shared interfaces; `demangled` defaults to `symbol`).
  - `parse_objdump(text:str) -> list[AsmFunc]` — splits GNU `objdump -d` output into per-symbol blocks; `asm_text` includes the `<name>:` header line through the block's instructions.
  - (`disassemble(...)` that runs objdump in the container is added in Task 6.)

- [ ] **Step 1: Write fixture** — `tests/fixtures/objdump_sample.txt`

```
sample.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000000000 <addtwo>:
   0:	8d 04 37             	lea    (%rdi,%rsi,1),%eax
   4:	c3                   	ret

0000000000000010 <_Z3addii>:
  10:	8d 04 37             	lea    (%rdi,%rsi,1),%eax
  14:	c3                   	ret
```

- [ ] **Step 2: Write the failing test** — `tests/test_disasm.py`

```python
import os
import pipeline.disasm as disasm

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_parse_objdump_splits_symbols():
    text = open(os.path.join(FIX, "objdump_sample.txt")).read()
    funcs = disasm.parse_objdump(text)
    by_sym = {f.symbol: f for f in funcs}
    assert set(by_sym) == {"addtwo", "_Z3addii"}
    assert by_sym["addtwo"].asm_text.startswith("<addtwo>:")
    assert "ret" in by_sym["addtwo"].asm_text
    # the second function's instructions do not leak into the first
    assert "_Z3addii" not in by_sym["addtwo"].asm_text
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_disasm.py -v`
Expected: FAIL — module not written.

- [ ] **Step 4: Write minimal implementation** — `pipeline/disasm.py`

```python
import re
from dataclasses import dataclass

_HEADER = re.compile(r"^[0-9a-fA-F]+ <(?P<name>.+)>:$")


@dataclass(frozen=True)
class AsmFunc:
    symbol: str
    demangled: str
    asm_text: str


def parse_objdump(text: str):
    funcs = []
    cur_name = None
    cur_lines = []

    def flush():
        if cur_name is not None:
            asm = "\n".join(cur_lines).rstrip()
            funcs.append(AsmFunc(symbol=cur_name, demangled=cur_name, asm_text=asm))

    for raw in text.splitlines():
        m = _HEADER.match(raw.strip())
        if m:
            flush()
            cur_name = m.group("name")
            cur_lines = [f"<{cur_name}>:"]
        elif cur_name is not None:
            if raw.strip() == "":
                continue
            cur_lines.append(raw.rstrip())
    flush()
    return funcs
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_disasm.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add pipeline/disasm.py tests/test_disasm.py tests/fixtures/objdump_sample.txt
git commit -m "feat: pure objdump-output parser splitting per symbol

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL"
```

---

## Task 4: `pair.py` — join source functions to disassembled symbols

**Files:**
- Create: `pipeline/pair.py`
- Test: `tests/test_pair.py`

**Interfaces:**
- Consumes: `extract.FunctionRecord`, `disasm.AsmFunc`.
- Produces:
  - `Pair` dataclass (fields in shared interfaces).
  - `base_name(symbol:str, demangled:str) -> str` — strips GCC clone suffixes + leading underscore; for C++ derives the trailing identifier from the demangled signature.
  - `pair_functions(records:list[FunctionRecord], asm:list[AsmFunc]) -> list[Pair]` — matches by base identifier (first asm wins on collision), preserving `records` order; unmatched records are dropped.

- [ ] **Step 1: Write the failing test** — `tests/test_pair.py`

```python
from pipeline.extract import FunctionRecord
from pipeline.disasm import AsmFunc
import pipeline.pair as pair


def _rec(name, lang="c"):
    return FunctionRecord(name=name, signature=f"int {name}(void)",
                          source_text=f"int {name}(void){{return 0;}}",
                          start_line=1, is_static=False, lang=lang)


def test_base_name_strips_gcc_clone_suffix():
    assert pair.base_name("deflate.constprop.0", "deflate.constprop.0") == "deflate"
    assert pair.base_name("fill.part.3", "fill.part.3") == "fill"


def test_base_name_cpp_from_demangled():
    assert pair.base_name("_Z3addii", "add(int, int)") == "add"


def test_pair_matches_by_name_and_drops_unmatched():
    recs = [_rec("addtwo"), _rec("inlined_away")]
    asm = [AsmFunc(symbol="addtwo", demangled="addtwo", asm_text="<addtwo>:\n ret")]
    pairs = pair.pair_functions(recs, asm)
    assert len(pairs) == 1
    assert pairs[0].func_name == "addtwo"
    assert pairs[0].asm_text == "<addtwo>:\n ret"


def test_pair_matches_gcc_clone_to_source():
    recs = [_rec("deflate")]
    asm = [AsmFunc(symbol="deflate.constprop.0", demangled="deflate.constprop.0",
                   asm_text="<deflate.constprop.0>:\n ret")]
    pairs = pair.pair_functions(recs, asm)
    assert len(pairs) == 1 and pairs[0].func_name == "deflate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pair.py -v`
Expected: FAIL — module not written.

- [ ] **Step 3: Write minimal implementation** — `pipeline/pair.py`

```python
import re
from dataclasses import dataclass

from pipeline.extract import FunctionRecord
from pipeline.disasm import AsmFunc

_CLONE = re.compile(r"\.(constprop|isra|part|cold|lto_priv|clone)(\.\d+)*$")


@dataclass(frozen=True)
class Pair:
    func_name: str
    signature: str
    source_text: str
    asm_text: str
    lang: str


def base_name(symbol: str, demangled: str) -> str:
    if "(" in demangled:                       # C++ demangled signature
        head = demangled.split("(", 1)[0]
        return head.split("::")[-1].strip()
    s = _CLONE.sub("", symbol)
    return s.lstrip("_")


def pair_functions(records, asm):
    index = {}
    for a in asm:
        key = base_name(a.symbol, a.demangled)
        index.setdefault(key, a)             # first symbol wins on collision
    out = []
    for r in records:
        a = index.get(r.name)
        if a is None:
            continue
        out.append(Pair(func_name=r.name, signature=r.signature,
                        source_text=r.source_text, asm_text=a.asm_text, lang=r.lang))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pair.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/pair.py tests/test_pair.py
git commit -m "feat: name-based pairing of source functions to asm symbols

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL"
```

---

## Task 5: `env.py` — auto-provisioned Docker toolchain

**Files:**
- Create: `pipeline/env.py`
- Create: `tests/conftest.py`
- Test: `tests/test_env.py`

**Interfaces:**
- Consumes: `docker/Dockerfile` (Task 0).
- Produces:
  - `IMAGE = "disasm-toolchain:latest"`
  - `docker_available() -> bool` (True iff `docker info` succeeds).
  - `ensure_image(image:str=IMAGE) -> None` (build from `docker/` if missing; ensure Colima up).
  - `start_toolchain(repo_dir:str, image:str=IMAGE) -> Toolchain` (starts a `--platform linux/amd64` container with `repo_dir` mounted read-only at `/src` and a fresh host scratch dir mounted read-write at `/out`).
  - `Toolchain.exec(argv, input=None) -> subprocess.CompletedProcess`, `Toolchain.stop() -> None`.
- Provides pytest fixture `toolchain` (in `conftest.py`) that skips when `docker_available()` is False and tears the container down after the test.

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import os
import pytest
import pipeline.env as env

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(scope="session")
def toolchain():
    if not env.docker_available():
        pytest.skip("Docker/Colima not available")
    env.ensure_image()
    tc = env.start_toolchain(os.path.join(FIX, "minirepo"))
    yield tc
    tc.stop()
```

- [ ] **Step 2: Write the failing test** — `tests/test_env.py`

```python
import pytest
import pipeline.env as env

pytestmark = pytest.mark.integration


def test_container_runs_gcc_and_objdump(toolchain):
    r = toolchain.exec(["gcc", "--version"])
    assert r.returncode == 0 and "gcc" in r.stdout.lower()
    r = toolchain.exec(["clang", "--version"])
    assert r.returncode == 0 and "clang" in r.stdout.lower()
    r = toolchain.exec(["objdump", "--version"])
    assert r.returncode == 0
    # /src is mounted read-only and contains the mini repo
    r = toolchain.exec(["ls", "/src"])
    assert "add.c" in r.stdout
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_env.py -v`
Expected: FAIL — module not written (collection/attribute error). (If Docker is down it would skip; write the code regardless.)

- [ ] **Step 4: Write minimal implementation** — `pipeline/env.py`

```python
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass

IMAGE = "disasm-toolchain:latest"
_DOCKERFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docker")


def _run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def docker_available() -> bool:
    try:
        return _run(["docker", "info"]).returncode == 0
    except FileNotFoundError:
        return False


def _ensure_colima():
    st = _run(["colima", "status"])
    if st.returncode != 0:
        _run(["colima", "start"])


def ensure_image(image: str = IMAGE) -> None:
    _ensure_colima()
    if _run(["docker", "image", "inspect", image]).returncode == 0:
        return
    build = _run(["docker", "build", "--platform", "linux/amd64",
                  "-t", image, _DOCKERFILE_DIR])
    if build.returncode != 0:
        raise RuntimeError(f"toolchain image build failed:\n{build.stderr}")


@dataclass
class Toolchain:
    container: str
    scratch: str

    def exec(self, argv, input=None):
        return _run(["docker", "exec", "-i", self.container] + list(argv), input=input)

    def stop(self):
        _run(["docker", "rm", "-f", self.container])


def start_toolchain(repo_dir: str, image: str = IMAGE) -> Toolchain:
    ensure_image(image)
    scratch = tempfile.mkdtemp(prefix="disasm_out_")
    name = "disasm_tc_" + uuid.uuid4().hex[:12]
    run = _run(["docker", "run", "-d", "--platform", "linux/amd64", "--name", name,
                "-v", f"{os.path.abspath(repo_dir)}:/src:ro",
                "-v", f"{scratch}:/out",
                image])
    if run.returncode != 0:
        raise RuntimeError(f"container start failed:\n{run.stderr}")
    return Toolchain(container=name, scratch=scratch)
```

- [ ] **Step 5: Create the mini-repo fixture used by the fixture container**

`tests/fixtures/minirepo/add.h`:
```c
int add(int a, int b);
```
`tests/fixtures/minirepo/add.c`:
```c
#include "add.h"
int add(int a, int b) { return a + b; }
static int mul(int a, int b) { return a * b; }
int use(int x) { return add(x, mul(x, 2)); }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_env.py -v`
Expected: PASS (first run builds the image — may take a few minutes). If Docker is unavailable, it SKIPs — start Colima with `colima start` and re-run.

- [ ] **Step 7: Commit**

```bash
git add pipeline/env.py tests/conftest.py tests/test_env.py tests/fixtures/minirepo/add.c tests/fixtures/minirepo/add.h
git commit -m "feat: auto-provisioned Docker toolchain (Colima + image + exec)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL"
```

---

## Task 6: `compile.py` + `disasm.disassemble` — in-container compile & disassemble

**Files:**
- Create: `pipeline/compile.py`
- Modify: `pipeline/disasm.py` (add `disassemble` + `_demangle`)
- Test: `tests/test_compile.py`

**Interfaces:**
- Consumes: `env.Toolchain`, `disasm.parse_objdump`, `disasm.AsmFunc`.
- Produces:
  - `compiler_binary(compiler:str, lang:str) -> str` (`gcc`/`g++`/`clang`/`clang++`).
  - `compiler_label(tc, compiler:str, lang:str) -> str` (e.g. `"gcc-12.2.0"`).
  - `compile_tu(tc, rel_src:str, compiler:str, opt:str, lang:str, include_dirs:list[str]) -> CompileResult`.
  - `disasm.disassemble(tc, obj_container_path:str) -> list[AsmFunc]` (runs `objdump -d`, demangles C++ symbols via `c++filt`).

- [ ] **Step 1: Write the failing test** — `tests/test_compile.py`

```python
import pytest
import pipeline.compile as compile_mod
import pipeline.disasm as disasm

pytestmark = pytest.mark.integration


def test_compile_and_disassemble_minirepo(toolchain):
    res = compile_mod.compile_tu(toolchain, "add.c", "gcc", "O0", "c", ["/src"])
    assert res.ok, res.reason
    funcs = disasm.disassemble(toolchain, res.obj_path)
    names = {f.symbol for f in funcs}
    # 'add' and 'use' are external; 'mul' is static (may survive at O0)
    assert "add" in names and "use" in names


def test_compile_failure_is_reported(toolchain):
    # rel_src does not exist in /src -> compiler error, not an exception
    res = compile_mod.compile_tu(toolchain, "nope.c", "gcc", "O2", "c", ["/src"])
    assert res.ok is False and res.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_compile.py -v`
Expected: FAIL — module not written.

- [ ] **Step 3: Write `pipeline/compile.py`**

```python
import hashlib
import re
from dataclasses import dataclass

_BIN = {("gcc", "c"): "gcc", ("gcc", "cpp"): "g++",
        ("clang", "c"): "clang", ("clang", "cpp"): "clang++"}
_VER = re.compile(r"(\d+\.\d+\.\d+)")


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    obj_path: str | None
    reason: str | None


def compiler_binary(compiler: str, lang: str) -> str:
    return _BIN[(compiler, lang)]


def compiler_label(tc, compiler: str, lang: str) -> str:
    out = tc.exec([compiler_binary(compiler, lang), "--version"]).stdout
    m = _VER.search(out)
    return f"{compiler}-{m.group(1)}" if m else compiler


def compile_tu(tc, rel_src: str, compiler: str, opt: str, lang: str, include_dirs) -> CompileResult:
    cc = compiler_binary(compiler, lang)
    obj = hashlib.sha1(f"{rel_src}:{compiler}:{opt}".encode()).hexdigest()[:16] + ".o"
    obj_path = f"/out/{obj}"
    argv = [cc, f"-{opt}", "-g", "-c", f"/src/{rel_src}", "-o", obj_path]
    for inc in include_dirs:
        argv += ["-I", inc]
    r = tc.exec(argv)
    if r.returncode != 0:
        return CompileResult(ok=False, obj_path=None, reason=r.stderr.strip()[:2000])
    return CompileResult(ok=True, obj_path=obj_path, reason=None)
```

- [ ] **Step 4: Add `disassemble` + `_demangle` to `pipeline/disasm.py`**

Append to `pipeline/disasm.py`:
```python
def _demangle(tc, names):
    """Batch-demangle symbol names with c++filt; returns {name: demangled}."""
    if not names:
        return {}
    ordered = list(names)
    out = tc.exec(["c++filt"], input="\n".join(ordered) + "\n")
    demangled = out.stdout.splitlines()
    result = {}
    for i, n in enumerate(ordered):
        result[n] = demangled[i] if i < len(demangled) else n
    return result


def disassemble(tc, obj_container_path: str):
    raw = tc.exec(["objdump", "-d", obj_container_path])
    parsed = parse_objdump(raw.stdout)
    dm = _demangle(tc, [f.symbol for f in parsed])
    return [AsmFunc(symbol=f.symbol, demangled=dm.get(f.symbol, f.symbol),
                    asm_text=f.asm_text) for f in parsed]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_compile.py tests/test_disasm.py -v`
Expected: PASS (both the new integration tests and the still-green pure parser test).

- [ ] **Step 6: Commit**

```bash
git add pipeline/compile.py pipeline/disasm.py tests/test_compile.py
git commit -m "feat: in-container compile + objdump/c++filt disassembly

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL"
```

---

## Task 7: `run_pipeline.py` — per-repo orchestrator + CLI

**Files:**
- Create: `pipeline/run_pipeline.py`
- Test: `tests/test_run_pipeline.py`

**Interfaces:**
- Consumes: `env`, `extract`, `compile`, `disasm`, `pair`, `store`.
- Produces:
  - `find_sources(repo_dir:str) -> list[str]` (repo-relative `.c/.cc/.cpp/...` paths).
  - `include_dirs_for(repo_dir:str) -> list[str]` (container paths: `/src` + every subdir containing a `.h`, as `/src/<rel>`).
  - `run(repo_dir, repo=None, db_path="dataset/pairs.db", compilers=("gcc","clang"), opt_levels=("O0","O1","O2","O3","Os")) -> dict` (stats: `{"pairs":int, "skipped":int, "files":int}`).
  - `main()` CLI: `python -m pipeline.run_pipeline <repo_dir> [--db PATH]`.

- [ ] **Step 1: Write the failing test** — `tests/test_run_pipeline.py`

```python
import os
import pytest
import pipeline.run_pipeline as rp
import pipeline.store as store

pytestmark = pytest.mark.integration
FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_run_on_minirepo_populates_db(tmp_path):
    import pipeline.env as env
    if not env.docker_available():
        pytest.skip("Docker/Colima not available")
    db = str(tmp_path / "pairs.db")
    stats = rp.run(os.path.join(FIX, "minirepo"), repo="minirepo", db_path=db,
                   compilers=("gcc",), opt_levels=("O0",))
    assert stats["pairs"] >= 1
    conn = store.connect(db)
    names = {row[0] for row in conn.execute("SELECT func_name FROM pairs")}
    assert "add" in names
    # idempotent: a second identical run adds no new rows
    before = store.count_pairs(conn)
    rp.run(os.path.join(FIX, "minirepo"), repo="minirepo", db_path=db,
           compilers=("gcc",), opt_levels=("O0",))
    assert store.count_pairs(store.connect(db)) == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_run_pipeline.py -v`
Expected: FAIL — module not written.

- [ ] **Step 3: Write minimal implementation** — `pipeline/run_pipeline.py`

```python
import argparse
import os

import pipeline.env as env
import pipeline.extract as extract
import pipeline.compile as compile_mod
import pipeline.disasm as disasm
import pipeline.pair as pair
import pipeline.store as store

_SRC_EXT = (".c", ".cc", ".cpp", ".cxx", ".c++", ".C")


def find_sources(repo_dir: str):
    out = []
    for root, _dirs, files in os.walk(repo_dir):
        for f in files:
            if f.endswith(_SRC_EXT):
                out.append(os.path.relpath(os.path.join(root, f), repo_dir))
    return sorted(out)


def include_dirs_for(repo_dir: str):
    incs = {"/src"}
    for root, _dirs, files in os.walk(repo_dir):
        if any(f.endswith((".h", ".hpp", ".hh")) for f in files):
            rel = os.path.relpath(root, repo_dir)
            incs.add("/src" if rel == "." else f"/src/{rel}")
    return sorted(incs)


def run(repo_dir, repo=None, db_path="dataset/pairs.db",
        compilers=("gcc", "clang"), opt_levels=("O0", "O1", "O2", "O3", "Os")):
    repo = repo or os.path.basename(os.path.abspath(repo_dir))
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = store.connect(db_path)
    store.init_schema(conn)

    sources = find_sources(repo_dir)
    incs = include_dirs_for(repo_dir)
    tc = env.start_toolchain(repo_dir)
    stats = {"pairs": 0, "skipped": 0, "files": len(sources)}
    labels = {}
    try:
        for rel in sources:
            lang = extract.lang_for(rel)
            if lang is None:
                continue
            records = extract.extract_functions(os.path.join(repo_dir, rel))
            if not records:
                continue
            for compiler in compilers:
                labels.setdefault((compiler, lang),
                                  compile_mod.compiler_label(tc, compiler, lang))
                label = labels[(compiler, lang)]
                for opt in opt_levels:
                    res = compile_mod.compile_tu(tc, rel, compiler, opt, lang, incs)
                    if not res.ok:
                        store.record_skip(conn, repo=repo, file_path=rel,
                                          opt_level=opt, reason=res.reason)
                        stats["skipped"] += 1
                        continue
                    asm = disasm.disassemble(tc, res.obj_path)
                    for p in pair.pair_functions(records, asm):
                        if store.insert_pair(conn, repo=repo, file_path=rel,
                                             func_name=p.func_name, signature=p.signature,
                                             lang=p.lang, arch="x86_64", opt_level=opt,
                                             obj_format="elf", compiler=label,
                                             source_text=p.source_text, asm_text=p.asm_text):
                            stats["pairs"] += 1
    finally:
        tc.stop()
    return stats


def main():
    ap = argparse.ArgumentParser(description="Extract (asm, source) function pairs from a repo.")
    ap.add_argument("repo_dir")
    ap.add_argument("--db", default="dataset/pairs.db")
    ap.add_argument("--repo", default=None)
    args = ap.parse_args()
    stats = run(args.repo_dir, repo=args.repo, db_path=args.db)
    print(f"pairs={stats['pairs']} skipped={stats['skipped']} files={stats['files']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_run_pipeline.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all unit tests PASS; integration tests PASS (or SKIP only if Docker is down).

- [ ] **Step 6: Commit**

```bash
git add pipeline/run_pipeline.py tests/test_run_pipeline.py
git commit -m "feat: per-repo orchestrator and CLI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL"
```

---

## Task 8: End-to-end zlib run + README

**Files:**
- Create: `README.md`
- Produces: a populated `dataset/pairs.db` (not committed).

**Interfaces:**
- Consumes: the whole pipeline (Tasks 0–7).
- Produces: verified real data + reproduction docs.

- [ ] **Step 1: Ensure the zlib sample is present**

Run:
```bash
cd /Users/jbradley/Desktop/create_disasm_dataset
ls first_example/zlib/deflate.c || git clone https://github.com/madler/zlib first_example/zlib
```
Expected: `first_example/zlib/deflate.c` exists.

- [ ] **Step 2: Run the pipeline on zlib**

Run:
```bash
.venv/bin/python -m pipeline.run_pipeline first_example/zlib --repo zlib
```
Expected: prints a line like `pairs=<N> skipped=<M> files=<F>` with **N well over 100** (zlib has many functions × 2 compilers × 5 opt levels).

- [ ] **Step 3: Verify the database content**

Run:
```bash
.venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect("dataset/pairs.db")
print("pairs:", c.execute("SELECT COUNT(*) FROM pairs").fetchone()[0])
print("distinct funcs:", c.execute("SELECT COUNT(DISTINCT func_name) FROM pairs").fetchone()[0])
print("by opt:", c.execute("SELECT opt_level,COUNT(*) FROM pairs GROUP BY opt_level").fetchall())
print("by compiler:", c.execute("SELECT compiler,COUNT(*) FROM pairs GROUP BY compiler").fetchall())
name, src, asm = c.execute(
    "SELECT func_name,source_text,asm_text FROM pairs WHERE func_name='adler32' AND opt_level='O0' LIMIT 1").fetchone()
print("\n--- sample:", name, "---\nSOURCE:\n", src[:200], "\nASM:\n", asm[:200])
PY
```
Expected: nonzero counts across multiple opt levels and both compilers; the sample shows a real `adler32` source snippet and its disassembly. **This is the Phase-1 success criterion.**

- [ ] **Step 4: Write `README.md`**

```markdown
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

## Reproduce the zlib dataset (end-to-end)

```bash
git clone https://github.com/madler/zlib first_example/zlib   # sample repo (gitignored)
.venv/bin/python -m pipeline.run_pipeline first_example/zlib --repo zlib
```

This auto-starts the Linux x86-64 toolchain container (GCC + Clang + binutils),
compiles every translation unit at `-O0/-O1/-O2/-O3/-Os` with both compilers,
disassembles with `objdump`, pairs each symbol back to its source function, and
writes unique pairs into `dataset/pairs.db`.

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

## Testing

```bash
.venv/bin/pytest -v            # unit tests always run; integration tests need Docker
```
Integration tests auto-skip when Docker/Colima is unavailable; start it with `colima start`.

## Troubleshooting

- **Colima won't start:** `colima delete && colima start`.
- **Rebuild the toolchain image:** `docker rmi disasm-toolchain:latest` then re-run.
- **x86-64 emulation:** builds run under `--platform linux/amd64` (Rosetta); we only
  compile/disassemble, never execute, so this only affects compile latency.
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: reproduction README; Phase-1 zlib dataset verified end-to-end

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HY7rFHeBudeQn8t2Sd14PL"
```

---

## Self-Review

**Spec coverage** (against `docs/DESIGN.md` + spec):
- Compile-whole-TU / join-by-name → Tasks 2, 6, 4, 7. ✓
- objdump ELF x86-64, AT&T + bytes → Tasks 3, 6. ✓
- All five opt levels × GCC + Clang → Task 7 defaults, verified Task 8. ✓
- Auto-provisioned toolchain (Colima + image + container) → Task 5. ✓
- SQLite schema + dedup + idempotency (`pair_hash`) → Task 1, verified Task 7/8. ✓
- Skip-on-failure, drop-unmatched → Tasks 6/7 (`record_skip`), Task 4 (drop). ✓
- Pairing nuances: GCC clone suffixes, C++ demangling, leading underscore, static → Task 4 + fixtures. ✓
- Reproduction README → Task 8. ✓
- `repos` table for Phase 2 → created in Task 1 schema (unused until scraper plan). ✓
- **Deferred to Phase 2 (separate plan):** `scrape.py`, `harvest.py`, GitHub selection, download-and-delete. Intentionally out of scope here.

**Placeholder scan:** No TBD/TODO; every code step contains complete code; every command has expected output. ✓

**Type consistency:** `FunctionRecord`, `AsmFunc`, `Pair`, `CompileResult`, `Toolchain` field/param names match across Tasks 1–7; `compile_tu`/`disassemble`/`pair_functions`/`insert_pair` signatures are consistent between definition and callers in `run_pipeline.run`. ✓

## Known v1 limitations (documented, acceptable)

- C++ overload disambiguation is best-effort: pairing keys on the base identifier, so multiple overloads of one name map to the first disassembled symbol. zlib (pure C) is unaffected; robust overload handling is a later enhancement (DWARF or signature-typed demangling).
- One container per `run()` (per repo) rather than one global container; simplest and fine for Phase 2's per-repo harvest loop.
- Best-effort include-dir discovery; repos needing generated headers or exact flags will show up in `skipped` until `compile_commands.json` support (future) is added.
